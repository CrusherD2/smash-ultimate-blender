"""Smash Toolbar: an editor-menu entry whose header holds the user's favorite add-on buttons."""
import json
import math
from pathlib import Path

import bpy
from bpy.props import BoolProperty, EnumProperty, FloatVectorProperty, IntProperty, StringProperty
from bpy.types import Menu, NodeTree, Operator, Panel, UIList

from ..addon_preferences import get_addon_preferences

TREE_ID = "SUB_SmashToolbarTree"
_SKIP_OPS = {"sub.toolbar_run", "sub.toolbar_add", "sub.toolbar_edit", "sub.toolbar_icon", "sub.toolbar_import_animation",
             "sub.toolbar_animation_menu", "sub.toolbar_group_toggle", "sub.toolbar_group_assign",
             "sub.toolbar_group_new", "sub.toolbar_add_setting", "sub.toolbar_apply_idle_pose",
             "sub.toolbar_idle_pose_menu"}
# Blender's collection colors, so new groups start out easy to tell apart.
GROUP_COLORS = ((0.89, 0.27, 0.25), (0.94, 0.58, 0.20), (0.93, 0.82, 0.27), (0.42, 0.75, 0.32),
                (0.27, 0.52, 0.92), (0.60, 0.40, 0.85), (0.90, 0.45, 0.70), (0.60, 0.45, 0.30))

_gate_state = {}


class SUB_SmashToolbarTree(NodeTree):
    """Holds favorite buttons in its header. Shrink the area to a thin strip."""
    bl_idname = TREE_ID
    bl_label = "Smash Toolbar"
    bl_icon = "SOLO_ON"


def operator_idname(identifier):
    """'SUB_OT_create_ik' -> 'sub.create_ik'; already-dotted names pass through."""
    if "." in identifier:
        return identifier
    module, sep, name = identifier.partition("_OT_")
    return f"{module.lower()}.{name}" if sep else ""


def _operator(idname):
    module, _, name = idname.partition(".")
    if not module or not name:
        return None
    try:
        op = getattr(getattr(bpy.ops, module), name)
        op.get_rna_type()
    except (AttributeError, KeyError):
        return None
    return op


def serialize_properties(op_props):
    """Only properties the button sets; JSON-safe."""
    values = {}
    for prop in op_props.bl_rna.properties:
        name = prop.identifier
        if name == "rna_type" or prop.type in {"POINTER", "COLLECTION"}:
            continue
        if not op_props.is_property_set(name):
            continue
        value = getattr(op_props, name)
        if isinstance(value, set):
            value = sorted(value)
        elif hasattr(value, "__len__") and not isinstance(value, str):
            value = list(value)
        values[name] = value
    return json.dumps(values, sort_keys=True)


def _call_kwargs(op, props_json):
    kwargs = json.loads(props_json or "{}")
    rna = op.get_rna_type().properties
    for name, value in list(kwargs.items()):
        prop = rna.get(name)
        if prop is None:
            kwargs.pop(name)
        elif prop.type == "ENUM" and prop.is_enum_flag:
            kwargs[name] = set(value)
    return kwargs


def _view3d_override(context):
    """Most add-on buttons live in the 3D View sidebar and poll for that context."""
    window = context.window
    screen = getattr(window, "screen", None)
    for area in getattr(screen, "areas", ()):
        if area.type != "VIEW_3D":
            continue
        region = next((r for r in area.regions if r.type == "WINDOW"), None)
        if region is not None:
            return {"window": window, "area": area, "region": region}
    return {}


def _buttons(context):
    prefs = get_addon_preferences(context)
    return prefs.toolbar_buttons if prefs is not None else None


def _setting_owner(context, kind):
    if kind == "SCENE":
        return context.scene
    if kind == "WINDOW_MANAGER":
        return context.window_manager
    obj = getattr(context, "active_object", None)
    if kind == "OBJECT":
        return obj
    if kind == "OBJECT_DATA":
        return getattr(obj, "data", None)
    return None


def resolve_setting(context, entry):
    """(data, property name) for a setting button, or None when it can't be shown right now."""
    owner = _setting_owner(context, entry.prop_owner)
    if owner is None:
        return None
    try:
        data = owner.path_resolve(entry.prop_base) if entry.prop_base else owner
    except (ValueError, AttributeError):
        return None
    if data is None or entry.prop_name not in data.bl_rna.properties:
        return None
    return data, entry.prop_name


def setting_source(context, pointer, prop):
    """(owner kind, base path, name) to find this setting again, or None if it isn't reachable."""
    if pointer is None or prop is None:
        return None
    name = prop.identifier
    if name == "rna_type" or prop.type in {"POINTER", "COLLECTION"}:
        return None
    id_data = getattr(pointer, "id_data", None)
    if id_data is None:
        return None
    try:
        base = "" if pointer == id_data else pointer.path_from_id()
    except ValueError:
        return None
    obj = getattr(context, "active_object", None)
    if id_data == context.scene:
        kind = "SCENE"
    elif id_data == context.window_manager:
        kind = "WINDOW_MANAGER"
    elif obj is not None and id_data == obj:
        kind = "OBJECT"
    elif obj is not None and id_data == getattr(obj, "data", None):
        kind = "OBJECT_DATA"
    else:
        return None
    return kind, base, name


def _is_setting(entry):
    return bool(entry.prop_name)


def _setting_index(buttons, source):
    if buttons is None or source is None:
        return -1
    kind, base, name = source
    return next((i for i, entry in enumerate(buttons)
                 if entry.prop_owner == kind and entry.prop_base == base and entry.prop_name == name), -1)


def _groups(buttons):
    return {entry.uid: entry for entry in buttons if entry.is_group and entry.uid}


def _parent_group(entry, groups):
    """The group a button sits in, or None for buttons on the bar (and orphans)."""
    if entry.is_group or not entry.group:
        return None
    return groups.get(entry.group)


def _level(entry, groups):
    parent = _parent_group(entry, groups)
    return parent.uid if parent is not None else ""


def _members(buttons, group):
    return [(index, entry) for index, entry in enumerate(buttons)
            if not entry.is_group and entry.group == group.uid]


def _entry_index(buttons, entry):
    if buttons is None or entry is None:
        return -1
    return next((index for index, item in enumerate(buttons) if item == entry), -1)


def _new_group_uid(buttons):
    used = {entry.uid for entry in buttons}
    number = 1
    while f"group{number}" in used:
        number += 1
    return f"group{number}"


