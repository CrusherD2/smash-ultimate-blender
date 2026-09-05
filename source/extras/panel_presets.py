"""Ultimate sidebar Panel Presets — show/hide top-level Ultimate panels."""

from __future__ import annotations

import json
from pathlib import Path

import bpy
from bpy.app.handlers import persistent
from bpy.props import (
    BoolProperty,
    CollectionProperty,
    IntProperty,
    StringProperty,
)
from bpy.types import Operator, Panel, PropertyGroup, UIList

# Always visible — never filtered by presets
_PRESETS_PANEL_ID = "SUB_PT_panel_presets"

# Preferred display order / labels for known panels
_PANEL_META = (
    ("SUB_PT_import_model", "Model Importer"),
    ("SUB_PT_export_model", "Model Exporter"),
    ("SUB_PT_import_anim", "Animation Importer"),
    ("SUB_PT_raw_animations", "Raw Animations"),
    ("SUB_PT_export_anim", "Animation Exporter"),
    ("SUB_PT_animation_tools", "Animation Tools"),
    ("SUB_PT_model_tools", "Model Tools"),
    ("SUB_PT_misc_utilities", "Misc."),
    ("SUB_PT_face_picker", "Easy Facial Animation"),
    ("SUB_PT_retargeting_main", "Retargeting"),
    ("SUB_PT_stage_tools", "Stage Tools"),
    ("SUB_PT_swing_io", "Swing"),
    ("SUB_PT_ultimate_exo_skel", "Magic Exo Skel Maker"),
    ("SUB_PT_reimport_materials", "Material Re-Importer"),
    ("SUB_PT_attribute_renamer", "Attribute Renamer"),
    ("SUB_PT_update_plugin", "Update Available!"),
)

_ANIMATE_DEFAULT_VISIBLE = {
    "SUB_PT_import_model",
    "SUB_PT_import_anim",
    "SUB_PT_export_anim",
    "SUB_PT_animation_tools",
}

_MODELING_DEFAULT_VISIBLE = {
    "SUB_PT_import_model",
    "SUB_PT_export_model",
    "SUB_PT_model_tools",
    "SUB_PT_ultimate_exo_skel",
}

_wrapped_polls: dict[str, object] = {}


def _presets_json_path() -> Path:
    return Path(bpy.utils.user_resource("CONFIG")) / "smash_ultimate_panel_presets.json"


def _tag_redraw(context=None):
    wm = bpy.context.window_manager if context is None else getattr(context, "window_manager", None)
    if wm is None:
        return
    for window in wm.windows:
        screen = getattr(window, "screen", None)
        if screen is None:
            continue
        for area in screen.areas:
            if area.type == "VIEW_3D":
                area.tag_redraw()


def _panel_class_id(cls) -> str:
    """Stable id for preset matching / poll wrapping."""
    explicit = cls.__dict__.get("bl_idname")
    if explicit:
        return str(explicit)
    name = getattr(cls, "__name__", "") or ""
    return name


def discover_controllable_panels():
    """Top-level Ultimate VIEW_3D panels (excluding Panel Presets)."""
    meta = {pid: label for pid, label in _PANEL_META}
    found = {}

    for attr in dir(bpy.types):
        cls = getattr(bpy.types, attr, None)
        if not isinstance(cls, type):
            continue
        try:
            if not issubclass(cls, Panel):
                continue
        except TypeError:
            continue
        if getattr(cls, "bl_category", None) != "Ultimate":
            continue
        if getattr(cls, "bl_space_type", None) != "VIEW_3D":
            continue
        if getattr(cls, "bl_parent_id", None):
            continue
        panel_id = _panel_class_id(cls) or attr
        if not panel_id or panel_id == _PRESETS_PANEL_ID:
            continue
        # Prefer the primary bpy.types attribute matching the class name
        if attr not in {panel_id, getattr(cls, "bl_idname", None), cls.__name__}:
            continue
        label = meta.get(panel_id) or getattr(cls, "bl_label", None) or panel_id
        found[panel_id] = (cls, label)

    ordered = []
    seen = set()
    for panel_id, label in _PANEL_META:
        if panel_id in found:
            ordered.append((panel_id, found[panel_id][0], found[panel_id][1]))
            seen.add(panel_id)
    for panel_id, (cls, label) in sorted(found.items(), key=lambda item: item[1][1].lower()):
        if panel_id not in seen:
            ordered.append((panel_id, cls, label))
    return ordered


