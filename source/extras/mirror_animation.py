import bpy
from bpy.types import Operator
from bpy.props import EnumProperty, BoolProperty
import logging
import mathutils

# Set up logging
logger = logging.getLogger(__name__)

NEGATE_DATA_PATH_XAXIS = (
    ('location', 0),
    ('rotation_quaternion', 2),
    ('rotation_quaternion', 3),
    ('rotation_euler', 2),
    ('rotation_euler', 1), # armature space z axis is y
)

NEGATE_DATA_PATH_YAXIS = (
    ('location', 2), # in armature space y axis is z
    ('rotation_quaternion', 2),
    ('rotation_quaternion', 1),
    ('rotation_euler', 0),
    ('rotation_euler', 1), # armature space z axis is y
)

NEGATE_DATA_PATH_ZAXIS = (
    ('location', 1),
    ('rotation_quaternion', 1),
    ('rotation_quaternion', 3),
    ('rotation_euler', 0),
    ('rotation_euler', 2),
)


#########################################################################################
# Create Mirror Map
#########################################################################################


def difference(a, b):
    """Find difference in two strings to check if they are left and right"""
    import os
    common_prefix = os.path.commonprefix((a,b))
    common_suffix = os.path.commonprefix((a[::-1],b[::-1]))[::-1]
    
    # TODO: add checks incase of 'alc' and 'arc'
    #       check if difference is at start or end
    #       check if surrounds with punctuation or camelcase
    return a[len(common_prefix) : len(a)-len(common_suffix)], b[len(common_prefix) : len(b)-len(common_suffix)]

def lower_tuple(wl):
    return tuple(w.lower() for w in wl)

def create_mirror_map(names, patterns=None):
    
    mirror_map = {}

    if patterns == None:
        # Insert more default pattern if necessary - add Smash Ultimate specific patterns
        patterns = (
            ('l', 'r'), 
            ('left', 'right'),
            ('L', 'R'),  # Add capitalized L/R for Smash Ultimate
            ('Left', 'Right')  # Add capitalized words
        )
    
    # lower case and remove difference eg. remove 't' from 'Left', 'Right'
    patterns = tuple(lower_tuple(difference(*pattern)) for pattern in patterns)
    rpatterns = tuple(pattern[::-1] for pattern in patterns)

    # First pass: exact pattern matching for clear L/R pairs
    for lname in names:
        for name in names:
            if lname == name:
                continue  # Skip same name
            if lower_tuple(difference(lname, name)) in (*patterns, *rpatterns):
                rname = name
                mirror_map[lname] = rname
                break
    
    # Second pass: handle Smash Ultimate specific naming patterns
    # Look for bones ending in L/R that weren't caught by the first pass
    unmatched_names = [name for name in names if name not in mirror_map]
    for bone_name in unmatched_names:
        if bone_name.endswith('L'):
            # Look for corresponding R bone
            r_bone_name = bone_name[:-1] + 'R'
            if r_bone_name in names:
                mirror_map[bone_name] = r_bone_name
                mirror_map[r_bone_name] = bone_name
        elif bone_name.endswith('R'):
            # Look for corresponding L bone  
            l_bone_name = bone_name[:-1] + 'L'
            if l_bone_name in names:
                mirror_map[bone_name] = l_bone_name
                mirror_map[l_bone_name] = bone_name
    
    return mirror_map


#########################################################################################
# Mirror Action
#########################################################################################


def negate_fcurve(fcurve, only_active_frame=False, current_frame=None):
    for k in fcurve.keyframe_points:
        if only_active_frame and current_frame is not None:
            # Only negate keyframes at the current frame
            if abs(k.co[0] - current_frame) < 0.001:  # Small tolerance for floating point comparison
                k.co[1] = -k.co[1]
                k.handle_left[1] = -k.handle_left[1]
                k.handle_right[1] = -k.handle_right[1]
        else:
            # Negate all keyframes
            k.co[1] = -k.co[1]
            k.handle_left[1] = -k.handle_left[1]
            k.handle_right[1] = -k.handle_right[1]