def _metrics(context):
    """Blender's UI sizes in pixels (wm_window.cc / interface_style.cc)."""
    prefs = context.preferences
    scale = prefs.system.dpi / 72.0
    unit = int(math.floor(18.0 * scale + 0.5)) + 2 * max(1, int(prefs.system.dpi / 64))
    points = prefs.ui_styles[0].widget.points if len(prefs.ui_styles) else 11.0
    return scale, unit, points


def _text_width(context, text):
    import blf
    scale, _unit, points = _metrics(context)
    blf.size(0, points * scale)
    return blf.dimensions(0, text)[0]


def _button_width(context, text, icon):
    """Width Blender gives a header button (interface_layout.cc ui_text_icon_width_ex)."""
    import math
    _scale, unit, _points = _metrics(context)
    if not text:
        return float(unit)
    margin = 1.5 + (0.25 if icon else 0.0)
    return float(int(_text_width(context, text)) + int(math.ceil(unit * margin)))


def _fixed(layout, context, width):
    """A sub-row exactly `width` pixels wide, so the color overlay knows where buttons are."""
    _scale, unit, _points = _metrics(context)
    sub = layout.row(align=True)
    sub.ui_units_x = width / unit
    return sub


def _swatch_icon(color):
    """A rounded color square as a custom icon. Blender can't tint a button itself."""
    previews = _gate_state.get("previews")
    if previews is None:
        return 0
    rgb = tuple(round(min(max(float(c), 0.0), 1.0), 3) for c in color)
    key = "swatch_%.3f_%.3f_%.3f" % rgb
    preview = previews.get(key)
    if preview is None:
        preview = previews.new(key)
        size, margin, radius = 32, 4, 7
        low, high = margin + radius, size - margin - radius - 1
        pixels = []
        for y in range(size):
            for x in range(size):
                dx = max(low - x, 0, x - high)
                dy = max(low - y, 0, y - high)
                inside = (margin <= x < size - margin and margin <= y < size - margin
                          and dx * dx + dy * dy <= radius * radius)
                pixels.extend((*rgb, 1.0) if inside else (0.0, 0.0, 0.0, 0.0))
        preview.icon_size = (size, size)
        preview.icon_pixels_float = pixels
    return preview.icon_id


class SUB_OT_toolbar_run(Operator):
    bl_idname = "sub.toolbar_run"
    bl_label = "Run Toolbar Button"
    bl_options = {"INTERNAL"}

    index: IntProperty(default=-1)

    @classmethod
    def description(cls, context, properties):
        buttons = _buttons(context)
        if buttons is None or not 0 <= properties.index < len(buttons):
            return ""
        entry = buttons[properties.index]
        op = _operator(entry.idname)
        text = op.get_rna_type().description if op else "This button's tool is no longer available"
        # Icon buttons have no visible text, so the tooltip carries the name.
        return f"{entry.label}" + chr(10) + text if entry.show_icon and entry.icon else text

    def invoke(self, context, _event):
        return self._run(context, "INVOKE_DEFAULT")

    def execute(self, context):
        return self._run(context, "EXEC_DEFAULT")

    def _run(self, context, call_context):
        buttons = _buttons(context)
        if buttons is None or not 0 <= self.index < len(buttons):
            return {"CANCELLED"}
        entry = buttons[self.index]
        op = _operator(entry.idname)
        if op is None:
            self.report({"WARNING"}, f"'{entry.label}' is no longer available")
            return {"CANCELLED"}
        kwargs = _call_kwargs(op, entry.props)
        with context.temp_override(**_view3d_override(context)):
            if not op.poll(call_context):
                self.report({"WARNING"}, f"'{entry.label}' can't run right now (check the mode and selection)")
                return {"CANCELLED"}
            # undo=True gives the real tool its own undo step and name.
            result = op(call_context, True, **kwargs)
        return {"CANCELLED"} if result == {"CANCELLED"} else {"FINISHED"}


class SUB_OT_toolbar_import_animation(Operator):
    bl_idname = "sub.toolbar_import_animation"
    bl_label = "Animation List"
    bl_description = "Import this animation onto the selected armature right away"
    bl_options = {"INTERNAL", "UNDO"}

    index: IntProperty(default=-1)

    @classmethod
    def description(cls, context, properties):
        files = context.scene.sub_scene_properties.animation_import_files
        if 0 <= properties.index < len(files):
            return f"Import {files[properties.index].name} onto the selected armature"
        return cls.bl_description

    def execute(self, context):
        from ..anim.import_anim import import_animation_paths
        ssp = context.scene.sub_scene_properties
        files = ssp.animation_import_files
        if not 0 <= self.index < len(files):
            return {"CANCELLED"}
        obj = context.object
        if obj is None or obj.type not in {"ARMATURE", "CAMERA"}:
            self.report({"WARNING"}, "Select an armature or camera to import onto")
            return {"CANCELLED"}
        from ..anim.import_anim import set_animation_list_index
        set_animation_list_index(ssp, self.index)
        with context.temp_override(**_view3d_override(context)):
            imported, _failed = import_animation_paths(bpy.context, self, [files[self.index].path])
        return {"FINISHED"} if imported else {"CANCELLED"}


class _ToolbarAnimationRows:
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        # A plain label, so clicks hit the list row. Blender keeps row clicks correct
        # after scrolling; an operator button here would import the previous row.
        layout.label(text=item.name, icon="ACTION")


class SUB_UL_toolbar_animations(_ToolbarAnimationRows, UIList):
    pass


class SUB_UL_toolbar_animations_expanded(_ToolbarAnimationRows, UIList):
    def filter_items(self, context, data, propname):
        items = getattr(data, propname)
        search = context.window_manager.sub_toolbar_animation_search
        flags = bpy.types.UI_UL_list.filter_items_by_name(search, self.bitflag_filter_item, items, "name")
        return flags, []


ANIMATION_LIST_UNITS = 12


class SUB_OT_toolbar_animation_menu(Operator):
    bl_idname = "sub.toolbar_animation_menu"
    bl_label = "Show All Animations"
    bl_description = "Open a bigger, searchable list of the folder's animations"
    bl_options = {"INTERNAL"}

    def execute(self, context):
        # Opened without a source button, Blender puts the popup's highlighted button
        # under the mouse: its bottom-right arrow lands on this arrow, so the popup
        # sits exactly on top of the bar's list instead of centered on the arrow.
        bpy.ops.wm.call_panel(name=SUB_PT_toolbar_animations.__name__, keep_open=True)
        return {"FINISHED"}


