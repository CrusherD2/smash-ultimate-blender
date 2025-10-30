"""
Retargeting module - Integration of expy_kit into Smash Ultimate Blender Tools
This module provides 1:1 integration of expy_kit retargeting tools.
Panels are always visible and will guide the user to enter POSE mode when necessary.
All functionality is consolidated in the 'Retargeting' section of the 'Ultimate' tab.
"""
import bpy
from bpy.types import Panel
from bpy.app.handlers import persistent

# Import expy_kit modules using relative imports
# expy_kit is at the plugin root level, so we go up two levels from source/retargeting/
from ...expy_kit import operators, properties, preferences, ui, preset_handler


# Auto-detection for Smash armatures
_last_detected_armature = None

def load_custom_bones_from_preset(preset_path):
    """Parse a preset file and extract custom bone definitions"""
    import os
    import re
    
    custom_bones = {}
    
    if not os.path.exists(preset_path):
        return custom_bones
    
    try:
        with open(preset_path, 'r') as f:
            content = f.read()
            
        # Look for lines like: skeleton.custom.identifier = 'BoneName'
        pattern = r"skeleton\.custom\.(\w+)\s*=\s*['\"]([^'\"]*)['\"]"
        matches = re.findall(pattern, content)
        
        for identifier, bone_name in matches:
            if identifier != 'name' and bone_name:  # Skip the legacy 'name' property
                custom_bones[identifier] = bone_name
    except Exception as e:
        print(f"Error parsing preset for custom bones: {e}")
    
    return custom_bones


def ensure_custom_bones_exist(skeleton, custom_bones_dict):
    """Ensure custom bone properties exist before setting them"""
    for identifier, bone_name in custom_bones_dict.items():
        if not hasattr(skeleton.custom, identifier):
            # Create the property using add_bone
            skeleton.custom.add_bone(identifier, bone_name)
        else:
            # Property exists, just set the value
            setattr(skeleton.custom, identifier, bone_name)


def load_preset_with_custom_bones(preset_name, armature_obj=None):
    """Load a preset and properly handle custom bones"""
    if armature_obj is None:
        armature_obj = bpy.context.object
    
    if not armature_obj or armature_obj.type != 'ARMATURE':
        return False
    
    try:
        # Get the preset path
        import os
        preset_dir = os.path.join(os.path.dirname(__file__), '..', '..', 'expy_kit', 'rig_mapping', 'presets')
        preset_path = os.path.join(preset_dir, preset_name)
        
        # Parse custom bones from preset
        custom_bones = load_custom_bones_from_preset(preset_path)
        
        # Get skeleton
        skeleton = armature_obj.data.expykit_retarget
        
        # Pre-create custom bone properties
        if custom_bones:
            ensure_custom_bones_exist(skeleton, custom_bones)
        
        # Now load the preset normally
        preset_handler.set_preset_skel(preset_name, validate=True)
        
        # Force UI refresh
        for area in bpy.context.screen.areas:
            if area.type == 'VIEW_3D':
                area.tag_redraw()
        
        return True
    except Exception as e:
        print(f"Error loading preset with custom bones: {e}")
        return False


def check_and_load_smash_preset(armature_obj):
    """Check if an armature is a smash rig and load preset if needed"""
    if not armature_obj or armature_obj.type != 'ARMATURE':
        return False
    
    armature_name = armature_obj.name
    if "smush_blender_import" not in armature_name.lower():
        return False
    
    # Check if settings are already loaded
    if armature_obj.data.expykit_retarget.has_settings():
        return False  # Already has settings
    
    # Load Smash preset with proper custom bone handling
    try:
        # Temporarily set as active to load preset
        original_active = bpy.context.view_layer.objects.active
        bpy.context.view_layer.objects.active = armature_obj
        
        if load_preset_with_custom_bones('Smash.py', armature_obj):
            print(f"Auto-loaded Smash preset for armature: {armature_name}")
            
            # Restore original active object
            if original_active:
                bpy.context.view_layer.objects.active = original_active
            return True
    except Exception as e:
        print(f"Failed to auto-load Smash preset for {armature_name}: {e}")
    
    return False