def _preset_collection(scene):
    return getattr(scene, "sub_panel_presets", None)


def _active_preset(scene):
    presets = _preset_collection(scene)
    if presets is None or not len(presets):
        return None
    index = int(getattr(scene, "sub_panel_presets_index", 0) or 0)
    if index < 0 or index >= len(presets):
        return None
    return presets[index]


def panel_allowed(context, panel_id: str) -> bool:
    """True if this top-level panel should draw under the active preset."""
    if panel_id == _PRESETS_PANEL_ID:
        return True
    scene = getattr(context, "scene", None)
    if scene is None:
        return True
    presets = _preset_collection(scene)
    if presets is None or not len(presets):
        return True
    preset = _active_preset(scene)
    if preset is None:
        return True
    if getattr(preset, "show_all", False):
        return True
    for entry in preset.panels:
        if entry.panel_id == panel_id:
            return bool(entry.enabled)
    return False


def _sync_preset_panels(preset, *, default_enabled=True, enabled_ids=None):
    """Ensure preset.panels matches currently known Ultimate panels."""
    known = discover_controllable_panels()
    known_ids = {pid for pid, _cls, _label in known}

    for i in range(len(preset.panels) - 1, -1, -1):
        if preset.panels[i].panel_id not in known_ids:
            preset.panels.remove(i)

    existing = {entry.panel_id: entry for entry in preset.panels}
    for panel_id, _cls, label in known:
        entry = existing.get(panel_id)
        if entry is None:
            entry = preset.panels.add()
            entry.panel_id = panel_id
            if enabled_ids is not None:
                entry.enabled = panel_id in enabled_ids
            else:
                entry.enabled = bool(default_enabled)
        entry.label = label


def serialize_presets(scene) -> dict:
    presets = _preset_collection(scene)
    payload = {
        "version": 1,
        "active": int(getattr(scene, "sub_panel_presets_index", 0) or 0),
        "presets": [],
    }
    if presets is None:
        return payload
    for preset in presets:
        payload["presets"].append(
            {
                "name": preset.name,
                "show_all": bool(preset.show_all),
                "is_builtin": bool(preset.is_builtin),
                "panels": [
                    {
                        "panel_id": entry.panel_id,
                        "enabled": bool(entry.enabled),
                    }
                    for entry in preset.panels
                ],
            }
        )
    return payload


def apply_presets_payload(scene, payload: dict):
    """Replace scene presets from a saved JSON payload."""
    presets = _preset_collection(scene)
    if presets is None or not isinstance(payload, dict):
        return False

    presets.clear()
    for item in payload.get("presets") or []:
        preset = presets.add()
        preset.name = str(item.get("name") or "Preset")
        preset.show_all = bool(item.get("show_all", False))
        preset.is_builtin = bool(item.get("is_builtin", False))
        enabled_ids = {
            str(p.get("panel_id"))
            for p in (item.get("panels") or [])
            if p.get("enabled")
        }
        if preset.show_all:
            _sync_preset_panels(preset, default_enabled=True)
        else:
            _sync_preset_panels(preset, enabled_ids=enabled_ids)
            by_id = {e.panel_id: e for e in preset.panels}
            for p in item.get("panels") or []:
                entry = by_id.get(str(p.get("panel_id")))
                if entry is not None:
                    entry.enabled = bool(p.get("enabled", False))

    if not len(presets):
        ensure_default_presets(scene, force_builtins=True)
        return True

    active = int(payload.get("active", 0) or 0)
    scene.sub_panel_presets_index = max(0, min(active, len(presets) - 1))
    return True