class SUB_PT_toolbar_animations(Panel):
    bl_label = "Animations"
    bl_space_type = "NODE_EDITOR"
    bl_region_type = "HEADER"
    # Bar list plus its one-unit arrow.
    bl_ui_units_x = ANIMATION_LIST_UNITS + 1

    def draw(self, context):
        ssp = context.scene.sub_scene_properties
        wm = context.window_manager
        files = ssp.animation_import_files
        layout = self.layout
        layout.label(text="Click an animation to import it", icon="ACTION")
        folders = {item.path for item in ssp.animation_import_folders}
        folders.add(ssp.animation_import_folder_path)
        if len(folders - {""}) > 1:
            from ..anim.import_anim import SUB_MT_animation_folders
            # Same folder switcher as the Animation Importer; it refreshes this list.
            folder = Path(ssp.animation_import_folder_path).name or ssp.animation_import_folder_path
            layout.menu(SUB_MT_animation_folders.bl_idname, text=f"Folder: {folder}", icon="FILE_FOLDER")
        layout.template_list(SUB_UL_toolbar_animations_expanded.__name__, "smash_toolbar_expanded", ssp,
                             "animation_import_files", wm, "sub_toolbar_popup_index", rows=12)
        layout.prop(wm, "sub_toolbar_animation_search", text="", icon="VIEWZOOM")
        bottom = layout.row(align=True)
        index = wm.sub_toolbar_animation_index
        name = files[index].name if 0 <= index < len(files) else "Animations"
        bottom.label(text=name, icon="ACTION")
        # The only highlighted button; Blender aligns it with the mouse (see the menu operator).
        bottom.prop(wm, "sub_toolbar_menu_open", text="", icon="DOWNARROW_HLT", toggle=True)


class SUB_OT_toolbar_apply_idle_pose(Operator):
    bl_idname = "sub.toolbar_apply_idle_pose"
    bl_label = "Idle Pose List"
    bl_description = "Apply this idle pose to the selected armature right away"
    bl_options = {"INTERNAL"}

    index: IntProperty(default=-1)

    @classmethod
    def description(cls, context, properties):
        poses = context.scene.sub_scene_properties.idle_pose_list
        if 0 <= properties.index < len(poses):
            return f"Apply {poses[properties.index].name} to the selected armature"
        return cls.bl_description

    def execute(self, context):
        ssp = context.scene.sub_scene_properties
        if not 0 <= self.index < len(ssp.idle_pose_list):
            return {"CANCELLED"}
        obj = context.object
        if obj is None or obj.type != "ARMATURE":
            self.report({"WARNING"}, "Select an armature to apply the pose to")
            return {"CANCELLED"}
        # The library's own Apply button reads the panel's selected pose, with its options.
        ssp.idle_pose_list_index = self.index
        with context.temp_override(**_view3d_override(context)):
            if not bpy.ops.sub.apply_idle_pose_from_list.poll():
                self.report({"WARNING"}, "Can't apply a pose right now (use Object or Pose Mode)")
                return {"CANCELLED"}
            result = bpy.ops.sub.apply_idle_pose_from_list("EXEC_DEFAULT", True)
        return {"CANCELLED"} if result == {"CANCELLED"} else {"FINISHED"}


class _ToolbarPoseRows:
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        layout.label(text=item.name, icon="ARMATURE_DATA")


class SUB_UL_toolbar_poses(_ToolbarPoseRows, UIList):
    pass


class SUB_UL_toolbar_poses_expanded(_ToolbarPoseRows, UIList):
    def filter_items(self, context, data, propname):
        items = getattr(data, propname)
        search = context.window_manager.sub_toolbar_pose_search
        flags = bpy.types.UI_UL_list.filter_items_by_name(search, self.bitflag_filter_item, items, "name")
        return flags, []


class SUB_OT_toolbar_idle_pose_menu(Operator):
    bl_idname = "sub.toolbar_idle_pose_menu"
    bl_label = "Show All Idle Poses"
    bl_description = "Open a bigger, searchable list of the idle pose library"
    bl_options = {"INTERNAL"}

    def execute(self, context):
        # Same alignment trick as the animation list (see SUB_OT_toolbar_animation_menu).
        bpy.ops.wm.call_panel(name=SUB_PT_toolbar_poses.__name__, keep_open=True)
        return {"FINISHED"}


class SUB_PT_toolbar_poses(Panel):
    bl_label = "Idle Poses"
    bl_space_type = "NODE_EDITOR"
    bl_region_type = "HEADER"
    bl_ui_units_x = ANIMATION_LIST_UNITS + 1

    def draw(self, context):
        ssp = context.scene.sub_scene_properties
        wm = context.window_manager
        poses = ssp.idle_pose_list
        top = self.layout.column()
        bottom = self.layout.row(align=True)
        # Fill the bottom row first: Blender aligns the popup on the first highlighted
        # button it created, and the switched-on option toggles above would win otherwise.
        index = wm.sub_toolbar_pose_index
        name = poses[index].name if 0 <= index < len(poses) else "Idle Poses"
        bottom.label(text=name, icon="ARMATURE_DATA")
        bottom.prop(wm, "sub_toolbar_menu_open", text="", icon="DOWNARROW_HLT", toggle=True)
        top.label(text="Click a pose to apply it", icon="ARMATURE_DATA")
        options = top.row(align=True)
        options.prop(ssp, "idle_pose_include_trans", text="Trans", toggle=True)
        options.prop(ssp, "idle_pose_mirrored", text="Mirrored", toggle=True)
        options.prop(ssp, "idle_pose_180_rotate", text="180", toggle=True)
        top.template_list(SUB_UL_toolbar_poses_expanded.__name__, "smash_toolbar_poses_expanded", ssp,
                          "idle_pose_list", wm, "sub_toolbar_pose_popup_index", rows=12)
        top.prop(wm, "sub_toolbar_pose_search", text="", icon="VIEWZOOM")


def _pick_toolbar_pose(wm, context):
    index = wm.sub_toolbar_pose_popup_index
    if index < 0:
        return
    wm.sub_toolbar_pose_popup_index = -1
    wm.sub_toolbar_pose_index = index


def _apply_toolbar_pose(wm, context):
    window = context.window
    override = {"window": window, **_view3d_override(context)} if window else {}
    with context.temp_override(**override):
        bpy.ops.sub.toolbar_apply_idle_pose("EXEC_DEFAULT", True, index=wm.sub_toolbar_pose_index)


