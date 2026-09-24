"""Rest-relative mirroring for bones authored outside the Smash importer."""
import re

from mathutils import Matrix

from .anim_flip import find_custom_mirror_bones, create_mirror_map, is_ik_control


def custom_mirror_names(obj):
    names = set(find_custom_mirror_bones(obj))
    names.update(p.name for p in obj.pose.bones if p.bone.get('sub_component_control'))
    return {name for name in names if not obj.data.bones[name].get('sub_face_helper')
            and not name.startswith('BL_CC_MCH_')}


# Smash's Z reflection becomes Blender armature-space Y for the posed body.
_Y_REFLECTION = Matrix.Diagonal((1.0, -1.0, 1.0, 1.0))
_X_REFLECTION = Matrix.Diagonal((-1.0, 1.0, 1.0, 1.0))
# anim_flip negates each Smash bone's local Z (translateZ, rotateX/Y), which
# is also Z in the imported Blender bone axes.
_SMASH_LOCAL_FLIP = Matrix.Diagonal((1.0, 1.0, -1.0, 1.0))


def _rest_axes(bone):
    return bone.matrix_local.to_3x3().normalized().to_4x4()


def rest_reflection(obj):
    """The armature plane the rest skeleton is left/right symmetric across.

    Imported Smash skeletons are symmetric across armature X even though
    anim_flip mirrors the posed body across Y (the character turns around).
    """
    bones = obj.data.bones
    spread = [0.0, 0.0]
    for source, target in create_mirror_map(bones.keys()).items():
        if source != target:
            offset = bones[source].head_local - bones[target].head_local
            spread[0] += abs(offset.x)
            spread[1] += abs(offset.y)
    return _X_REFLECTION if spread[0] > spread[1] else _Y_REFLECTION


class MirrorSpace:
    """Target basis for a mirrored extra bone.

    Every mirrored bone satisfies target world = R @ source world @ S: R is
    the posed-body reflection, S a fixed local flip. Smash bones use their
    local Z flip. A parented extra bone inherits S through its rest offset,
    so its basis is conjugated by S. A parentless bone (IK controls, floating
    handles) has no mirrored parent, so its S comes from the rest symmetry.
    """

    def __init__(self, obj, custom=None, pose_reflection=None):
        self.obj = obj
        self.custom = custom_mirror_names(obj) if custom is None else custom
        self.pose = _Y_REFLECTION if pose_reflection is None else pose_reflection
        self.rest = rest_reflection(obj)
        self._fix = {}

    def world_fix(self, source_name, target_name):
        if source_name not in self.custom:
            return _SMASH_LOCAL_FLIP
        key = (source_name, target_name)
        if key not in self._fix:
            source = self.obj.data.bones[source_name]
            target = self.obj.data.bones[target_name]
            if source.parent is None or target.parent is None:
                fix = _rest_axes(source).inverted() @ self.rest @ _rest_axes(target)
            else:
                parent_fix = self.world_fix(source.parent.name, target.parent.name)
                offset_s = _rest_axes(source.parent).inverted() @ _rest_axes(source)
                offset_t = _rest_axes(target.parent).inverted() @ _rest_axes(target)
                fix = offset_s.inverted() @ parent_fix @ offset_t
            self._fix[key] = fix
        return self._fix[key]

    def basis(self, source_name, target_name, basis):
        source = self.obj.data.bones[source_name]
        target = self.obj.data.bones[target_name]
        if (source.parent is None or target.parent is None) and source_name != target_name:
            # Full rest matrices: the posed and rest reflections differ, so the
            # rest head itself moves when the body turns around. In place, a
            # bone keeps its side and only its delta is reflected (below).
            world = (self.pose @ source.matrix_local @ basis
                     @ source.matrix_local.inverted() @ self.rest @ target.matrix_local)
            return target.matrix_local.inverted() @ world
        fix = self.world_fix(source_name, target_name)
        return fix.inverted() @ basis @ fix

    def world(self, source_name, target_name, source_world):
        """Target world that mirrors the source's deformation.

        A vertex skinned to the source maps to its mirror image skinned to
        the target, so the mirrored mesh matches even when a vanilla rig
        places its left and right bones slightly asymmetrically.
        """
        source = self.obj.data.bones[source_name]
        target = self.obj.data.bones[target_name]
        return (self.pose @ source_world @ source.matrix_local.inverted()
                @ self.rest @ target.matrix_local)