def mirror_action(act, axis='X', selected_bones_only=False, context=None, only_active_frame=False):
    
    if not (act and act.fcurves):
        print("No Keyframes")
        return
    
    # Get current frame if only_active_frame is enabled
    current_frame = None
    if only_active_frame and context:
        current_frame = context.scene.frame_current
    
    # Get selected bone names if filtering is enabled
    selected_bone_names = set()
    if selected_bones_only and context and context.active_object and context.active_object.type == 'ARMATURE':
        selected_bone_names = {bone.name for bone in context.selected_pose_bones or []}
    
    # create name map
    # strip attribute suffix eg. 'pose.bones["root"].location' -> 'pose.bones["root"]'
    bone_names = {fc.data_path.rsplit('.', 1)[0] for fc in act.fcurves if '.' in fc.data_path}
    mirror_map = create_mirror_map(bone_names)

    if axis == 'X':
        negate_data_path_tuples = NEGATE_DATA_PATH_XAXIS
    elif axis == 'Y':
        negate_data_path_tuples = NEGATE_DATA_PATH_YAXIS
    elif axis == 'Z':
        negate_data_path_tuples = NEGATE_DATA_PATH_ZAXIS
    else:
        raise ValueError(f"Unsupported {axis=}")

    if only_active_frame and current_frame is not None:
        # Frame-specific mirroring: only affect keyframes at current frame
        fcurves_to_process = []
        
        # First pass: collect fcurves that have keyframes at current frame
        for fc in act.fcurves:
            data_path = fc.data_path
            path, _dot, attribute = data_path.rpartition('.')
            
            # Check if this bone should be processed
            if selected_bones_only and path:
                if 'pose.bones[' in path:
                    bone_name = path.split('"')[1] if '"' in path else path.split("'")[1] if "'" in path else ""
                    if bone_name and bone_name not in selected_bone_names:
                        continue
            
            # Check if there's a keyframe at current frame
            for kf in fc.keyframe_points:
                if abs(kf.co[0] - current_frame) < 0.001:
                    fcurves_to_process.append(fc)
                    break
        
        # Second pass: process the keyframes
        for fc in fcurves_to_process:
            data_path = fc.data_path
            array_index = fc.array_index
            path, _dot, attribute = data_path.rpartition('.')
            
            # Find the keyframe at current frame
            current_kf = None
            for kf in fc.keyframe_points:
                if abs(kf.co[0] - current_frame) < 0.001:
                    current_kf = kf
                    break
            
            if current_kf is None:
                continue
                
            # Get the value and handles
            value = current_kf.co[1]
            left_handle = current_kf.handle_left[1]
            right_handle = current_kf.handle_right[1]
            
            # Apply negation if needed
            if (attribute, array_index) in negate_data_path_tuples:
                value = -value
                left_handle = -left_handle
                right_handle = -right_handle
            
            # Find target fcurve (mirrored bone)
            target_data_path = data_path
            if path and (path in mirror_map):
                target_data_path = "".join((mirror_map[path], _dot, attribute))
            
            # Find or create target fcurve
            target_fc = None
            for fc_check in act.fcurves:
                if fc_check.data_path == target_data_path and fc_check.array_index == array_index:
                    target_fc = fc_check
                    break
            
            if target_fc is None:
                target_fc = act.fcurves.new(target_data_path, index=array_index)
            
            # Set keyframe at current frame
            target_fc.keyframe_points.insert(current_frame, value)
            
            # Update the keyframe handles
            for kf in target_fc.keyframe_points:
                if abs(kf.co[0] - current_frame) < 0.001:
                    kf.handle_left = (kf.handle_left[0], left_handle)
                    kf.handle_right = (kf.handle_right[0], right_handle)
                    break
                    
    else:
        # Original behavior: process entire fcurves
        for fc in act.fcurves:
            data_path = fc.data_path
            array_index = fc.array_index

            # bone curves are 'pose.bones["root"].location'
            # objects curves are simply 'location'
            path, _dot, attribute = data_path.rpartition('.')
            
            # If selected bones only is enabled, check if this bone is selected
            if selected_bones_only and path:
                # Extract bone name from path like 'pose.bones["bone_name"]'
                if 'pose.bones[' in path:
                    bone_name = path.split('"')[1] if '"' in path else path.split("'")[1] if "'" in path else ""
                    if bone_name and bone_name not in selected_bone_names:
                        continue
            
            # check if it is bone curve then flip data_path
            if path and (path in mirror_map):
                fc.data_path = "".join((mirror_map[path], _dot, attribute))
            
            if (attribute, array_index) in negate_data_path_tuples:
                negate_fcurve(fc, only_active_frame=False, current_frame=None)