def _pick_toolbar_animation(wm, context):
    """A click in the popup list imports through the bar list, so both show the same choice."""
    index = wm.sub_toolbar_popup_index
    if index < 0:
        return
    wm.sub_toolbar_popup_index = -1
    wm.sub_toolbar_animation_index = index


def _import_toolbar_animation(wm, context):
    """Clicking a row in the toolbar list imports it."""
    index = wm.sub_toolbar_animation_index
    window = context.window
    override = {"window": window, **_view3d_override(context)} if window else {}
    with context.temp_override(**override):
        bpy.ops.sub.toolbar_import_animation("EXEC_DEFAULT", True, index=index)


class SUB_OT_toolbar_add(Operator):
    bl_idname = "sub.toolbar_add"
    bl_label = "Add to Smash Toolbar"
    bl_description = "Add this button to the Smash Toolbar editor"
    bl_options = {"INTERNAL"}

    idname: StringProperty()
    props: StringProperty(default="{}")

    def execute(self, context):
        buttons = _buttons(context)
        op = _operator(self.idname)
        if buttons is None or op is None:
            return {"CANCELLED"}
        for entry in buttons:
            if entry.idname == self.idname and entry.props == self.props:
                self.report({"INFO"}, f"'{entry.label}' is already on the Smash Toolbar")
                return {"CANCELLED"}
        entry = buttons.add()
        entry.idname = self.idname
        entry.props = self.props
        entry.label = op.get_rna_type().name or self.idname
        context.preferences.is_dirty = True
        self.report({"INFO"}, f"Added '{entry.label}' to the Smash Toolbar")
        return {"FINISHED"}


class SUB_OT_toolbar_add_setting(Operator):
    bl_idname = "sub.toolbar_add_setting"
    bl_label = "Add to Smash Toolbar"
    bl_description = "Add this setting to the Smash Toolbar editor"
    bl_options = {"INTERNAL"}

    owner: StringProperty()
    base: StringProperty()
    name: StringProperty()

    def execute(self, context):
        buttons = _buttons(context)
        if buttons is None:
            return {"CANCELLED"}
        source = (self.owner, self.base, self.name)
        if _setting_index(buttons, source) >= 0:
            self.report({"INFO"}, "That setting is already on the Smash Toolbar")
            return {"CANCELLED"}
        entry = buttons.add()
        entry.prop_owner, entry.prop_base, entry.prop_name = source
        resolved = resolve_setting(context, entry)
        if resolved is None:
            buttons.remove(len(buttons) - 1)
            return {"CANCELLED"}
        data, name = resolved
        entry.label = data.bl_rna.properties[name].name or name
        context.preferences.is_dirty = True
        self.report({"INFO"}, f"Added '{entry.label}' to the Smash Toolbar")
        return {"FINISHED"}


class SUB_OT_toolbar_edit(Operator):
    bl_idname = "sub.toolbar_edit"
    bl_label = "Edit Smash Toolbar"
    bl_description = "Move or remove a Smash Toolbar button"
    bl_options = {"INTERNAL"}

    index: IntProperty(default=-1)
    action: StringProperty(default="REMOVE")

    def execute(self, context):
        buttons = _buttons(context)
        if buttons is None or not 0 <= self.index < len(buttons):
            return {"CANCELLED"}
        if self.action == "REMOVE":
            entry = buttons[self.index]
            if entry.is_group:
                # Removing a group keeps its buttons; they go back on the bar.
                for _index, member in _members(buttons, entry):
                    member.group = ""
            buttons.remove(self.index)
        elif self.action == "TEXT":
            buttons[self.index].show_icon = False
        else:
            # Move past the neighbor on the same level: the bar, or inside the same group.
            groups = _groups(buttons)
            level = _level(buttons[self.index], groups)
            siblings = [i for i, entry in enumerate(buttons) if _level(entry, groups) == level]
            position = siblings.index(self.index) + (-1 if self.action == "UP" else 1)
            if not 0 <= position < len(siblings):
                return {"CANCELLED"}
            buttons.move(self.index, siblings[position])
        context.preferences.is_dirty = True
        return {"FINISHED"}


class SUB_OT_toolbar_group_toggle(Operator):
    bl_idname = "sub.toolbar_group_toggle"
    bl_label = "Open Group"
    bl_options = {"INTERNAL"}

    index: IntProperty(default=-1)

    @classmethod
    def description(cls, context, properties):
        buttons = _buttons(context)
        if buttons is None or not 0 <= properties.index < len(buttons):
            return ""
        group = buttons[properties.index]
        count = len(_members(buttons, group))
        action = "Hide" if group.expanded else "Show"
        return f"{group.label}" + chr(10) + f"{action} its {count} button{'s' if count != 1 else ''}"

    def execute(self, context):
        buttons = _buttons(context)
        if buttons is None or not 0 <= self.index < len(buttons) or not buttons[self.index].is_group:
            return {"CANCELLED"}
        group = buttons[self.index]
        group.expanded = not group.expanded
        return {"FINISHED"}


class SUB_OT_toolbar_group_assign(Operator):
    bl_idname = "sub.toolbar_group_assign"
    bl_label = "Move to Group"
    bl_description = "Put this Smash Toolbar button in the group"
    bl_options = {"INTERNAL"}

    index: IntProperty(default=-1)
    group: StringProperty(description="Group to move into; empty puts the button back on the bar")

    def execute(self, context):
        buttons = _buttons(context)
        if buttons is None or not 0 <= self.index < len(buttons) or buttons[self.index].is_group:
            return {"CANCELLED"}
        if self.group and self.group not in _groups(buttons):
            return {"CANCELLED"}
        buttons[self.index].group = self.group
        context.preferences.is_dirty = True
        return {"FINISHED"}


