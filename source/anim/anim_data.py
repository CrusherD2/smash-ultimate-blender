import re
import sys
import inspect

import bpy

from bpy.types import Panel, Operator, UIList, Menu, PropertyGroup, Armature
from bpy.props import (
    IntProperty,
    StringProperty, 
    EnumProperty, 
    BoolProperty, 
    FloatProperty, 
    CollectionProperty, 
    PointerProperty,
    FloatVectorProperty,)

mat_sub_types = (
    ('VECTOR', 'Custom Vector', 'Custom Vector'),
    ('FLOAT', 'Custom Float', 'Custom Float'),
    ('BOOL', 'Custom Bool', 'Custom Bool'),
    ('PATTERN', 'Pattern Index', 'Pattern Index'),
    ('TEXTURE', 'Texture Transform', 'Texture Transform')
)

# Store the last known action for each armature to detect changes
_last_known_actions = {}

# Global owner object for msgbus subscriptions
_msgbus_owner = object()

# Handler to sync SAP data action with bone animation action
@bpy.app.handlers.persistent
def sync_sap_action_handler(scene):
    """
    Handler that automatically switches the SAP data action when the main action changes.
    This ensures that visibility and material animation data stays in sync with bone animation.
    """
    global _last_known_actions
    
    for obj in bpy.data.objects:
        if obj.type != 'ARMATURE':
            continue
        
        # Skip if no animation data
        if not obj.animation_data or not obj.animation_data.action:
            # Clear the stored action if there's no current action
            if obj.name in _last_known_actions:
                print(f"Clearing stored action for {obj.name}")
                del _last_known_actions[obj.name]
            continue
            
        # Skip if no armature data animation data
        if not obj.data.animation_data:
            continue
            
        current_action = obj.animation_data.action
        current_sap_action = obj.data.animation_data.action
        
        # Check if the action has changed since last time
        last_action = _last_known_actions.get(obj.name)
        if last_action == current_action:
            continue  # No change, skip
            
        # Update the stored action
        _last_known_actions[obj.name] = current_action
        
        # Look for corresponding SAP action
        expected_sap_action_name = f"{obj.name} {current_action.name} SAP Data"
        expected_sap_action = bpy.data.actions.get(expected_sap_action_name)
        
        # If we found a matching SAP action and it's different from current, switch to it
        if expected_sap_action and expected_sap_action != current_sap_action:
            obj.data.animation_data.action = expected_sap_action

# Additional handler for depsgraph updates (more frequent)
@bpy.app.handlers.persistent  
def sync_sap_action_depsgraph_handler(scene, depsgraph):
    """
    Alternative handler that runs on depsgraph updates.
    This catches more events including action changes.
    """
    sync_sap_action_handler(scene)

# Timer function for periodic checking
def sync_sap_timer():
    """
    Timer function that runs periodically to check for action changes.
    This is a fallback method to ensure SAP actions stay synced.
    """
    try:
        # Check if we're in a valid context for modifying data
        if bpy.context.mode in {'OBJECT', 'POSE'}:
            scene = bpy.context.scene
            sync_sap_action_handler(scene)
    except Exception as e:
        # Silently handle context errors
        pass
    
    # Return the interval for the next call (0.1 seconds)
    return 0.1

# Message bus callback for action changes
def action_change_msgbus_callback(*args):
    """
    Callback function for msgbus that triggers when animation_data.action changes.
    This provides more direct detection of action changes in the UI.
    """
    try:
        if bpy.context.mode in {'OBJECT', 'POSE'}:
            scene = bpy.context.scene
            sync_sap_action_handler(scene)
    except Exception as e:
        # Silently handle context errors
        pass

# Subscribe to action changes via msgbus
def subscribe_to_action_changes():
    """
    Subscribe to animation_data.action changes using Blender's message bus system.
    This provides more direct detection of action switching in the UI.
    """
    try:
        # Subscribe to changes in animation_data.action for all objects
        bpy.msgbus.subscribe_rna(
            key=(bpy.types.AnimData, "action"),
            owner=_msgbus_owner,
            args=(),
            notify=action_change_msgbus_callback,
        )
    except Exception as e:
        # Silently handle msgbus errors
        pass

def unsubscribe_from_action_changes():
    """
    Unsubscribe from action changes when cleaning up.
    """
    try:
        bpy.msgbus.clear_by_owner(_msgbus_owner)
    except:
        pass

# Modal operator for continuous monitoring
class SUB_OP_sap_sync_monitor(Operator):
    bl_idname = 'sub.sap_sync_monitor'
    bl_label = 'SAP Sync Monitor'
    bl_description = 'Start/stop continuous SAP action monitoring'
    
    action: EnumProperty(
        items=[
            ('TOGGLE', 'Toggle', 'Toggle monitoring on/off'),
            ('START', 'Start', 'Start monitoring'),
            ('STOP', 'Stop', 'Stop monitoring'),
        ],
        default='TOGGLE'
    )
    
    _timer = None
    _is_running = False
    
    @classmethod
    def poll(cls, context):
        return True
    
    def modal(self, context, event):
        if event.type == 'TIMER':
            # Check for action changes
            try:
                if context.mode in {'OBJECT', 'POSE'}:
                    sync_sap_action_handler(context.scene)
            except Exception as e:
                if "not allowed" not in str(e):
                    print(f"SAP sync monitor error: {e}")
        
        # Continue running
        return {'PASS_THROUGH'}
    
    def execute(self, context):
        should_start = False
        
        if self.action == 'START' or (self.action == 'TOGGLE' and not SUB_OP_sap_sync_monitor._is_running):
            should_start = True
        elif self.action == 'STOP' or (self.action == 'TOGGLE' and SUB_OP_sap_sync_monitor._is_running):
            should_start = False
        
        if should_start and not SUB_OP_sap_sync_monitor._is_running:
            # Start monitoring
            wm = context.window_manager
            SUB_OP_sap_sync_monitor._timer = wm.event_timer_add(0.1, window=context.window)
            wm.modal_handler_add(self)
            SUB_OP_sap_sync_monitor._is_running = True
            self.report({'INFO'}, "SAP sync monitoring started")
            return {'RUNNING_MODAL'}
        elif not should_start and SUB_OP_sap_sync_monitor._is_running:
            # Stop monitoring
            if SUB_OP_sap_sync_monitor._timer:
                wm = context.window_manager
                wm.event_timer_remove(SUB_OP_sap_sync_monitor._timer)
                SUB_OP_sap_sync_monitor._timer = None
            SUB_OP_sap_sync_monitor._is_running = False
            self.report({'INFO'}, "SAP sync monitoring stopped")
            return {'FINISHED'}
        
        return {'FINISHED'}



