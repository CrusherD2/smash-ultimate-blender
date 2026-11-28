"""Pose the receiving armature so its mapped bones point like the driving armature's rest pose."""
import bpy
from mathutils import Matrix, Vector

from ..extras import fk_to_ik
from . import guided, mapping_ui

IK_SOLVE_PASSES = 4
# Below these, a bone already lines up and isn't counted as changed (moves are a fraction of limb length).
MIN_ANGLE = 1e-3
MIN_MOVE = 1e-4
POLE_TOLERANCE = 0.01
EFFECTOR_TOLERANCE = 1e-3
# Closed-loop IK settling leaves tiny leftovers; under this a control counts as unchanged.
CONTROL_ANGLE_TOLERANCE = 5e-3
# Pull an out-of-reach target just inside the limb's reach so the IK solve can settle.
REACH_MARGIN = 0.999


def mapping_chains() -> list[tuple[str, list[tuple[str, str, str]]]]:
    """(kind, chain) where each chain step is (mapping group, finger or '', slot)."""
    chains = [('body', [('spine', '', slot) for slot in ('hips', 'spine1', 'spine2', 'neck', 'head')])]
    for side, _ in mapping_ui.SIDES:
        chains.append(('body', [(f'{side}_arm', '', slot) for slot in ('shoulder', 'arm', 'forearm', 'hand')]
                       + [(f'{side}_fingers', 'middle', 'a')]))
        chains.append(('body', [(f'{side}_leg', '', slot) for slot in ('upleg', 'leg', 'foot', 'toe')]))
        for finger in mapping_ui.FINGERS:
            chains.append(('finger', [(f'{side}_fingers', finger, slot) for slot in mapping_ui.FINGER_SLOTS]))
    return chains


def _bone_name(ob, attr: str, finger: str, slot: str) -> str:
    group = getattr(ob.data.expykit_retarget, attr)
    if finger:
        group = getattr(group, finger)
    name = getattr(group, slot)
    return name if name and name in ob.data.bones else ''


def direction_pairs(receiver, driver, kinds=('body', 'finger'), skip=frozenset()):
    """(receiver bone, receiver next, driver bone, driver next), parents before children."""
    pairs, seen = [], set(skip)
    for kind, chain in mapping_chains():
        if kind not in kinds:
            continue
        both = [(r, d) for r, d in ((_bone_name(receiver, *s), _bone_name(driver, *s)) for s in chain) if r and d]
        for (r, d), (r_next, d_next) in zip(both, both[1:]):
            # Rotating a bone only moves the next head if that bone is below it.
            if r in seen or receiver.data.bones[r] not in receiver.data.bones[r_next].parent_recursive:
                continue
            seen.add(r)
            pairs.append((r, r_next, d, d_next))
    pairs.sort(key=lambda p: len(receiver.data.bones[p[0]].parent_recursive))
    return pairs


def palm_bones(ob, side: str) -> list[str]:
    """Middle, index and pinky base bones: where the hand points and which way the palm faces."""
    return [_bone_name(ob, f'{side}_fingers', finger, 'a') for finger in ('middle', 'index', 'pinky')]


def palm_frame(hand_head, middle, index, pinky) -> Matrix | None:
    """Orientation from hand-to-middle-finger (forward) and index-to-pinky (across the palm)."""
    forward = middle - hand_head
    across = pinky - index
    if forward.length < 1e-6 or across.length < 1e-6:
        return None
    forward.normalize()
    across -= forward * across.dot(forward)
    if across.length < 1e-6:
        return None
    across.normalize()
    return Matrix((forward, across, forward.cross(across))).transposed()


def chain_frame(root, mid, end) -> Matrix | None:
    """Orientation of a limb: along the upper bone, and toward the end joint within the bend plane."""
    along = mid - root
    toward = end - root
    if along.length < 1e-6:
        return None
    along = along.normalized()
    toward -= along * toward.dot(along)
    if toward.length < 1e-6:
        return None
    toward.normalize()
    return Matrix((along, toward, along.cross(toward))).transposed()