def save_presets_to_disk(scene) -> Path:
    path = _presets_json_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(serialize_presets(scene), indent=2), encoding="utf-8")
    return path


def load_presets_from_disk(scene) -> bool:
    path = _presets_json_path()
    if not path.is_file():
        return False
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return False
    return apply_presets_payload(scene, payload)


def ensure_default_presets(scene, *, force_builtins=False):
    """Create built-in presets when empty. Never call from Panel.draw."""
    presets = _preset_collection(scene)
    if presets is None:
        return False

    if len(presets) and not force_builtins:
        for preset in presets:
            if preset.show_all:
                _sync_preset_panels(preset, default_enabled=True)
            else:
                enabled = {e.panel_id for e in preset.panels if e.enabled}
                _sync_preset_panels(preset, enabled_ids=enabled)
        return False

    if not force_builtins and load_presets_from_disk(scene):
        return True

    presets.clear()

    all_preset = presets.add()
    all_preset.name = "All Panels"
    all_preset.show_all = True
    all_preset.is_builtin = True
    _sync_preset_panels(all_preset, default_enabled=True)

    animate = presets.add()
    animate.name = "Animate"
    animate.show_all = False
    animate.is_builtin = True
    _sync_preset_panels(animate, enabled_ids=set(_ANIMATE_DEFAULT_VISIBLE))

    modeling = presets.add()
    modeling.name = "Modeling"
    modeling.show_all = False
    modeling.is_builtin = True
    _sync_preset_panels(modeling, enabled_ids=set(_MODELING_DEFAULT_VISIBLE))

    scene.sub_panel_presets_index = 0
    return True


_seed_scheduled = False


def _seed_presets_timer():
    global _seed_scheduled
    _seed_scheduled = False
    try:
        for scene in bpy.data.scenes:
            ensure_default_presets(scene)
        _tag_redraw()
    except Exception:
        pass
    return None


def schedule_seed_presets():
    global _seed_scheduled
    if _seed_scheduled:
        return
    if bpy.app.timers.is_registered(_seed_presets_timer):
        return
    _seed_scheduled = True
    bpy.app.timers.register(_seed_presets_timer, first_interval=0.0)


def _on_preset_index_update(self, context):
    try:
        ensure_default_presets(self)
    except Exception:
        schedule_seed_presets()
    _tag_redraw(context)


def _on_panel_flag_update(self, context):
    _tag_redraw(context)


class SUB_PG_panel_preset_entry(PropertyGroup):
    panel_id: StringProperty(name="Panel ID", default="")
    label: StringProperty(name="Label", default="")
    enabled: BoolProperty(
        name="Visible",
        description="Show this panel when this preset is active",
        default=True,
        update=_on_panel_flag_update,
    )


class SUB_PG_panel_preset(PropertyGroup):
    name: StringProperty(name="Name", default="New Preset")
    show_all: BoolProperty(
        name="Show All",
        description="Ignore the checklist and show every Ultimate panel",
        default=False,
        update=_on_panel_flag_update,
    )
    is_builtin: BoolProperty(name="Builtin", default=False)
    panels: CollectionProperty(type=SUB_PG_panel_preset_entry)


class SUB_UL_panel_presets(UIList):
    bl_idname = "SUB_UL_panel_presets"

    def draw_item(self, _context, layout, _data, item, _icon, _active_data, _active_propname, _index):
        row = layout.row(align=True)
        row.prop(item, "name", text="", emboss=False, icon="PRESET")
        if item.show_all:
            row.label(text="", icon="HIDE_OFF")


class SUB_OP_panel_preset_ensure(Operator):
    bl_idname = "sub.panel_preset_ensure"
    bl_label = "Initialize Panel Presets"
    bl_description = "Create the built-in All / Animate / Modeling presets"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        ensure_default_presets(context.scene)
        _tag_redraw(context)
        return {"FINISHED"}


