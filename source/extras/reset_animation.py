import bpy
from bpy.types import Operator
from bpy.props import BoolProperty, EnumProperty
import logging

# Set up logging
logger = logging.getLogger(__name__)

class SUB_OT_reset_bone_locations(Operator):
    """Reset bone locations and scales to 0/1 at frame 1 and delete their keyframes for selected bones, except for hip/trans/rot bones"""
    bl_idname = "sub.reset_bone_locations"
    bl_label = "Reset Bone Locations"
    bl_options = {'REGISTER', 'UNDO'}
    
    @classmethod
    def poll(cls, context):
        return (context.mode == 'POSE' and 
                context.object and 
                context.object.type == 'ARMATURE' and
                context.selected_pose_bones)
    
    def execute(self, context):
        # Check if we have selected bones
        if not context.selected_pose_bones:
            self.report({'ERROR'}, "Please select some bones")
            return {'CANCELLED'}
        
        armature = context.object
        
        # Check if the armature has an action
        if not armature.animation_data or not armature.animation_data.action:
            self.report({'ERROR'}, "Armature must have an action/animation")
            return {'CANCELLED'}
        
        # Store original mode to restore later
        original_mode = context.mode
        
        # Switch to pose mode if not already
        if original_mode != 'POSE':
            bpy.ops.object.mode_set(mode='POSE')
        
        # Store original frame
        original_frame = context.scene.frame_current
        
        # Jump to frame 1
        context.scene.frame_set(1)
        
        # Get action
        action = armature.animation_data.action
        
        # Identify excluded bones from selected bones (hip, trans, rot)
        excluded_bones = []
        selected_bones = []
        for bone in context.selected_pose_bones:
            if any(keyword in bone.name.lower() for keyword in ['hip', 'trans', 'rot']):
                excluded_bones.append(bone.name)
                print(f"Excluding selected bone from reset: {bone.name}")
            else:
                selected_bones.append(bone)
        
        # Find location and scale fcurves for selected bones
        location_fcurves = []
        scale_fcurves = []
        selected_bone_names = [bone.name for bone in selected_bones]
        
        for fcurve in action.fcurves:
            # Parse the data path to get bone name
            # Format: pose.bones["BoneName"].location[0]
            if "pose.bones" not in fcurve.data_path:
                continue
                
            # Extract bone name
            bone_name = fcurve.data_path.split('"')[1]
            
            # Only process fcurves for selected bones (excluding hip/trans/rot)
            if bone_name not in selected_bone_names:
                continue
            
            # Categorize fcurve
            if ".location" in fcurve.data_path:
                location_fcurves.append(fcurve)
            elif ".scale" in fcurve.data_path:
                scale_fcurves.append(fcurve)
        
        # Reset location to 0 and scale to 1 for selected bones (excluding hip/trans/rot)
        bones_affected = set()
        
        for bone in selected_bones:
            # Reset location to 0
            bone.location = (0, 0, 0)
            
            # Reset scale to 1
            bone.scale = (1, 1, 1)
            
            bones_affected.add(bone.name)
        
        # Insert keyframes at frame 1 for all affected bones
        for bone_name in bones_affected:
            bone = armature.pose.bones[bone_name]
            bone.keyframe_insert(data_path="location", frame=1)
            bone.keyframe_insert(data_path="scale", frame=1)
        
        # Delete all other keyframes for location and scale fcurves
        fcurves_to_clear = location_fcurves + scale_fcurves
            
        keyframes_removed = 0
        for fcurve in fcurves_to_clear:
            # Keep only keyframe at frame 1, delete all others
            to_remove = []
            for i, keyframe in enumerate(fcurve.keyframe_points):
                if abs(keyframe.co[0] - 1.0) > 0.01:  # If not frame 1 (allowing small float difference)
                    to_remove.append(i)
            
            # Remove keyframes in reverse order to avoid index shifting
            for i in reversed(to_remove):
                fcurve.keyframe_points.remove(fcurve.keyframe_points[i])
                keyframes_removed += 1
        
        # Update the view
        context.scene.frame_set(original_frame)
        
        # Force a redraw
        for area in context.screen.areas:
            if area.type in ['DOPESHEET_EDITOR', 'GRAPH_EDITOR', 'TIMELINE']:
                area.tag_redraw()
        
        # Find and process head bone descendants
        head_bone = None
        for bone in armature.pose.bones:
            bone_name_lower = bone.name.lower()
            if 'head' in bone_name_lower and not head_bone:
                head_bone = bone
                break
        
        head_keyframes_removed = 0
        head_transforms_cleared = 0
        
        if head_bone:
            # Remove keyframes and clear transforms from ALL descendants of head bone
            head_descendants = self._get_all_children_bones(head_bone, armature)
            
            # Reset all transforms to default values for head descendants
            head_transforms_cleared = self._clear_transforms_for_bones(armature, head_descendants)
            
            # Insert keyframes at frame 1 for head descendants
            self._insert_keyframes_for_bones(armature, head_descendants, frame=1)
            print(f"Reset transforms to default for {head_transforms_cleared} head descendants and inserted keyframes at frame 1")
            
            # Remove ALL other keyframes for head descendants (keeping only frame 1)
            if armature.animation_data and armature.animation_data.action:
                head_keyframes_removed = self._remove_keyframes_for_bones(armature.animation_data.action, head_descendants)
                print(f"Removed old keyframes for {len(head_descendants)} head descendants, total keyframes removed: {head_keyframes_removed}")
            else:
                print(f"No animation data found, only reset transforms to default for {len(head_descendants)} head descendants")
        else:
            print("No head bone found for processing head descendants")
        
        # Restore original mode
        if original_mode != 'POSE':
            bpy.ops.object.mode_set(mode=original_mode.replace('_', ' ').title())
        
        excluded_count = len(excluded_bones)
        if excluded_count > 0:
            self.report({'INFO'}, f"Reset {len(bones_affected)} selected bones and {head_transforms_cleared} head descendants to default at frame 1. Excluded {excluded_count} hip/trans/rot bones. Removed {keyframes_removed + head_keyframes_removed} keyframes.")
        else:
            self.report({'INFO'}, f"Reset {len(bones_affected)} selected bones and {head_transforms_cleared} head descendants to default at frame 1. Removed {keyframes_removed + head_keyframes_removed} keyframes.")
        return {'FINISHED'}
    
    def _get_all_children_bones(self, parent_bone, armature):
        """Recursively get ALL descendants (children, grandchildren, etc.) of a parent bone"""
        children = []
        
        def get_children_recursive(pose_bone, depth=0):
            indent = "  " * depth  # For debug output
            # Get the edit bone to access children
            edit_bone = armature.data.bones.get(pose_bone.name)
            if edit_bone:
                for child_edit_bone in edit_bone.children:
                    child_pose_bone = armature.pose.bones.get(child_edit_bone.name)
                    if child_pose_bone:
                        children.append(child_pose_bone.name)
                        print(f"{indent}Found child bone: {child_edit_bone.name} (depth {depth})")
                        # Recursively get children of this child
                        get_children_recursive(child_pose_bone, depth + 1)
        
        print(f"Getting all descendants of: {parent_bone.name}")
        get_children_recursive(parent_bone, 0)
        print(f"Total descendants found: {len(children)}")
        return children
    
    def _clear_transforms_for_bones(self, armature, bone_names):
        """Reset all transforms to their default values (equivalent to Alt+G, Alt+R, Alt+S in Blender)"""
        transforms_cleared = 0
        
        for bone_name in bone_names:
            bone = armature.pose.bones.get(bone_name)
            if bone:
                # Reset location to default (0,0,0)
                bone.location = (0, 0, 0)
                
                # Reset rotation to default based on rotation mode
                if bone.rotation_mode == 'QUATERNION':
                    bone.rotation_quaternion = (1, 0, 0, 0)  # Identity quaternion
                elif bone.rotation_mode == 'AXIS_ANGLE':
                    bone.rotation_axis_angle = (0, 0, 1, 0)  # No rotation
                else:
                    bone.rotation_euler = (0, 0, 0)  # No rotation
                
                # Reset scale to default (1,1,1)
                bone.scale = (1, 1, 1)
                
                transforms_cleared += 1
                print(f"Reset transforms to default for bone: {bone_name}")
        
        return transforms_cleared
    
    def _insert_keyframes_for_bones(self, armature, bone_names, frame):
        """Insert keyframes for location, rotation, and scale at specified frame for given bones"""
        keyframes_inserted = 0
        
        for bone_name in bone_names:
            bone = armature.pose.bones.get(bone_name)
            if bone:
                # Insert keyframes for all transform channels
                bone.keyframe_insert(data_path="location", frame=frame)
                
                if bone.rotation_mode == 'QUATERNION':
                    bone.keyframe_insert(data_path="rotation_quaternion", frame=frame)
                elif bone.rotation_mode == 'AXIS_ANGLE':
                    bone.keyframe_insert(data_path="rotation_axis_angle", frame=frame)
                else:
                    bone.keyframe_insert(data_path="rotation_euler", frame=frame)
                
                bone.keyframe_insert(data_path="scale", frame=frame)
                
                keyframes_inserted += 1
                print(f"Inserted keyframes at frame {frame} for bone: {bone_name}")
        
        return keyframes_inserted
    
    def _remove_keyframes_for_bones(self, action, bone_names):
        """Remove all keyframes for specified bones from the action except frame 1"""
        keyframes_removed = 0
        jaw_fcurves_found = []
        
        print(f"Looking for fcurves for bones: {bone_names}")
        
        for fcurve in action.fcurves:
            # Check if this fcurve belongs to one of the specified bones
            if fcurve.data_path.startswith('pose.bones["'):
                # Extract bone name from data path
                try:
                    bone_name = fcurve.data_path.split('"')[1]
                    
                    # Special debug for Jaw bone
                    if "Jaw" in bone_name:
                        jaw_fcurves_found.append(f"{bone_name}: {fcurve.data_path}")
                        print(f"Found Jaw-related fcurve: {bone_name} -> {fcurve.data_path}")
                    
                    if bone_name in bone_names:
                        # Count existing keyframes
                        original_keyframe_count = len(fcurve.keyframe_points)
                        
                        # Remove all keyframes except frame 1
                        to_remove = []
                        for i, keyframe in enumerate(fcurve.keyframe_points):
                            if abs(keyframe.co[0] - 1.0) > 0.01:  # If not frame 1
                                to_remove.append(i)
                        
                        # Remove keyframes in reverse order to avoid index shifting
                        for i in reversed(to_remove):
                            fcurve.keyframe_points.remove(fcurve.keyframe_points[i])
                            keyframes_removed += 1
                        
                        remaining_keyframes = len(fcurve.keyframe_points)
                        print(f"Bone {bone_name} ({fcurve.data_path}): removed {len(to_remove)} keyframes, {remaining_keyframes} remain")
                        
                except IndexError:
                    continue
        
        print(f"All Jaw-related fcurves found: {jaw_fcurves_found}")
        return keyframes_removed