def heading_frame(head, ahead, up) -> Matrix | None:
    """Orientation from a forward direction, kept level with ``up`` (how a foot or toe sits on the ground)."""
    forward = ahead - head
    if forward.length < 1e-6:
        return None
    forward = forward.normalized()
    side = forward.cross(up)
    if side.length < 1e-6:
        return None
    side.normalize()
    return Matrix((forward, side, side.cross(forward))).transposed()


def bone_tip(bones, name, matrix):
    """Where a bone points to: its first child's head, else its tail (in world space via ``matrix``)."""
    bone = bones[name]
    return matrix @ (bone.children[0].head_local if bone.children else bone.tail_local)


def source_toe_tip(bones, toe, foot, matrix, up):
    """Where the source toe points. A last toe bone's tail is only trusted if it points on from the foot:
    imported rigs often end in short stubs facing any way, so then the toe lies flat ahead of the foot."""
    bone = bones[toe]
    if bone.children:
        return matrix @ bone.children[0].head_local
    head, tail = matrix @ bone.head_local, matrix @ bone.tail_local
    ahead = head - matrix @ bones[foot].head_local
    if (tail - head).dot(ahead) > 0.0:
        return tail
    level = ahead - up * ahead.dot(up)
    if level.length < 1e-6:
        level = ahead
    return head + level.normalized() * max((tail - head).length, ahead.length * 0.5)


def _deform_toe(receiver, foot, toe_control):
    children = list(receiver.data.bones[foot].children)
    for child in children:
        if any(getattr(c, 'subtarget', '') == toe_control for c in receiver.pose.bones[child.name].constraints):
            return child.name
    return next((c.name for c in children if 'toe' in c.name.lower()), '')


def ik_limbs(receiver, driver) -> list[dict]:
    """Smash IK arms and legs whose IK controls are what the mapping points at."""
    limbs = []
    for side, letter in mapping_ui.SIDES:
        arm = lambda slot: _bone_name(receiver, f'{side}_arm', '', slot)
        for chain in fk_to_ik.iter_arm_fk_chains(receiver):
            effector, pole = chain['hand_ik'], chain['arm_ik']
            if chain['side'] != letter or chain['shoulder'] is None or effector is None or pole is None:
                continue
            if effector.name != arm('hand') and pole.name != arm('forearm'):
                continue
            limbs.append({
                'driver': [_bone_name(driver, f'{side}_arm', '', s) for s in ('arm', 'forearm', 'hand')]
                + [_bone_name(driver, f'{side}_fingers', 'middle', 'a')],
                'driver_clavicle': _bone_name(driver, f'{side}_arm', '', 'shoulder'),
                'clavicle': arm('shoulder'),
                'joints': [chain['shoulder'].name, chain['arm'].name, chain['hand'].name],
                'next': _bone_name(receiver, f'{side}_fingers', 'middle', 'a'),
                'effector': effector.name, 'pole': pole.name,
                'palm': palm_bones(receiver, side), 'driver_palm': palm_bones(driver, side),
                'toe': '', 'toe_control': '',
            })
        leg = lambda slot: _bone_name(receiver, f'{side}_leg', '', slot)
        for chain in fk_to_ik.iter_leg_fk_chains(receiver):
            effector, pole = chain['foot_ik'], chain['knee_ik']
            if chain['side'] != letter or (effector.name != leg('foot') and pole.name != leg('leg')):
                continue
            toe_control = leg('toe')
            bones = receiver.data.bones
            if toe_control and bones[effector.name] not in bones[toe_control].parent_recursive:
                toe_control = ''
            limbs.append({
                'driver': [_bone_name(driver, f'{side}_leg', '', s) for s in ('upleg', 'leg', 'foot', 'toe')],
                'driver_clavicle': '', 'clavicle': '',
                'joints': [chain['leg'].name, chain['knee'].name, chain['foot'].name],
                'next': leg('toe'),
                'effector': effector.name, 'pole': pole.name,
                'palm': [], 'driver_palm': [],
                'toe': _deform_toe(receiver, chain['foot'].name, toe_control) if toe_control else '',
                'toe_control': toe_control,
            })
    return [limb for limb in limbs if all(limb['driver'][:3])]


