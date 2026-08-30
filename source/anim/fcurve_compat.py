"""
Compatibility layer for bpy.types.Action F-Curves on Blender 4 and 5.

Blender 4.0–4.3 expose the legacy `action.fcurves` / `action.groups` API.
Blender 4.4 introduced layered Actions (layers, strips, slots, channelbags)
and kept `action.fcurves` as a first-slot wrapper.
Blender 5.0 removed that wrapper. Code that used `action.fcurves.new(...)`
must now go through a channelbag.

These helpers feature-detect the available API so one codebase works on both.
"""

import re

import bpy

from ..blender_compat import (
    id_type_for_id_data,
    slot_display_name,
    slot_id_type,
    uses_legacy_action_fcurves,
)

_POSE_BONE_NAME = re.compile(r'^pose\.bones\[["\']([^"\']+)["\']')


def _get_or_create_first_slot(action: bpy.types.Action, id_type: str = 'OBJECT', slot_name: str | None = None):
    matches = [slot for slot in action.slots if slot_id_type(slot) == id_type]
    if slot_name:
        for slot in matches:
            if slot_display_name(slot) == slot_name:
                return slot
    for slot in matches:
        if slot_display_name(slot) != "Slot":
            return slot
    if matches:
        return matches[0]
    return action.slots.new(id_type, name=slot_name or "Slot")


def _get_or_create_channelbag(action: bpy.types.Action, id_type: str = 'OBJECT', ensure: bool = True):
    if not ensure:
        if len(action.slots) == 0 or len(action.layers) == 0 or len(action.layers[0].strips) == 0:
            return None
        slot = action.slots[0]
        strip = action.layers[0].strips[0]
        return strip.channelbag(slot, ensure=False)

    slot = _get_or_create_first_slot(action, id_type)

    if len(action.layers) == 0:
        layer = action.layers.new("Layer")
    else:
        layer = action.layers[0]

    if len(layer.strips) == 0:
        strip = layer.strips.new(type='KEYFRAME')
    else:
        strip = layer.strips[0]

    return strip.channelbag(slot, ensure=True)


def get_fcurves(action: bpy.types.Action, id_type: str = 'OBJECT'):
    """
    Equivalent of the old `action.fcurves` for the action's first slot.
    This is read-only: it does NOT create a layer/strip/slot/channelbag if
    none exist yet. Use new_fcurve() to create F-Curves.
    """
    if action is None:
        return []
    if uses_legacy_action_fcurves(action):
        return action.fcurves
    channelbag = _get_or_create_channelbag(action, id_type, ensure=False)
    return channelbag.fcurves if channelbag is not None else []


def _iter_channelbags(action: bpy.types.Action):
    """Yield existing channelbags for a layered action (Blender 5+)."""
    if action is None or uses_legacy_action_fcurves(action):
        return
    for layer in action.layers:
        for strip in layer.strips:
            for slot in action.slots:
                channelbag = strip.channelbag(slot, ensure=False)
                if channelbag is not None:
                    yield channelbag


def _find_fcurve_in_channelbag(channelbag, fcurve):
    """Return the channelbag fcurve matching fcurve, if any."""
    if channelbag is None or fcurve is None:
        return None
    for fc in channelbag.fcurves:
        if fc == fcurve:
            return fc
        if fc.data_path == fcurve.data_path and fc.array_index == fcurve.array_index:
            return fc
    return None


def find_fcurve(action: bpy.types.Action, data_path: str, index: int = 0, id_type: str = 'OBJECT'):
    """Equivalent of the old `action.fcurves.find(...)`."""
    if action is None:
        return None
    if uses_legacy_action_fcurves(action):
        return action.fcurves.find(data_path, index=index)
    for channelbag in _iter_channelbags(action):
        found = channelbag.fcurves.find(data_path, index=index)
        if found is not None:
            return found
    channelbag = _get_or_create_channelbag(action, id_type, ensure=False)
    if channelbag is None:
        return None
    return channelbag.fcurves.find(data_path, index=index)