@persistent
def auto_detect_smash_armature(scene):
    """Auto-load Smash preset when a smush_blender_import armature is selected"""
    global _last_detected_armature
    
    try:
        # Check active object
        if bpy.context.object and bpy.context.object.type == 'ARMATURE':
            armature_name = bpy.context.object.name
            
            # Only process if we haven't already processed this armature
            if _last_detected_armature != armature_name:
                if check_and_load_smash_preset(bpy.context.object):
                    _last_detected_armature = armature_name
        
        # Also check the "Bind To" target if set
        if hasattr(bpy.context.scene, 'expykit_bind_to') and bpy.context.scene.expykit_bind_to:
            target_armature = bpy.context.scene.expykit_bind_to
            if target_armature and target_armature.type == 'ARMATURE':
                check_and_load_smash_preset(target_armature)
    
    except Exception as e:
        # Silently fail to avoid spamming console
        pass


# Override preset execution to handle custom bones properly
class ULTIMATE_OT_execute_preset_retarget(bpy.types.Operator):
    """Apply a Bone Retarget Preset with Custom Bone Support"""
    bl_idname = "object.ultimate_armature_preset_apply"
    bl_label = "Apply Bone Retarget Preset"

    filepath: bpy.props.StringProperty(
        subtype='FILE_PATH',
        options={'SKIP_SAVE'},
    )
    menu_idname: bpy.props.StringProperty(
        name="Menu ID Name",
        description="ID name of the menu this was called from",
        options={'SKIP_SAVE'},
    )

    def execute(self, context):
        from os.path import basename, splitext
        filepath = self.filepath

        # change the menu title to the most recently chosen option
        preset_class = ui.VIEW3D_MT_retarget_presets
        preset_class.bl_label = bpy.path.display_name(basename(filepath), title_case=False)

        ext = splitext(filepath)[1].lower()

        if ext not in {".py", ".xml"}:
            self.report({'ERROR'}, "Unknown file type: %r" % ext)
            return {'CANCELLED'}

        if hasattr(preset_class, "reset_cb"):
            preset_class.reset_cb(context)

        if ext == ".py":
            try:
                # PRE-PROCESS: Extract and create custom bone properties
                custom_bones = load_custom_bones_from_preset(filepath)
                if custom_bones and context.object and context.object.type == 'ARMATURE':
                    skeleton = context.object.data.expykit_retarget
                    ensure_custom_bones_exist(skeleton, custom_bones)
                
                # Execute the preset file
                bpy.utils.execfile(filepath)
            except Exception as ex:
                self.report({'ERROR'}, "Failed to execute the preset: " + repr(ex))

        elif ext == ".xml":
            import rna_xml
            rna_xml.xml_file_run(context,
                                 filepath,
                                 preset_class.preset_xml_map)

        if hasattr(preset_class, "post_cb"):
            preset_class.post_cb(context)

        preset_handler.validate_preset(context.object.data)

        settings = context.object.data.expykit_retarget
        preset_handler.reset_preset_names(settings)
        
        # Force UI refresh to show custom bones
        for area in context.screen.areas:
            if area.type == 'VIEW_3D':
                area.tag_redraw()

        return {'FINISHED'}


# Custom preset menu that uses our custom operator
class ULTIMATE_MT_retarget_presets(ui.VIEW3D_MT_retarget_presets):
    """Retarget presets menu with custom bone support"""
    preset_operator = "object.ultimate_armature_preset_apply"  # Use our custom operator


# Monkey patch the original constrain operator to add auto-detection
_original_constrain_invoke = None

def custom_constrain_invoke(self, context, event):
    """Enhanced invoke with auto-detection for Smash presets"""
    # Auto-detect and load presets for both armatures before showing dialog
    try:
        # Get source armature (the one being bound FROM)
        to_bind = None
        for ob in context.selected_objects:
            if ob != context.active_object and ob.type == 'ARMATURE':
                to_bind = ob
                break
        
        if to_bind:
            check_and_load_smash_preset(to_bind)
        
        # Get target armature (the active one being bound TO)
        if context.active_object and context.active_object.type == 'ARMATURE':
            check_and_load_smash_preset(context.active_object)
    except Exception as e:
        print(f"Auto-detection in dialog failed: {e}")
    
    # Call original invoke
    return _original_constrain_invoke(self, context, event)