class _Poser:
    def __init__(self, receiver, driver, view_layer, use_object_transform):
        self.receiver, self.driver, self.view_layer = receiver, driver, view_layer
        # Without Match Object Transform, binding reads the receiver's pose in armature space.
        self.mw = receiver.matrix_world.copy() if use_object_transform else Matrix.Identity(4)
        self.mw_inv = self.mw.inverted_safe()
        view_layer.update()
        # Includes any Create Transforms Offset parent, as binding does.
        self.dmw = driver.matrix_world.copy()
        self.up = (self.mw.to_3x3() @ Vector((0.0, 0.0, 1.0))).normalized()
        self.driver_up = (self.dmw.to_3x3() @ Vector((0.0, 0.0, 1.0))).normalized()

    def head(self, name):
        return self.mw @ self.receiver.pose.bones[name].head

    def tail(self, name):
        return self.mw @ self.receiver.pose.bones[name].tail

    def rest(self, name):
        return self.dmw @ self.driver.data.bones[name].head_local

    def rest_tail(self, name):
        return self.dmw @ self.driver.data.bones[name].tail_local

    def world(self, name):
        return (self.mw @ self.receiver.pose.bones[name].matrix).copy()

    def rest_rot(self, name):
        return (self.mw.to_3x3() @ self.receiver.data.bones[name].matrix_local.to_3x3()).normalized()

    def posed_rot(self, name):
        return (self.mw.to_3x3() @ self.receiver.pose.bones[name].matrix.to_3x3()).normalized()

    def rest_head(self, name):
        return self.mw @ self.receiver.data.bones[name].head_local

    def set_rotation(self, name, rotation):
        pose_bone = self.receiver.pose.bones[name]
        location, _rotation, scale = (self.mw @ pose_bone.matrix).decompose()
        pose_bone.matrix = self.mw_inv @ Matrix.LocRotScale(location, rotation.to_quaternion(), scale)

    def keep_if_changed(self, name, before, tolerance=MIN_MOVE, angle=MIN_ANGLE) -> bool:
        """Undo leftovers too small to matter, so matching an already-matched pose changes nothing."""
        after = self.world(name)
        moved = (after.to_translation() - before.to_translation()).length >= tolerance
        turned = (before.to_3x3().normalized().to_quaternion()
                  .rotation_difference(after.to_3x3().normalized().to_quaternion()).angle >= angle)
        if moved or turned:
            return True
        self.receiver.pose.bones[name].matrix = self.mw_inv @ before
        return False

    def aim_from_rest(self, name, next_name, wanted) -> bool:
        """Point ``name`` at ``wanted``, twisted as in the rest pose rather than the current animated frame."""
        before = self.world(name)
        rest_dir = self.rest_head(next_name) - self.rest_head(name)
        if rest_dir.length < 1e-6 or wanted.length < 1e-6:
            return False
        self.set_rotation(name, rest_dir.rotation_difference(wanted).to_matrix() @ self.rest_rot(name))
        self.view_layer.update()
        # Bones between this one and the next may be posed; fix the direction from where it really lands.
        pivot = self.head(name)
        self.rotate(name, pivot, self.head(next_name) - pivot, wanted)
        self.view_layer.update()
        return self.keep_if_changed(name, before)

    def level_rotation(self, name, rest_ahead, source_head, source_ahead):
        """Rotation for ``name`` that sits like the source bone does, keeping each rig's rest roll to the ground."""
        rest_frame = heading_frame(self.rest_head(name), rest_ahead, self.up)
        source_frame = heading_frame(source_head, source_ahead, self.driver_up)
        if rest_frame is None or source_frame is None:
            return None
        return source_frame @ rest_frame.transposed() @ self.rest_rot(name)

    def rotate(self, name, pivot, current, wanted) -> bool:
        if current.length < 1e-6 or wanted.length < 1e-6:
            return False
        return self.turn(name, pivot, current.rotation_difference(wanted).to_matrix())

    def turn(self, name, pivot, rotation) -> bool:
        if rotation.to_quaternion().angle < MIN_ANGLE:
            return False
        pose_bone = self.receiver.pose.bones[name]
        world = (Matrix.Translation(pivot) @ rotation.to_4x4() @ Matrix.Translation(-pivot)
                 @ (self.mw @ pose_bone.matrix))
        pose_bone.matrix = self.mw_inv @ world
        return True

    def receiver_palm(self, hand, bones) -> Matrix | None:
        # Feet have no palm; all([]) would wrongly pass an empty list.
        if not hand or len(bones) != 3 or not all(bones):
            return None
        return palm_frame(self.head(hand), *(self.head(name) for name in bones))

    def driver_palm(self, hand, bones) -> Matrix | None:
        if not hand or len(bones) != 3 or not all(bones):
            return None
        return palm_frame(self.rest(hand), *(self.rest(name) for name in bones))

    def orient_fk_hands(self, skip) -> int:
        """Turn FK hands so the palm faces like the source's, not just points the same way."""
        changed = 0
        for side, _ in mapping_ui.SIDES:
            hand = _bone_name(self.receiver, f'{side}_arm', '', 'hand')
            palm = palm_bones(self.receiver, side)
            if not hand or hand in skip or not all(palm):
                continue
            bone = self.receiver.data.bones[hand]
            if any(bone not in self.receiver.data.bones[name].parent_recursive for name in palm):
                continue
            self.view_layer.update()
            current = self.receiver_palm(hand, palm)
            wanted = self.driver_palm(_bone_name(self.driver, f'{side}_arm', '', 'hand'), palm_bones(self.driver, side))
            if current is not None and wanted is not None:
                changed += self.turn(hand, self.head(hand), wanted @ current.transposed())
        self.view_layer.update()
        return changed

    def foot_rotation(self, foot, toe, source_foot, source_toe):
        # Different ankle heights must not turn into a downward tilt of the sole.
        rest_forward = self.rest_head(toe) - self.rest_head(foot)
        rest_forward -= self.up * rest_forward.dot(self.up)
        source_forward = self.rest(source_toe) - self.rest(source_foot)
        source_forward -= self.driver_up * source_forward.dot(self.driver_up)
        rest_frame = heading_frame(self.rest_head(foot), self.rest_head(foot) + rest_forward, self.up)
        source_frame = heading_frame(self.rest(source_foot), self.rest(source_foot) + source_forward, self.driver_up)
        if rest_frame is None or source_frame is None:
            return None
        return source_frame @ rest_frame.transposed() @ self.rest_rot(foot)

    def orient_fk_feet(self, skip) -> int:
        changed = 0
        for side, _ in mapping_ui.SIDES:
            foot, toe = (_bone_name(self.receiver, f'{side}_leg', '', slot) for slot in ('foot', 'toe'))
            source_foot, source_toe = (_bone_name(self.driver, f'{side}_leg', '', slot)
                                       for slot in ('foot', 'toe'))
            if not all((foot, toe, source_foot, source_toe)) or foot in skip:
                continue
            if self.receiver.data.bones[foot] not in self.receiver.data.bones[toe].parent_recursive:
                continue
            rotation = self.foot_rotation(foot, toe, source_foot, source_toe)
            if rotation is None:
                continue
            self.view_layer.update()
            before = self.world(foot)
            self.set_rotation(foot, rotation)
            self.view_layer.update()
            changed += self.keep_if_changed(foot, before)
            if toe not in skip:
                before = self.world(toe)
                rotation = self.level_rotation(toe, bone_tip(self.receiver.data.bones, toe, self.mw),
                    self.rest(source_toe), source_toe_tip(self.driver.data.bones, source_toe,
                                                         source_foot, self.dmw, self.driver_up))
                if rotation is not None:
                    self.set_rotation(toe, rotation)
                    self.view_layer.update()
                    changed += self.keep_if_changed(toe, before)
        return changed

    def place(self, name, world, tolerance: float = MIN_MOVE) -> bool:
        """Set a bone's world matrix unless it's already there (within tolerance and MIN_ANGLE)."""
        pose_bone = self.receiver.pose.bones[name]
        current = self.mw @ pose_bone.matrix
        moved = (world.to_translation() - current.to_translation()).length >= tolerance
        turned = current.to_quaternion().rotation_difference(world.to_quaternion()).angle >= MIN_ANGLE
        if not (moved or turned):
            return False
        pose_bone.matrix = self.mw_inv @ world
        return True

    def move(self, name, delta, tolerance: float = MIN_MOVE) -> bool:
        if delta.length < tolerance:
            return False
        pose_bone = self.receiver.pose.bones[name]
        pose_bone.matrix = self.mw_inv @ (Matrix.Translation(delta) @ (self.mw @ pose_bone.matrix))
        return True

    def aim_pairs(self, pairs) -> int:
        changed = 0
        for r, r_next, d, d_next in pairs:
            self.view_layer.update()
            changed += self.aim_from_rest(r, r_next, self.rest(d_next) - self.rest(d))
        self.view_layer.update()
        return changed

    def place_pole(self, limb, upper, elbow, wrist) -> bool:
        """Put ArmIK/KneeIK where it sits on the rest rig, carried over to the source's elbow/knee and bend.

        The rest rig's limb (shoulder-elbow-wrist) is turned onto the source's limb; the pole gets the same
        turn, for both its offset from the elbow/knee and its own rotation.
        """
        root, mid, end = limb['joints']
        d_root, d_mid, d_end, _ = limb['driver']
        pole = limb['pole']
        bones = self.receiver.data.bones
        rest = lambda name: self.mw @ bones[name].head_local
        rest_frame = chain_frame(rest(root), rest(mid), rest(end))
        source_frame = chain_frame(self.rest(d_root), self.rest(d_mid), self.rest(d_end))
        if rest_frame is None or source_frame is None:
            # Straight limb: no bend plane to copy, so turn the rest layout with the upper limb only.
            rest_upper = rest(mid) - rest(root)
            source_upper = self.rest(d_mid) - self.rest(d_root)
            if rest_upper.length < 1e-6 or source_upper.length < 1e-6:
                return False
            turn = rest_upper.rotation_difference(source_upper).to_matrix().to_4x4()
        else:
            turn = (source_frame @ rest_frame.transposed()).to_4x4()
        pole_rest = self.mw @ bones[pole].matrix_local
        anchor = self.rest(d_mid)
        world = (Matrix.Translation(anchor) @ turn @ Matrix.Translation(-rest(mid))) @ pole_rest
        # The IK solve leaves the elbow slightly off, so tiny pole corrections aren't changes.
        return self.place(pole, world, upper * POLE_TOLERANCE)

    def ik_limb(self, limb) -> int:
        d_root, d_mid, d_end, d_next = limb['driver']
        root, mid, end = limb['joints']
        effector, toe_control = limb['effector'], limb['toe_control']
        changed = 0
        if limb['clavicle'] and limb['driver_clavicle']:
            self.view_layer.update()
            changed += self.aim_from_rest(limb['clavicle'], root, self.rest(d_root) - self.rest(limb['driver_clavicle']))
        self.view_layer.update()
        before = {name: self.world(name) for name in (effector, toe_control) if name}
        p0, p1, p2 = self.head(root), self.head(mid), self.head(end)
        upper, lower = (p1 - p0).length, (p2 - p1).length
        elbow = p0 + (self.rest(d_mid) - self.rest(d_root)).normalized() * upper
        # IK hands and feet go where the source's are, pulled in only if the limb can't reach.
        wrist = self.rest(d_end)
        reach = (upper + lower) * REACH_MARGIN
        if (wrist - p0).length > reach:
            wrist = p0 + (wrist - p0).normalized() * reach
        changed += self.place_pole(limb, upper, elbow, wrist)

        wanted_palm = self.driver_palm(d_end, limb['driver_palm'])
        wanted_foot = None
        if wanted_palm is None and limb['next'] and d_next:
            toe = limb['toe'] or limb['next']
            wanted_foot = self.foot_rotation(end, toe, d_end, d_next)
        wanted_end = (self.rest(d_next) if d_next else self.rest_tail(d_end)) - self.rest(d_end)
        # The IK solve moves the end joint after each change, so settle position and rotation together.
        for _ in range(IK_SOLVE_PASSES):
            self.view_layer.update()
            current_palm = self.receiver_palm(end, limb['palm'])
            if wanted_palm is not None and current_palm is not None:
                self.turn(effector, self.head(end), wanted_palm @ current_palm.transposed())
            elif wanted_foot is not None:
                self.turn(effector, self.head(end), wanted_foot @ self.posed_rot(end).transposed())
            else:
                current_end = (self.head(limb['next']) if limb['next'] else self.tail(end)) - self.head(end)
                self.rotate(effector, self.head(end), current_end, wanted_end)
            self.view_layer.update()
            self.move(effector, wrist - self.head(end), (upper + lower) * EFFECTOR_TOLERANCE)
        if toe_control and limb['toe'] and d_next:
            bones = self.receiver.data.bones
            wanted_toe = self.level_rotation(limb['toe'], bone_tip(bones, limb['toe'], self.mw), self.rest(d_next),
                                             source_toe_tip(self.driver.data.bones, d_next, d_end, self.dmw,
                                                            self.driver_up))
            for _ in range(2):
                self.view_layer.update()
                if wanted_toe is not None:
                    self.turn(toe_control, self.head(toe_control),
                              wanted_toe @ self.posed_rot(limb['toe']).transposed())
        self.view_layer.update()
        tolerance = (upper + lower) * EFFECTOR_TOLERANCE
        for name, matrix in before.items():
            changed += self.keep_if_changed(name, matrix, tolerance, CONTROL_ANGLE_TOLERANCE)
        self.view_layer.update()
        return changed