def _is_weight_control(pose_bone):
    """Expression sliders and eye pads: channels are weights, not space."""
    return bool(pose_bone.get('expression')) or (
        pose_bone.name.endswith('_Look') and bool(pose_bone.bone.get('sub_face_owner')))


def snapshot_custom_sources(obj, names):
    """Per-bone (basis, world before own constraints, evaluated world)."""
    result = {}
    for name in names:
        bone = obj.pose.bones[name]
        rest = bone.bone.matrix_local
        if bone.parent is None:
            own = rest @ bone.matrix_basis
        else:
            own = bone.parent.matrix @ bone.parent.bone.matrix_local.inverted() @ rest @ bone.matrix_basis
        result[name] = (bone.matrix_basis.copy(), own, bone.matrix.copy())
    return result


def _depth(bone):
    depth = 0
    while bone.parent is not None:
        bone, depth = bone.parent, depth + 1
    return depth


def mirrored_custom_pose(space, snapshot, mirror_map, in_place=False, excluded=()):
    """Target bases for a snapshot, parents first.

    Call with the frame evaluated after every other bone was mirrored: a
    target whose parent is not written here is posed against that parent's
    actual mirrored matrix.
    """
    obj = space.obj
    targets = {}
    for name, entry in snapshot.items():
        target = name if in_place else mirror_map.get(name, name)
        if target in obj.pose.bones and target not in excluded:
            targets[target] = (name, entry)
    written = {}
    result = []
    for target in sorted(targets, key=lambda n: _depth(obj.data.bones[n])):
        name, (basis, own, evaluated) = targets[target]
        source = obj.pose.bones[name]
        if _is_weight_control(source):
            basis = basis.copy()
            # Eye pads and Look X / Y use authored Left/Right channels.
            if source.get('expression') == 'Look X / Y' or not source.get('expression'):
                basis.translation.x *= -1
        elif in_place:
            basis = space.basis(name, target, basis)
        else:
            bone = obj.data.bones[target]
            if bone.parent is None:
                parent_space = bone.matrix_local
            else:
                parent_world = written.get(bone.parent.name)
                if parent_world is None:
                    parent_world = obj.pose.bones[bone.parent.name].matrix
                parent_space = parent_world @ bone.parent.matrix_local.inverted() @ bone.matrix_local
            basis = parent_space.inverted() @ space.world(name, target, own)
            written[target] = space.world(name, target, evaluated)
        result.append((target, basis))
    return result


def snapshot_custom_pose(obj, names, mirror_map, in_place=False, pose_reflection=None):
    # Reflect the animation delta, not the rest translation: arbitrary custom
    # rest poses and controller offsets must stay neutral when their channels
    # are zero.
    space = MirrorSpace(obj, pose_reflection=pose_reflection)
    result = {}
    for name in names:
        source = obj.pose.bones[name]
        target_name = name if in_place else mirror_map.get(name, name)
        target = obj.pose.bones.get(target_name)
        if target is None:
            continue
        basis = source.matrix_basis.copy()
        eye_pad = source.name.endswith('_Look') and source.bone.get('sub_face_owner')
        if source.get('expression') or eye_pad:
            # Expression slider values are weights, not spatial translations.
            # Eye pads use authored Left/Right and Up/Down channels instead.
            if source.get('expression') == 'Look X / Y' or eye_pad:
                basis.translation.x *= -1
        else:
            basis = space.basis(name, target_name, basis)
        result[target_name] = basis
    return result