class SUB_OT_toolbar_group_new(Operator):
    bl_idname = "sub.toolbar_group_new"
    bl_label = "New Group"
    bl_description = "Make a new Smash Toolbar group and put this button in it"
    bl_options = {"INTERNAL"}

    index: IntProperty(default=-1)
    name: StringProperty(name="Name", default="New Group")
    color: FloatVectorProperty(name="Color", subtype="COLOR_GAMMA", size=3, min=0.0, max=1.0,
                               default=GROUP_COLORS[4])

    def invoke(self, context, _event):
        buttons = _buttons(context)
        if buttons is None or not 0 <= self.index < len(buttons) or buttons[self.index].is_group:
            return {"CANCELLED"}
        self.color = GROUP_COLORS[len(_groups(buttons)) % len(GROUP_COLORS)]
        return context.window_manager.invoke_props_dialog(self)

    def execute(self, context):
        buttons = _buttons(context)
        if buttons is None or not 0 <= self.index < len(buttons) or buttons[self.index].is_group:
            return {"CANCELLED"}
        groups = _groups(buttons)
        member = buttons[self.index]
        current = _parent_group(member, groups)
        # The new group takes the bar spot of the button (or of the group it came from).
        anchor = _entry_index(buttons, current) if current is not None else self.index
        uid = _new_group_uid(buttons)
        member.group = uid
        group = buttons.add()
        group.is_group = True
        group.uid = uid
        group.label = self.name.strip() or "Group"
        group.color = self.color
        group.expanded = True
        buttons.move(len(buttons) - 1, anchor)
        context.preferences.is_dirty = True
        return {"FINISHED"}


class SUB_MT_toolbar_groups(Menu):
    bl_idname = "SUB_MT_toolbar_groups"
    bl_label = "Add to Group"

    def draw(self, context):
        buttons = _buttons(context)
        index = _entry_index(buttons, getattr(context, "sub_toolbar_entry", None))
        if index < 0:
            return
        layout = self.layout
        layout.operator_context = "INVOKE_DEFAULT"
        current = buttons[index].group
        groups = [entry for entry in buttons if entry.is_group and entry.uid and entry.uid != current]
        for group in groups:
            op = layout.operator(SUB_OT_toolbar_group_assign.bl_idname, text=group.label,
                                 icon_value=_swatch_icon(group.color))
            op.index, op.group = index, group.uid
        if groups:
            layout.separator()
        layout.operator(SUB_OT_toolbar_group_new.bl_idname, text="New Group...", icon="ADD").index = index


def _icon_items():
    items = bpy.types.UILayout.bl_rna.functions["prop"].parameters["icon"].enum_items
    return [(i.identifier, i.identifier.replace("_", " ").title(), "", i.identifier, index)
            for index, i in enumerate(items) if i.identifier not in {"NONE", "BLANK1"}]


class SUB_OT_toolbar_icon(Operator):
    bl_idname = "sub.toolbar_icon"
    bl_label = "Display as Icon"
    bl_description = "Pick an icon and show this Smash Toolbar button as that icon"
    bl_options = {"INTERNAL"}
    bl_property = "icon"

    index: IntProperty(default=-1)
    icon: EnumProperty(name="Icon", items=_icon_items())

    def invoke(self, context, _event):
        buttons = _buttons(context)
        if buttons is None or not 0 <= self.index < len(buttons):
            return {"CANCELLED"}
        context.window_manager.invoke_search_popup(self)
        return {"RUNNING_MODAL"}

    def execute(self, context):
        buttons = _buttons(context)
        if buttons is None or not 0 <= self.index < len(buttons):
            return {"CANCELLED"}
        buttons[self.index].icon = self.icon
        buttons[self.index].show_icon = True
        context.preferences.is_dirty = True
        return {"FINISHED"}


class SUB_PT_toolbar_edit(Panel):
    bl_label = "Edit Smash Toolbar"
    bl_space_type = "NODE_EDITOR"
    bl_region_type = "HEADER"
    bl_ui_units_x = 16

    def draw(self, context):
        layout = self.layout
        buttons = _buttons(context)
        if not buttons:
            layout.label(text="Right-click a button, then 'Add to Smash Toolbar'", icon="INFO")
            return
        groups = _groups(buttons)
        for index, entry in enumerate(buttons):
            if _parent_group(entry, groups) is not None:
                continue
            self._draw_entry(layout, index, entry, indent=False)
            if entry.is_group:
                for member_index, member in _members(buttons, entry):
                    self._draw_entry(layout, member_index, member, indent=True)
        layout.label(text="Saved with your Blender preferences", icon="PREFERENCES")

    @staticmethod
    def _draw_entry(layout, index, entry, indent):
        row = layout.row(align=True)
        if indent:
            row.label(text="", icon="BLANK1")
        if entry.is_group:
            swatch = row.row(align=True)
            swatch.ui_units_x = 1.2
            swatch.prop(entry, "color", text="")
        row.prop(entry, "label", text="")
        if entry.show_icon and entry.icon:
            text_op = row.operator(SUB_OT_toolbar_edit.bl_idname, text="", icon=entry.icon)
            text_op.index, text_op.action = index, "TEXT"
        else:
            row.operator(SUB_OT_toolbar_icon.bl_idname, text="", icon="IMAGE_DATA").index = index
        for action, icon in (("UP", "TRIA_UP"), ("DOWN", "TRIA_DOWN"), ("REMOVE", "X")):
            op = row.operator(SUB_OT_toolbar_edit.bl_idname, text="", icon=icon)
            op.index, op.action = index, action


def draw_animation_list(layout, context):
    ssp = context.scene.sub_scene_properties
    if not len(ssp.animation_import_files):
        layout.label(text="No animations: pick a folder in Animation Importer", icon="ACTION")
        return
    row = layout.row(align=True)
    strip = row.row()
    strip.ui_units_x = ANIMATION_LIST_UNITS
    # One visible row: the mouse wheel scrolls it and clicking a name imports it.
    strip.template_list(SUB_UL_toolbar_animations.__name__, "smash_toolbar", ssp, "animation_import_files",
                        context.window_manager, "sub_toolbar_animation_index", rows=1, maxrows=1)
    row.operator(SUB_OT_toolbar_animation_menu.bl_idname, text="", icon="DOWNARROW_HLT")


def draw_pose_list(layout, context):
    ssp = context.scene.sub_scene_properties
    if not len(ssp.idle_pose_list):
        layout.label(text="No idle poses: set a folder in Idle Pose Library", icon="ARMATURE_DATA")
        return
    row = layout.row(align=True)
    strip = row.row()
    strip.ui_units_x = ANIMATION_LIST_UNITS
    strip.template_list(SUB_UL_toolbar_poses.__name__, "smash_toolbar_poses", ssp, "idle_pose_list",
                        context.window_manager, "sub_toolbar_pose_index", rows=1, maxrows=1)
    row.operator(SUB_OT_toolbar_idle_pose_menu.bl_idname, text="", icon="DOWNARROW_HLT")


LIST_KINDS = {
    "sub.toolbar_import_animation": draw_animation_list,
    "sub.toolbar_apply_idle_pose": draw_pose_list,
}
# Toolbar list -> its window-manager index, used to spot right-clicks on its rows.
LIST_INDEX_PROPS = {
    "sub_toolbar_animation_index": "sub.toolbar_import_animation",
    "sub_toolbar_pose_index": "sub.toolbar_apply_idle_pose",
}