class SUB_OP_sync_sap_action(Operator):
    bl_idname = 'sub.sync_sap_action'
    bl_label = 'Sync SAP Action'
    bl_description = 'Manually sync the SAP data action with the current bone animation action'
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return (context.object and 
                context.object.type == 'ARMATURE' and 
                context.object.animation_data and 
                context.object.animation_data.action)

    def execute(self, context):
        obj = context.object
        
        if not obj.data.animation_data:
            self.report({'WARNING'}, "No SAP animation data found")
            return {'CANCELLED'}
            
        current_action = obj.animation_data.action
        expected_sap_action_name = f"{obj.name} {current_action.name} SAP Data"
        expected_sap_action = bpy.data.actions.get(expected_sap_action_name)
        
        if expected_sap_action:
            obj.data.animation_data.action = expected_sap_action
            self.report({'INFO'}, f"Synced SAP action to: {expected_sap_action_name}")
        else:
            self.report({'WARNING'}, f"No matching SAP action found: {expected_sap_action_name}")
            
        return {'FINISHED'}

class SUB_PT_sub_smush_anim_data_main(Panel):
    bl_label = "Ultimate Animation Data"
    bl_idname = __qualname__
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = "data"
    bl_options = {'DEFAULT_CLOSED'}

    @classmethod
    def poll(cls, context):
        if not context.object:
            return False
        return context.object.type == 'ARMATURE'

    def draw(self, context):
        layout = self.layout
        arma = context.object
        
        # Show auto-sync status and manual control
        box = layout.box()
        row = box.row()
        
        # Check if handlers are registered to show auto-sync status
        handlers_active = (sync_sap_action_handler in bpy.app.handlers.frame_change_post and
                          sync_sap_action_depsgraph_handler in bpy.app.handlers.depsgraph_update_post and
                          bpy.app.timers.is_registered(sync_sap_timer))
        
        if handlers_active:
            row.label(text="SAP Auto-Sync: Active", icon='CHECKMARK')
        else:
            row.label(text="SAP Auto-Sync: Inactive", icon='ERROR')
            
        # Manual sync button
        row.operator(SUB_OP_sync_sap_action.bl_idname, icon='FILE_REFRESH', text="Manual Sync")

class SUB_PT_sub_smush_anim_data_vis_tracks(Panel):
    bl_label = "Ultimate Visibility Track Entries"
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = "data"
    bl_options = {'DEFAULT_CLOSED'}
    bl_parent_id = SUB_PT_sub_smush_anim_data_main.bl_idname

    @classmethod
    def poll(cls, context):
        if not context.object:
            return False
        return context.object.type == 'ARMATURE'

    def draw(self, context):
        layout = self.layout
        obj = context.object
        arma = obj.data
        row = layout.row()
        row.template_list(
            "SUB_UL_vis_track_entries",
            "",
            arma.sub_anim_properties,
            "vis_track_entries",
            arma.sub_anim_properties,
            "active_vis_track_index",
            rows=5,
            maxrows=10,
            )
        col = row.column(align=True)
        col.operator(SUB_OP_vis_entry_add.bl_idname, icon='ADD', text="")
        col.operator(SUB_OP_vis_entry_remove.bl_idname, icon='REMOVE', text="")
        col.separator()
        col.menu("SUB_MT_vis_entry_context_menu", icon='DOWNARROW_HLT', text="")
        col.separator()
        col.operator(SUB_OP_vis_entry_shift.bl_idname, icon='TRIA_UP', text='').shift_direction = 'UP'
        col.operator(SUB_OP_vis_entry_shift.bl_idname, icon='TRIA_DOWN', text='').shift_direction = 'DOWN'