# Custom bind operator with auto-detection and auto pose mode
class ULTIMATE_OT_bind_armatures(bpy.types.Operator):
    """Bind armatures with automatic Smash preset detection and pose mode switching"""
    bl_idname = "object.ultimate_bind_armatures"
    bl_label = "Bind Armatures"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        # Allow binding even if not in pose mode - we'll switch automatically
        return (context.object and context.object.type == 'ARMATURE' and 
                context.scene.expykit_bind_to and 
                context.object != context.scene.expykit_bind_to)
    
    def execute(self, context):
        source_armature = context.object
        target_armature = context.scene.expykit_bind_to
        
        # Auto-detect and load Smash preset for both armatures
        check_and_load_smash_preset(source_armature)
        check_and_load_smash_preset(target_armature)
        
        # Ensure we're in pose mode
        if context.mode != 'POSE':
            # Switch to object mode first, then to pose mode
            if context.mode != 'OBJECT':
                bpy.ops.object.mode_set(mode='OBJECT')
            # Select source armature and enter pose mode
            for ob in context.selected_objects:
                ob.select_set(False)
            source_armature.select_set(True)
            context.view_layer.objects.active = source_armature
            bpy.ops.object.mode_set(mode='POSE')
        
        # Deselect all objects except source
        for ob in context.selected_objects:
            ob.select_set(ob == source_armature)
        
        # Select target armature and make it active
        target_armature.select_set(True)
        context.view_layer.objects.active = target_armature
        
        # Ensure target is in pose mode
        if target_armature != source_armature:
            bpy.ops.object.mode_set(mode='POSE')
        
        # Set action range if target has animation
        if target_armature.animation_data and target_armature.animation_data.action:
            try:
                bpy.ops.object.expykit_action_to_range()
            except:
                pass  # Operator may not always work
        
        # Call the original constrain operator with dialog
        bpy.ops.armature.expykit_constrain_to_armature('INVOKE_DEFAULT', force_dialog=True)
        
        return {'FINISHED'}


# Help operator for how to use retargeting
class ULTIMATE_OT_retargeting_help(bpy.types.Operator):
    """Show instructions for using the retargeting system"""
    bl_idname = "object.ultimate_retargeting_help"
    bl_label = "How to Use Expy Kit Retargeting"
    
    def execute(self, context):
        return {'FINISHED'}
    
    def invoke(self, context, event):
        return context.window_manager.invoke_popup(self, width=500)
    
    def draw(self, context):
        layout = self.layout
        
        col = layout.column(align=True)
        col.label(text="Expy Kit Retargeting - Quick Guide", icon='INFO')
        col.separator()
        
        # Step 1
        box = layout.box()
        box.label(text="1. Set Up Source Armature (the one you want to retarget FROM):", icon='ARMATURE_DATA')
        col = box.column(align=True)
        col.label(text="   • Select your source armature")
        col.label(text="   • Load the animations you want to retarget")
        col.label(text="   • Enter Pose Mode")
        col.label(text="   • Choose or create a preset in 'Expy Mapping'")
        col.label(text="   • Map bones to the preset's skeleton structure")
        
        # Step 2
        box = layout.box()
        box.label(text="2. Set Up Target Armature (the one you want to retarget TO):", icon='ARMATURE_DATA')
        col = box.column(align=True)
        col.label(text="   • Select your target armature")
        col.label(text="   • Enter Pose Mode")
        col.label(text="   • Choose or create a matching preset")
        
        # Step 3
        box = layout.box()
        box.label(text="3. Bind Armatures:", icon='LINKED')
        col = box.column(align=True)
        col.label(text="   • Select your target armature")
        col.label(text="   • In 'Bind To' panel, choose the target armature")
        col.label(text="   • A panel will appear with 'To Bind' and 'Bind To' options;")
        col.label(text="     choose presets for each model as needed and click OK")
        col.label(text="   • Click 'Bind Armatures'")
        col.label(text="   • A panel will appear in the bottom-left viewport corner")
        col.label(text="   • Use it to: adjust time stretching, toggle constraints,")
        col.label(text="     pick the Root Animation bone (e.g., 'Trans') for the armature,")
        col.label(text="     set offsets at the top (e.g., 'Bone Offset',")
        col.label(text="     'Current Pose is Target Pose'), and preview in real-time")
        
        # Step 4 - Tweaking
        box = layout.box()
        box.label(text="4. Tweaking:", icon='OUTLINER_OB_ARMATURE')
        col = box.column(align=True)
        col.label(text="   • A new set of helper bones is created for the source armature")
        col.label(text="   • Find them in the Bone Collections; use them to fix imperfections")
        col.label(text="   • Every target bone has constraints you can adjust")
        col.label(text="     if you don't want certain motions from the source")
        
        # Step 5
        box = layout.box()
        box.label(text="5. Bake Animation:", icon='RENDER_ANIMATION')
        col = box.column(align=True)
        col.label(text="   • Select your target armature in Pose Mode")
        col.label(text="   • Right-click in the viewport")
        col.label(text="   • Navigate to: Expy Kit > Animation > Bake Constrained Actions")
        col.label(text="   • Animation will be converted to keyframes")
        col.label(text="   • You can now unbind and use the baked animation")
        
        # Tips
        layout.separator()
        box = layout.box()
        box.label(text="Tips:", icon='LIGHTPROBE_CUBEMAP')
        col = box.column(align=True)
        col.label(text="   • Custom Bones: Add unique bones not in standard skeleton")
        col.label(text="   • Use the eyedropper to quickly assign active bone")
        col.label(text="   • Smash armatures auto-load the Smash preset")
        col.label(text="   • Both armatures must use the same preset structure")