class _BarCursor:
    """Tracks where each bar item lands, in the header's view coordinates."""

    def __init__(self, context, x):
        self.context = context
        self.x = x
        self.tints = []

    def add(self, width):
        self.x += width

    def separator(self, factor):
        scale, _unit, _points = _metrics(self.context)
        self.x += int(6.0 * scale * factor)


def _draw_button(layout, context, cursor, index, entry):
    if entry.idname in LIST_KINDS:
        _scale, unit, _points = _metrics(context)
        LIST_KINDS[entry.idname](_fixed(layout, context, unit * (ANIMATION_LIST_UNITS + 1)), context)
        cursor.add(unit * (ANIMATION_LIST_UNITS + 1))
        return
    if _is_setting(entry):
        _draw_setting(layout, context, cursor, entry)
        return
    run = SUB_OT_toolbar_run.bl_idname
    if entry.show_icon and entry.icon:
        width = _button_width(context, "", True)
        _fixed(layout, context, width).operator(run, text="", icon=entry.icon).index = index
    else:
        width = _button_width(context, entry.label, False)
        _fixed(layout, context, width).operator(run, text=entry.label).index = index
    cursor.add(width)


def _setting_width(context, entry, prop, icon_mode):
    _scale, unit, _points = _metrics(context)
    if icon_mode:
        return float(unit)
    if prop is None:
        return _button_width(context, entry.label, True)
    length = prop.array_length if getattr(prop, "is_array", False) else 1
    if prop.type == "BOOLEAN":
        return _button_width(context, entry.label, False) * min(length, 4)
    if prop.type == "ENUM":
        return max(_button_width(context, entry.label, False) + unit, unit * 6.0)
    if prop.type == "STRING":
        return unit * 8.0
    return max(_button_width(context, entry.label + ": 0.000", False), unit * 6.0) * min(length, 4)


def _draw_setting(layout, context, cursor, entry):
    resolved = resolve_setting(context, entry)
    icon_mode = bool(entry.show_icon and entry.icon)
    if resolved is None:
        # Shown greyed out, e.g. an armature setting while no armature is selected.
        width = _setting_width(context, entry, None, icon_mode)
        sub = _fixed(layout, context, width)
        sub.enabled = False
        if icon_mode:
            sub.label(text="", icon=entry.icon)
        else:
            sub.label(text=entry.label, icon="ERROR")
        cursor.add(width)
        return
    data, name = resolved
    prop = data.bl_rna.properties[name]
    width = _setting_width(context, entry, prop, icon_mode)
    sub = _fixed(layout, context, width)
    is_bool = prop.type == "BOOLEAN"
    if icon_mode:
        sub.prop(data, name, text="", icon=entry.icon, toggle=True if is_bool else -1, icon_only=True)
    else:
        sub.prop(data, name, text=entry.label, toggle=True if is_bool else -1)
    cursor.add(width)


def _draw_group(layout, context, cursor, buttons, index, group):
    members = _members(buttons, group) if group.expanded else []
    block = layout.row(align=True) if members else layout
    icon_mode = bool(group.show_icon and group.icon)
    toggle = SUB_OT_toolbar_group_toggle.bl_idname
    if icon_mode:
        width = _button_width(context, "", True)
        _fixed(block, context, width).operator(toggle, text="", icon=group.icon).index = index
    else:
        arrow = "TRIA_LEFT" if group.expanded else "TRIA_RIGHT"
        width = _button_width(context, group.label, True)
        _fixed(block, context, width).operator(toggle, text=group.label, icon=arrow).index = index
    cursor.tints.append({
        "x": cursor.x, "width": width, "color": tuple(group.color), "label": group.label,
        "icon_mode": icon_mode, "open": group.expanded, "joined": bool(members),
    })
    cursor.add(width)
    for member_index, member in members:
        _draw_button(block, context, cursor, member_index, member)


def draw_toolbar(layout, context):
    layout.template_header()
    row = layout.row(align=True)
    buttons = _buttons(context)
    cursor = _BarCursor(context, _bar_start(context))
    if not buttons:
        row.label(text="Right-click any button, then 'Add to Smash Toolbar'", icon="INFO")
    else:
        groups = _groups(buttons)
        for index, entry in enumerate(buttons):
            if entry.is_group:
                row.separator(factor=0.6)
                cursor.separator(0.6)
                _draw_group(row, context, cursor, buttons, index, entry)
                row.separator(factor=0.6)
                cursor.separator(0.6)
            elif _parent_group(entry, groups) is None:
                _draw_button(row, context, cursor, index, entry)
    area = getattr(context, "area", None)
    if area is not None:
        _gate_state.setdefault("tints", {})[area.as_pointer()] = cursor.tints
    layout.separator_spacer()
    layout.popover(SUB_PT_toolbar_edit.__name__, text="", icon="PREFERENCES")


def _bar_start(context):
    """View x of the bar's first button. Fitted to Blender's header layout at 100-200% UI
    scale, with and without the area corner handle (see tests/test_smash_toolbar_groups)."""
    scale, unit, _points = _metrics(context)
    corner = 16.0 if context.preferences.view.show_area_handle else 8.0
    return int(corner * scale) + int(1.7 * unit) + int(5.0 * scale) - int(2.0 * scale)


def _rounded_rect(x0, y0, x1, y1, radius, round_right):
    import math
    radius = max(0.0, min(radius, (x1 - x0) / 2, (y1 - y0) / 2))
    points = []
    corners = ((x0 + radius, y0 + radius, 180, 270, True), (x1 - radius, y0 + radius, 270, 360, round_right),
               (x1 - radius, y1 - radius, 0, 90, round_right), (x0 + radius, y1 - radius, 90, 180, True))
    for cx, cy, start, end, rounded in corners:
        if not rounded:
            points.append((x1 if cx > (x0 + x1) / 2 else x0, y1 if cy > (y0 + y1) / 2 else y0))
            continue
        for step in range(7):
            angle = math.radians(start + (end - start) * step / 6)
            points.append((cx + math.cos(angle) * radius, cy + math.sin(angle) * radius))
    return points