#########################################################################################
# Hip Bone 180 Rotation
#########################################################################################

def find_hip_bone(armature):
    """Find the hip bone in the armature"""
    if not armature or armature.type != 'ARMATURE':
        return None
    
    # Common hip bone names
    hip_keywords = ['hip', 'pelvis', 'root']
    
    for bone in armature.pose.bones:
        bone_name_lower = bone.name.lower()
        for keyword in hip_keywords:
            if keyword in bone_name_lower:
                return bone
    
    return None

def rotate_hip_180(armature, axis, only_active_frame=False, current_frame=None):
    """Rotate hip bone 180 degrees on specified axis"""
    hip_bone = find_hip_bone(armature)
    
    if not hip_bone:
        print("No hip bone found for 180 degree rotation")
        return False
    
    import math
    rotation_180 = math.radians(180)
    
    # Store original mode and ensure we're in pose mode
    original_mode = bpy.context.mode
    if original_mode != 'POSE':
        bpy.ops.object.mode_set(mode='POSE')
    
    if only_active_frame and current_frame is not None:
        # Only rotate at current frame
        if hip_bone.rotation_mode == 'QUATERNION':
            # Create rotation quaternion and apply it
            if axis == 'X':
                rot_quat = mathutils.Quaternion((1, 0, 0), rotation_180)
            elif axis == 'Y':
                rot_quat = mathutils.Quaternion((0, 1, 0), rotation_180)
            elif axis == 'Z':
                rot_quat = mathutils.Quaternion((0, 0, 1), rotation_180)
            hip_bone.rotation_quaternion = rot_quat @ hip_bone.rotation_quaternion
            hip_bone.keyframe_insert(data_path="rotation_quaternion", frame=current_frame)
        else:
            # Apply 180 degree rotation to euler
            if axis == 'X':
                hip_bone.rotation_euler[0] += rotation_180
            elif axis == 'Y':
                hip_bone.rotation_euler[1] += rotation_180
            elif axis == 'Z':
                hip_bone.rotation_euler[2] += rotation_180
            hip_bone.keyframe_insert(data_path="rotation_euler", frame=current_frame)
    else:
        # Rotate for entire animation
        action = armature.animation_data.action if armature.animation_data else None
        if not action:
            print("No action found for hip bone rotation")
            return False
        
        # Find all frames with keyframes for the hip bone
        hip_frames = set()
        for fcurve in action.fcurves:
            if f'pose.bones["{hip_bone.name}"]' in fcurve.data_path and 'rotation' in fcurve.data_path:
                for keyframe in fcurve.keyframe_points:
                    hip_frames.add(int(keyframe.co[0]))
        
        # If no keyframes found, apply to current frame only
        if not hip_frames:
            hip_frames = {current_frame or 1}
        
        # Store original frame
        original_frame = bpy.context.scene.frame_current
        
        # Apply rotation to each frame
        for frame in hip_frames:
            bpy.context.scene.frame_set(frame)
            
            if hip_bone.rotation_mode == 'QUATERNION':
                # Create rotation quaternion and apply it
                if axis == 'X':
                    rot_quat = mathutils.Quaternion((1, 0, 0), rotation_180)
                elif axis == 'Y':
                    rot_quat = mathutils.Quaternion((0, 1, 0), rotation_180)
                elif axis == 'Z':
                    rot_quat = mathutils.Quaternion((0, 0, 1), rotation_180)
                hip_bone.rotation_quaternion = rot_quat @ hip_bone.rotation_quaternion
                hip_bone.keyframe_insert(data_path="rotation_quaternion", frame=frame)
            else:
                if axis == 'X':
                    hip_bone.rotation_euler[0] += rotation_180
                elif axis == 'Y':
                    hip_bone.rotation_euler[1] += rotation_180
                elif axis == 'Z':
                    hip_bone.rotation_euler[2] += rotation_180
                hip_bone.keyframe_insert(data_path="rotation_euler", frame=frame)
        
        # Restore original frame
        bpy.context.scene.frame_set(original_frame)
    
    # Restore original mode
    if original_mode != 'POSE':
        bpy.ops.object.mode_set(mode=original_mode)
    
    print(f"Applied 180 degree rotation to hip bone '{hip_bone.name}' on {axis}-axis")
    return True