def get_all_action_fcurves(action: bpy.types.Action, id_type: str = 'OBJECT'):
    """Return every fcurve on an action across all layered slots."""
    if action is None:
        return []
    if uses_legacy_action_fcurves(action):
        return list(get_fcurves(action))

    fcurves = []
    seen = set()
    for channelbag in _iter_channelbags(action):
        for fc in channelbag.fcurves:
            key = (fc.data_path, fc.array_index)
            if key not in seen:
                seen.add(key)
                fcurves.append(fc)
    if not fcurves:
        for slot_type in ('ARMATURE', 'OBJECT', id_type):
            for fc in get_fcurves(action, id_type=slot_type):
                key = (fc.data_path, fc.array_index)
                if key not in seen:
                    seen.add(key)
                    fcurves.append(fc)
    return fcurves


def _fcurve_resolves(path_resolve, fcurve):
    data_path = fcurve.data_path
    if fcurve.array_index:
        data_path = f"{data_path}[{fcurve.array_index}]"
    path_resolve(data_path)


def bone_names_from_action(action):
    """Extract pose bone names referenced by an action's fcurves."""
    names = set()
    for fc in get_all_action_fcurves(action):
        match = _POSE_BONE_NAME.match(fc.data_path)
        if match:
            names.add(match.group(1))
    return names


def action_matches_armature(action, armature):
    """True when the action animates at least one bone on the armature."""
    if action is None or armature is None:
        return False
    fcurves = get_all_action_fcurves(action)
    if not fcurves:
        return False
    armature_bones = {bone.name for bone in armature.data.bones}
    if bone_names_from_action(action) & armature_bones:
        return True
    path_resolve = armature.path_resolve
    for fc in fcurves:
        try:
            _fcurve_resolves(path_resolve, fc)
            return True
        except ValueError:
            continue
    return False


def action_matches_path_resolve(action, path_resolve):
    """True when at least one fcurve on the action resolves via path_resolve."""
    if action is None or path_resolve is None:
        return False
    fcurves = get_all_action_fcurves(action)
    if not fcurves:
        return False
    for fc in fcurves:
        try:
            _fcurve_resolves(path_resolve, fc)
            return True
        except ValueError:
            continue
    return False


def action_matches_id(action, armature_or_path_resolve):
    """Accept an armature object or a path_resolve callable."""
    if isinstance(armature_or_path_resolve, bpy.types.Object):
        return action_matches_armature(action, armature_or_path_resolve)
    return action_matches_path_resolve(action, armature_or_path_resolve)


def get_or_create_fcurves(action: bpy.types.Action, id_type: str = 'OBJECT'):
    """
    Like get_fcurves(), but ensures the layer/strip/slot/channelbag exist
    on Blender 5. On Blender 4 this is simply action.fcurves.
    """
    if action is None:
        return []
    if uses_legacy_action_fcurves(action):
        return action.fcurves
    channelbag = _get_or_create_channelbag(action, id_type, ensure=True)
    return channelbag.fcurves


def new_fcurve(action: bpy.types.Action, data_path: str, index: int = 0, action_group: str = '', id_type: str = 'OBJECT') -> bpy.types.FCurve:
    """Equivalent of the old `action.fcurves.new(...)`."""
    if uses_legacy_action_fcurves(action):
        return action.fcurves.new(data_path, index=index, action_group=action_group)
    channelbag = _get_or_create_channelbag(action, id_type, ensure=True)
    return channelbag.fcurves.new(data_path, index=index, group_name=action_group)