class SUB_PT_sub_smush_anim_data_mat_tracks(Panel):
    bl_label = "Ultimate Material Tracks"
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = "data"
    bl_options = {'DEFAULT_CLOSED'}
    bl_parent_id = SUB_PT_sub_smush_anim_data_main.bl_idname

    @classmethod
    def poll(cls, context):
        if not context.object:
            return False
        return context.object.type == 'ARMATURE'

    def draw(self, context):
        layout = self.layout
        obj = context.object
        arma = obj.data
        col = layout.column()
        row = col.row()
        split = row.split(factor=.4)
        c = split.column()
        c.label(text='Material Names')
        c.template_list(
            "SUB_UL_mat_tracks",
            "",
            arma.sub_anim_properties,
            "mat_tracks",
            arma.sub_anim_properties,
            "active_mat_track_index",
            rows=5,
            maxrows=5,
            )
        split = split.split(factor=.66)
        c = split.column()
        c.label(text='Property Names')
        amti = arma.sub_anim_properties.active_mat_track_index
        if len(arma.sub_anim_properties.mat_tracks) > 0:
            c.template_list(
                "SUB_UL_mat_properties",
                "",
                arma.sub_anim_properties.mat_tracks[amti],
                "properties",
                arma.sub_anim_properties.mat_tracks[amti],
                "active_property_index",
                rows=5,
                maxrows=5,
            )
        else:
            c.enabled = False
        split = split.split()
        c = split.column()
        c.enabled = False
        c.label(text='Property Values')
        if len(arma.sub_anim_properties.mat_tracks) > 0:
            if len(arma.sub_anim_properties.mat_tracks[amti].properties) > 0:
                '''
                After removing the last entry from the list, the 'active' index can remain its previous value
                which is now out of bounds
                '''
                amtpi = arma.sub_anim_properties.mat_tracks[amti].active_property_index
                if amtpi < len(arma.sub_anim_properties.mat_tracks[amti].properties):
                    ap = arma.sub_anim_properties.mat_tracks[amti].properties[amtpi]
                    if ap.sub_type == 'VECTOR':
                        c.prop(ap, "custom_vector", text="")
                        c.prop(ap, "custom_vector", text="", index=0)
                        c.prop(ap, "custom_vector", text="", index=1)
                        c.prop(ap, "custom_vector", text="", index=2)
                        c.prop(ap, "custom_vector", text="", index=3)
                    elif ap.sub_type == 'FLOAT':
                        c.prop(ap, "custom_float", text="", emboss=False)
                    elif ap.sub_type == 'BOOL':
                        icon = 'CHECKBOX_HLT' if ap.custom_bool == True else 'CHECKBOX_DEHLT'
                        c.prop(ap, "custom_bool", text="", icon=icon, emboss=False)
                    elif ap.sub_type == 'PATTERN':
                        c.prop(ap, "pattern_index", text="", emboss=False)
                    elif ap.sub_type == 'TEXTURE':
                        c.prop(ap, "texture_transform", text="", emboss=False)
                    c.enabled = True
        # Bottom Row, composed of 3 Sub Rows algined with the above columns
        row = layout.row()
        # Sub Row 1
        split = row.split(factor=.4)
        sr = split.row(align=True)
        sr.operator(SUB_OP_mat_track_add.bl_idname, text='+')
        sr.operator(SUB_OP_mat_track_remove.bl_idname, text='-')
        # Sub Row 2
        split = split.split(factor=.66)
        sr = split.row(align=True)
        sr.operator(SUB_OP_mat_property_add.bl_idname, text='+')
        sr.operator(SUB_OP_mat_property_remove.bl_idname, text='-')
        sr.operator(SUB_OP_mat_property_shift.bl_idname, icon='TRIA_UP', text='').shift_direction = 'UP'
        sr.operator(SUB_OP_mat_property_shift.bl_idname, icon='TRIA_DOWN', text='').shift_direction = 'DOWN'
        # Sub 3
        split = split.split()
        sr = split.row(align=True)
        sr.menu('SUB_MT_mat_entry_context_menu', text='Drivers...')      

class SUB_OP_mat_track_add(Operator):
    bl_idname = 'sub.mat_track_add'
    bl_label  = 'Add Mat Track'

    def execute(self, context):
        mat_tracks = context.object.data.sub_anim_properties.mat_tracks
        mat_track = mat_tracks.add()
        mat_track.name = 'NewMaterialTrack'
        sap = context.object.data.sub_anim_properties
        sap.active_mat_track_index = sap.mat_tracks.find(mat_track.name)
        return {'FINISHED'}

class SUB_OP_mat_track_remove(Operator):
    bl_idname = 'sub.mat_track_remove'
    bl_label = 'Remove Mat Track'

    @classmethod
    def poll(cls, context):
        sap = context.object.data.sub_anim_properties
        return len(sap.mat_tracks) > 0

    def execute(self, context):
        sap = context.object.data.sub_anim_properties
        amt = sap.mat_tracks[sap.active_mat_track_index]
        # Find matching Fcurve and Remove
        try:
            fcurves = context.object.data.animation_data.action.fcurves
        except AttributeError:
            sap.mat_tracks.remove(sap.active_mat_track_index)
            i = sap.active_mat_track_index
            sap.active_mat_track_index = min(max(0,i-1),len(sap.mat_tracks))
            return {'FINISHED'}
        # Remove fcurves of all properties of this material track
        for fc in fcurves:
            amti = sap.active_mat_track_index
            if fc.data_path.startswith(f"sub_anim_properties.mat_tracks[{amti}]"):
                fcurves.remove(fc)
        # The remaining materials with an index greater than this one must have all thier fcurves adjusted
        fcurves = context.object.data.animation_data.action.fcurves
        for fc in fcurves:
            regex = r"sub_anim_properties\.mat_tracks\[(\d+)\](\.properties\[\d+\]\.\w+)"
            matches = re.match(regex, fc.data_path)
            if matches is None:
                continue
            if len(matches.groups()) < 2:
                continue
            cmti = int(matches.groups()[0])
            suffix = matches.groups()[1]
            amti = sap.active_mat_track_index
            if cmti < amti:
                continue
            new_data_path = f"sub_anim_properties.mat_tracks[{cmti-1}]{suffix}"
            fc.data_path = new_data_path
        # Now actually remove the material track
        sap.mat_tracks.remove(sap.active_mat_track_index)
        i = sap.active_mat_track_index
        sap.active_mat_track_index = min(max(0,i-1),len(sap.mat_tracks))
        # Refresh Material Drivers
        remove_anim_material_drivers(context.object)
        from .import_anim import setup_material_drivers
        setup_material_drivers(context.object)
        return {'FINISHED'}

class SUB_OP_mat_property_add(Operator):
    bl_idname = 'sub.mat_prop_add'
    bl_label = 'Add Material Property'
    bl_property = "sub_type"

    sub_type: bpy.props.EnumProperty(
        name='Mat Track Entry Subtype',
        description='',
        items=mat_sub_types, 
        default='VECTOR',)

    @classmethod
    def poll(cls, context):
        sap = context.object.data.sub_anim_properties
        return len(sap.mat_tracks) > 0

    def execute(self, context):
        sap = context.object.data.sub_anim_properties
        props = sap.mat_tracks[sap.active_mat_track_index].properties
        prop = props.add()
        prop.sub_type = self.sub_type
        if prop.sub_type == 'VECTOR':
            prop.name = f'CustomVectorX'
        elif prop.sub_type == 'FLOAT':
            prop.name = f'CustomFloatX'
        elif prop.sub_type == 'BOOL':
            prop.name = f'CustomBooleanX'
        else:
            prop.name = f'New{prop.sub_type}Property'
        sap.mat_tracks[sap.active_mat_track_index].active_property_index = props.find(prop.name)
        return {'FINISHED'}
    def invoke(self, context, event):
        context.window_manager.invoke_search_popup(self)
        return {'RUNNING_MODAL'}

