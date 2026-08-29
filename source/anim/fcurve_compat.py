"""
Compatibility layer for bpy.types.Action F-Curves on Blender 4 and 5.

Blender 4.0–4.3 expose the legacy `action.fcurves` / `action.groups` API.
Blender 4.4 introduced layered Actions (layers, strips, slots, channelbags)
and kept `action.fcurves` as a first-slot wrapper.
Blender 5.0 removed that wrapper. Code that used `action.fcurves.new(...)`
must now go through a channelbag.

These helpers feature-detect the available API so one codebase works on both.
"""

import bpy

from ..blender_compat import uses_legacy_action_fcurves


def _get_or_create_first_slot(action: bpy.types.Action, id_type: str = 'OBJECT'):
    if len(action.slots) == 0:
        return action.slots.new(id_type, name="Slot")
    return action.slots[0]


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
    for channelbag in _iter_channelbags(action):
        fcurves.extend(channelbag.fcurves)
    if not fcurves:
        fcurves.extend(get_fcurves(action, id_type=id_type))
    return fcurves


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
    return get_or_create_fcurves(action)


def _action_valid_for_armature(action, armature):
    """True when every fcurve path resolves on the given armature."""
    if action is None or armature is None:
        return False
    path_resolve = armature.path_resolve
    for fc in get_fcurves(action):
        data_path = fc.data_path
        if fc.array_index:
            data_path = f"{data_path}[{fc.array_index}]"
        try:
            path_resolve(data_path)
        except ValueError:
            return False
    return True


def collect_actions_for_armatures(armatures):
    """
    Return actions that resolve on any of the given armatures and are eligible
    for retarget baking (skips SAP Data and _old backups).
    """
    armatures = [
        ob for ob in armatures
        if ob and getattr(ob, 'type', None) == 'ARMATURE'
    ]
    if not armatures:
        return []

    results = []
    seen = set()
    for action in bpy.data.actions:
        name = action.name
        if name in seen:
            continue
        if "SAP Data" in name or "_old" in name:
            continue
        if any(_action_valid_for_armature(action, ob) for ob in armatures):
            seen.add(name)
            results.append(action)
    return results
