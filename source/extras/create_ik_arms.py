import bpy
import mathutils
from mathutils import Vector, Matrix
import math

class SUB_OP_create_arm_ik_operator(bpy.types.Operator):
    """Generate FK/IK Setup for Arms with Animation Transfer"""
    bl_idname = "sub.create_arm_ik"
    bl_label = "Create Arm FK/IK Setup"
    bl_options = {'REGISTER', 'UNDO'}
    
    side: bpy.props.EnumProperty(
        name="Side",
        description="Which side to apply IK/FK setup",
        items=[
            ('BOTH', 'Both Sides', 'Apply to both L and R'),
            ('L', 'Left Side', 'Apply to L side only'),
            ('R', 'Right Side', 'Apply to R side only')
        ],
        default='BOTH'
    )
    
    ik_scale_factor: bpy.props.FloatProperty(
        name="IK Scale",
        description="Scale factor for IK bones (makes them larger for easier selection)",
        default=1.5,
        min=0.1,
        max=5.0
    )
    
    def execute(self, context):
        armature_object = context.object
        
        if not armature_object or armature_object.type != 'ARMATURE':
            self.report({'ERROR'}, "No armature selected. Please select an armature in Object Mode.")
            return {'CANCELLED'}
        
        # Determine which sides to process
        if self.side == 'BOTH':
            sides = ["L", "R"]
        else:
            sides = [self.side]
            
        bpy.ops.object.mode_set(mode='EDIT')
        
        # Store original bone data before modifications
        original_bone_data = {}
        armature = armature_object.data
        
        for i in sides:
            shoulder_bone = armature.edit_bones.get("Shoulder"+i)
            arm_bone = armature.edit_bones.get("Arm"+i)
            hand_bone = armature.edit_bones.get("Hand"+i)
            
            if not arm_bone or not hand_bone:
                continue
            
            # Store original bone matrices for FK bone creation
            original_bone_data[f"Shoulder{i}"] = shoulder_bone.matrix.copy() if shoulder_bone else None
            original_bone_data[f"Arm{i}"] = arm_bone.matrix.copy()
            original_bone_data[f"Hand{i}"] = hand_bone.matrix.copy()
            
            # Create FK bones (duplicates of original bones)
            if shoulder_bone:
                shoulder_fk_bone = armature.edit_bones.new("ShoulderFK" + i)
                shoulder_fk_bone.head = shoulder_bone.head.copy()
                shoulder_fk_bone.tail = shoulder_bone.tail.copy()
                shoulder_fk_bone.roll = shoulder_bone.roll
                shoulder_fk_bone.parent = shoulder_bone.parent
            
            arm_fk_bone = armature.edit_bones.new("ArmFK" + i)
            arm_fk_bone.head = arm_bone.head.copy()
            arm_fk_bone.tail = arm_bone.tail.copy()
            arm_fk_bone.roll = arm_bone.roll
            if shoulder_bone:
                arm_fk_bone.parent = armature.edit_bones.get("ShoulderFK" + i)
            else:
                arm_fk_bone.parent = arm_bone.parent
            
            hand_fk_bone = armature.edit_bones.new("HandFK" + i)
            hand_fk_bone.head = hand_bone.head.copy()
            hand_fk_bone.tail = hand_bone.tail.copy()
            hand_fk_bone.roll = hand_bone.roll
            hand_fk_bone.parent = arm_fk_bone
            
            # Add small offset to improve IK solving for original bones
            if shoulder_bone:
                shoulder_bone.tail += Vector((0.0, -0.05, 0.0))
            arm_bone.head += Vector((0.0, -0.05, 0.0))
            
            # Create IK pole target
            arm_ik_bone = armature.edit_bones.new("ArmIK" + i)
            # Position the pole target at a fixed distance behind
            arm_ik_bone.head = Vector((arm_bone.head.x, -5.5, arm_bone.head.z))
            arm_ik_bone.tail = Vector((arm_bone.head.x, 5.5, arm_bone.head.z))
            
            # Scale the pole target bone to be larger for better visibility
            arm_bone_length = (arm_bone.tail - arm_bone.head).length
            if arm_bone_length > 0.001:
                pole_length = arm_bone_length * 0.2 * self.ik_scale_factor
                pole_dir = (arm_ik_bone.tail - arm_ik_bone.head).normalized()
                arm_ik_bone.tail = arm_ik_bone.head + pole_dir * pole_length
            
            # Create IK target with proper orientation (in rest position)
            hand_ik_bone = armature.edit_bones.new("HandIK" + i)
            hand_ik_bone.head = arm_bone.tail.copy()
            
            # Calculate hand direction and make it longer
            hand_direction = (hand_bone.tail - hand_bone.head).normalized()
            hand_ik_length = (hand_bone.tail - hand_bone.head).length
            if hand_ik_length < 0.1:
                hand_ik_length = 0.5
            hand_ik_length *= self.ik_scale_factor  # Make it longer
            
            # Set tail in the same direction as the original hand bone
            hand_ik_bone.tail = hand_ik_bone.head + hand_direction * hand_ik_length
            hand_ik_bone.roll = hand_bone.roll  # Match the roll of the original hand
        
        bpy.ops.object.mode_set(mode="POSE")
        
        # Transfer animation from original bones to FK bones
        self.transfer_animation_to_fk_bones(context, armature_object, sides)
        
        # Setup constraints so original bones follow FK bones by default
        self.setup_fk_constraints(context, armature_object, sides)
        
        # Setup bone collections and coloring
        self.setup_bone_collections_and_colors(context, armature_object)
        
        # Setup FK bone groups for better organization
        self.setup_bone_groups(context, armature_object, sides)
        
        self.report({'INFO'}, "FK/IK arm setup created successfully!")
        return {'FINISHED'}
    
    def transfer_animation_to_fk_bones(self, context, armature_object, sides):
        """Transfer animation from original bones to FK bones"""
        if not armature_object.animation_data or not armature_object.animation_data.action:
            return  # No animation to transfer
        
        action = armature_object.animation_data.action
        bone_mapping = {}
        
        # Create mapping of original bones to FK bones
        for side in sides:
            bone_mapping[f"Shoulder{side}"] = f"ShoulderFK{side}"
            bone_mapping[f"Arm{side}"] = f"ArmFK{side}"
            bone_mapping[f"Hand{side}"] = f"HandFK{side}"
        
        # Copy FCurves from original bones to FK bones
        for original_bone, fk_bone in bone_mapping.items():
            if armature_object.pose.bones.get(fk_bone):  # FK bone exists
                # Find FCurves for the original bone
                original_fcurves = [fc for fc in action.fcurves 
                                    if f'pose.bones["{original_bone}"]' in fc.data_path]
                
                # Create matching FCurves for the FK bone
                for fc in original_fcurves:
                    new_data_path = fc.data_path.replace(f'pose.bones["{original_bone}"]', 
                                                        f'pose.bones["{fk_bone}"]')
                    
                    # Create new FCurve for FK bone
                    new_fc = action.fcurves.new(data_path=new_data_path, index=fc.array_index)
                    
                    # Copy all keyframe points
                    new_fc.keyframe_points.clear()
                    for kf in fc.keyframe_points:
                        new_kf = new_fc.keyframe_points.insert(kf.co[0], kf.co[1])
                        new_kf.handle_left = kf.handle_left
                        new_kf.handle_right = kf.handle_right
                        new_kf.interpolation = kf.interpolation
                        new_kf.easing = kf.easing
                    
                    new_fc.update()
    
    def setup_fk_constraints(self, context, armature_object, sides):
        """Setup both FK and IK constraints with FK enabled by default"""
        for side in sides:
            # Setup shoulder constraint if shoulder exists
            shoulder_bone = armature_object.pose.bones.get(f"Shoulder{side}")
            shoulder_fk_bone = armature_object.pose.bones.get(f"ShoulderFK{side}")
            if shoulder_bone and shoulder_fk_bone:
                # FK constraint (Copy Transforms from ShoulderFK)
                fk_constraint = shoulder_bone.constraints.new('COPY_TRANSFORMS')
                fk_constraint.target = armature_object
                fk_constraint.subtarget = f"ShoulderFK{side}"
                fk_constraint.name = "FK_Copy"
                fk_constraint.influence = 1.0  # Enabled by default
            
            # Setup arm constraint
            arm_bone = armature_object.pose.bones.get(f"Arm{side}")
            arm_fk_bone = armature_object.pose.bones.get(f"ArmFK{side}")
            if arm_bone and arm_fk_bone:
                # FK constraint
                fk_constraint = arm_bone.constraints.new('COPY_TRANSFORMS')
                fk_constraint.target = armature_object
                fk_constraint.subtarget = f"ArmFK{side}"
                fk_constraint.name = "FK_Copy"
                fk_constraint.influence = 1.0  # Enabled by default
            
            # Setup hand constraint with both FK and IK
            hand_bone = armature_object.pose.bones.get(f"Hand{side}")
            hand_fk_bone = armature_object.pose.bones.get(f"HandFK{side}")
            hand_ik_bone = armature_object.pose.bones.get(f"HandIK{side}")
            arm_ik_bone = armature_object.pose.bones.get(f"ArmIK{side}")
            
            if hand_bone and hand_fk_bone:
                # FK constraint
                fk_constraint = hand_bone.constraints.new('COPY_TRANSFORMS')
                fk_constraint.target = armature_object
                fk_constraint.subtarget = f"HandFK{side}"
                fk_constraint.name = "FK_Copy"
                fk_constraint.influence = 1.0  # Enabled by default
                
            # Add IK constraint to hand bone if IK bones exist
            if hand_bone and hand_ik_bone:
                ik_constraint = hand_bone.constraints.new('IK')
                ik_constraint.name = "IK_Constraint"
                ik_constraint.target = armature_object
                ik_constraint.subtarget = f"HandIK{side}"
                ik_constraint.chain_count = 3  # Include shoulder if it exists
                ik_constraint.influence = 0.0  # Disabled by default
                
                # Add pole target if arm IK bone exists
                if arm_ik_bone:
                    ik_constraint.pole_target = armature_object
                    ik_constraint.pole_subtarget = f"ArmIK{side}"
                    ik_constraint.pole_angle = 0.0
    
    def setup_bone_collections_and_colors(self, context, armature_object):
        """Setup bone collections and colors for FK/IK bones"""
        armature = armature_object.data
        
        # Create collections with better organization
        fk_collection_name = "FK Control Bones"
        ik_collection_name = "IK Control Bones"
        
        if fk_collection_name not in armature.collections:
            fk_collection = armature.collections.new(name=fk_collection_name)
        else:
            fk_collection = armature.collections[fk_collection_name]
        
        if ik_collection_name not in armature.collections:
            ik_collection = armature.collections.new(name=ik_collection_name)
        else:
            ik_collection = armature.collections[ik_collection_name]
        
        # Assign bones to collections and set colors
        for bone in armature.bones:
            if "FK" in bone.name and "IK" not in bone.name:
                fk_collection.assign(bone)
                # Set FK bones to green (THEME03)
                if bone.name in armature_object.pose.bones:
                    armature_object.pose.bones[bone.name].color.palette = 'THEME03'
                    bone.color.palette = 'THEME03'
            elif "IK" in bone.name:
                ik_collection.assign(bone)
                # Set IK bones to red (THEME01)
                if bone.name in armature_object.pose.bones:
                    armature_object.pose.bones[bone.name].color.palette = 'THEME01'
                    bone.color.palette = 'THEME01'
    
    def setup_bone_groups(self, context, armature_object, sides):
        """Setup bone groups for better organization"""
        # This method can be expanded for additional organization if needed
        pass