class SUB_OP_panel_preset_save(Operator):
    bl_idname = "sub.panel_preset_save"
    bl_label = "Save Presets"
    bl_description = (
        "Save all panel presets to disk so they persist across .blend files "
        "(also stored in the current .blend when you save the file)"
    )
    bl_options = {"REGISTER"}

    def execute(self, context):
        ensure_default_presets(context.scene)
        path = save_presets_to_disk(context.scene)
        self.report({"INFO"}, f"Saved panel presets to {path}")
        return {"FINISHED"}


class SUB_OP_panel_preset_load(Operator):
    bl_idname = "sub.panel_preset_load"
    bl_label = "Load Presets"
    bl_description = "Load panel presets from the saved disk file"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        if not load_presets_from_disk(context.scene):
            self.report({"WARNING"}, "No saved panel presets found. Use Save Presets first.")
            return {"CANCELLED"}
        _tag_redraw(context)
        self.report({"INFO"}, "Loaded panel presets from disk")
        return {"FINISHED"}


class SUB_OP_panel_preset_add(Operator):
    bl_idname = "sub.panel_preset_add"
    bl_label = "Add Panel Preset"
    bl_description = "Create a new panel visibility preset"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        scene = context.scene
        ensure_default_presets(scene)
        presets = scene.sub_panel_presets
        preset = presets.add()
        preset.name = f"Preset {len(presets)}"
        preset.show_all = False
        preset.is_builtin = False
        _sync_preset_panels(preset, default_enabled=True)
        scene.sub_panel_presets_index = len(presets) - 1
        _tag_redraw(context)
        return {"FINISHED"}


class SUB_OP_panel_preset_remove(Operator):
    bl_idname = "sub.panel_preset_remove"
    bl_label = "Remove Panel Preset"
    bl_description = "Delete the selected panel preset"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        scene = context.scene
        presets = getattr(scene, "sub_panel_presets", None)
        if presets is None or not len(presets):
            return False
        index = int(getattr(scene, "sub_panel_presets_index", 0) or 0)
        if index < 0 or index >= len(presets):
            return False
        return not presets[index].is_builtin

    def execute(self, context):
        scene = context.scene
        presets = scene.sub_panel_presets
        index = scene.sub_panel_presets_index
        presets.remove(index)
        scene.sub_panel_presets_index = min(index, max(0, len(presets) - 1))
        ensure_default_presets(scene)
        _tag_redraw(context)
        return {"FINISHED"}


class SUB_OP_panel_preset_duplicate(Operator):
    bl_idname = "sub.panel_preset_duplicate"
    bl_label = "Duplicate Panel Preset"
    bl_description = "Duplicate the selected preset"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        presets = getattr(context.scene, "sub_panel_presets", None)
        return presets is not None and len(presets) > 0

    def execute(self, context):
        scene = context.scene
        ensure_default_presets(scene)
        presets = scene.sub_panel_presets
        src = _active_preset(scene)
        if src is None:
            return {"CANCELLED"}
        dst = presets.add()
        dst.name = f"{src.name} Copy"
        dst.show_all = bool(src.show_all)
        dst.is_builtin = False
        enabled = {e.panel_id for e in src.panels if e.enabled} if not src.show_all else None
        if src.show_all:
            _sync_preset_panels(dst, default_enabled=True)
        else:
            _sync_preset_panels(dst, enabled_ids=enabled)
        scene.sub_panel_presets_index = len(presets) - 1
        _tag_redraw(context)
        return {"FINISHED"}


class SUB_OP_panel_preset_select_all(Operator):
    bl_idname = "sub.panel_preset_select_all"
    bl_label = "Enable All Panels"
    bl_options = {"REGISTER", "UNDO"}

    enable: BoolProperty(default=True)

    def execute(self, context):
        preset = _active_preset(context.scene)
        if preset is None or preset.show_all:
            return {"CANCELLED"}
        for entry in preset.panels:
            entry.enabled = bool(self.enable)
        _tag_redraw(context)
        return {"FINISHED"}