def refresh_material_drivers(context):
    from .import_anim import setup_material_drivers
    remove_anim_material_drivers(context.object)
    setup_material_drivers(context.object)

class SUB_OP_mat_property_remove(Operator):
    bl_idname = 'sub.mat_prop_remove'
    bl_label = 'Remove Material Property'

    @classmethod
    def poll(cls, context):
        sap = context.object.data.sub_anim_properties
        if len(sap.mat_tracks) > 0:
            active_track = sap.mat_tracks[sap.active_mat_track_index]
            if len(active_track.properties) > 0:
                return True
        return False

    def execute(self, context):
        sap = context.object.data.sub_anim_properties
        amt = sap.mat_tracks[sap.active_mat_track_index]  
        try:
            fcurves = context.object.data.animation_data.action.fcurves
        except AttributeError:
            amt.properties.remove(amt.active_property_index)
            i = amt.active_property_index
            amt.active_property_index = min(max(0,i-1), len(amt.properties)-1)
            return {'FINISHED'}
        # Remove matching fcurve
        for fc in fcurves:
            amti = sap.active_mat_track_index
            api = sap.mat_tracks[amti].active_property_index
            if fc.data_path.startswith(f"sub_anim_properties.mat_tracks[{amti}].properties[{api}]"):
                fcurves.remove(fc)
        # The material's remaining properties' fcurves with indexes greater to this one must be decremented
        fcurves = context.object.data.animation_data.action.fcurves

        for fc in fcurves:    
            regex = r"sub_anim_properties\.mat_tracks\[(\d+)\]\.properties\[(\d+)\](\.\w+)"
            matches = re.match(regex, fc.data_path)
            if matches is None:
                continue
            if len(matches.groups()) < 3:
                continue
            cmti = int(matches.groups()[0])
            cpi = int(matches.groups()[1])
            suffix = matches.groups()[2]
            amti = sap.active_mat_track_index
            api = sap.mat_tracks[amti].active_property_index
            if cmti != amti or cpi <= api:
                continue
            new_data_path = f"sub_anim_properties.mat_tracks[{cmti}].properties[{cpi-1}]{suffix}"
            fc.data_path = new_data_path 
        # Now actually remove the property
        amt.properties.remove(amt.active_property_index)
        i = amt.active_property_index
        amt.active_property_index = min(max(0,i-1), len(amt.properties)-1)
        # Refresh Material Drivers
        refresh_material_drivers(context)
        return {'FINISHED'}

def change_mat_property_fcurve_target_index(fcurve, new_property_index):
    regex = r"sub_anim_properties\.mat_tracks\[(\d+)\]\.properties\[(\d+)\](\.\w+)"
    matches = re.match(regex, fcurve.data_path)
    if matches is None:
        return
    if len(matches.groups()) < 3:
        return
    mat_track_index = int(matches.groups()[0])
    _property_index = int(matches.groups()[1])
    suffix = matches.groups()[2]
    new_data_path = f"sub_anim_properties.mat_tracks[{mat_track_index}].properties[{new_property_index}]{suffix}"
    fcurve.data_path = new_data_path

def swap_mat_property_fcurve_target_indices(fcurves, sap, index_a, index_b):
    amti = sap.active_mat_track_index

    a_data_path = f"sub_anim_properties.mat_tracks[{amti}].properties[{index_a}]"
    a_fcurves = [fc for fc in fcurves if fc.data_path.startswith(a_data_path)]
    
    b_data_path = f"sub_anim_properties.mat_tracks[{amti}].properties[{index_b}]"
    b_fcurves = [fc for fc in fcurves if fc.data_path.startswith(b_data_path)]
    
    for fc in a_fcurves:
        change_mat_property_fcurve_target_index(fc, index_b)
    for fc in b_fcurves:
        change_mat_property_fcurve_target_index(fc, index_a)
          
class SUB_OP_mat_property_shift(Operator):
    bl_idname = 'sub.mat_property_shift'
    bl_label = 'Shift Mat Propery'

    shift_direction: EnumProperty(
        name='Shift Direction',
        description='The direction to shift',
        items=[('UP', 'Up', 'Shift it up'),
                ('DOWN', 'Down', 'Shift it down')])
    
    @classmethod
    def poll(cls, context):
        sap = context.object.data.sub_anim_properties
        if len(sap.mat_tracks) >= 1:
            active_track = sap.mat_tracks[sap.active_mat_track_index]
            if len(active_track.properties) >= 2:
                return True
        return False
    
    def execute(self, context):
        sap = context.object.data.sub_anim_properties
        active_mat = sap.mat_tracks[sap.active_mat_track_index]
        active_property_index = active_mat.active_property_index
            
        if (self.shift_direction == 'UP' and active_property_index == 0) or \
           (self.shift_direction == 'DOWN' and active_property_index == len(active_mat.properties)-1):
                return {'CANCELLED'}
        
        other_index = active_property_index-1 if self.shift_direction == 'UP' else active_property_index+1
            
        # Getting fcurves without throwing an exception is hard, so rather than do 3 "is not None" checks do one "try"    
        try:
            fcurves = context.object.data.animation_data.action.fcurves
        except AttributeError: # Theres no fcurves
            pass
        else: # Theres fcurves
            swap_mat_property_fcurve_target_indices(fcurves, sap, active_property_index, other_index)

        active_mat.properties.move(active_property_index, other_index)
        active_mat.active_property_index = other_index
        # Refresh Material Drivers
        refresh_material_drivers(context)
        return {'FINISHED'}
    
