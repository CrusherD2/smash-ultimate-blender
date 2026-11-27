from . import operators
from . import sub_swing_data
from . import ui    
from . import preset_handler

# Install presets on import
preset_handler.install_presets()

def register():
    preset_handler.register()
    import bpy
    if not bpy.app.timers.is_registered(operators.follow_active_bone_timer):
        bpy.app.timers.register(operators.follow_active_bone_timer, first_interval=0.5, persistent=True)

def unregister():
    import bpy
    if bpy.app.timers.is_registered(operators.follow_active_bone_timer):
        bpy.app.timers.unregister(operators.follow_active_bone_timer)
    preset_handler.unregister()    