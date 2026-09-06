import bpy
from bpy.props import BoolProperty, CollectionProperty, EnumProperty, IntProperty, StringProperty
from bpy.types import AddonPreferences, Operator, PropertyGroup, UIList


ADDON_MODULE_NAME = (__package__ or "").split(".")[0]


class SUB_PG_param_labels_path(PropertyGroup):
    name: StringProperty(name="Label", default="")
    path: StringProperty(
        name="Path",
        description="An additional ParamLabels CSV file that receives generated hashes",
        default="",
        subtype="FILE_PATH",
    )


class SUB_PG_ultimate_panel_order_item(PropertyGroup):
    panel_id: StringProperty(options={'HIDDEN'})


class SUB_UL_ultimate_panel_order(UIList):
    def draw_item(self, _context, layout, _data, item, _icon, _active_data, _active_propname, _index):
        layout.label(text=item.name, icon='PREFERENCES')


class SUB_OP_move_ultimate_panel(Operator):
    bl_idname = "sub.move_ultimate_panel"
    bl_label = "Move Ultimate Panel"
    bl_description = "Move the selected panel in the persistent Ultimate sidebar order"
    bl_options = {'INTERNAL'}

    direction: EnumProperty(
        items=(('UP', "Up", "Move the panel up"), ('DOWN', "Down", "Move the panel down")),
        options={'HIDDEN'},
    )

    def execute(self, context):
        preferences = get_addon_preferences(context)
        if preferences is None:
            return {'CANCELLED'}
        from .panel_order import apply_saved_order, sync_preferences

        sync_preferences(preferences)
        index = preferences.ultimate_panel_order_index
        target = index - 1 if self.direction == 'UP' else index + 1
        if target < 0 or target >= len(preferences.ultimate_panel_order):
            return {'CANCELLED'}
        preferences.ultimate_panel_order.move(index, target)
        preferences.ultimate_panel_order_index = target
        apply_saved_order(preferences)
        return {'FINISHED'}


class SUB_OP_reset_ultimate_panel_order(Operator):
    bl_idname = "sub.reset_ultimate_panel_order"
    bl_label = "Reset Ultimate Panel Order"
    bl_description = "Restore the add-on's default Ultimate sidebar panel order"

    def execute(self, context):
        preferences = get_addon_preferences(context)
        if preferences is None:
            return {'CANCELLED'}
        from .panel_order import reset_to_default

        reset_to_default(preferences)
        return {'FINISHED'}


class SUB_AddonPreferences(AddonPreferences):
    bl_idname = ADDON_MODULE_NAME

    param_labels_paths: CollectionProperty(type=SUB_PG_param_labels_path)
    param_labels_paths_index: IntProperty(default=0)

    show_timeline_fps_shortcuts: BoolProperty(
        name="Show Timeline FPS Shortcuts",
        description="Show the configurable FPS buttons in the Timeline header",
        default=True,
    )
    fps_preset_1: IntProperty(name="FPS 1", default=5, min=1, max=1000)
    fps_preset_2: IntProperty(name="FPS 2", default=15, min=1, max=1000)
    fps_preset_3: IntProperty(name="FPS 3", default=30, min=1, max=1000)
    fps_preset_4: IntProperty(name="FPS 4", default=60, min=1, max=1000)

    show_nuanmb_extension_on_import: BoolProperty(
        name=".nuanmb",
        description="Keep the .nuanmb extension in imported Blender action names",
        default=False,
    )
    show_rawanim_extension_on_import: BoolProperty(
        name=".rawanim",
        description="Keep the .rawanim extension in imported Blender action names",
        default=True,
    )

    collection_preset_directory: StringProperty(
        name="Custom Collection Preset Directory",
        description="Directory used when the Collection Presets panel library is set to Custom",
        default="",
        subtype="DIR_PATH",
    )

    ultimate_panel_order: CollectionProperty(type=SUB_PG_ultimate_panel_order_item)
    ultimate_panel_order_index: IntProperty(default=0)

    def draw(self, _context):
        layout = self.layout

        box = layout.box()
        box.label(text="Timeline FPS Shortcuts")
        box.prop(self, "show_timeline_fps_shortcuts")
        row = box.row(align=True)
        row.prop(self, "fps_preset_1")
        row.prop(self, "fps_preset_2")
        row.prop(self, "fps_preset_3")
        row.prop(self, "fps_preset_4")

        box = layout.box()
        box.label(text="Show Animation File Extension")
        box.prop(self, "show_nuanmb_extension_on_import")
        box.prop(self, "show_rawanim_extension_on_import")

        box = layout.box()
        box.label(text="Armature Collection Presets")
        box.prop(self, "collection_preset_directory")

        box = layout.box()
        box.label(text="Ultimate Sidebar Panel Order")
        box.label(text="Select a panel and use the arrows. The order is saved in preferences.", icon='INFO')
        from .panel_order import sync_preferences

        sync_preferences(self)
        row = box.row()
        row.template_list(
            "SUB_UL_ultimate_panel_order",
            "",
            self,
            "ultimate_panel_order",
            self,
            "ultimate_panel_order_index",
            rows=8,
        )
        controls = row.column(align=True)
        op = controls.operator("sub.move_ultimate_panel", text="", icon='TRIA_UP')
        op.direction = 'UP'
        op = controls.operator("sub.move_ultimate_panel", text="", icon='TRIA_DOWN')
        op.direction = 'DOWN'
        controls.separator()
        controls.operator("sub.reset_ultimate_panel_order", text="", icon='LOOP_BACK')

        box = layout.box()
        box.label(text="Additional ParamLabels Files")
        controls = box.row(align=True)
        controls.operator("sub.add_param_labels_path", text="Add", icon="ADD")
        controls.operator("sub.remove_param_labels_path", text="Remove", icon="REMOVE")
        for item in self.param_labels_paths:
            box.prop(item, "path", text="")
        if not self.param_labels_paths:
            box.label(text="No additional files configured.", icon="INFO")


CLASSES = (
    SUB_PG_param_labels_path,
    SUB_PG_ultimate_panel_order_item,
    SUB_UL_ultimate_panel_order,
    SUB_OP_move_ultimate_panel,
    SUB_OP_reset_ultimate_panel_order,
    SUB_AddonPreferences,
)


def get_addon_preferences(context=None):
    context = context or bpy.context
    addon = context.preferences.addons.get(ADDON_MODULE_NAME)
    return addon.preferences if addon is not None else None


def fps_presets(context=None):
    prefs = get_addon_preferences(context)
    if prefs is None:
        return (5, 15, 30, 60)
    values = (
        prefs.fps_preset_1,
        prefs.fps_preset_2,
        prefs.fps_preset_3,
        prefs.fps_preset_4,
    )
    # Avoid duplicate buttons while preserving the configured order.
    return tuple(dict.fromkeys(int(value) for value in values))


def show_animation_extension_on_import(extension, context=None):
    """Return the configured import-name behavior, including safe defaults."""
    extension = extension.lower()
    prefs = get_addon_preferences(context)
    if extension == ".rawanim":
        return True if prefs is None else prefs.show_rawanim_extension_on_import
    if extension == ".nuanmb":
        return False if prefs is None else prefs.show_nuanmb_extension_on_import
    return False


def format_animation_name_on_import(stem, extension, context=None):
    """Format an imported action name using the per-format extension setting."""
    return stem + extension if show_animation_extension_on_import(extension, context) else stem


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
