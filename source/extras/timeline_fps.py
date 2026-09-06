import bpy
from bpy.props import IntProperty
from bpy.types import Operator

from ..addon_preferences import fps_presets, get_addon_preferences


class SUB_OT_set_fps_preset(Operator):
    bl_idname = "sub.set_fps_preset"
    bl_label = "Set Timeline FPS"
    bl_description = "Set the scene frame rate without changing FPS Base"
    bl_options = {"REGISTER", "UNDO"}

    fps: IntProperty(name="FPS", default=30, min=1, max=1000)

    def execute(self, context):
        context.scene.render.fps = int(self.fps)
        return {"FINISHED"}


def _is_timeline(context):
    area = context.area
    space = context.space_data
    if area is None or space is None or space.type != "DOPESHEET_EDITOR":
        return False
    if getattr(area, "ui_type", None) == "TIMELINE":
        return True
    if getattr(space, "mode", None) == "TIMELINE":
        return True
    dopesheet = getattr(space, "dopesheet", None)
    return dopesheet is not None and getattr(dopesheet, "mode", None) == "TIMELINE"


def draw_timeline_fps_buttons(self, context):
    if not _is_timeline(context):
        return
    prefs = get_addon_preferences(context)
    if prefs is not None and not prefs.show_timeline_fps_shortcuts:
        return

    row = self.layout.row(align=True)
    row.label(text="FPS:")
    current = context.scene.render.fps
    for fps in fps_presets(context):
        op = row.operator(
            SUB_OT_set_fps_preset.bl_idname,
            text=str(fps),
            depress=current == fps,
        )
        op.fps = fps
    self.layout.separator()


def register():
    bpy.utils.register_class(SUB_OT_set_fps_preset)
    bpy.types.DOPESHEET_HT_header.prepend(draw_timeline_fps_buttons)


def unregister():
    bpy.types.DOPESHEET_HT_header.remove(draw_timeline_fps_buttons)
    bpy.utils.unregister_class(SUB_OT_set_fps_preset)