class SUB_OP_vis_entry_add(Operator):
    bl_idname = 'sub.vis_entry_add'
    bl_label = 'Add Vis Track Entry'

    def execute(self, context):
        entries = context.object.data.sub_anim_properties.vis_track_entries
        entry = entries.add()
        entry.name = 'NewVisTrackEntry'
        entry.value = True
        sap = context.object.data.sub_anim_properties
        sap.active_vis_track_index = entries.find(entry.name)
        return {'FINISHED'} 

def refresh_visibility_drivers(context):
    from .import_anim import setup_visibility_drivers
    remove_visibility_drivers(context)
    setup_visibility_drivers(context.object)

class SUB_OP_vis_entry_remove(Operator):
    bl_idname = 'sub.vis_entry_remove'
    bl_label = 'Remove Vis Track Entry'

    @classmethod
    def poll(cls, context):
        sap = context.object.data.sub_anim_properties
        return len(sap.vis_track_entries) > 0

    def execute(self, context):
        sap = context.object.data.sub_anim_properties
        active_vis_track_index = sap.active_vis_track_index
        
        try:
            fcurves = context.object.data.animation_data.action.fcurves
        except AttributeError:
            pass
        else:
            fcurve_to_remove = fcurves.find(f'sub_anim_properties.vis_track_entries[{active_vis_track_index}].value')
            if fcurve_to_remove is not None:
                fcurves.remove(fcurve_to_remove)
            for index in range(active_vis_track_index+1, len(sap.vis_track_entries)):
                fcurve_to_decrement = fcurves.find(f'sub_anim_properties.vis_track_entries[{index}].value')
                if fcurve_to_decrement is not None:
                    fcurve_to_decrement.data_path = f'sub_anim_properties.vis_track_entries[{index-1}].value'
        
        sap.vis_track_entries.remove(active_vis_track_index)
        i = active_vis_track_index
        sap.active_vis_track_index = min(max(0, i-1), len(sap.vis_track_entries))

        refresh_visibility_drivers(context)       
        return {'FINISHED'} 
    
class SUB_OP_vis_entry_shift(Operator):
    bl_idname = 'sub.vis_entry_shift'
    bl_label = 'Shift Vis Entry'

    shift_direction: EnumProperty(
        name='Shift Direction',
        description='The direction to shift',
        items=[('UP', 'Up', 'Shift it up'),
                ('DOWN', 'Down', 'Shift it down')])
    
    @classmethod
    def poll(cls, context):
        sap = context.object.data.sub_anim_properties
        return len(sap.vis_track_entries) > 1
    
    def execute(self, context):
        sap = context.object.data.sub_anim_properties
        vis_entries = sap.vis_track_entries
        active_vis_entry_index = sap.active_vis_track_index
            
        if (self.shift_direction == 'UP' and active_vis_entry_index == 0) or \
           (self.shift_direction == 'DOWN' and active_vis_entry_index == len(vis_entries)-1):
                return {'CANCELLED'}
        
        other_index = active_vis_entry_index-1 if self.shift_direction == 'UP' else active_vis_entry_index+1
            
        # Getting fcurves without throwing an exception is hard, so rather than do 3 "is not None" checks do one "try"    
        try:
            fcurves = context.object.data.animation_data.action.fcurves
        except AttributeError: # Theres no fcurves
            pass
        else: # Theres fcurves
            active_fcurve = fcurves.find(f"sub_anim_properties.vis_track_entries[{active_vis_entry_index}].value")
            other_fcurve = fcurves.find(f"sub_anim_properties.vis_track_entries[{other_index}].value")
            if active_fcurve is not None:
                active_fcurve.data_path = f"sub_anim_properties.vis_track_entries[{other_index}].value"
            if other_fcurve is not None:
                other_fcurve.data_path = f"sub_anim_properties.vis_track_entries[{active_vis_entry_index}].value"

        vis_entries.move(active_vis_entry_index, other_index)
        sap.active_vis_track_index = other_index
        refresh_visibility_drivers(context)
        return {'FINISHED'}

class SUB_OP_vis_drivers_refresh(Operator):
    bl_idname = 'sub.vis_drivers_refresh'
    bl_label = 'Refresh Visibility Drivers'

    def execute(self, context):
        refresh_visibility_drivers(context)
        return {'FINISHED'} 

class SUB_OP_vis_drivers_remove(Operator):
    bl_idname = 'sub.vis_drivers_remove'
    bl_label = 'Remove Visibility Drivers'

    def execute(self, context):
        remove_visibility_drivers(context)
        return {'FINISHED'}

class SUB_OP_auto_fill_vis_entries(Operator):
    bl_idname = 'sub.auto_fill_vis_entries'
    bl_label = 'Auto Fill Vis Entries'

    @classmethod
    def poll(cls, context):
        if not context.object:
            return False
        return context.object.type == 'ARMATURE'

    def execute(self, context):
        arma: bpy.types.Object = context.object
        mesh_names = {child.name for child in arma.children if child.type == 'MESH'}
        vis_names: set[str] = set()
        for name in mesh_names:
            regex = r"(.*)\_VIS\_.*"
            match = re.match(regex, name)
            if match:
                vis_names.add(match.groups()[0])
        sap: SUB_PG_sub_anim_data = arma.data.sub_anim_properties
        for vis_name in vis_names:
            if vis_name not in sap.vis_track_entries:
                new_entry: SUB_PG_vis_track_entry = sap.vis_track_entries.add()
                new_entry.name = vis_name
                new_entry.value = True
        return {'FINISHED'}

class SUB_OP_set_all_vis_entries_false(Operator):
    bl_idname = 'sub.set_all_vis_entries_false'
    bl_label = 'Set All Vis Entries False'

    @classmethod
    def poll(cls, context):
        if not context.object:
            return False
        return context.object.type == 'ARMATURE'
    
    def execute(self, context):
        for vis_entry in context.object.data.sub_anim_properties.vis_track_entries:
            vis_entry.value = False
        return {'FINISHED'}