def _install_poll_wrappers():
    """Wrap top-level Ultimate panel polls so presets can hide them.

    Do NOT unregister/re-register panels — that orphans children (Retargeting
    subpanels like Bind To / Expy Mapping / Actions become loose top-level panels).
    Assigning poll on the live class is enough in Blender 4.2+/5.x.
    """
    global _wrapped_polls
    _uninstall_poll_wrappers()

    for panel_id, cls, _label in discover_controllable_panels():
        if cls is None or not issubclass(cls, Panel):
            continue
        original = cls.__dict__.get("poll")
        if original is None:
            inherited = getattr(cls, "poll", None)
            if inherited is not None and getattr(inherited, "__func__", None) is not None:
                if getattr(inherited, "__func__", None) is getattr(Panel.poll, "__func__", None):
                    original = None
                else:
                    original = inherited

        def _make_poll(pid, orig):
            def _poll(panel_cls, context):
                if not panel_allowed(context, pid):
                    return False
                if orig is None:
                    return True
                try:
                    return orig.__get__(panel_cls, type(panel_cls))(context)
                except TypeError:
                    return orig(context)

            return classmethod(_poll)

        cls.poll = _make_poll(panel_id, original)
        _wrapped_polls[panel_id] = (cls, original)


def _uninstall_poll_wrappers():
    global _wrapped_polls
    for panel_id, stored in list(_wrapped_polls.items()):
        if isinstance(stored, tuple):
            cls, original = stored
        else:
            cls = getattr(bpy.types, panel_id, None)
            original = stored
        if cls is None:
            continue
        try:
            if original is None:
                if "poll" in cls.__dict__:
                    try:
                        delattr(cls, "poll")
                    except Exception:
                        cls.poll = classmethod(lambda panel_cls, context: True)
            else:
                cls.poll = original
        except Exception:
            pass
    _wrapped_polls.clear()


def repair_retargeting_panel_hierarchy():
    """Re-register Retargeting panels in parent-first order if children were orphaned.

    A previous Panel Presets wrap used unregister/register on the Retargeting
    parent, which left Bind To / Expy Mapping / Actions as loose top-level panels.
    """
    try:
        from .. import retargeting
        panels = list(getattr(retargeting, "custom_panels", []) or [])
    except Exception:
        return False
    if not panels:
        return False

    # Unregister children before parents (reverse), then register parent-first.
    for cls in reversed(panels):
        try:
            bpy.utils.unregister_class(cls)
        except Exception:
            pass
    for cls in panels:
        try:
            bpy.utils.register_class(cls)
        except Exception:
            pass
    return True


def repair_updater_panel_hierarchy():
    """Re-nest Plugin Updater under Update Available! after a bad wrap."""
    try:
        from ..updater import ui as updater_ui
    except Exception:
        return False
    panels = []
    for name in ("SUB_PT_update_plugin", "SUB_PT_updater_settings"):
        cls = getattr(updater_ui, name, None)
        if cls is not None:
            panels.append(cls)
    if not panels:
        return False
    for cls in reversed(panels):
        try:
            bpy.utils.unregister_class(cls)
        except Exception:
            pass
    for cls in panels:
        try:
            bpy.utils.register_class(cls)
        except Exception:
            pass
    return True


