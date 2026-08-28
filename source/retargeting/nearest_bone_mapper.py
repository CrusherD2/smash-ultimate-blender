"""Map retarget bone slots by nearest world-space position between armatures."""

_LIMB_GROUPS = (
    'right_arm', 'left_arm', 'right_arm_ik', 'left_arm_ik',
    'right_leg', 'left_leg', 'right_leg_ik', 'left_leg_ik',
)

_LIMB_SLOTS = (
    'shoulder', 'arm', 'arm_twist', 'arm_twist_02',
    'forearm', 'forearm_twist', 'forearm_twist_02', 'hand',
    'upleg', 'upleg_twist', 'upleg_twist_02',
    'leg', 'leg_twist', 'leg_twist_02', 'foot', 'toe',
)

_SPINE_SLOTS = ('head', 'neck', 'spine2', 'spine1', 'spine', 'hips')

_FACE_SLOTS = ('jaw', 'left_eye', 'right_eye', 'left_upLid', 'right_upLid')

_FINGER_GROUPS = ('left_fingers', 'right_fingers')
_FINGER_NAMES = ('thumb', 'index', 'middle', 'ring', 'pinky')
_FINGER_SLOTS = ('meta', 'a', 'b', 'c')

# Process larger / structural bones first so they claim the best matches.
_SLOT_PRIORITY = [
    ('root', None, None),
    ('spine', None, 'hips'),
    ('spine', None, 'spine'),
    ('spine', None, 'spine1'),
    ('spine', None, 'spine2'),
    ('spine', None, 'neck'),
    ('spine', None, 'head'),
]
for _group in _LIMB_GROUPS:
    for _slot in _LIMB_SLOTS:
        _SLOT_PRIORITY.append((_group, None, _slot))
for _group in _FINGER_GROUPS:
    for _finger in _FINGER_NAMES:
        for _slot in _FINGER_SLOTS:
            _SLOT_PRIORITY.append((_group, _finger, _slot))
for _slot in _FACE_SLOTS:
    _SLOT_PRIORITY.append(('face', None, _slot))


def _bone_world_head(armature_obj, bone_name):
    bone = armature_obj.data.bones.get(bone_name)
    if not bone:
        return None
    return armature_obj.matrix_world @ bone.head_local


def _find_nearest_bone(world_pos, target_armature_obj, used_bones):
    best_name = ""
    best_dist = float('inf')

    for bone in target_armature_obj.data.bones:
        if bone.name in used_bones:
            continue
        bone_pos = target_armature_obj.matrix_world @ bone.head_local
        dist = (bone_pos - world_pos).length
        if dist < best_dist:
            best_dist = dist
            best_name = bone.name

    return best_name


def _get_slot_bone_name(settings, group_name, finger_name, slot_name):
    if group_name == 'root':
        return settings.root or ""

    group = getattr(settings, group_name)
    if finger_name:
        finger = getattr(group, finger_name)
        return getattr(finger, slot_name, "") or ""

    return getattr(group, slot_name, "") or ""


def _set_slot_bone_name(settings, group_name, finger_name, slot_name, bone_name):
    if group_name == 'root':
        settings.root = bone_name
        return

    group = getattr(settings, group_name)
    if finger_name:
        setattr(getattr(group, finger_name), slot_name, bone_name)
    else:
        setattr(group, slot_name, bone_name)


def map_bones_by_proximity(reference_armature_obj, target_armature_obj):
    """Fill target retarget settings using nearest bones to reference mappings.

    Returns (mapped_count, custom_count).
    """
    ref_settings = reference_armature_obj.data.expykit_retarget
    target_settings = target_armature_obj.data.expykit_retarget
    used_bones = set()
    mapped_count = 0

    for group_name, finger_name, slot_name in _SLOT_PRIORITY:
        ref_bone = _get_slot_bone_name(ref_settings, group_name, finger_name, slot_name)
        if not ref_bone:
            continue

        world_pos = _bone_world_head(reference_armature_obj, ref_bone)
        if world_pos is None:
            continue

        nearest = _find_nearest_bone(world_pos, target_armature_obj, used_bones)
        if not nearest:
            continue

        _set_slot_bone_name(target_settings, group_name, finger_name, slot_name, nearest)
        used_bones.add(nearest)
        mapped_count += 1

    custom_count = 0
    ref_settings.custom.migrate_legacy_bones()
    for identifier, ref_bone in ref_settings.custom.get_bones():
        world_pos = _bone_world_head(reference_armature_obj, ref_bone)
        if world_pos is None:
            continue

        nearest = _find_nearest_bone(world_pos, target_armature_obj, used_bones)
        if not nearest:
            continue

        target_settings.custom.add_bone(identifier, nearest)
        used_bones.add(nearest)
        custom_count += 1

    if ref_settings.custom.name:
        ref_bone = ref_settings.custom.name
        world_pos = _bone_world_head(reference_armature_obj, ref_bone)
        if world_pos is not None:
            nearest = _find_nearest_bone(world_pos, target_armature_obj, used_bones)
            if nearest:
                from ...expy_kit.properties import _clean_custom_identifier
                identifier = _clean_custom_identifier(ref_bone)
                target_settings.custom.add_bone(identifier, nearest)
                used_bones.add(nearest)
                custom_count += 1

    target_settings.custom.sync_all_dynamic_props()
    return mapped_count, custom_count
