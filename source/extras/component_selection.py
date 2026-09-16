"""Follow viewport controller selection without evaluating the rig."""
import bpy

_last = None


def sync(context):
    global _last
    scene=context.scene
    editor=getattr(scene,'sub_component_editor',None) if scene else None
    obj=context.view_layer.objects.active if context.view_layer else None
    if not editor or not editor.is_open or not obj or obj.type!='ARMATURE' or obj.mode!='POSE':
        _last=None
        return False
    bone=obj.data.bones.active
    token=(scene.as_pointer(),obj.as_pointer(),bone.as_pointer() if bone else 0)
    if token==_last:
        return False
    _last=token
    if editor.armature and editor.armature!=obj:
        return False
    if not bone or not bone.get('sub_component_control'):
        return False
    uid=bone.get('sub_face_owner') or bone.get('sub_component_id')
    for index,component in enumerate(editor.components):
        if component.uid==uid:
            editor.active_index=index
            for window in context.window_manager.windows:
                for area in window.screen.areas:
                    if area.type=='VIEW_3D': area.tag_redraw()
            return True
    return False


def _poll():
    try:
        sync(bpy.context)
    except (ReferenceError,AttributeError):
        pass
    return .2


def register():
    global _last
    _last=None
    if not bpy.app.background and not bpy.app.timers.is_registered(_poll):
        bpy.app.timers.register(_poll,first_interval=.2,persistent=True)


def unregister():
    global _last
    if bpy.app.timers.is_registered(_poll):
        bpy.app.timers.unregister(_poll)
    _last=None
