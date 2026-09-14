"""Rest-relative mirroring for bones authored outside the Smash importer."""
from mathutils import Matrix

from .anim_flip import find_custom_mirror_bones, create_mirror_map


def custom_mirror_names(obj):
    names = set(find_custom_mirror_bones(obj))
    names.update(p.name for p in obj.pose.bones if p.bone.get('sub_component_control'))
    return {name for name in names if not obj.data.bones[name].get('sub_face_helper')
            and not name.startswith('BL_CC_MCH_')}


def snapshot_custom_pose(obj, names, mirror_map, in_place=False):
    # Smash's Z reflection becomes Blender armature-space Y. Reflect the
    # animation delta, not the rest translation: arbitrary custom rest poses
    # and controller offsets must stay neutral when their channels are zero.
    reflection = Matrix.Diagonal((1.0, -1.0, 1.0, 1.0))
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
            source_axes = source.bone.matrix_local.to_3x3().normalized().to_4x4()
            target_axes = target.bone.matrix_local.to_3x3().normalized().to_4x4()
            change = target_axes.inverted() @ reflection @ source_axes
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