# Snap FK to IK operator with animation range dialog
class SUB_OP_snap_fk_to_ik_arms(bpy.types.Operator):
    """Snap FK controls to match IK pose for arms"""
    bl_idname = "sub.snap_fk_to_ik_arms"
    bl_label = "Snap FK to IK (Arms)"
    bl_options = {'REGISTER', 'UNDO'}
    
    entire_animation: bpy.props.BoolProperty(
        name="Entire Animation",
        description="Apply to the entire animation instead of just the current frame",
        default=False
    )
    
    auto_keyframe: bpy.props.BoolProperty(
        name="Auto Keyframe",
        description="Automatically insert keyframes when applying to the entire animation",
        default=True
    )

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)
    
    def draw(self, context):
        layout = self.layout
        layout.prop(self, "entire_animation")
        
        # Only show auto keyframe option if entire animation is selected
        if self.entire_animation:
            layout.prop(self, "auto_keyframe")

    def execute(self, context):
        armature_object = context.object
        
        if not armature_object or armature_object.type != 'ARMATURE':
            self.report({'ERROR'}, "No armature selected")
            return {'CANCELLED'}
        
        # Determine frame range
        if self.entire_animation:
            frame_start = bpy.context.scene.frame_start
            frame_end = bpy.context.scene.frame_end
        else:
            frame_start = frame_end = bpy.context.scene.frame_current
        
        # Snap for each frame in range
        for frame in range(frame_start, frame_end + 1):
            bpy.context.scene.frame_set(frame)
            self.snap_fk_to_ik_frame(armature_object)
            
            if self.entire_animation and self.auto_keyframe:
                self.insert_keyframes(armature_object)
        
        if self.entire_animation:
            self.report({'INFO'}, f"FK snapped to IK for frames {frame_start}-{frame_end}")
        else:
            self.report({'INFO'}, "FK snapped to IK for current frame")
        
        return {'FINISHED'}
    
    def snap_fk_to_ik_frame(self, armature_object):
        """Snap FK bones to match IK pose for current frame"""
        sides = ["L", "R"]
        
        for side in sides:
            # Get bones
            shoulder_bone = armature_object.pose.bones.get(f"Shoulder{side}")
            arm_bone = armature_object.pose.bones.get(f"Arm{side}")
            hand_bone = armature_object.pose.bones.get(f"Hand{side}")
            
            shoulder_fk_bone = armature_object.pose.bones.get(f"ShoulderFK{side}")
            arm_fk_bone = armature_object.pose.bones.get(f"ArmFK{side}")
            hand_fk_bone = armature_object.pose.bones.get(f"HandFK{side}")
            
            # Copy transforms from deformed bones to FK bones
            if shoulder_bone and shoulder_fk_bone:
                shoulder_fk_bone.matrix = shoulder_bone.matrix.copy()
            
            if arm_bone and arm_fk_bone:
                arm_fk_bone.matrix = arm_bone.matrix.copy()
            
            if hand_bone and hand_fk_bone:
                hand_fk_bone.matrix = hand_bone.matrix.copy()
    
    def insert_keyframes(self, armature_object):
        """Insert keyframes for FK bones"""
        sides = ["L", "R"]
        
        for side in sides:
            for bone_name in [f"ShoulderFK{side}", f"ArmFK{side}", f"HandFK{side}"]:
                bone = armature_object.pose.bones.get(bone_name)
                if bone:
                    bone.keyframe_insert(data_path="rotation_quaternion")
                    bone.keyframe_insert(data_path="location")
                    bone.keyframe_insert(data_path="scale")


def register():
    bpy.utils.register_class(SUB_OP_create_arm_ik_operator)
    bpy.utils.register_class(SUB_OP_snap_fk_to_ik_arms)

def unregister():
    bpy.utils.unregister_class(SUB_OP_create_arm_ik_operator)
    bpy.utils.unregister_class(SUB_OP_snap_fk_to_ik_arms)

if __name__ == "__main__":
    register()
