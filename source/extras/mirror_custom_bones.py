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


def apply_custom_pose(obj, pose):
    applied = []
    for name, basis in pose.items():
        bone = obj.pose.bones[name]
        bone.matrix_basis = basis
        applied.append(bone)
    return applied


def custom_mirror_sources(names, animated, mirror_map):
    """Custom bones to snapshot: the animated ones plus their counterparts.

    An unanimated counterpart still has to be written (its rest pose becomes
    the other side), otherwise a one-sided animation is duplicated, not moved.
    """
    animated = set(names) & set(animated)
    sources = set(animated)
    for name in names:
        if mirror_map.get(name, name) in animated:
            sources.add(name)
    sources.update(mirror_map.get(name, name) for name in animated)
    return sources & set(names)


def mirror_custom_frames(context, obj, names, mirror_map, frames, in_place=False, excluded=(),
                         pose_reflection=None):
    """Rest-relative mirror of custom bones, keyed on every given frame."""
    from .anim_flip import keyframe_pose_bones
    scene = context.scene
    original_frame = scene.frame_current
    snapshots = []
    try:
        # Snapshot every frame before keying: a new key on the opposite side
        # changes the interpolation of later source frames.
        for frame in frames:
            scene.frame_set(frame)
            pose = snapshot_custom_pose(obj, names, mirror_map, in_place, pose_reflection)
            snapshots.append((frame, {n: m for n, m in pose.items() if n not in excluded}))
        for frame, pose in snapshots:
            keyframe_pose_bones(apply_custom_pose(obj, pose), frame)
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


def control_mirror_map(obj):
    """Pair generated UUID/hash names through component bone assignments."""
    import json
    mapping = create_mirror_map(obj.pose.bones.keys())
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