class SUB_OP_set_all_vis_entries_true(Operator):
    bl_idname = 'sub.set_all_vis_entries_true'
    bl_label = 'Set All Vis Entries True'

    @classmethod
    def poll(cls, context):
        if not context.object:
            return False
        return context.object.type == 'ARMATURE'
    
    def execute(self, context):
        for vis_entry in context.object.data.sub_anim_properties.vis_track_entries:
            vis_entry.value = True
        return {'FINISHED'}

class SUB_OP_insert_all_vis_entry_keyframes(Operator):
    bl_idname = 'sub.insert_all_vis_entry_keyframes'
    bl_label = 'Insert All Vis Entry Keyframes'

    @classmethod
    def poll(cls, context):
        if not context.object:
            return False
        return context.object.type == 'ARMATURE'
    
    def execute(self, context):
        arma: bpy.types.Object = context.object
        sap: SUB_PG_sub_anim_data = arma.data.sub_anim_properties
        for index, vis_entry in enumerate(sap.vis_track_entries):
            arma.data.keyframe_insert(data_path=f'sub_anim_properties.vis_track_entries[{index}].value', group='Visibility')
        return {'FINISHED'}

class SUB_OP_organize_vis_entries_alphabetically(Operator):
    bl_idname = 'sub.organize_vis_entries_alphabetically'
    bl_label = 'Organize Vis Entries Alphabetically'

    @classmethod
    def poll(cls, context):
        if not context.object:
            return False
        return context.object.type == 'ARMATURE'
    
    def execute(self, context):
        arma: bpy.types.Object = context.object
        sap: SUB_PG_sub_anim_data = arma.data.sub_anim_properties
        
        # Get all entries and sort them alphabetically by full name
        entries = list(sap.vis_track_entries)
        entries.sort(key=lambda x: x.name.lower())
        
        # Use bubble sort approach to avoid conflicts
        for i in range(len(entries)):
            for j in range(len(entries) - 1):
                current_entry = sap.vis_track_entries[j]
                next_entry = sap.vis_track_entries[j + 1]
                
                # Compare names (case-insensitive)
                if current_entry.name.lower() > next_entry.name.lower():
                    # Swap positions
                    sap.vis_track_entries.move(j, j + 1)
        
        # Reset active index
        sap.active_vis_track_index = 0
        
        refresh_visibility_drivers(context)
        return {'FINISHED'}

class SUB_OP_organize_vis_entries_by_move(Operator):
    bl_idname = 'sub.organize_vis_entries_by_move'
    bl_label = 'Organize Vis Entries by Move'

    @classmethod
    def poll(cls, context):
        if not context.object:
            return False
        return context.object.type == 'ARMATURE'
    
    def execute(self, context):
        arma: bpy.types.Object = context.object
        sap: SUB_PG_sub_anim_data = arma.data.sub_anim_properties
        
        # Get all entries
        entries = list(sap.vis_track_entries)
        
        # Group entries by their move type (last part after underscore)
        move_groups = {}
        for entry in entries:
            # Split by underscore and get the last part
            parts = entry.name.split('_')
            if len(parts) > 1:
                move_type = parts[-1]  # Last part after underscore
                if move_type not in move_groups:
                    move_groups[move_type] = []
                move_groups[move_type].append(entry)
            else:
                # If no underscore, put in a special group
                if 'no_move_type' not in move_groups:
                    move_groups['no_move_type'] = []
                move_groups['no_move_type'].append(entry)
        
        # Sort move types alphabetically
        sorted_move_types = sorted(move_groups.keys())
        
        # Create the desired order - group by move type, then sort alphabetically within each group
        desired_order = []
        for move_type in sorted_move_types:
            # Sort entries within each move type alphabetically
            move_entries = sorted(move_groups[move_type], key=lambda x: x.name.lower())
            desired_order.extend(move_entries)
        
        # Move entries to their correct positions using a more direct approach
        # Create a mapping of entry names to their desired positions
        name_to_desired = {entry.name: i for i, entry in enumerate(desired_order)}
        
        # Sort the current list based on the desired order
        for i in range(len(sap.vis_track_entries)):
            for j in range(len(sap.vis_track_entries) - 1):
                current_entry = sap.vis_track_entries[j]
                next_entry = sap.vis_track_entries[j + 1]
                
                # Get desired positions
                current_desired = name_to_desired.get(current_entry.name, len(desired_order))
                next_desired = name_to_desired.get(next_entry.name, len(desired_order))
                
                # If they're in wrong order, swap them
                if current_desired > next_desired:
                    sap.vis_track_entries.move(j, j + 1)
        
        # Reset active index
        sap.active_vis_track_index = 0
        
        refresh_visibility_drivers(context)
        return {'FINISHED'}

def remove_visibility_drivers(context):
    arma = context.object
    mesh_children = [child for child in arma.children if child.type == 'MESH']
    for m in mesh_children:
        if not m.animation_data:
            continue
        drivers = m.animation_data.drivers
        for d in drivers:
            if any(d.data_path == s for s in ['hide_viewport', 'hide_render']):
                drivers.remove(d)

def remove_anim_material_drivers(arma:bpy.types.Object):
    from ..model.material.sub_matl_data import SUB_PG_sub_matl_data
    from ..model.material.create_blender_materials_from_matl import setup_sub_matl_data_node_drivers
    mesh_children = [child for child in arma.children if child.type == 'MESH']
    materials = {material_slot.material for mesh in mesh_children for material_slot in mesh.material_slots}
    for material in materials:
        for node in material.node_tree.nodes:
            for output in node.outputs:
                if hasattr(output, 'default_value'):
                    output.driver_remove('default_value')
        
        sub_matl_data: SUB_PG_sub_matl_data = material.sub_matl_data
        if sub_matl_data is not None:
            setup_sub_matl_data_node_drivers(sub_matl_data)    