# Main Retargeting panel in Ultimate tab
class SUB_PT_retargeting_main(Panel):
    """Main Retargeting panel in Ultimate tab"""
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'Ultimate'
    bl_label = 'Retargeting'
    bl_options = {'DEFAULT_CLOSED'}

    @classmethod
    def poll(cls, context):
        # Always visible
        return True

    def draw(self, context):
        layout = self.layout
        
        # Check if we need to auto-switch to pose mode
        needs_pose_mode = False
        if context.object and context.object.type == 'ARMATURE':
            if context.mode != 'POSE':
                needs_pose_mode = True
        
        # Header
        box = layout.box()
        col = box.column(align=True)
        col.label(text="Expy Kit Retargeting Tools", icon='ARMATURE_DATA')
        
        # How to use button
        row = col.row()
        row.operator("object.ultimate_retargeting_help", text="How to Use", icon='QUESTION')
        
        # Mode check - offer to auto-switch
        if needs_pose_mode:
            col.separator()
            row = col.row()
            row.alert = True
            row.label(text="Most features require Pose Mode", icon='INFO')
            col.operator("object.mode_set", text="Enter Pose Mode", icon='POSE_HLT').mode = 'POSE'


# Expy_kit panels moved to Ultimate tab, all as children of Retargeting
# These will replace the original panels

class ULTIMATE_PT_expy_retarget(ui.VIEW3D_PT_expy_retarget):
    """Expy Mapping panel in Ultimate tab"""
    bl_category = 'Ultimate'
    bl_parent_id = "SUB_PT_retargeting_main"
    
    @classmethod
    def poll(cls, context):
        # Always show the panel
        return True
    
    def draw(self, context):
        layout = self.layout

        # Add help button for active bone functionality
        row = layout.row()
        row.operator(ui.SetToActiveBoneHelpText.bl_idname, text="How to Set Active Bone", icon='HELP')
        layout.separator()

        # Use our custom preset menu that handles custom bones
        split = layout.split(factor=0.75)
        split.menu(ULTIMATE_MT_retarget_presets.__name__, text=ULTIMATE_MT_retarget_presets.bl_label)
        row = split.row(align=True)
        row.operator(ui.AddPresetArmatureRetarget.bl_idname, text="+")
        row.operator(ui.AddPresetArmatureRetarget.bl_idname, text="-").remove_active = True


class ULTIMATE_PT_BindPanel(ui.VIEW3D_PT_BindPanel):
    """Bind To panel in Ultimate tab with custom bind operator"""
    bl_category = 'Ultimate'
    bl_parent_id = "SUB_PT_retargeting_main"
    
    @classmethod
    def poll(cls, context):
        # Always show the panel
        return True
    
    def draw(self, context):
        layout = self.layout
        layout.prop(context.scene, 'expykit_bind_to', text="")
        
        # Use our custom bind operator with auto-detection and auto pose mode
        layout.operator("object.ultimate_bind_armatures")


class ULTIMATE_PT_retarget_spine(ui.VIEW3D_PT_expy_retarget_spine):
    """Spine panel in Ultimate tab"""
    bl_category = 'Ultimate'
    bl_parent_id = "ULTIMATE_PT_expy_retarget"
    
    @classmethod
    def poll(cls, context):
        # Always show the panel
        return True


class ULTIMATE_PT_retarget_arms(ui.VIEW3D_PT_expy_retarget_arms):
    """Arms panel in Ultimate tab"""
    bl_category = 'Ultimate'
    bl_parent_id = "ULTIMATE_PT_expy_retarget"
    
    @classmethod
    def poll(cls, context):
        # Always show the panel
        return True