def match_rest_pose(receiver, driver, view_layer, use_object_transform: bool = True) -> int:
    """Pose receiver bones to point like the driver's rest bones. Returns bones changed."""
    poser = _Poser(receiver, driver, view_layer, use_object_transform)
    limbs = ik_limbs(receiver, driver)
    # IK controls are placed by the limb solve, not aimed like FK bones.
    controlled = {name for limb in limbs
                  for name in (limb['effector'], limb['pole'], limb['clavicle'], limb['toe_control']) if name}
    fk_feet = {_bone_name(receiver, f'{side}_leg', '', 'foot') for side, _ in mapping_ui.SIDES
               if all(_bone_name(ob, f'{side}_leg', '', slot)
                      for ob in (receiver, driver) for slot in ('foot', 'toe'))}
    changed = poser.aim_pairs(direction_pairs(receiver, driver, ('body',), controlled | fk_feet))
    changed += poser.orient_fk_feet(controlled)
    changed += poser.orient_fk_hands(controlled)
    for limb in limbs:
        changed += poser.ik_limb(limb)
    changed += poser.aim_pairs(direction_pairs(receiver, driver, ('finger',)))
    return changed


class SUB_OT_retarget_match_rest_pose(bpy.types.Operator):
    bl_idname = 'sub.retarget_match_rest_pose'
    bl_label = 'Match Source Pose to Target Pose'
    bl_description = ('Rotate the "Apply To" armature\'s bones to match the "Animation From" armature\'s rest pose '
                      '(IK controls may also move), then set Match to Current Pose is Source Rest Pose')
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        if mapping_ui.animation_from(context.scene) is None or mapping_ui.apply_to(context) is None:
            cls.poll_message_set('Set "Animation From" and "Apply To" first')
            return False
        return True

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(
            self, event, title='Match Source Pose to Target Pose', icon='WARNING', confirm_text='Match Pose',
            message='This is a close approximation. Verify that it looks good before binding.')

    def execute(self, context):
        scene = context.scene
        driver, receiver = mapping_ui.animation_from(scene), mapping_ui.apply_to(context)
        for ob in (driver, receiver):
            if not ob.data.expykit_retarget.has_settings():
                self.report({'ERROR'}, f'Map the bones of {ob.name} first (step 1)')
                return {'CANCELLED'}
        if not direction_pairs(receiver, driver) and not ik_limbs(receiver, driver):
            self.report({'WARNING'}, 'The two mappings share no connected bones to line up')
            return {'CANCELLED'}

        driver.data.pose_position = 'REST'
        switched = mapping_ui.ensure_pose_position(receiver)
        constrained, bound_driver = guided.bound_pair(scene)
        # Bind constraints would hide the lined-up pose, so a bound pair is unbound and left that way.
        unbound = bool(getattr(scene, 'expykit_bind_is_active', False) and constrained == receiver
                       and guided.clear_bound_constraints(constrained, bound_driver))
        if unbound:
            scene.expykit_bind_is_active = False
        changed = match_rest_pose(receiver, driver, context.view_layer, scene.expykit_match_object_transform)
        scene.expykit_match_transform = 'Pose'
        scene['sub_retarget_confirm_mapping'] = True
        for window in context.window_manager.windows:
            for area in window.screen.areas:
                if area.type == 'VIEW_3D':
                    shading = area.spaces.active.shading
                    if shading.type == 'SOLID':
                        shading.show_xray = True
                        shading.xray_alpha = 0.7
                        area.tag_redraw()

        if changed:
            message = f"Posed {changed} bones of {receiver.name} like {driver.name}'s rest pose"
        else:
            message = f"{receiver.name} already lines up with {driver.name}'s rest pose; nothing to change"
        if switched:
            message += f". Switched {receiver.name} to Pose Position so the new pose shows"
        if unbound:
            message += ". Removed the old bind so the pose shows; click Bind Armatures when ready"
        animation = receiver.animation_data
        if animation is not None and animation.action is not None:
            self.report({'WARNING'}, f'{message}. {receiver.name} has animation: bind before changing frames')
        else:
            self.report({'INFO'}, message)
        return {'FINISHED'}


class SUB_OT_retarget_confirm_pose_mapping(bpy.types.Operator):
    bl_idname = 'sub.retarget_confirm_pose_mapping'
    bl_label = 'Confirm Mapping'
    bl_description = 'Finish checking the matched pose and restore full Solid-view opacity'
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        for window in context.window_manager.windows:
            for area in window.screen.areas:
                if area.type == 'VIEW_3D':
                    shading = area.spaces.active.shading
                    if shading.type == 'SOLID':
                        shading.xray_alpha = 1.0
                        shading.show_xray = False
                        area.tag_redraw()
        context.scene['sub_retarget_confirm_mapping'] = False
        guided.tag_retargeting_redraw()
        return {'FINISHED'}


def draw_match_button(layout, context):
    operator = (SUB_OT_retarget_confirm_pose_mapping if context.scene.get('sub_retarget_confirm_mapping')
                else SUB_OT_retarget_match_rest_pose)
    layout.operator(operator.bl_idname, icon='CHECKMARK' if operator == SUB_OT_retarget_confirm_pose_mapping else 'POSE_HLT')
