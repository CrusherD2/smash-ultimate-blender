"""Rest-relative mirroring for bones authored outside the Smash importer."""
from mathutils import Matrix

from .anim_flip import find_custom_mirror_bones, create_mirror_map


def custom_mirror_names(obj):
    names = set(find_custom_mirror_bones(obj))
    names.update(p.name for p in obj.pose.bones if p.bone.get('sub_component_control'))
    return {name for name in names if not obj.data.bones[name].get('sub_face_helper')
            and not name.startswith('BL_CC_MCH_')}


# Smash's Z reflection becomes Blender armature-space Y for a parentless bone.
_ARMATURE_REFLECTION = Matrix.Diagonal((1.0, -1.0, 1.0, 1.0))
# anim_flip negates each Smash bone's local Z (translateZ, rotateX/Y), which
# is also Z in the imported Blender bone axes.
_SMASH_LOCAL_FLIP = Matrix.Diagonal((1.0, 1.0, -1.0, 1.0))


def _rest_axes(bone):
    return bone.matrix_local.to_3x3().normalized().to_4x4()


def mirror_change(obj, source_name, target_name, custom=None, _cache=None):
    """Basis conjugation C so that target basis = C @ source basis @ C⁻¹.

    A mirrored bone must follow its mirrored parent: world mirror is
    target = R @ source @ S, where each Smash parent's S is its local Z flip
    and an extra parent's S is its own C⁻¹. Parentless bones use the armature
    reflection. Mirroring every extra bone across the armature plane instead
    breaks as soon as its parent is flipped in local space (tails swing into
    the floor).
    """
    if custom is None:
        custom = custom_mirror_names(obj)
    if _cache is None:
        _cache = {}
    key = (source_name, target_name)
    if key in _cache:
        return _cache[key]
    source = obj.data.bones[source_name]
    target = obj.data.bones[target_name]
    if source.parent is None or target.parent is None:
        change = _rest_axes(target).inverted() @ _ARMATURE_REFLECTION @ _rest_axes(source)
    else:
        if source.parent.name in custom:
            parent_flip = mirror_change(obj, source.parent.name, target.parent.name, custom, _cache)
        else:
            parent_flip = _SMASH_LOCAL_FLIP
        offset_s = _rest_axes(source.parent).inverted() @ _rest_axes(source)
        offset_t = _rest_axes(target.parent).inverted() @ _rest_axes(target)
        change = offset_t.inverted() @ parent_flip @ offset_s
    _cache[key] = change
    return change


def snapshot_custom_pose(obj, names, mirror_map, in_place=False):
    # Reflect the animation delta, not the rest translation: arbitrary custom
    # rest poses and controller offsets must stay neutral when their channels
    # are zero.
    custom = custom_mirror_names(obj)
    cache = {}
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
            change = mirror_change(obj, name, target_name, custom, cache)
            basis = change @ basis @ change.inverted()
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


def mirror_custom_frames(context, obj, names, mirror_map, frames, in_place=False, excluded=()):
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
            pose = snapshot_custom_pose(obj, names, mirror_map, in_place)
            snapshots.append((frame, {n: m for n, m in pose.items() if n not in excluded}))
        for frame, pose in snapshots:
            keyframe_pose_bones(apply_custom_pose(obj, pose), frame)
    finally:
        scene.frame_set(original_frame)


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
