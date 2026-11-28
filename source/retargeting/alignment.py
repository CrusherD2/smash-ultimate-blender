"""Line Up step: compare where the two armatures stand and fix it with a Transforms Offset."""
import math
import re

import bpy
from mathutils import Matrix, Vector

from ...expy_kit import offsets
from . import mapping_ui

SCALE_TOLERANCE = 1.1          # hip heights may differ by 10%
LOCATION_TOLERANCE = 0.02      # fraction of the Apply To hip height
RESTORE_KEY = 'sub_restore_pose_position'
ANGLE_TOLERANCE = math.radians(15.0)

_HIPS = re.compile(r'hips?$|pelvis$', re.IGNORECASE)
_HEAD = re.compile(r'head$', re.IGNORECASE)
_LIMB = re.compile(r'arm|shoulder|clavicle|leg|thigh', re.IGNORECASE)
# Side markers: "Right"/"Left" words, a lone r/l (arm.r, R_Arm), or a capital suffix (ArmR); "Shoulder" is not right.
_RIGHT = re.compile(r'(?i:right)|(?<![A-Za-z])[Rr](?![A-Za-z])|[a-z]R$')
_LEFT = re.compile(r'(?i:left)|(?<![A-Za-z])[Ll](?![A-Za-z])|[a-z]L$')


def _short(name: str) -> str:
    return name.rsplit(':', 1)[-1]


def _world_points(ob, matrix=None):
    """Rest positions of the deforming bones; IK controls and helpers can sit far from the body."""
    matrix = ob.matrix_world if matrix is None else matrix
    bones = [bone for bone in ob.data.bones if bone.use_deform] or list(ob.data.bones)
    points = []
    for bone in bones:
        points.append(matrix @ bone.head_local)
        points.append(matrix @ bone.tail_local)
    return points


def _root_name(ob):
    name = ob.data.expykit_retarget.root
    return name if name in ob.data.bones else ''


def _bone_head(ob, name, matrix):
    bone = ob.data.bones.get(name) if name else None
    return None if bone is None else matrix @ bone.head_local


def _by_name(ob, pattern):
    return next((bone.name for bone in ob.data.bones if pattern.search(_short(bone.name))), '')


def _sides(ob):
    """Right and left limb bones: from the mapping when set, otherwise from bone names."""
    mapping = ob.data.expykit_retarget
    right = [getattr(mapping.right_arm, 'arm', ''), getattr(mapping.right_leg, 'upleg', '')]
    left = [getattr(mapping.left_arm, 'arm', ''), getattr(mapping.left_leg, 'upleg', '')]
    pairs = [(r, l) for r, l in zip(right, left) if r and l]
    if pairs:
        return [r for r, _ in pairs], [l for _, l in pairs]
    names = [bone.name for bone in ob.data.bones if _LIMB.search(_short(bone.name))]
    rights = [n for n in names if _RIGHT.search(_short(n)) and not _LEFT.search(_short(n))]
    lefts = [n for n in names if _LEFT.search(_short(n)) and not _RIGHT.search(_short(n))]
    return rights, lefts


def body_frame(ob, matrix=None):
    """(up, right) world directions of the character, or None for any it can't find."""
    matrix = ob.matrix_world if matrix is None else matrix
    spine = ob.data.expykit_retarget.spine
    hips = _bone_head(ob, spine.hips or _by_name(ob, _HIPS), matrix)
    head = _bone_head(ob, spine.head or _by_name(ob, _HEAD), matrix)
    up = (head - hips).normalized() if hips is not None and head is not None and (head - hips).length > 1e-6 else None
    rights, lefts = _sides(ob)
    right = None
    if rights and lefts:
        r = sum((_bone_head(ob, n, matrix) for n in rights), Vector()) / len(rights)
        l = sum((_bone_head(ob, n, matrix) for n in lefts), Vector()) / len(lefts)
        if (r - l).length > 1e-6:
            right = (r - l).normalized()
    return up, right