def remove_fcurve(action: bpy.types.Action, fcurve: bpy.types.FCurve, id_type: str = 'OBJECT'):
    """Equivalent of the old `action.fcurves.remove(fcurve)`."""
    if action is None or fcurve is None:
        return
    if uses_legacy_action_fcurves(action):
        action.fcurves.remove(fcurve)
        return
    for channelbag in _iter_channelbags(action):
        match = _find_fcurve_in_channelbag(channelbag, fcurve)
        if match is not None:
            channelbag.fcurves.remove(match)
            return
    channelbag = _get_or_create_channelbag(action, id_type, ensure=False)
    if channelbag is not None:
        match = _find_fcurve_in_channelbag(channelbag, fcurve)
        if match is not None:
            channelbag.fcurves.remove(match)


def get_id_action_fcurves(id_data):
    """
    Return the mutable F-Curve collection for id_data.animation_data.action,
    or None if the ID has no action. Safe on Blender 4 and 5.
    """
    try:
        action = id_data.animation_data.action
    except AttributeError:
        return None
    if action is None:
        return None
    return get_or_create_fcurves(action, id_type=id_type_for_id_data(id_data))


def _action_valid_for_armature(action, armature):
    return action_matches_armature(action, armature)


def _is_bake_backup_action(action):
    name = action.name
    return "SAP Data" in name or "_old" in name


def action_has_pose_fcurves(action):
    """True when the action contains at least one pose-bone fcurve."""
    if action is None:
        return False
    for fc in get_all_action_fcurves(action):
        if fc.data_path.startswith('pose.bones['):
            return True
    return False


def sap_armature_name_for_action(bone_action_name):
    """
    Return the armature object name encoded in a SAP Data action name, if any.

    Import creates SAP actions named ``{armature} {anim_stem} SAP Data``.
    """
    sap_suffix = f" {bone_action_name} SAP Data"
    for sap_action in bpy.data.actions:
        if sap_action.name.endswith(sap_suffix):
            return sap_action.name[:-len(sap_suffix)]
    return None


def action_frame_range_safe(action):
    """Return a usable (start, end) frame range for baking."""
    if action is None:
        return 1, 1
    try:
        start, end = action.frame_range
        start, end = int(start), int(end)
        if end > start:
            return start, end
    except (AttributeError, TypeError, ValueError):
        pass

    frames = []
    for fc in get_all_action_fcurves(action):
        for kp in fc.keyframe_points:
            frames.append(kp.co[0])
    if frames:
        return int(min(frames)), int(max(frames))
    return 1, 1


def _expand_bake_armatures(armatures):
    """Include armatures referenced by SAP Data import pairs."""
    expanded = []
    seen = set()

    def add_armature(ob):
        if ob and getattr(ob, 'type', None) == 'ARMATURE' and ob.name not in seen:
            seen.add(ob.name)
            expanded.append(ob)

    for ob in armatures:
        add_armature(ob)

    for action in bpy.data.actions:
        if _is_bake_backup_action(action) or not action_has_pose_fcurves(action):
            continue
        armature_name = sap_armature_name_for_action(action.name)
        if not armature_name:
            continue
        add_armature(bpy.data.objects.get(armature_name))

    return expanded


def collect_actions_for_armatures(armatures):
    """
    Return actions that resolve on any of the given armatures and are eligible
    for retarget baking (skips SAP Data and _old backups).
    """
    armatures = _expand_bake_armatures(armatures)
    if not armatures:
        return []

    armature_names = {ob.name for ob in armatures}
    results = []
    seen = set()
    for action in bpy.data.actions:
        name = action.name
        if name in seen or _is_bake_backup_action(action):
            continue
        if any(_action_valid_for_armature(action, ob) for ob in armatures):
            seen.add(name)
            results.append(action)
            continue
        if not action_has_pose_fcurves(action):
            continue
        sap_armature = sap_armature_name_for_action(name)
        if sap_armature and sap_armature in armature_names:
            seen.add(name)
            results.append(action)
    return results


def collect_actions_for_bake(action_armature, bake_armature, extra_armatures=()):
    """Collect pose actions for a constrained/visual bake pair."""
    armatures = [action_armature, bake_armature, *extra_armatures]
    return collect_actions_for_armatures(armatures)