def _draw_fan(points, color):
    import gpu
    from gpu_extras.batch import batch_for_shader
    shader = gpu.shader.from_builtin("UNIFORM_COLOR")
    center = (sum(p[0] for p in points) / len(points), sum(p[1] for p in points) / len(points))
    verts = [center] + points
    indices = [(0, i, i % len(points) + 1) for i in range(1, len(points) + 1)]
    batch = batch_for_shader(shader, "TRIS", {"pos": verts}, indices=indices)
    shader.uniform_float("color", color)
    batch.draw(shader)


def _draw_group_colors():
    context = bpy.context
    space = getattr(context, "space_data", None)
    area = getattr(context, "area", None)
    region = getattr(context, "region", None)
    if getattr(space, "tree_type", "") != TREE_ID or area is None or region is None:
        return
    tints = _gate_state.get("tints", {}).get(area.as_pointer())
    if not tints:
        return
    import gpu
    scale, unit, _points = _metrics(context)
    y0 = (region.height - unit) / 2 + BAR_Y_OFFSET * scale
    y1 = y0 + unit
    gpu.state.blend_set("ALPHA")
    for tint in tints:
        x0, _y = region.view2d.view_to_region(tint["x"], 0, clip=False)
        x1 = x0 + tint["width"]
        if x1 < 0 or x0 > region.width:
            continue
        r, g, b = tint["color"]
        # See-through, so Blender's own text, arrow, icon and hover highlight show underneath.
        alpha = GROUP_TINT_OPEN if tint["open"] else GROUP_TINT
        shape = _rounded_rect(x0, y0, x1, y1, BAR_ROUNDNESS * unit, round_right=not tint["joined"])
        _draw_fan(shape, (r, g, b, alpha))
    gpu.state.blend_set("NONE")


BAR_Y_OFFSET = 0.0
GROUP_TINT = 0.45
GROUP_TINT_OPEN = 0.6
BAR_ROUNDNESS = 0.2


def _draw_group_items(layout, buttons, index):
    entry = buttons[index]
    in_group = _parent_group(entry, _groups(buttons)) is not None
    layout.context_pointer_set("sub_toolbar_entry", entry)
    layout.menu(SUB_MT_toolbar_groups.bl_idname, text="Move to Group" if in_group else "Add to Group",
                icon="FILE_FOLDER")
    if in_group:
        out = layout.operator(SUB_OT_toolbar_group_assign.bl_idname, text="Remove from Group", icon="FILE_PARENT")
        out.index, out.group = index, ""


def draw_group_context(layout, context, index):
    buttons = _buttons(context)
    if buttons is None or not 0 <= index < len(buttons) or not buttons[index].is_group:
        return
    group = buttons[index]
    layout.separator()
    layout.operator_context = "INVOKE_DEFAULT"
    layout.prop(group, "label", text="Name")
    layout.prop(group, "color", text="Color")
    if group.show_icon and group.icon:
        text_op = layout.operator(SUB_OT_toolbar_edit.bl_idname, text="Display as Text", icon="SORTALPHA")
        text_op.index, text_op.action = index, "TEXT"
        layout.operator(SUB_OT_toolbar_icon.bl_idname, text="Change Icon...", icon=group.icon).index = index
    else:
        layout.operator(SUB_OT_toolbar_icon.bl_idname, text="Display as Icon...", icon="IMAGE_DATA").index = index
    ungroup = layout.operator(SUB_OT_toolbar_edit.bl_idname, text="Ungroup (keep its buttons)", icon="X")
    ungroup.index, ungroup.action = index, "REMOVE"


def draw_toolbar_button_context(layout, context, index):
    buttons = _buttons(context)
    if buttons is None or not 0 <= index < len(buttons):
        return
    entry = buttons[index]
    layout.separator()
    layout.operator_context = "INVOKE_DEFAULT"
    if entry.show_icon and entry.icon:
        text_op = layout.operator(SUB_OT_toolbar_edit.bl_idname, text="Display as Text", icon="SORTALPHA")
        text_op.index, text_op.action = index, "TEXT"
        layout.operator(SUB_OT_toolbar_icon.bl_idname, text="Change Icon...", icon=entry.icon).index = index
    else:
        layout.operator(SUB_OT_toolbar_icon.bl_idname, text="Display as Icon...", icon="IMAGE_DATA").index = index
    _draw_group_items(layout, buttons, index)
    remove = layout.operator(SUB_OT_toolbar_edit.bl_idname, text="Remove from Smash Toolbar", icon="X")
    remove.index, remove.action = index, "REMOVE"


def draw_button_context(self, context):
    op_props = getattr(context, "button_operator", None)
    prop = getattr(context, "button_prop", None)
    if op_props is None and getattr(prop, "identifier", "") in LIST_INDEX_PROPS:
        buttons = _buttons(context) or ()
        kind = LIST_INDEX_PROPS[prop.identifier]
        index = next((i for i, b in enumerate(buttons) if b.idname == kind), -1)
        if index >= 0:
            self.layout.separator()
            _draw_group_items(self.layout, buttons, index)
            remove = self.layout.operator(SUB_OT_toolbar_edit.bl_idname, text="Remove from Smash Toolbar", icon="X")
            remove.index, remove.action = index, "REMOVE"
        return
    if op_props is None and prop is not None and getattr(prop, "identifier", "") not in {
            "animation_import_files_index", "idle_pose_list_index", *LIST_INDEX_PROPS}:
        source = setting_source(context, getattr(context, "button_pointer", None), prop)
        if source is None:
            return
        buttons = _buttons(context)
        index = _setting_index(buttons, source)
        on_toolbar = getattr(getattr(context, "space_data", None), "tree_type", "") == TREE_ID
        if on_toolbar and index >= 0:
            draw_toolbar_button_context(self.layout, context, index)
            return
        if index < 0:
            self.layout.separator()
            add = self.layout.operator(SUB_OT_toolbar_add_setting.bl_idname, icon="SOLO_ON")
            add.owner, add.base, add.name = source
        return
    if op_props is None and getattr(prop, "identifier", "") == "idle_pose_list_index":
        if getattr(context, "button_pointer", None) == context.scene.sub_scene_properties:
            self.layout.separator()
            add = self.layout.operator(SUB_OT_toolbar_add.bl_idname, text="Add Idle Pose List to Smash Toolbar",
                                       icon="SOLO_ON")
            add.idname = SUB_OT_toolbar_apply_idle_pose.bl_idname
            add.props = "{}"
        return
    if op_props is None:
        # Right-clicking a row of the Animation Importer list (not the Visibility Layer one).
        pointer = getattr(context, "button_pointer", None)
        if (getattr(prop, "identifier", "") == "animation_import_files_index"
                and pointer == context.scene.sub_scene_properties):
            self.layout.separator()
            add = self.layout.operator(SUB_OT_toolbar_add.bl_idname, text="Add Animation List to Smash Toolbar", icon="SOLO_ON")
            add.idname = SUB_OT_toolbar_import_animation.bl_idname
            add.props = "{}"
        return
    idname = operator_idname(op_props.bl_rna.identifier)
    if idname == SUB_OT_toolbar_run.bl_idname:
        draw_toolbar_button_context(self.layout, context, op_props.index)
        return
    if idname == SUB_OT_toolbar_group_toggle.bl_idname:
        draw_group_context(self.layout, context, op_props.index)
        return
    if not idname or idname in _SKIP_OPS or _operator(idname) is None:
        return
    layout = self.layout
    layout.separator()
    add = layout.operator(SUB_OT_toolbar_add.bl_idname, icon="SOLO_ON")
    add.idname = idname
    add.props = serialize_properties(op_props)