class SUB_OP_mat_drivers_refresh(Operator):
    bl_idname = 'sub.mat_drivers_refresh'
    bl_label = 'Refresh Material Drivers'   

    def execute(self, context):
        refresh_material_drivers(context)
        return {'FINISHED'}  

class SUB_OP_mat_drivers_remove(Operator):
    bl_idname = 'sub.mat_drivers_remove'
    bl_label = 'Remove Material Drivers'

    def execute(self, context):
        remove_anim_material_drivers(context.object)
        return {'FINISHED'}  

class SUB_MT_vis_entry_context_menu(Menu):
    bl_label = "Vis Entry Specials"

    def draw(self, context):
        layout = self.layout
        layout.operator('sub.vis_drivers_refresh', icon='FILE_REFRESH', text='Refresh Visibility Drivers')
        layout.operator('sub.vis_drivers_remove', icon='X', text='Remove Visibility Drivers')
        layout.separator()
        layout.operator('sub.auto_fill_vis_entries', icon='SHADERFX', text='Autofill Visibility Entries')
        layout.operator('sub.insert_all_vis_entry_keyframes', icon='KEY_HLT', text='Insert Keyframes for All Entries')
        layout.separator()
        layout.operator('sub.organize_vis_entries_alphabetically', icon='SORTALPHA', text='Organize Alphabetically')
        layout.operator('sub.organize_vis_entries_by_move', icon='SORTSIZE', text='Organize by Move')
        layout.separator()
        layout.operator('sub.set_all_vis_entries_false', icon='HIDE_ON', text='Set All Entries Off')
        layout.operator('sub.set_all_vis_entries_true', icon='HIDE_OFF', text='Set All Entries On')
        
class SUB_MT_mat_entry_context_menu(Menu):
    bl_label = "Mat Entry Specials"

    def draw(self, context):
        layout = self.layout
        layout.operator(SUB_OP_mat_drivers_refresh.bl_idname, icon='FILE_REFRESH', text='Refresh Material Drivers')
        layout.operator(SUB_OP_mat_drivers_remove.bl_idname, icon='X', text='Remove Material Drivers')

class SUB_UL_vis_track_entries(UIList):
    def draw_item(self, _context, layout, _data, item, icon, active_data, _active_propname, index):
        # assert(isinstance(item, bpy.types.ShapeKey))
        obj = active_data
        # key = data
        entry = item
        if self.layout_type in {'DEFAULT', 'COMPACT'}:
            split = layout.split(factor=0.66, align=False)
            split.prop(entry, "name", text="", emboss=False, icon='HIDE_OFF')
            row = split.row(align=True)
            row.emboss = 'NONE_OR_STATUS'
            row.label(text="")
            icon = 'CHECKBOX_HLT' if entry.value == True else 'CHECKBOX_DEHLT'
            row.prop(entry, "value", text="", icon=icon, emboss=False)
        elif self.layout_type == 'GRID':
            layout.alignment = 'CENTER'
            layout.label(text="", icon_value=icon)

class SUB_UL_mat_tracks(UIList):
    def draw_item(self, _context, layout, _data, item, icon, active_data, _active_propname, index):
        obj = active_data
        entry = item
        if self.layout_type in {'DEFAULT', 'COMPACT'}:
            row = layout.row()
            row.prop(entry, "name", text="", emboss=False, icon='MATERIAL')
        elif self.layout_type == 'GRID':
            layout.alignment = 'CENTER'
            layout.label(text="", icon_value=icon)

class SUB_UL_mat_properties(UIList):
    def draw_item(self, _context, layout, _data, item, icon, active_data, _active_propname, index):
        obj = active_data
        entry = item
        if self.layout_type in {'DEFAULT', 'COMPACT'}:
            row = layout.row()
            row.prop(entry, "name", text="", emboss=False)
        elif self.layout_type == 'GRID':
            layout.alignment = 'CENTER'
            layout.label(text="", icon_value=icon)

class SUB_UL_mat_property_values(UIList):
    def draw_item(self, _context, layout, _data, item, icon, active_data, _active_propname, index):
        obj = active_data
        entry = item
        if self.layout_type in {'DEFAULT', 'COMPACT'}:
            row = layout.row()
            if entry.sub_type == 'VECTOR':
                row.prop(entry, "custom_vector", text="", emboss=False)
            elif entry.sub_type == 'FLOAT':
                row.prop(entry, "custom_float", text="", emboss=False)
            elif entry.sub_type == 'BOOL':
                row.prop(entry, "custom_bool", text="", emboss=False)
            elif entry.sub_type == 'PATTERN':
                row.prop(entry, "pattern_index", text="", emboss=False)
            elif entry.sub_type == 'TEXTURE':
                row.prop(entry, "texture_transform", text="", emboss=False)
        elif self.layout_type == 'GRID':
            layout.alignment = 'CENTER'
            layout.label(text="", icon_value=icon)        




def vis_track_name_update(self, context):
    sap = context.object.data.sub_anim_properties
    dupe = None
    for vt in sap.vis_track_entries:
        if vt.as_pointer() == self.as_pointer():
            continue
        if vt.name == self.name:
            dupe = vt
            break  
    if dupe is None:
        return
    regex = r"(\w+\.)(\d+)"
    matches = re.match(regex, self.name)
    if matches is None:
        self.name = self.name + '.001'
    else:
        base_name = matches.groups()[0]
        number = int(matches.groups()[1])
        self.name = f'{base_name}{number+1:003d}' 