class SUB_OT_invert_rotation_values(Operator):
    """Invert rotation values of selected bones from negative to positive and vice versa"""
    bl_idname = "sub.invert_rotation_values"
    bl_label = "Invert Positive and Negative"
    bl_options = {'REGISTER', 'UNDO'}
    
    @classmethod
    def poll(cls, context):
        return (context.mode == 'POSE' and 
                context.object and 
                context.object.type == 'ARMATURE' and
                context.selected_pose_bones)
    
    def execute(self, context):
        if not context.selected_pose_bones:
            self.report({'WARNING'}, "No bones selected")
            return {'CANCELLED'}
        
        bones_affected = 0
        current_frame = context.scene.frame_current
        
        for bone in context.selected_pose_bones:
            # Handle rotation based on rotation mode
            if bone.rotation_mode == 'QUATERNION':
                # Flip the sign of each quaternion component
                bone.rotation_quaternion = (-bone.rotation_quaternion.w, 
                                          -bone.rotation_quaternion.x,
                                          -bone.rotation_quaternion.y, 
                                          -bone.rotation_quaternion.z)
                # Insert keyframe if auto-keyframing is enabled
                if context.scene.tool_settings.use_keyframe_insert_auto:
                    bone.keyframe_insert(data_path="rotation_quaternion", frame=current_frame)
            else:
                # Flip the sign of each euler component
                bone.rotation_euler = (-bone.rotation_euler.x, 
                                     -bone.rotation_euler.y, 
                                     -bone.rotation_euler.z)
                # Insert keyframe if auto-keyframing is enabled
                if context.scene.tool_settings.use_keyframe_insert_auto:
                    bone.keyframe_insert(data_path="rotation_euler", frame=current_frame)
            
            bones_affected += 1
        
        self.report({'INFO'}, f"Inverted rotation values for {bones_affected} selected bones")
        return {'FINISHED'}