class WM_MT_button_context(Menu):
    """Blender looks up this exact name for add-on entries in the button right-click menu."""
    bl_label = ""

    def draw(self, context):
        pass


def _install_button_menu():
    if not hasattr(bpy.types, "WM_MT_button_context"):
        bpy.utils.register_class(WM_MT_button_context)
        _gate_state["own_menu"] = True
    bpy.types.WM_MT_button_context.append(draw_button_context)


def _remove_button_menu():
    menu = getattr(bpy.types, "WM_MT_button_context", None)
    if menu is None:
        return
    menu.remove(draw_button_context)
    # Other add-ons may still use the shared menu; only drop it if nothing else is in it.
    if _gate_state.pop("own_menu", False):
        funcs = getattr(menu.draw, "_draw_funcs", [])
        if all(getattr(f, "__qualname__", "") == "WM_MT_button_context.draw" for f in funcs):
            bpy.utils.unregister_class(WM_MT_button_context)


def _install_header_gate():
    header = bpy.types.NODE_HT_header
    # Reuse Blender's draw list so other add-ons' header additions keep working.
    funcs = header._dyn_ui_initialize()
    for index, func in enumerate(funcs):
        if getattr(func, "__qualname__", "") == "NODE_HT_header.draw":
            original = func

            def gated(self, context):
                if getattr(context.space_data, "tree_type", "") == TREE_ID:
                    draw_toolbar(self.layout, context)
                else:
                    original(self, context)

            funcs[index] = gated
            _gate_state["pair"] = (original, gated)
            return


def _remove_header_gate():
    pair = _gate_state.pop("pair", None)
    if pair is None:
        return
    original, gated = pair
    funcs = bpy.types.NODE_HT_header._dyn_ui_initialize()
    for index, func in enumerate(funcs):
        if func is gated:
            funcs[index] = original


CLASSES = (
    SUB_SmashToolbarTree,
    SUB_OT_toolbar_run,
    SUB_OT_toolbar_import_animation,
    SUB_UL_toolbar_animations,
    SUB_UL_toolbar_animations_expanded,
    SUB_OT_toolbar_animation_menu,
    SUB_PT_toolbar_animations,
    SUB_OT_toolbar_apply_idle_pose,
    SUB_UL_toolbar_poses,
    SUB_UL_toolbar_poses_expanded,
    SUB_OT_toolbar_idle_pose_menu,
    SUB_PT_toolbar_poses,
    SUB_OT_toolbar_add,
    SUB_OT_toolbar_add_setting,
    SUB_OT_toolbar_edit,
    SUB_OT_toolbar_icon,
    SUB_OT_toolbar_group_toggle,
    SUB_OT_toolbar_group_assign,
    SUB_OT_toolbar_group_new,
    SUB_MT_toolbar_groups,
    SUB_PT_toolbar_edit,
)


def register():
    from bpy.utils import previews
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    _gate_state["previews"] = previews.new()
    _gate_state["draw_handler"] = bpy.types.SpaceNodeEditor.draw_handler_add(
        _draw_group_colors, (), "HEADER", "POST_PIXEL")
    bpy.types.WindowManager.sub_toolbar_animation_index = IntProperty(
        name="Toolbar Animation", default=-1, options={"SKIP_SAVE"}, update=_import_toolbar_animation)
    bpy.types.WindowManager.sub_toolbar_popup_index = IntProperty(
        name="Toolbar Animation", default=-1, options={"SKIP_SAVE"}, update=_pick_toolbar_animation)
    bpy.types.WindowManager.sub_toolbar_animation_search = StringProperty(
        name="Search", description="Only show animations whose name contains this",
        options={"SKIP_SAVE", "TEXTEDIT_UPDATE"})
    bpy.types.WindowManager.sub_toolbar_pose_index = IntProperty(
        name="Toolbar Idle Pose", default=-1, options={"SKIP_SAVE"}, update=_apply_toolbar_pose)
    bpy.types.WindowManager.sub_toolbar_pose_popup_index = IntProperty(
        name="Toolbar Idle Pose", default=-1, options={"SKIP_SAVE"}, update=_pick_toolbar_pose)
    bpy.types.WindowManager.sub_toolbar_pose_search = StringProperty(
        name="Search", description="Only show poses whose name contains this",
        options={"SKIP_SAVE", "TEXTEDIT_UPDATE"})
    bpy.types.WindowManager.sub_toolbar_menu_open = BoolProperty(
        name="Animations", get=lambda _self: True, set=lambda _self, _value: None, options={"SKIP_SAVE"})
    _install_header_gate()
    _install_button_menu()


def unregister():
    _remove_button_menu()
    _remove_header_gate()
    handler = _gate_state.pop("draw_handler", None)
    if handler is not None:
        bpy.types.SpaceNodeEditor.draw_handler_remove(handler, "HEADER")
    _gate_state.pop("tints", None)
    previews = _gate_state.pop("previews", None)
    if previews is not None:
        from bpy.utils import previews as preview_api
        preview_api.remove(previews)
    del bpy.types.WindowManager.sub_toolbar_animation_index
    del bpy.types.WindowManager.sub_toolbar_popup_index
    del bpy.types.WindowManager.sub_toolbar_animation_search
    del bpy.types.WindowManager.sub_toolbar_menu_open
    del bpy.types.WindowManager.sub_toolbar_pose_index
    del bpy.types.WindowManager.sub_toolbar_pose_popup_index
    del bpy.types.WindowManager.sub_toolbar_pose_search
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