def mat_track_prop_name_update(self, context):
    sap = context.object.data.sub_anim_properties
    found = False
    current_mat_track_index = None
    for mat_track_index, mat_track in enumerate(sap.mat_tracks):
        for property in mat_track.properties:
            if property.as_pointer() == self.as_pointer():
                current_mat_track_index = mat_track_index
                found = True
                break
        if found:
            break
    current_mat_track = sap.mat_tracks[current_mat_track_index]
    # There should be at most only one duplicate
    dupe = None
    for p in current_mat_track.properties:
        if p.as_pointer() == self.as_pointer():
            continue
        if p.name == self.name:
            dupe = p
            break
    # No duplicate found, name can remain as is
    if dupe is None:
        return
    # Regex match the name, see if it already has like '.001'
    # if it doesnt then add the '.001', otherwise increment the number
    regex = r"(\w+\.)(\d+)"
    matches = re.match(regex, self.name)
    if matches is None:
        self.name = self.name + '.001'
    else:
        base_name = matches.groups()[0]
        number = int(matches.groups()[1])
        self.name = f'{base_name}{number+1:003d}'

def mat_track_name_update(self, context):
    sap = context.object.data.sub_anim_properties
    dupe = None
    for mt in sap.mat_tracks:
        if mt.as_pointer() == self.as_pointer():
            continue
        if mt.name == self.name:
            dupe = mt
            break  
    if dupe is None:
        return
    regex = r"(\w+\.)(\d+)"
    matches = re.match(regex, self.name)
    if matches is None:
        self.name = self.name + '.001'
    else:
        base_name = matches.groups()[0]
        number = int(matches.groups()[1])
        self.name = f'{base_name}{number+1:003d}' 

def dummy_update(self, context):
    '''
    This is needed to force blender to update the driver values when updating via a modal.
    '''
    pass

class SUB_PG_vis_track_entry(PropertyGroup):
    name: StringProperty(
        name="Vis Name",
        default="Unknown",
        update=vis_track_name_update,)
    value: BoolProperty(name="Visible", default=False, update=dummy_update)

class SUB_PG_mat_track_property(PropertyGroup):
    name: StringProperty(
        name="Property Name",
        default="Unknown",
        update=mat_track_prop_name_update,)
    sub_type: EnumProperty(
        name='Mat Track Entry Subtype',
        description='CustomVector or CustomFloat or CustomBool',
        items=mat_sub_types, 
        default='VECTOR',)
    custom_vector: FloatVectorProperty(name='Custom Vector', size=4, update=dummy_update, subtype='COLOR_GAMMA', soft_min=0.0, soft_max=1.0)
    custom_bool: BoolProperty(name='Custom Bool')
    custom_float: FloatProperty(name='Custom Float')
    pattern_index: IntProperty(name='Pattern Index', subtype='UNSIGNED')
    texture_transform: FloatVectorProperty(name='Texture Transform', size=5)

class SUB_PG_mat_track(PropertyGroup):
    name: StringProperty(
        name="Material Name",
        default="Unknown",
        update=mat_track_name_update,)
    properties: CollectionProperty(type=SUB_PG_mat_track_property)
    active_property_index: IntProperty(name='Active Mat Property Index', default=0, options={'HIDDEN'})

class SUB_PG_sub_anim_data(PropertyGroup):
    vis_track_entries: CollectionProperty(type=SUB_PG_vis_track_entry)
    active_vis_track_index: IntProperty(name='Active Vis Track Index', default=0, options={'HIDDEN'})
    mat_tracks: CollectionProperty(type=SUB_PG_mat_track)
    active_mat_track_index: IntProperty(name='Active Mat Track Index', default=0, options={'HIDDEN'})

# Auto-start system functions
def init_sap_auto_sync():
    """Initialize the SAP auto-sync system - called from main addon register"""
    print("SAP Auto-Sync system activated")
    print("✅ SAP handlers and timer registered for automatic synchronization")
    
    # Subscribe to action changes for more direct detection
    subscribe_to_action_changes()

def cleanup_sap_auto_sync():
    """Cleanup the SAP auto-sync system - called from main addon unregister"""
    # Stop the SAP monitor if running
    if SUB_OP_sap_sync_monitor._is_running and SUB_OP_sap_sync_monitor._timer:
        try:
            wm = bpy.context.window_manager
            if wm:
                wm.event_timer_remove(SUB_OP_sap_sync_monitor._timer)
            SUB_OP_sap_sync_monitor._timer = None
            SUB_OP_sap_sync_monitor._is_running = False
            print("SAP Monitor stopped")
        except:
            pass
    
    # Unsubscribe from action changes
    unsubscribe_from_action_changes()

def register():
    """Register only handlers and timers - classes are registered separately"""
    # Register the SAP action sync handlers
    if sync_sap_action_handler not in bpy.app.handlers.frame_change_post:
        bpy.app.handlers.frame_change_post.append(sync_sap_action_handler)
    
    if sync_sap_action_depsgraph_handler not in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.append(sync_sap_action_depsgraph_handler)
    
    # Also register a timer for more frequent checking
    if not bpy.app.timers.is_registered(sync_sap_timer):
        bpy.app.timers.register(sync_sap_timer, first_interval=0.1, persistent=True)
    
    # Subscribe to action changes for direct detection
    subscribe_to_action_changes()
    

    """
    for name, obj in inspect.getmembers(
        sys.modules[__name__], 
        lambda member: inspect.isclass(member) and member.__module__ == __name__ and issubclass(member, bpy.types.bpy_struct)):
        print(f"{name}, {obj}")
        bpy.utils.register_class()
    """

def unregister():
    """Unregister only handlers and timers - classes are unregistered separately"""
    # Unregister all SAP action sync handlers
    if sync_sap_action_handler in bpy.app.handlers.frame_change_post:
        bpy.app.handlers.frame_change_post.remove(sync_sap_action_handler)
    
    if sync_sap_action_depsgraph_handler in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.remove(sync_sap_action_depsgraph_handler)
    
    # Unregister the timer
    if bpy.app.timers.is_registered(sync_sap_timer):
        bpy.app.timers.unregister(sync_sap_timer)
    
    # Clear the stored actions
    global _last_known_actions
    _last_known_actions.clear()
    
    # Unsubscribe from action changes
    unsubscribe_from_action_changes()
    
if __name__ == '__main__':
    register()