def custom_mirror_sources(names, animated, mirror_map, obj=None):
    """Custom bones to snapshot: the animated ones plus their counterparts.

    An unanimated counterpart still has to be written (its rest pose becomes
    the other side), otherwise a one-sided animation is duplicated, not moved.
    With ``obj``, unanimated custom ancestors are written too: a chain whose
    left and right rests differ can only be mirrored exactly as a whole.
    """
    names = set(names)
    animated = names & set(animated)
    sources = set(animated)
    if obj is not None:
        for name in animated:
            parent = obj.data.bones[name].parent
            while parent is not None and parent.name in names:
                sources.add(parent.name)
                parent = parent.parent
    for name in list(sources):
        sources.add(mirror_map.get(name, name))
    for name in names:
        if mirror_map.get(name, name) in sources:
            sources.add(name)
    return sources & names


def snapshot_custom_frames(context, obj, names, frames):
    """Source transforms for every frame, taken before anything is keyed:
    a new key on the opposite side changes later source interpolation."""
    scene = context.scene
    original_frame = scene.frame_current
    try:
        snapshots = []
        for frame in frames:
            scene.frame_set(frame)
            snapshots.append((frame, snapshot_custom_sources(obj, names)))
        return snapshots
    finally:
        scene.frame_set(original_frame)


def key_custom_pose(obj, pose, frame):
    from .anim_flip import keyframe_pose_bones
    bones = []
    for name, basis in pose:
        bone = obj.pose.bones[name]
        bone.matrix_basis = basis
        bones.append(bone)
    keyframe_pose_bones(bones, frame)


def mirror_custom_frames(context, obj, snapshots, mirror_map, in_place=False, excluded=(),
                         pose_reflection=None):
    """Key mirrored custom bones after every other bone has been mirrored."""
    space = MirrorSpace(obj, pose_reflection=pose_reflection)
    scene = context.scene
    original_frame = scene.frame_current
    try:
        for frame, snapshot in snapshots:
            scene.frame_set(frame)
            pose = mirrored_custom_pose(space, snapshot, mirror_map, in_place, excluded)
            key_custom_pose(obj, pose, frame)
    finally:
        scene.frame_set(original_frame)


_POLE_ANGLE_PATH = re.compile(r'^pose\.bones\["([^"]+)"\](\.constraints\[.+\]\.pole_angle)$')


def mirror_pole_angles(obj, action, names, mirror_map, in_place=False, frame=None):
    """Swap keyed IK pole angles to the opposite side, negated.

    A reflection reverses the pole's rotation about the root-to-target axis.
    ``frame`` limits the swap to keys on that frame.
    """
    from ..anim.fcurve_compat import get_fcurves, new_fcurve, find_fcurve, remove_fcurve
    moves = []
    for fc in list(get_fcurves(action)):
        match = _POLE_ANGLE_PATH.match(fc.data_path)
        if not match or match.group(1) not in names:
            continue
        target = match.group(1) if in_place else mirror_map.get(match.group(1), match.group(1))
        if target not in obj.pose.bones:
            continue
        target_path = f'pose.bones["{target}"]{match.group(2)}'
        try:
            obj.path_resolve(target_path)
        except ValueError:
            continue
        keys = [(k.co.x, -k.co.y, k.handle_left.x, -k.handle_left.y,
                 k.handle_right.x, -k.handle_right.y, k.interpolation)
                for k in fc.keyframe_points
                if frame is None or abs(k.co.x - frame) < 0.001]
        moves.append((fc.data_path, fc.array_index, target_path, keys, fc.group.name if fc.group else ''))
    if frame is None:
        for path, index, _target, _keys, _group in moves:
            existing = find_fcurve(action, path, index=index)
            if existing is not None:
                remove_fcurve(action, existing)
    for _path, index, target_path, keys, group in moves:
        fc = find_fcurve(action, target_path, index=index)
        if fc is None:
            fc = new_fcurve(action, target_path, index=index, action_group=group)
        for x, y, lx, ly, rx, ry, interpolation in keys:
            key = fc.keyframe_points.insert(x, y)
            key.handle_left = (lx, ly)
            key.handle_right = (rx, ry)
            key.interpolation = interpolation


