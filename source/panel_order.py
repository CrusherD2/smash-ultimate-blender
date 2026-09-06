"""Persistent ordering for top-level panels in the Ultimate sidebar tab."""

import bpy


# Preserve the add-on's established panel order the first time the preference is
# initialized. Newly added panels are appended automatically by sync_preferences.
DEFAULT_PANEL_ORDER = (
    "SUB_PT_import_model",
    "SUB_PT_export_model",
    "SUB_PT_ultimate_exo_skel",
    "SUB_PT_import_anim",
    "SUB_PT_raw_animations",
    "SUB_PT_export_anim",
    "SUB_PT_animation_tools",
    "SUB_PT_model_tools",
    "SUB_PT_collection_presets",
    "SUB_PT_face_picker",
    "SUB_PT_misc_utilities",
    "SUB_PT_stage_tools",
    "SUB_PT_reimport_materials",
    "SUB_PT_attribute_renamer",
    "SUB_PT_swing_io",
    "SUB_PT_sub_smush_anim_data_main",
    "SUB_PT_retargeting_main",
    "SUB_PT_update_plugin",
)


def _registered_ultimate_panels():
    panels = {}
    for type_name in dir(bpy.types):
        panel_type = getattr(bpy.types, type_name, None)
        if not isinstance(panel_type, type) or not issubclass(panel_type, bpy.types.Panel):
            continue
        if getattr(panel_type, "bl_space_type", "") != "VIEW_3D":
            continue
        if getattr(panel_type, "bl_region_type", "") != "UI":
            continue
        if getattr(panel_type, "bl_category", "") != "Ultimate":
            continue
        if getattr(panel_type, "bl_parent_id", ""):
            continue
        module_name = getattr(panel_type, "__module__", "")
        if ".source." not in module_name:
            continue
        panel_id = panel_type.bl_rna.identifier
        panels[panel_id] = panel_type
    return panels


def _default_sort_key(panel_id, panel_type):
    try:
        return (0, DEFAULT_PANEL_ORDER.index(panel_id))
    except ValueError:
        return (1, int(getattr(panel_type, "bl_order", 0)), panel_type.bl_label.casefold())


def sync_preferences(preferences):
    """Reconcile saved entries with the currently registered Ultimate panels."""
    panels = _registered_ultimate_panels()
    saved_ids = {item.panel_id for item in preferences.ultimate_panel_order}

    # Entries can become stale when a feature is removed or renamed.
    for index in reversed(range(len(preferences.ultimate_panel_order))):
        if preferences.ultimate_panel_order[index].panel_id not in panels:
            preferences.ultimate_panel_order.remove(index)

    missing = [panel_id for panel_id in panels if panel_id not in saved_ids]
    missing.sort(key=lambda panel_id: _default_sort_key(panel_id, panels[panel_id]))
    for panel_id in missing:
        item = preferences.ultimate_panel_order.add()
        item.panel_id = panel_id
        item.name = panels[panel_id].bl_label

    for item in preferences.ultimate_panel_order:
        panel_type = panels.get(item.panel_id)
        if panel_type is not None and item.name != panel_type.bl_label:
            item.name = panel_type.bl_label

    if len(preferences.ultimate_panel_order):
        preferences.ultimate_panel_order_index = min(
            preferences.ultimate_panel_order_index,
            len(preferences.ultimate_panel_order) - 1,
        )
    else:
        preferences.ultimate_panel_order_index = 0
    return panels


def apply_saved_order(preferences=None):
    if preferences is None:
        from .addon_preferences import get_addon_preferences

        preferences = get_addon_preferences()
    if preferences is None:
        return

    panels = sync_preferences(preferences)
    for index, item in enumerate(preferences.ultimate_panel_order):
        panel_type = panels.get(item.panel_id)
        if panel_type is not None:
            # Gaps make it easy to insert future built-in defaults without ties.
            panel_type.bl_order = (index + 1) * 10

    # Blender exposes restricted data while an add-on is being enabled. The
    # order is still applied then; redrawing is only needed for live changes.
    for screen in getattr(bpy.data, "screens", ()):
        for area in screen.areas:
            if area.type == "VIEW_3D":
                area.tag_redraw()


def reset_to_default(preferences):
    panels = _registered_ultimate_panels()
    ordered_ids = sorted(
        panels,
        key=lambda panel_id: _default_sort_key(panel_id, panels[panel_id]),
    )
    preferences.ultimate_panel_order.clear()
    for panel_id in ordered_ids:
        item = preferences.ultimate_panel_order.add()
        item.panel_id = panel_id
        item.name = panels[panel_id].bl_label
    preferences.ultimate_panel_order_index = 0
    apply_saved_order(preferences)
