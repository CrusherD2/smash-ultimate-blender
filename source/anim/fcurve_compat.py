"""
Compatibility layer for bpy.types.Action's legacy F-Curve API.

Blender 5.0 fully removed the legacy `action.fcurves` / `action.groups` /
`action.id_root` properties (they were deprecated back in 4.4 when the
layered Action system - layers, strips, slots, channelbags - was
introduced). Code that used to do `action.fcurves.new(...)` or iterate
over `action.fcurves` must now go through a "channelbag", which belongs
to a specific (layer, strip, slot) combination.

Since this plugin only ever uses a single layer with a single keyframe strip,
and a single slot pe action, these helpers assume that simple case and always
operate on the action's first slot - creating the layer/strip/slot as needed. 
This mirrors the "first slot" convenience behavior that Blender's own legacy
`action.fcurves` compatibility properties used to provide.
"""

import bpy


def _get_or_create_first_slot(action: bpy.types.Action, id_type: str = 'OBJECT') -> bpy.types.ActionSlot:
    if len(action.slots) == 0:
        return action.slots.new(id_type, name="Slot")
    return action.slots[0]


def _get_or_create_channelbag(action: bpy.types.Action, id_type: str = 'OBJECT', ensure: bool = True):
    if not ensure:
        # Read-only path: don't create anything, just look at what's there.
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
    none exist yet (matching the old API, where an untouched action's
    `.fcurves` was simply an empty collection). Use new_fcurve() to create
    F-Curves, which does ensure the necessary structure exists.
    """
    channelbag = _get_or_create_channelbag(action, id_type, ensure=False)
    return channelbag.fcurves if channelbag is not None else []


def get_or_create_fcurves(action: bpy.types.Action, id_type: str = 'OBJECT'):
    """
    Like get_fcurves(), but ensures the layer/strip/slot/channelbag exist,
    creating them if necessary, and returns the real mutable
    ActionChannelbagFCurves collection (so callers can call .new()/.find()/
    .remove() on it directly, same as the old action.fcurves). Note that
    the new API's .new() takes a `group_name` keyword argument, where the
    legacy API used `action_group`.
    """
    channelbag = _get_or_create_channelbag(action, id_type, ensure=True)
    return channelbag.fcurves


def new_fcurve(action: bpy.types.Action, data_path: str, index: int = 0, action_group: str = '', id_type: str = 'OBJECT') -> bpy.types.FCurve:
    """Equivalent of the old `action.fcurves.new(...)`."""
    channelbag = _get_or_create_channelbag(action, id_type, ensure=True)
    return channelbag.fcurves.new(data_path, index=index, group_name=action_group)


def find_fcurve(action: bpy.types.Action, data_path: str, index: int = 0, id_type: str = 'OBJECT'):
    """Equivalent of the old `action.fcurves.find(...)`."""
    channelbag = _get_or_create_channelbag(action, id_type, ensure=False)
    if channelbag is None:
        return None
    return channelbag.fcurves.find(data_path, index=index)


def remove_fcurve(action: bpy.types.Action, fcurve: bpy.types.FCurve, id_type: str = 'OBJECT'):
    """Equivalent of the old `action.fcurves.remove(fcurve)`."""
    channelbag = _get_or_create_channelbag(action, id_type, ensure=False)
    if channelbag is not None:
        channelbag.fcurves.remove(fcurve)