class ULTIMATE_PT_retarget_arms_IK(ui.VIEW3D_PT_expy_retarget_arms_IK):
    """Arms IK panel in Ultimate tab"""
    bl_category = 'Ultimate'
    bl_parent_id = "ULTIMATE_PT_expy_retarget"
    
    @classmethod
    def poll(cls, context):
        # Always show the panel
        return True


class ULTIMATE_PT_retarget_legs(ui.VIEW3D_PT_expy_retarget_leg):
    """Legs panel in Ultimate tab"""
    bl_category = 'Ultimate'
    bl_parent_id = "ULTIMATE_PT_expy_retarget"
    
    @classmethod
    def poll(cls, context):
        # Always show the panel
        return True


class ULTIMATE_PT_retarget_legs_IK(ui.VIEW3D_PT_expy_retarget_leg_IK):
    """Legs IK panel in Ultimate tab"""
    bl_category = 'Ultimate'
    bl_parent_id = "ULTIMATE_PT_expy_retarget"
    
    @classmethod
    def poll(cls, context):
        # Always show the panel
        return True


class ULTIMATE_PT_retarget_fingers(ui.VIEW3D_PT_expy_retarget_fingers):
    """Fingers panel in Ultimate tab"""
    bl_category = 'Ultimate'
    bl_parent_id = "ULTIMATE_PT_expy_retarget"
    
    @classmethod
    def poll(cls, context):
        # Always show the panel
        return True


class ULTIMATE_PT_retarget_face(ui.VIEW3D_PT_expy_retarget_face):
    """Face panel in Ultimate tab"""
    bl_category = 'Ultimate'
    bl_parent_id = "ULTIMATE_PT_expy_retarget"
    
    @classmethod
    def poll(cls, context):
        # Always show the panel
        return True


class ULTIMATE_PT_retarget_root(ui.VIEW3D_PT_expy_retarget_root):
    """Root panel in Ultimate tab"""
    bl_category = 'Ultimate'
    bl_parent_id = "ULTIMATE_PT_expy_retarget"
    
    @classmethod
    def poll(cls, context):
        # Always show the panel
        return True


class ULTIMATE_PT_retarget_custom(ui.VIEW3D_PT_expy_retarget_custom):
    """Custom Bones panel in Ultimate tab - first item under Expy Mapping"""
    bl_category = 'Ultimate'
    bl_parent_id = "ULTIMATE_PT_expy_retarget"  # Under Expy Mapping, but first
    
    @classmethod
    def poll(cls, context):
        # Always show the panel
        return True
    
    def draw(self, context):
        # Call parent draw method
        super().draw(context)
        # Force UI refresh to update custom bones list immediately
        for area in context.screen.areas:
            if area.type == 'VIEW_3D':
                area.tag_redraw()


# List of custom panels to register (all in Ultimate tab under Retargeting)
custom_panels = [
    SUB_PT_retargeting_main,
    ULTIMATE_PT_BindPanel,  # Bind To panel at the top
    ULTIMATE_PT_expy_retarget,  # Expy Mapping panel
    ULTIMATE_PT_retarget_custom,  # Custom Bones - first under Expy Mapping
    ULTIMATE_PT_retarget_spine,
    ULTIMATE_PT_retarget_arms,
    ULTIMATE_PT_retarget_arms_IK,
    ULTIMATE_PT_retarget_legs,
    ULTIMATE_PT_retarget_legs_IK,
    ULTIMATE_PT_retarget_fingers,
    ULTIMATE_PT_retarget_face,
    ULTIMATE_PT_retarget_root,
    # Action Name Candidates removed per user request
]