def measure(ob, matrix=None, use_root=True):
    """(anchor, size, up, right).

    anchor: the root bone's head when mapped (root motion follows it), else the footprint centre on the floor.
    size: hip height above the floor (what foot contact depends on), else the body's height.
    """
    matrix = ob.matrix_world if matrix is None else matrix
    points = _world_points(ob, matrix)
    up, right = body_frame(ob, matrix)
    if not points:
        return Vector(), 0.0, up, right
    axis = up if up is not None else Vector((0, 0, 1))
    heights = [p.dot(axis) for p in points]
    root = _bone_head(ob, _root_name(ob), matrix) if use_root else None
    if root is not None:
        anchor, low = root, root.dot(axis)
    else:
        low = min(heights)
        centre = sum(points, Vector()) / len(points)
        anchor = centre - axis * (centre.dot(axis) - low)
    hips = _bone_head(ob, ob.data.expykit_retarget.spine.hips or _by_name(ob, _HIPS), matrix)
    size = hips.dot(axis) - low if hips is not None else 0.0
    if size <= 1e-6:
        size = max(heights) - low
    return anchor, size, up, right


def _use_root(driver, receiver):
    return bool(_root_name(driver) and _root_name(receiver))


def _angle(a, b):
    if a is None or b is None:
        return None
    return a.angle(b, 0.0)


def issues(driver, receiver):
    """[(kind, text)] for every way the source stands differently from the target; empty when lined up."""
    use_root = _use_root(driver, receiver)
    base, height, up, right = measure(driver, use_root=use_root)
    t_base, t_height, t_up, t_right = measure(receiver, use_root=use_root)
    found = []
    if height > 1e-6 and t_height > 1e-6:
        ratio = height / t_height
        if max(ratio, 1 / ratio) > SCALE_TOLERANCE:
            found.append(('SCALE', f"Hip height: {height:.2f} vs {t_height:.2f} m (\u00d7{t_height / height:.2f})"))
    turned = [a for a in (_angle(up, t_up), _angle(right, t_right)) if a is not None]
    if turned and max(turned) > ANGLE_TOLERANCE:
        found.append(('ROTATION', f"Turned {math.degrees(max(turned)):.0f}\u00b0 from the target"))
    if t_height > 1e-6 and (base - t_base).length > LOCATION_TOLERANCE * t_height:
        what = "Root is" if use_root else "Stands"
        found.append(('LOCATION', f"{what} {(base - t_base).length:.2f} m away"))
    return found


def _turn(driver, receiver):
    """World rotation that faces the source like the target, from whatever body directions both have."""
    up, right = body_frame(driver)
    t_up, t_right = body_frame(receiver)
    if up is not None and t_up is not None:
        turn = up.rotation_difference(t_up)
        if right is not None and t_right is not None:
            # Spin around the target's up so the sides match too.
            r = turn @ right
            r -= t_up * r.dot(t_up)
            t_r = t_right - t_up * t_right.dot(t_up)
            if r.length > 1e-6 and t_r.length > 1e-6:
                turn = r.rotation_difference(t_r) @ turn
        # Small differences are posture (a leaning spine), not a turned rig.
        if turn.angle <= ANGLE_TOLERANCE:
            return Matrix.Identity(3)
        return turn.to_matrix()
    return Matrix.Identity(3)


def suggest(driver, receiver):
    """(location, rotation euler, scale) for a new offset around the source's origin that lines it up."""
    origin = driver.matrix_world.translation.copy()
    turn = _turn(driver, receiver)
    turned = Matrix.Translation(origin) @ turn.to_4x4() @ Matrix.Translation(-origin) @ driver.matrix_world
    use_root = _use_root(driver, receiver)
    _, height, _, _ = measure(driver, turned, use_root)
    t_base, t_height, _, _ = measure(receiver, use_root=use_root)
    scale = t_height / height if height > 1e-6 and t_height > 1e-6 else 1.0
    placed = Matrix.Translation(origin) @ turn.to_4x4() @ Matrix.Scale(scale, 4) @ Matrix.Translation(-origin) \
        @ driver.matrix_world
    base, _, _, _ = measure(driver, placed, use_root)
    return t_base - base, turn.to_euler(), scale


