import bpy
import mathutils
from mathutils import Vector, Matrix
import math

class SUB_OP_create_foot_ik_operator(bpy.types.Operator):
    """Generate FK/IK Setup for Legs with Animation Transfer"""
    bl_idname = "sub.create_foot_ik"
    bl_label = "Create Leg FK/IK Setup"
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
            leg_bone = armature.edit_bones.get("Leg"+i)
            knee_bone = armature.edit_bones.get("Knee"+i)
            foot_bone = armature.edit_bones.get("Foot"+i)
            
            if not leg_bone or not knee_bone or not foot_bone:
                continue
            
            # Store original bone matrices for FK bone creation
            original_bone_data[f"Leg{i}"] = leg_bone.matrix.copy()
            original_bone_data[f"Knee{i}"] = knee_bone.matrix.copy()
            original_bone_data[f"Foot{i}"] = foot_bone.matrix.copy()
            
            # Create FK bones (duplicates of original bones)
            leg_fk_bone = armature.edit_bones.new("LegFK" + i)
            leg_fk_bone.head = leg_bone.head.copy()
            leg_fk_bone.tail = leg_bone.tail.copy()
            leg_fk_bone.roll = leg_bone.roll
            leg_fk_bone.parent = leg_bone.parent
            
            knee_fk_bone = armature.edit_bones.new("KneeFK" + i)
            knee_fk_bone.head = knee_bone.head.copy()
            knee_fk_bone.tail = knee_bone.tail.copy()
            knee_fk_bone.roll = knee_bone.roll
            knee_fk_bone.parent = leg_fk_bone
            
            foot_fk_bone = armature.edit_bones.new("FootFK" + i)
            foot_fk_bone.head = foot_bone.head.copy()
            foot_fk_bone.tail = foot_bone.tail.copy()
            foot_fk_bone.roll = foot_bone.roll
            foot_fk_bone.parent = knee_fk_bone
            
            # Add small offset to improve IK solving for original bones
            leg_bone.tail += Vector((0.0, -0.05, 0.0))
            
            # Determine direction of the leg for pole target placement
            # The knee should point backward if it's not already bent backward
            knee_ik_bone = armature.edit_bones.new("KneeIK" + i)
            
            # Get the thigh bone vector for context
            thigh_vec = leg_bone.tail - leg_bone.head
            
            # Position the pole target in front of the knee
            knee_forward_direction = Vector((0.0, 1.0, 0.0))  # Assume character faces forward
            pole_distance = thigh_vec.length * 1.0  # Distance from knee
            
            knee_ik_bone.head = knee_bone.head.copy()
            
            # Calculate initial pole direction based on current knee bend
            shinbone_vec = foot_bone.head - knee_bone.head
            thigh_bone_vec = knee_bone.head - leg_bone.head
            
            # Cross product to get pole direction
            cross_vec = thigh_bone_vec.cross(shinbone_vec).normalized()
            
            # If no bend, use forward direction
            if cross_vec.length < 0.01:
                pole_dir_initial = knee_forward_direction
            else:
                pole_dir_initial = cross_vec
            
            # Scale and position the pole bone
            pole_bone_length = leg_bone.length * 0.15 * self.ik_scale_factor
            knee_ik_bone.tail = knee_ik_bone.head + pole_dir_initial * pole_bone_length
            
            # Create foot IK target with proper orientation
            foot_ik_bone = armature.edit_bones.new("FootIK" + i)
            foot_ik_bone.head = knee_bone.tail.copy() # FK Shin bone's tail (ankle position)
            
            # Calculate foot direction and make it longer
            foot_direction = (foot_bone.tail - foot_bone.head).normalized()
            foot_ik_length = foot_bone.length if foot_bone.length > 0.01 else leg_bone.length * 0.3
            foot_ik_length *= self.ik_scale_factor
            
            # Set tail in the same direction as the original foot bone
            foot_ik_bone.tail = foot_ik_bone.head + foot_direction * foot_ik_length
            foot_ik_bone.roll = foot_bone.roll  # Match the roll of the original foot

        bpy.ops.object.mode_set(mode="POSE")
        
        # Transfer animation from original bones to FK bones
        self.transfer_animation_to_fk_bones(context, armature_object, sides)
        
        # Setup constraints so original bones follow FK bones by default
        self.setup_fk_constraints(context, armature_object, sides)
        
        # Setup bone collections and coloring
        self.setup_bone_collections_and_colors(context, armature_object)
        
        # Setup FK bone groups for better organization
        self.setup_bone_groups(context, armature_object, sides)
        
        self.report({'INFO'}, "FK/IK leg setup created successfully!")
        return {'FINISHED'}
    
    def transfer_animation_to_fk_bones(self, context, armature_object, sides):
        """Transfer animation from original bones to FK bones"""
        if not armature_object.animation_data or not armature_object.animation_data.action:
            return  # No animation to transfer
        
        action = armature_object.animation_data.action
        bone_mapping = {}
        
        # Create mapping of original bones to FK bones
        for side in sides:
            bone_mapping[f"Leg{side}"] = f"LegFK{side}"
            bone_mapping[f"Knee{side}"] = f"KneeFK{side}"  
            bone_mapping[f"Foot{side}"] = f"FootFK{side}"
        
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
            # Setup leg constraint
            leg_bone = armature_object.pose.bones.get(f"Leg{side}")
            leg_fk_bone = armature_object.pose.bones.get(f"LegFK{side}")
            if leg_bone and leg_fk_bone:
                # FK constraint
                fk_constraint = leg_bone.constraints.new('COPY_TRANSFORMS')
                fk_constraint.target = armature_object
                fk_constraint.subtarget = f"LegFK{side}"
                fk_constraint.name = "FK_Copy"
                fk_constraint.influence = 1.0  # Enabled by default
            
            # Setup knee constraint
            knee_bone = armature_object.pose.bones.get(f"Knee{side}")
            knee_fk_bone = armature_object.pose.bones.get(f"KneeFK{side}")
            if knee_bone and knee_fk_bone:
                # FK constraint
                fk_constraint = knee_bone.constraints.new('COPY_TRANSFORMS')
                fk_constraint.target = armature_object
                fk_constraint.subtarget = f"KneeFK{side}"
                fk_constraint.name = "FK_Copy"
                fk_constraint.influence = 1.0  # Enabled by default
            
            # Setup foot constraint with both FK and IK
            foot_bone = armature_object.pose.bones.get(f"Foot{side}")
            foot_fk_bone = armature_object.pose.bones.get(f"FootFK{side}")
            foot_ik_bone = armature_object.pose.bones.get(f"FootIK{side}")
            knee_ik_bone = armature_object.pose.bones.get(f"KneeIK{side}")
            
            if foot_bone and foot_fk_bone:
                # FK constraint
                fk_constraint = foot_bone.constraints.new('COPY_TRANSFORMS')
                fk_constraint.target = armature_object
                fk_constraint.subtarget = f"FootFK{side}"
                fk_constraint.name = "FK_Copy"
                fk_constraint.influence = 1.0  # Enabled by default
                
            # Add IK constraint to foot bone if IK bones exist
            if foot_bone and foot_ik_bone:
                ik_constraint = foot_bone.constraints.new('IK')
                ik_constraint.name = "IK_Constraint"
                ik_constraint.target = armature_object
                ik_constraint.subtarget = f"FootIK{side}"
                ik_constraint.chain_count = 3  # Include hip/pelvis connection
                ik_constraint.influence = 0.0  # Disabled by default
                
                # Add pole target if knee IK bone exists
                if knee_ik_bone:
                    ik_constraint.pole_target = armature_object
                    ik_constraint.pole_subtarget = f"KneeIK{side}"
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
class SUB_OP_snap_fk_to_ik_legs(bpy.types.Operator):
    """Snap FK controls to match IK pose for legs"""
    bl_idname = "sub.snap_fk_to_ik_legs"
    bl_label = "Snap FK to IK (Legs)"
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
            leg_bone = armature_object.pose.bones.get(f"Leg{side}")
            knee_bone = armature_object.pose.bones.get(f"Knee{side}")
            foot_bone = armature_object.pose.bones.get(f"Foot{side}")
            
            leg_fk_bone = armature_object.pose.bones.get(f"LegFK{side}")
            knee_fk_bone = armature_object.pose.bones.get(f"KneeFK{side}")
            foot_fk_bone = armature_object.pose.bones.get(f"FootFK{side}")
            
            # Copy transforms from deformed bones to FK bones
            if leg_bone and leg_fk_bone:
                leg_fk_bone.matrix = leg_bone.matrix.copy()
            
            if knee_bone and knee_fk_bone:
                knee_fk_bone.matrix = knee_bone.matrix.copy()
            
            if foot_bone and foot_fk_bone:
                foot_fk_bone.matrix = foot_bone.matrix.copy()
    
    def insert_keyframes(self, armature_object):
        """Insert keyframes for FK bones"""
        sides = ["L", "R"]
        
        for side in sides:
            for bone_name in [f"LegFK{side}", f"KneeFK{side}", f"FootFK{side}"]:
                bone = armature_object.pose.bones.get(bone_name)
                if bone:
                    bone.keyframe_insert(data_path="rotation_quaternion")
                    bone.keyframe_insert(data_path="location")
                    bone.keyframe_insert(data_path="scale")


def register():
    bpy.utils.register_class(SUB_OP_create_foot_ik_operator)
    bpy.utils.register_class(SUB_OP_snap_fk_to_ik_legs)


def unregister():
    bpy.utils.unregister_class(SUB_OP_create_foot_ik_operator)
    bpy.utils.unregister_class(SUB_OP_snap_fk_to_ik_legs)


if __name__ == "__main__":
    register()