# Side markers, plus the common "_flip" suffix for a mirrored copy.
_SIDE_MARKERS = {'l', 'r', '_l', '_r', '.l', '.r', 'left', 'right', '_left', '_right',
                 'flip', '_flip'}


def _pair_marked_counterparts(obj, mapping):
    """Pair bones like Hammer / HammerR or rope / rope_flip, where only one
    name carries a side.

    Name rules cannot tell which bone is the other side's, so both conditions
    are required: the names differ only by a side marker, and the bone sits
    at the mirrored rest position under the mirrored parent. ``EmeraldR``
    (R for red) has no such twin and stays unpaired.
    """
    from .anim_flip import _difference
    bones = obj.data.bones
    reflection = rest_reflection(obj).to_3x3()
    lonely = sorted((b for b in bones if mapping.get(b.name, b.name) == b.name),
                    key=lambda b: (_depth(b), b.name))
    for bone in lonely:
        if mapping.get(bone.name, bone.name) != bone.name:
            continue
        mirrored = reflection @ bone.head_local
        tolerance = max(1e-3, 0.02 * bone.length)
        if (mirrored - bone.head_local).length <= tolerance:
            continue
        parent = mapping.get(bone.parent.name, bone.parent.name) if bone.parent else None
        for other in lonely:
            if other is bone or mapping.get(other.name, other.name) != other.name:
                continue
            if (other.parent.name if other.parent else None) != parent:
                continue
            if {part.lower() for part in _difference(bone.name, other.name)} - {''} - _SIDE_MARKERS:
                continue
            if (other.head_local - mirrored).length <= tolerance:
                mapping[bone.name], mapping[other.name] = other.name, bone.name
                break
    return mapping


def control_mirror_map(obj):
    """Pair generated UUID/hash names through component bone assignments."""
    import json
    mapping = _pair_marked_counterparts(obj, create_mirror_map(obj.pose.bones.keys()))
    definitions = json.loads(obj.get('sub_custom_components', '[]'))
    owners = {}
    for definition in definitions:
        names = frozenset(item['bone'] for item in definition.get('bones', []))
        owners[definition['uid']] = (definition.get('kind'), names)
    counterpart = {}
    for uid, (kind, names) in owners.items():
        mirrored = frozenset(mapping.get(n, n) for n in names)
        matches = [other for other, entry in owners.items() if entry == (kind, mirrored)]
        if len(matches) == 1:
            counterpart[uid] = matches[0]
    controls = [p for p in obj.pose.bones if p.bone.get('sub_component_control')]
    labels = create_mirror_map({p.get('expression', '') for p in controls})
    for source in controls:
        uid = source.bone.get('sub_face_owner', source.bone.get('sub_component_id'))
        other = counterpart.get(uid)
        if other is None:
            continue
        label = source.get('expression', '')
        is_main = bool(source.bone.get('sub_component_id'))
        candidates = [p for p in controls
                      if p.bone.get('sub_face_owner', p.bone.get('sub_component_id')) == other
                      and p.get('expression', '') == labels.get(label, label)
                      and bool(p.bone.get('sub_component_id')) == is_main]
        if len(candidates) == 1:
            mapping[source.name] = candidates[0].name
    # Isolated components can have several independent handles, whose hash
    # names are identified by the original bone's output constraint.
    isolated = {}
    for bone in obj.pose.bones:
        for con in bone.constraints:
            if con.type == 'COPY_TRANSFORMS' and con.target == obj:
                helper = obj.pose.bones.get(con.subtarget)
                if helper and helper.bone.get('sub_face_helper') and helper.parent:
                    control = helper.parent
                    if control.bone.get('sub_component_kind') == 'ISOLATED':
                        isolated[bone.name] = control.name
    for original, control in isolated.items():
        opposite = isolated.get(mapping.get(original, original))
        if opposite:
            mapping[control] = opposite
    return mapping