#########################################################################################
# OPERATORS
#########################################################################################


class SUB_OT_mirror_action(Operator):
    """Mirror/flip animation on selected axis"""
    bl_idname = "sub.mirror_action"
    bl_label = "Mirror Action"
    bl_options = {"REGISTER","UNDO"}

    axis : EnumProperty(
        name="Axis",
        description="Select mirror axis",
        default='Y',
        items = (
            ('X', 'X', "X axis"),
            ('Y', 'Y', "Y axis"),
            ('Z', 'Z', "Z axis"),
            ('XY', 'XY', "Both XY axes"),
            ('XZ', 'XZ', "Both XZ axes"),
            ('YZ', 'YZ', "Both YZ axes"),
            ('XYZ', 'XYZ', "All XYZ axes"),
            ('O', 'Original', "Original"),
        )
    )

    rotate_180 : BoolProperty(
        name="180 Rotate",
        description="Rotate hip bone 180 degrees on selected axis after mirroring",
        default=False
    )

    selected_bones_only : BoolProperty(
        name="Selected Bones Only",
        description="Mirror only selected bones (armatures only)",
        default=False
    )

    only_active_frame : BoolProperty(
        name="Only Active Frame",
        description="Mirror only keyframes at the current frame",
        default=False
    )

    @classmethod
    def poll(cls, context):
        return context.active_object

    def execute(self, context):

        if not context.active_object.animation_data:
            self.report({"ERROR"}, "No Animation Data")
            return {'CANCELLED'}
        if not context.active_object.animation_data.action:
            self.report({"ERROR"}, "No Action assigned")
            return {'CANCELLED'}
        if not context.active_object.animation_data.action.fcurves:
            self.report({"ERROR"}, "No Keyframes")
            return {'CANCELLED'}
        
        # Get current frame for hip rotation
        current_frame = context.scene.frame_current if self.only_active_frame else None
        
        # Apply mirroring
        if self.axis in ('X', 'Y', 'Z'): 
            mirror_action(context.active_object.animation_data.action, axis=self.axis, selected_bones_only=self.selected_bones_only, context=context, only_active_frame=self.only_active_frame)
            # Apply 180 rotation to hip if enabled
            if self.rotate_180:
                rotate_hip_180(context.active_object, self.axis, only_active_frame=self.only_active_frame, current_frame=current_frame)
        elif self.axis == 'XY':
            mirror_action(context.active_object.animation_data.action, axis='X', selected_bones_only=self.selected_bones_only, context=context, only_active_frame=self.only_active_frame)
            mirror_action(context.active_object.animation_data.action, axis='Y', selected_bones_only=self.selected_bones_only, context=context, only_active_frame=self.only_active_frame)
            # Apply 180 rotation to hip if enabled (for each axis)
            if self.rotate_180:
                rotate_hip_180(context.active_object, 'X', only_active_frame=self.only_active_frame, current_frame=current_frame)
                rotate_hip_180(context.active_object, 'Y', only_active_frame=self.only_active_frame, current_frame=current_frame)
        elif self.axis == 'XZ':
            mirror_action(context.active_object.animation_data.action, axis='X', selected_bones_only=self.selected_bones_only, context=context, only_active_frame=self.only_active_frame)
            mirror_action(context.active_object.animation_data.action, axis='Z', selected_bones_only=self.selected_bones_only, context=context, only_active_frame=self.only_active_frame)
            # Apply 180 rotation to hip if enabled (for each axis)
            if self.rotate_180:
                rotate_hip_180(context.active_object, 'X', only_active_frame=self.only_active_frame, current_frame=current_frame)
                rotate_hip_180(context.active_object, 'Z', only_active_frame=self.only_active_frame, current_frame=current_frame)
        elif self.axis == 'YZ':
            mirror_action(context.active_object.animation_data.action, axis='Y', selected_bones_only=self.selected_bones_only, context=context, only_active_frame=self.only_active_frame)
            mirror_action(context.active_object.animation_data.action, axis='Z', selected_bones_only=self.selected_bones_only, context=context, only_active_frame=self.only_active_frame)
            # Apply 180 rotation to hip if enabled (for each axis)
            if self.rotate_180:
                rotate_hip_180(context.active_object, 'Y', only_active_frame=self.only_active_frame, current_frame=current_frame)
                rotate_hip_180(context.active_object, 'Z', only_active_frame=self.only_active_frame, current_frame=current_frame)
        elif self.axis == 'XYZ':
            mirror_action(context.active_object.animation_data.action, axis='X', selected_bones_only=self.selected_bones_only, context=context, only_active_frame=self.only_active_frame)
            mirror_action(context.active_object.animation_data.action, axis='Y', selected_bones_only=self.selected_bones_only, context=context, only_active_frame=self.only_active_frame)
            mirror_action(context.active_object.animation_data.action, axis='Z', selected_bones_only=self.selected_bones_only, context=context, only_active_frame=self.only_active_frame)
            # Apply 180 rotation to hip if enabled (for each axis)
            if self.rotate_180:
                rotate_hip_180(context.active_object, 'X', only_active_frame=self.only_active_frame, current_frame=current_frame)
                rotate_hip_180(context.active_object, 'Y', only_active_frame=self.only_active_frame, current_frame=current_frame)
                rotate_hip_180(context.active_object, 'Z', only_active_frame=self.only_active_frame, current_frame=current_frame)
        # Skip 'O'; helps back and forth between poses
        
        # Update success message to include hip rotation info
        message = f"Action mirrored on {self.axis}-axis!"
        if self.rotate_180:
            message += f" Hip rotated 180° on {self.axis}-axis."
        self.report({"INFO"}, message)
        return {'FINISHED'}


#########################################################################################
# REGISTER/UNREGISTER
#########################################################################################


classes = (
    SUB_OT_mirror_action,
)

def register():
    logger.info("Registering mirror_animation.py classes")
    for cls in classes:
        try:
            bpy.utils.register_class(cls)
            logger.info(f"Successfully registered {cls.__name__}")
        except Exception as e:
            logger.error(f"Failed to register {cls.__name__}: {str(e)}")

def unregister():
    logger.info("Unregistering mirror_animation.py classes")
    for cls in reversed(classes):
        try:
            bpy.utils.unregister_class(cls)
            logger.info(f"Successfully unregistered {cls.__name__}")
        except Exception as e:
            logger.error(f"Failed to unregister {cls.__name__}: {str(e)}")


if __name__ == "__main__":
    register() 