class SUB_OT_ground_character(Operator):
    """Move the hip bone on the Y axis until either FootL or FootR bone head touches the ground"""
    bl_idname = "sub.ground_character"
    bl_label = "Ground Character"
    bl_options = {'REGISTER', 'UNDO'}
    
    frame_mode: EnumProperty(
        name="Frame Mode",
        description="Choose whether to apply to current frame or all frames",
        items=[
            ('CURRENT', "Current Frame", "Apply grounding to current frame only"),
            ('ALL', "All Frames", "Apply grounding to all frames in animation"),
        ],
        default='CURRENT'
    )
    
    @classmethod
    def poll(cls, context):
        return (context.object and 
                context.object.type == 'ARMATURE' and
                context.mode == 'POSE')
    
    def execute(self, context):
        armature = context.object
        
        # Check if the armature has an action for all frames mode
        if self.frame_mode == 'ALL' and (not armature.animation_data or not armature.animation_data.action):
            self.report({'ERROR'}, "Armature must have an action/animation to ground all frames")
            return {'CANCELLED'}
        
        # Find required bones
        hip_bone = None
        foot_l_bone = None
        foot_r_bone = None
        
        for bone in armature.pose.bones:
            bone_name_lower = bone.name.lower()
            if 'hip' in bone_name_lower and not hip_bone:
                hip_bone = bone
            elif bone.name == 'FootL':
                foot_l_bone = bone
            elif bone.name == 'FootR':
                foot_r_bone = bone
        
        # Validate that we found all required bones
        missing_bones = []
        if not hip_bone:
            missing_bones.append("hip bone")
        if not foot_l_bone:
            missing_bones.append("FootL")
        if not foot_r_bone:
            missing_bones.append("FootR")
        
        if missing_bones:
            self.report({'ERROR'}, f"Could not find required bones: {', '.join(missing_bones)}")
            return {'CANCELLED'}
        
        # Store original mode and frame
        original_mode = context.mode
        original_frame = context.scene.frame_current
        
        # Switch to pose mode if not already
        if original_mode != 'POSE':
            bpy.ops.object.mode_set(mode='POSE')
        
        frames_processed = 0
        
        if self.frame_mode == 'CURRENT':
            # Process current frame only
            print(f"Hip bone current location: {hip_bone.location}")
            adjustment = self._calculate_ground_adjustment(armature, hip_bone, foot_l_bone, foot_r_bone)
            print(f"Calculated adjustment: {adjustment}")
            if adjustment != 0:
                old_y = hip_bone.location[1]
                hip_bone.location[1] += adjustment
                print(f"Hip bone Y changed from {old_y:.4f} to {hip_bone.location[1]:.4f}")
                # Insert keyframe if auto-keyframing is enabled
                if context.scene.tool_settings.use_keyframe_insert_auto:
                    hip_bone.keyframe_insert(data_path="location", frame=context.scene.frame_current)
            frames_processed = 1
        else:
            # Process all frames - apply current frame logic to each frame
            action = armature.animation_data.action
            frame_start = int(action.frame_range[0])
            frame_end = int(action.frame_range[1])
            
            print(f"Processing frames {frame_start} to {frame_end}")
            
            for frame in range(frame_start, frame_end + 1):
                # Set to current frame
                context.scene.frame_set(frame)
                
                # Apply the same logic as current frame mode
                print(f"\n--- Frame {frame} ---")
                print(f"Hip bone current location: {hip_bone.location}")
                adjustment = self._calculate_ground_adjustment(armature, hip_bone, foot_l_bone, foot_r_bone)
                print(f"Calculated adjustment: {adjustment}")
                
                if adjustment != 0:
                    old_y = hip_bone.location[1]
                    hip_bone.location[1] += adjustment
                    print(f"Hip bone Y changed from {old_y:.4f} to {hip_bone.location[1]:.4f}")
                    # Always insert keyframe for all frames mode
                    hip_bone.keyframe_insert(data_path="location", frame=frame)
                    frames_processed += 1
                else:
                    print("No adjustment needed for this frame")
        

        
        # Restore original frame and mode
        context.scene.frame_set(original_frame)
        if original_mode != 'POSE':
            bpy.ops.object.mode_set(mode=original_mode.replace('_', ' ').title())
        
        if frames_processed > 0:
            mode_text = "current frame" if self.frame_mode == 'CURRENT' else f"{frames_processed} frames"
            self.report({'INFO'}, f"Grounded character for {mode_text}")
        else:
            self.report({'INFO'}, "Character was already grounded")
        
        return {'FINISHED'}
    
    def _calculate_ground_adjustment(self, armature, hip_bone, foot_l_bone, foot_r_bone):
        """Calculate how much to adjust the hip bone on Y axis to ground the character using foot bone heads"""
        # Update the armature to get current pose positions
        bpy.context.view_layer.update()
        
        # Get world positions of foot bone heads
        foot_l_head_world = armature.matrix_world @ foot_l_bone.head
        foot_r_head_world = armature.matrix_world @ foot_r_bone.head
        
        print(f"FootL head Z: {foot_l_head_world.z:.4f}")
        print(f"FootR head Z: {foot_r_head_world.z:.4f}")
        
        min_head_z = min(foot_l_head_world.z, foot_r_head_world.z)
        max_head_z = max(foot_l_head_world.z, foot_r_head_world.z)
        
        # If either foot is below ground, raise character so the lowest head touches ground
        if min_head_z < -0.0001:
            adjustment_needed = -min_head_z  # positive value, move hip up on Y axis
            print(f"Lowest head below ground at Z: {min_head_z:.4f}. Moving hip UP on Y axis by {adjustment_needed:.4f} units.")
            return adjustment_needed
        # Otherwise, both feet are on or above ground. Lower character so the lowest head touches ground.
        elif min_head_z > 0.0001:
            adjustment_needed = -min_head_z  # negative value, move hip down on Y axis
            print(f"Both heads above ground. Lowest above ground at Z: {min_head_z:.4f}. Moving hip DOWN on Y axis by {abs(adjustment_needed):.4f} units.")
            return adjustment_needed
        else:
            print("At least one head already touching ground. No adjustment needed.")
            return 0
    

    
    def invoke(self, context, event):
        # Show popup dialog
        return context.window_manager.invoke_props_dialog(self)
    
    def draw(self, context):
        layout = self.layout
        layout.prop(self, "frame_mode", expand=True)




# List of classes to register
classes = (
    SUB_OT_reset_bone_locations,
    SUB_OT_invert_rotation_values,
    SUB_OT_ground_character,
)

def register():
    logger.info("Registering reset_animation.py classes")
    for cls in classes:
        try:
            bpy.utils.register_class(cls)
            logger.info(f"Successfully registered {cls.__name__}")
        except Exception as e:
            logger.error(f"Failed to register {cls.__name__}: {str(e)}")

def unregister():
    logger.info("Unregistering reset_animation.py classes")
    for cls in reversed(classes):
        if hasattr(bpy.types, cls.__name__):
            try:
                bpy.utils.unregister_class(cls)
                logger.info(f"Successfully unregistered {cls.__name__}")
            except Exception as e:
                logger.error(f"Failed to unregister {cls.__name__}: {str(e)}")

# Test if registration works when this script is run directly
if __name__ == "__main__":
    register() 