def register():
    """Register the retargeting module and all expy_kit components"""
    print("  Registering Retargeting module (expy_kit integration)...")
    
    # Install expy_kit presets if not already installed
    try:
        preset_handler.install_presets()
    except Exception as e:
        print(f"  Warning: Could not install expy_kit presets: {e}")
    
    # Register expy_kit properties
    properties.register_classes()
    
    # Register expy_kit operators
    operators.register_classes()
    
    # Register expy_kit preferences
    preferences.register_classes()
    
    # Register original expy_kit UI classes (menus, operators UI, etc)
    # But we'll unregister the panels and replace them with our versions
    ui.register_classes()
    
    # Register our custom operators and menu
    try:
        bpy.utils.register_class(ULTIMATE_OT_execute_preset_retarget)
        bpy.utils.register_class(ULTIMATE_MT_retarget_presets)
        bpy.utils.register_class(ULTIMATE_OT_bind_armatures)
        bpy.utils.register_class(ULTIMATE_OT_retargeting_help)
    except Exception as e:
        print(f"  Warning: Could not register custom operators/menu: {e}")
    
    # Monkey patch the constrain operator to add auto-detection
    global _original_constrain_invoke
    try:
        from ..expy_kit.operators import ConstrainToArmature
        _original_constrain_invoke = ConstrainToArmature.invoke
        ConstrainToArmature.invoke = custom_constrain_invoke
        print("  Applied auto-detection patch to constrain operator")
    except Exception as e:
        print(f"  Warning: Could not patch constrain operator: {e}")
    
    # Unregister original panels
    original_panels = [
        ui.VIEW3D_PT_expy_retarget,
        ui.VIEW3D_PT_BindPanel,
        ui.VIEW3D_PT_expy_retarget_spine,
        ui.VIEW3D_PT_expy_retarget_arms,
        ui.VIEW3D_PT_expy_retarget_arms_IK,
        ui.VIEW3D_PT_expy_retarget_leg,
        ui.VIEW3D_PT_expy_retarget_leg_IK,
        ui.VIEW3D_PT_expy_retarget_fingers,
        ui.VIEW3D_PT_expy_retarget_face,
        ui.VIEW3D_PT_expy_retarget_root,
        ui.VIEW3D_PT_expy_retarget_custom,
        ui.VIEW3D_PT_expy_rename_candidates,
        ui.VIEW3D_PT_expy_rename_advanced,
    ]
    
    for panel in original_panels:
        try:
            bpy.utils.unregister_class(panel)
        except:
            pass
    
    # Register our custom panels
    for panel in custom_panels:
        try:
            bpy.utils.register_class(panel)
        except Exception as e:
            print(f"  Warning: Could not register panel {panel.__name__}: {e}")
    
    # Callback for when bind_to property changes
    def on_bind_to_update(self, context):
        """Check if the selected bind_to armature is a smash rig"""
        if self.expykit_bind_to and self.expykit_bind_to.type == 'ARMATURE':
            check_and_load_smash_preset(self.expykit_bind_to)
    
    # Register scene properties for binding
    if not hasattr(bpy.types.Scene, 'expykit_bind_to'):
        bpy.types.Scene.expykit_bind_to = bpy.props.PointerProperty(
            type=bpy.types.Object,
            name="Bind To",
            description="Target armature to bind to",
            poll=ui.poll_armature_bind_to,
            update=on_bind_to_update
        )
    
    # Register auto-detection handler for Smash armatures
    if auto_detect_smash_armature not in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.append(auto_detect_smash_armature)
    
    print("  Retargeting module registered successfully!")


def unregister():
    """Unregister the retargeting module and all expy_kit components"""
    print("  Unregistering Retargeting module...")
    
    # Unregister auto-detection handler
    if auto_detect_smash_armature in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.remove(auto_detect_smash_armature)
    
    # Unregister our custom panels
    for panel in reversed(custom_panels):
        try:
            bpy.utils.unregister_class(panel)
        except:
            pass
    
    # Restore original constrain operator invoke method
    global _original_constrain_invoke
    if _original_constrain_invoke:
        try:
            from ..expy_kit.operators import ConstrainToArmature
            ConstrainToArmature.invoke = _original_constrain_invoke
            print("  Restored original constrain operator")
        except:
            pass
    
    # Unregister our custom operators and menu
    try:
        bpy.utils.unregister_class(ULTIMATE_OT_retargeting_help)
        bpy.utils.unregister_class(ULTIMATE_OT_bind_armatures)
        bpy.utils.unregister_class(ULTIMATE_MT_retarget_presets)
        bpy.utils.unregister_class(ULTIMATE_OT_execute_preset_retarget)
    except:
        pass
    
    # Unregister original expy_kit UI classes
    try:
        ui.unregister_classes()
    except:
        pass
    
    # Unregister expy_kit preferences
    try:
        preferences.unregister_classes()
    except:
        pass
    
    # Unregister expy_kit operators
    try:
        operators.unregister_classes()
    except:
        pass
    
    # Unregister expy_kit properties
    try:
        properties.unregister_classes()
    except:
        pass
    
    # Remove scene properties
    if hasattr(bpy.types.Scene, 'expykit_bind_to'):
        del bpy.types.Scene.expykit_bind_to
    
    # Reset global state
    global _last_detected_armature
    _last_detected_armature = None
    
    print("  Retargeting module unregistered successfully!")