class SUB_PT_panel_presets(Panel):
    bl_label = "Panel Presets"
    bl_idname = _PRESETS_PANEL_ID
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Ultimate"
    bl_order = 999
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        layout = self.layout
        scene = context.scene
        presets = getattr(scene, "sub_panel_presets", None)

        if presets is None:
            layout.label(text="Panel presets unavailable", icon="ERROR")
            return
        if not len(presets):
            layout.label(text="No presets yet.")
            layout.operator("sub.panel_preset_ensure", icon="PRESET")
            schedule_seed_presets()
            return

        layout.label(text="Active preset controls which Ultimate panels are visible.")

        row = layout.row()
        row.template_list(
            "SUB_UL_panel_presets",
            "",
            scene,
            "sub_panel_presets",
            scene,
            "sub_panel_presets_index",
            rows=4,
        )
        col = row.column(align=True)
        col.operator("sub.panel_preset_add", text="", icon="ADD")
        col.operator("sub.panel_preset_remove", text="", icon="REMOVE")
        col.separator()
        col.operator("sub.panel_preset_duplicate", text="", icon="DUPLICATE")

        row = layout.row(align=True)
        row.operator("sub.panel_preset_save", icon="FILE_TICK")
        row.operator("sub.panel_preset_load", icon="IMPORT")

        preset = _active_preset(scene)
        if preset is None:
            return

        box = layout.box()
        name_row = box.row(align=True)
        name_row.prop(preset, "name", text="Name")
        if preset.is_builtin:
            name_row.enabled = False

        if preset.show_all and preset.is_builtin:
            box.label(text="Built-in: every Ultimate panel is visible.", icon="INFO")
            return

        box.prop(preset, "show_all", text="Show All Panels")
        if preset.show_all:
            box.label(text="Every Ultimate panel is visible.", icon="INFO")
            return

        if not len(preset.panels):
            box.operator("sub.panel_preset_ensure", text="Refresh Panel List", icon="FILE_REFRESH")
            schedule_seed_presets()
            return

        row = box.row(align=True)
        op = row.operator("sub.panel_preset_select_all", text="Check All")
        op.enable = True
        op = row.operator("sub.panel_preset_select_all", text="Uncheck All")
        op.enable = False

        col = box.column(align=True)
        for entry in preset.panels:
            col.prop(entry, "enabled", text=entry.label or entry.panel_id)

        box.label(
            text="Checklist applies immediately. Save Presets for other .blend files.",
            icon="INFO",
        )


classes = (
    SUB_PG_panel_preset_entry,
    SUB_PG_panel_preset,
    SUB_UL_panel_presets,
    SUB_OP_panel_preset_ensure,
    SUB_OP_panel_preset_save,
    SUB_OP_panel_preset_load,
    SUB_OP_panel_preset_add,
    SUB_OP_panel_preset_remove,
    SUB_OP_panel_preset_duplicate,
    SUB_OP_panel_preset_select_all,
    SUB_PT_panel_presets,
)


@persistent
def _panel_presets_load_post(_dummy):
    schedule_seed_presets()
    try:
        repair_retargeting_panel_hierarchy()
        repair_updater_panel_hierarchy()
        _install_poll_wrappers()
    except Exception:
        pass


def register():
    for cls in classes:
        try:
            bpy.utils.register_class(cls)
        except ValueError:
            pass

    if not hasattr(bpy.types.Scene, "sub_panel_presets"):
        bpy.types.Scene.sub_panel_presets = CollectionProperty(type=SUB_PG_panel_preset)
    if not hasattr(bpy.types.Scene, "sub_panel_presets_index"):
        bpy.types.Scene.sub_panel_presets_index = IntProperty(
            name="Panel Preset",
            description="Active Ultimate panel visibility preset",
            default=0,
            update=_on_preset_index_update,
        )

    try:
        repair_retargeting_panel_hierarchy()
        repair_updater_panel_hierarchy()
    except Exception:
        pass
    _install_poll_wrappers()

    if _panel_presets_load_post not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(_panel_presets_load_post)

    schedule_seed_presets()


def unregister():
    if _panel_presets_load_post in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(_panel_presets_load_post)
    if bpy.app.timers.is_registered(_seed_presets_timer):
        bpy.app.timers.unregister(_seed_presets_timer)

    _uninstall_poll_wrappers()
    if hasattr(bpy.types.Scene, "sub_panel_presets_index"):
        del bpy.types.Scene.sub_panel_presets_index
    if hasattr(bpy.types.Scene, "sub_panel_presets"):
        del bpy.types.Scene.sub_panel_presets
    for cls in reversed(classes):
        try:
            bpy.utils.unregister_class(cls)
        except RuntimeError:
            pass