def accepted(scene, driver, receiver) -> bool:
    from . import pair_key
    return scene.sub_retarget_aligned_pair == pair_key(driver, receiver)


def offset_open(scene) -> bool:
    return scene.expykit_offset.container is not None


class SUB_OT_retarget_line_up(bpy.types.Operator):
    bl_idname = 'sub.retarget_line_up'
    bl_label = 'Line Up Source'
    bl_description = ('Open a Transforms Offset on the "Animation From" armature, pre-filled to match the '
                      '"Apply To" armature\'s location, rotation and size. Animation is not changed')
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        scene = context.scene
        if mapping_ui.animation_from(scene) is None or mapping_ui.apply_to(context) is None:
            cls.poll_message_set('Set "Animation From" and "Apply To" first')
            return False
        if offset_open(scene):
            cls.poll_message_set('Apply the open offset first')
            return False
        return True

    def execute(self, context):
        scene = context.scene
        driver, receiver = mapping_ui.animation_from(scene), mapping_ui.apply_to(context)
        if driver.parent_type != 'OBJECT':
            self.report({'ERROR'}, f'{driver.name} is parented to a bone; unparent it first')
            return {'CANCELLED'}
        if not driver.visible_get():
            self.report({'ERROR'}, f'{driver.name} is hidden; unhide it first')
            return {'CANCELLED'}
        location, rotation, scale = suggest(driver, receiver)
        if context.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        for ob in context.selected_objects:
            ob.select_set(False)
        driver.select_set(True)
        context.view_layer.objects.active = driver
        if not offsets._begin(context):
            self.report({'ERROR'}, 'Could not create the offset')
            return {'CANCELLED'}
        settings = scene.expykit_offset
        container = settings.container
        # The offset's own frame is world-aligned and unscaled, even under an earlier offset.
        settings.scale = scale
        settings.rotation = rotation
        settings.location = location
        # Line up in rest pose so the animation doesn't hide where the rigs really stand; Apply restores it.
        container[RESTORE_KEY] = driver.data.pose_position
        driver.data.pose_position = 'REST'
        from . import guided
        if context.area and context.area.type == 'VIEW_3D':
            region = next((r for r in context.area.regions if r.type == 'WINDOW'), None)
            override = {'area': context.area, 'region': region} if region else None
        else:
            override = guided.view3d_override(context)
        if override:
            with context.temp_override(**override):
                bpy.ops.view3d.view_axis(type='FRONT', align_active=False)
        self.report({'INFO'}, 'Check the suggested offset, adjust it if needed, then click Apply')
        return {'FINISHED'}


class SUB_OT_retarget_accept_alignment(bpy.types.Operator):
    bl_idname = 'sub.retarget_accept_alignment'
    bl_label = 'Keep As Is'
    bl_description = 'The armatures are lined up well enough; stop flagging this pair'
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return mapping_ui.animation_from(context.scene) is not None and mapping_ui.apply_to(context) is not None

    def execute(self, context):
        from . import pair_key
        scene = context.scene
        scene.sub_retarget_aligned_pair = pair_key(mapping_ui.animation_from(scene), mapping_ui.apply_to(context))
        return {'FINISHED'}


def draw(layout, context, driver, receiver):
    scene = context.scene
    if offset_open(scene):
        layout.label(text="Adjust until both stand together, then Apply.", icon='INFO')
        offsets.draw_offset(layout, context)
        return
    if driver is None or receiver is None:
        return
    found = issues(driver, receiver)
    if not found:
        layout.label(text="Same size, facing and place.", icon='CHECKMARK')
        return
    col = layout.column(align=True)
    for _, text in found:
        col.label(text=text, icon='ERROR')
    if accepted(scene, driver, receiver):
        layout.label(text="Kept as is.", icon='CHECKMARK')
    col = layout.column()
    col.scale_y = 1.2
    col.operator(SUB_OT_retarget_line_up.bl_idname, icon='OBJECT_ORIGIN')
    if not accepted(scene, driver, receiver):
        layout.operator(SUB_OT_retarget_accept_alignment.bl_idname)


classes = (SUB_OT_retarget_line_up, SUB_OT_retarget_accept_alignment)
