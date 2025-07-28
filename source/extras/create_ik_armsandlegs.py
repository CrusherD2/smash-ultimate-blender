import bpy
import mathutils
from mathutils import Vector, Matrix
import math

class SUB_OP_create_ik_bones_operator(bpy.types.Operator):
    """Generate FK/IK Setup for Arms and Legs with Animation Transfer"""
    bl_idname = "sub.create_ik_bones"
    bl_label = "Create FK/IK Setup Arms + Legs"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        armature_object = context.object
        
        if not armature_object or armature_object.type != 'ARMATURE':
            self.report({'ERROR'}, "No armature selected. Please select an armature in Object Mode.")
            return {'CANCELLED'}

        armature = armature_object.data
        side = ("L", "R")
        
        # We'll use a larger size for IK bones for better visibility
        ik_scale_factor = 2.0  # Increased scale factor for longer bones
        
        bpy.ops.object.mode_set(mode="EDIT")
        
        # Store original bone data for animation transfer
        original_bone_data = {}
        
        for i in side:
            # Get edit bones
            leg_bone = armature.edit_bones.get("Leg"+i)
            knee_bone = armature.edit_bones.get("Knee"+i)
            foot_bone = armature.edit_bones.get("Foot"+i)
            shoulder_bone = armature.edit_bones.get("Shoulder"+i)
            arm_bone = armature.edit_bones.get("Arm"+i)
            hand_bone = armature.edit_bones.get("Hand"+i)
            
            # Skip if bones don't exist
            if not all([bone for bone in [leg_bone, knee_bone, foot_bone, arm_bone, hand_bone]]):
                continue

            # --- BONE CHAIN CONNECTIVITY CORRECTION ---
            # Ensure leg chain is connected
            knee_bone.head = leg_bone.tail.copy()
            foot_bone.head = knee_bone.tail.copy()
            # Ensure arm chain is connected
            if shoulder_bone:
                arm_bone.head = shoulder_bone.tail.copy()
            hand_bone.head = arm_bone.tail.copy()

            # Store original bone matrices for FK bone creation
            original_bone_data[f"Leg{i}"] = leg_bone.matrix.copy()
            original_bone_data[f"Knee{i}"] = knee_bone.matrix.copy()
            original_bone_data[f"Foot{i}"] = foot_bone.matrix.copy()
            original_bone_data[f"Shoulder{i}"] = shoulder_bone.matrix.copy() if shoulder_bone else None
            original_bone_data[f"Arm{i}"] = arm_bone.matrix.copy()
            original_bone_data[f"Hand{i}"] = hand_bone.matrix.copy()
            
            # Create FK bones for legs
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
            
            # Create FK bones for arms
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
            leg_bone.tail += Vector((0.0, -0.05, 0.0))
            knee_bone.head += Vector((0.0, -0.05, 0.0))
            if shoulder_bone:
                shoulder_bone.tail += Vector((0.0, -0.05, 0.0))
            arm_bone.head += Vector((0.0, -0.05, 0.0))
            
            # Create knee IK pole target (shorter than original)
            knee_ik_bone = armature.edit_bones.new("KneeIK"+i)
            knee_ik_bone.head = knee_bone.head.copy()
            knee_ik_bone.tail = knee_bone.head + (knee_bone.tail - knee_bone.head) * 0.5  # 50% length
            knee_ik_bone.roll = knee_bone.roll

            # Create arm IK pole target (same as original)
            arm_ik_bone = armature.edit_bones.new("ArmIK"+i)
            arm_ik_bone.head = arm_bone.head.copy()
            arm_ik_bone.tail = arm_bone.tail.copy()
            arm_ik_bone.roll = arm_bone.roll

            # Create foot IK target (even longer than before)
            foot_ik_bone = armature.edit_bones.new("FootIK"+i)
            foot_ik_bone.head = foot_bone.head.copy()
            foot_dir = (foot_bone.tail - foot_bone.head).normalized()
            foot_len = (foot_bone.tail - foot_bone.head).length * 2.5  # 250% length
            foot_ik_bone.tail = foot_ik_bone.head + foot_dir * foot_len
            foot_ik_bone.roll = foot_bone.roll

            # Create hand IK target (even longer than before)
            hand_ik_bone = armature.edit_bones.new("HandIK"+i)
            hand_ik_bone.head = hand_bone.head.copy()
            hand_dir = (hand_bone.tail - hand_bone.head).normalized()
            hand_len = (hand_bone.tail - hand_bone.head).length * 2.5  # 250% length
            hand_ik_bone.tail = hand_ik_bone.head + hand_dir * hand_len
            hand_ik_bone.roll = hand_bone.roll
        
        bpy.ops.object.mode_set(mode="POSE")
        
        # Transfer animation from original bones to FK bones
        self.transfer_animation_to_fk_bones(context, armature_object, side)
        
        # Setup constraints so original bones follow FK bones by default
        sides = ["L", "R"]
        self.setup_fk_constraints(context, armature_object, sides)
        
        # Setup bone collections and colors
        self.setup_bone_collections_and_colors(context, armature_object)
        
        self.report({'INFO'}, "FK/IK full setup created successfully!")
        return {'FINISHED'}
    
    def transfer_animation_to_fk_bones(self, context, armature_object, sides):
        """Transfer animation from original bones to FK bones (move, not copy). For arms, only keep first frame keyframes; for knees, reset to rest pose and keyframe at first frame."""
        if not armature_object.animation_data or not armature_object.animation_data.action:
            return  # No animation to transfer
        
        action = armature_object.animation_data.action
        bone_mapping = {}
        
        # Create mapping of original bones to FK bones
        for side in sides:
            bone_mapping[f"Leg{side}"] = f"LegFK{side}"
            bone_mapping[f"Knee{side}"] = f"KneeFK{side}"  
            bone_mapping[f"Foot{side}"] = f"FootFK{side}"
            bone_mapping[f"Shoulder{side}"] = f"ShoulderFK{side}"
            bone_mapping[f"Arm{side}"] = f"ArmFK{side}"  
            bone_mapping[f"Hand{side}"] = f"HandFK{side}"
        
        frame_start = context.scene.frame_start
        
        for original_bone, fk_bone in bone_mapping.items():
            if armature_object.pose.bones.get(fk_bone):
                original_fcurves = [fc for fc in action.fcurves 
                                  if fc.data_path.startswith(f'pose.bones["{original_bone}"]')]
                # Copy FCurves to FK bone
                for original_fcurve in original_fcurves:
                    fk_data_path = original_fcurve.data_path.replace(f'pose.bones["{original_bone}"]', 
                                                                   f'pose.bones["{fk_bone}"]')
                    existing_fcurve = None
                    for fc in action.fcurves:
                        if fc.data_path == fk_data_path and fc.array_index == original_fcurve.array_index:
                            existing_fcurve = fc
                            break
                    if not existing_fcurve:
                        fk_fcurve = action.fcurves.new(data_path=fk_data_path, 
                                                     index=original_fcurve.array_index)
                        for keyframe in original_fcurve.keyframe_points:
                            new_keyframe = fk_fcurve.keyframe_points.insert(keyframe.co.x, keyframe.co.y)
                            new_keyframe.interpolation = keyframe.interpolation
                            new_keyframe.handle_left = keyframe.handle_left.copy()
                            new_keyframe.handle_right = keyframe.handle_right.copy()
                        fk_fcurve.update()
                # Remove original FCurves (delete animation from original bone)
                for fc in original_fcurves:
                    action.fcurves.remove(fc)
                pose_bone = armature_object.pose.bones.get(original_bone)
                if pose_bone:
                    # For knees: reset to rest pose and keyframe at first frame
                    if original_bone.startswith("Knee"):
                        pose_bone.location = (0.0, 0.0, 0.0)
                        pose_bone.rotation_quaternion = (1.0, 0.0, 0.0, 0.0)
                        pose_bone.rotation_euler = (0.0, 0.0, 0.0)
                        pose_bone.scale = (1.0, 1.0, 1.0)
                        context.scene.frame_set(frame_start)
                        pose_bone.keyframe_insert(data_path="location", frame=frame_start)
                        pose_bone.keyframe_insert(data_path="rotation_quaternion", frame=frame_start)
                        pose_bone.keyframe_insert(data_path="rotation_euler", frame=frame_start)
                        pose_bone.keyframe_insert(data_path="scale", frame=frame_start)
                    # For arms: only keep first frame keyframes, do not reset to rest pose
                    elif original_bone.startswith("Arm") or original_bone.startswith("Hand") or original_bone.startswith("Shoulder"):
                        # Remove all keyframes except the first frame
                        for prop in ["location", "rotation_quaternion", "rotation_euler", "scale"]:
                            # Insert a keyframe at the first frame for current value (should be the transferred pose)
                            context.scene.frame_set(frame_start)
                            pose_bone.keyframe_insert(data_path=prop, frame=frame_start)
                            # Remove all other keyframes for this property
                            for fc in [fc for fc in action.fcurves if fc.data_path == f'pose.bones["{original_bone}"].{prop}']:
                                keyframes_to_remove = [k for k in fc.keyframe_points if k.co.x != frame_start]
                                for k in reversed(keyframes_to_remove):
                                    fc.keyframe_points.remove(k)
                                fc.update()
    
    def setup_fk_constraints(self, context, armature_object, sides):
        """Setup both FK and IK constraints with FK enabled by default"""
        for side in sides:
            # Setup leg constraints
            leg_bone = armature_object.pose.bones.get(f"Leg{side}")
            leg_fk_bone = armature_object.pose.bones.get(f"LegFK{side}")
            if leg_bone and leg_fk_bone:
                # FK constraint
                fk_constraint = leg_bone.constraints.new('COPY_TRANSFORMS')
                fk_constraint.target = armature_object
                fk_constraint.subtarget = f"LegFK{side}"
                fk_constraint.name = "FK_Copy"
                fk_constraint.influence = 1.0  # Enabled by default
            
            # Setup knee constraints
            knee_bone = armature_object.pose.bones.get(f"Knee{side}")
            knee_fk_bone = armature_object.pose.bones.get(f"KneeFK{side}")
            if knee_bone and knee_fk_bone:
                # FK constraint
                fk_constraint = knee_bone.constraints.new('COPY_TRANSFORMS')
                fk_constraint.target = armature_object
                fk_constraint.subtarget = f"KneeFK{side}"
                fk_constraint.name = "FK_Copy"
                fk_constraint.influence = 1.0  # Enabled by default
            
            # Setup foot constraints with both FK and IK
            foot_bone = armature_object.pose.bones.get(f"Foot{side}")
            foot_fk_bone = armature_object.pose.bones.get(f"FootFK{side}")
            foot_ik_bone = armature_object.pose.bones.get(f"FootIK{side}")
            leg_ik_bone = armature_object.pose.bones.get(f"LegIK{side}")
            
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
                
                # Add pole target if leg IK bone exists
                if leg_ik_bone:
                    ik_constraint.pole_target = armature_object
                    ik_constraint.pole_subtarget = f"LegIK{side}"
                    ik_constraint.pole_angle = 0.0
            
            # Setup shoulder constraints if shoulder exists
            shoulder_bone = armature_object.pose.bones.get(f"Shoulder{side}")
            shoulder_fk_bone = armature_object.pose.bones.get(f"ShoulderFK{side}")
            if shoulder_bone and shoulder_fk_bone:
                # FK constraint
                fk_constraint = shoulder_bone.constraints.new('COPY_TRANSFORMS')
                fk_constraint.target = armature_object
                fk_constraint.subtarget = f"ShoulderFK{side}"
                fk_constraint.name = "FK_Copy"
                fk_constraint.influence = 1.0  # Enabled by default
            
            # Setup arm constraints
            arm_bone = armature_object.pose.bones.get(f"Arm{side}")
            arm_fk_bone = armature_object.pose.bones.get(f"ArmFK{side}")
            if arm_bone and arm_fk_bone:
                # FK constraint
                fk_constraint = arm_bone.constraints.new('COPY_TRANSFORMS')
                fk_constraint.target = armature_object
                fk_constraint.subtarget = f"ArmFK{side}"
                fk_constraint.name = "FK_Copy"
                fk_constraint.influence = 1.0  # Enabled by default
            
            # Setup hand constraints with both FK and IK
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

# Snap FK to IK operator with animation range dialog
class SUB_OP_snap_fk_to_ik_all(bpy.types.Operator):
    """Snap FK controls to match IK pose for arms and legs"""
    bl_idname = "sub.snap_fk_to_ik_all"
    bl_label = "Snap FK to IK (All)"
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
    
    def execute(self, context):
        armature_object = context.object
        if not armature_object or armature_object.type != 'ARMATURE':
            self.report({'ERROR'}, "No active armature selected")
            return {'CANCELLED'}
        
        if self.entire_animation:
            # Process all frames in the animation
            original_frame = context.scene.frame_current
            start_frame = context.scene.frame_start
            end_frame = context.scene.frame_end
            
            total_frames = end_frame - start_frame + 1
            
            # Show a progress indicator in the status bar
            context.window_manager.progress_begin(0, 100)
            
            try:
                for frame_num in range(start_frame, end_frame + 1):
                    # Update progress
                    progress = (frame_num - start_frame) / total_frames * 100
                    context.window_manager.progress_update(progress)
                    
                    # Set the current frame
                    context.scene.frame_set(frame_num)
                    
                    # Process this frame
                    sides = ["L", "R"]
                    bones_to_keyframe = []
                    for side in sides:
                        keyframe_bones_leg = self.snap_fk_to_ik_leg(armature_object, side)
                        keyframe_bones_arm = self.snap_fk_to_ik_arm(armature_object, side)
                        bones_to_keyframe.extend(keyframe_bones_leg)
                        bones_to_keyframe.extend(keyframe_bones_arm)
                    
                    # Auto keyframe if needed
                    if self.auto_keyframe:
                        for bone in bones_to_keyframe:
                            bone.keyframe_insert(data_path="location", frame=frame_num)
                            bone.keyframe_insert(data_path="rotation_quaternion", frame=frame_num)
                            bone.keyframe_insert(data_path="scale", frame=frame_num)
                
                # End progress indicator
                context.window_manager.progress_end()
                
                # Return to the original frame
                context.scene.frame_set(original_frame)
                
                # Report success
                self.report({'INFO'}, f"Successfully snapped FK to IK across {total_frames} frames")
                return {'FINISHED'}
                
            except Exception as e:
                # End progress indicator if there was an error
                context.window_manager.progress_end()
                context.scene.frame_set(original_frame)
                self.report({'ERROR'}, f"Error processing animation: {str(e)}")
                return {'CANCELLED'}
        else:
            # Process only the current frame
            sides = ["L", "R"]
            for side in sides:
                self.snap_fk_to_ik_leg(armature_object, side)
                self.snap_fk_to_ik_arm(armature_object, side)
            
            self.report({'INFO'}, "Snapped FK to IK for all limbs")
            return {'FINISHED'}
    
    def snap_fk_to_ik_leg(self, armature_object, side):
        """Snap IK leg bones to match FK leg bone positions using direct matrix assignment"""
        
        # Get the pose bones (FK bones are the source, IK bones are the target)
        leg_fk = armature_object.pose.bones.get(f"LegFK{side}")
        knee_fk = armature_object.pose.bones.get(f"KneeFK{side}")
        foot_fk = armature_object.pose.bones.get(f"FootFK{side}")
        
        # IK control bones that need to be moved
        foot_ik = armature_object.pose.bones.get(f"FootIK{side}")
        knee_ik = armature_object.pose.bones.get(f"KneeIK{side}")  # pole target
        
        if not all([leg_fk, knee_fk, foot_fk, foot_ik, knee_ik]):
            self.report({'WARNING'}, f"Could not find all required leg bones for side {side}")
            return []
        
        # Snap IK to FK using the reference logic
        # Set IK effector matrix relative to the original FK end bone in armature space
        ik_relative_to_fk = foot_fk.bone.matrix_local.inverted() @ foot_ik.bone.matrix_local
        foot_ik.matrix = foot_fk.matrix @ ik_relative_to_fk
        bpy.context.view_layer.update()
        
        # Get the vector bisecting each FK control (object space)
        pv_normal = ((knee_fk.vector.normalized() + leg_fk.vector.normalized() * -1)).normalized()
        
        # Push the pole control in the opposite direction of the FK bisecting vector (object space)
        pv_matrix_loc = knee_fk.matrix.to_translation() + (pv_normal * -0.2)
        pv_matrix = mathutils.Matrix.LocRotScale(pv_matrix_loc, knee_ik.matrix.to_quaternion(), None)
        knee_ik.matrix = pv_matrix
        bpy.context.view_layer.update()
        
        return [foot_ik, knee_ik]
    
    def snap_fk_to_ik_arm(self, armature_object, side):
        """Snap IK arm bones to match FK arm bone positions using direct matrix assignment"""
        
        # Get the pose bones (FK bones are the source, IK bones are the target)
        shoulder_fk = armature_object.pose.bones.get(f"ShoulderFK{side}")
        arm_fk = armature_object.pose.bones.get(f"ArmFK{side}")
        hand_fk = armature_object.pose.bones.get(f"HandFK{side}")
        
        # IK control bones that need to be moved
        hand_ik = armature_object.pose.bones.get(f"HandIK{side}")
        arm_ik = armature_object.pose.bones.get(f"ArmIK{side}")  # pole target
        
        if not all([shoulder_fk, arm_fk, hand_fk, hand_ik, arm_ik]):
            self.report({'WARNING'}, f"Could not find all required arm bones for side {side}")
            return []
        
        # Snap IK to FK using the reference logic
        # Set IK effector matrix relative to the original FK end bone in armature space
        ik_relative_to_fk = hand_fk.bone.matrix_local.inverted() @ hand_ik.bone.matrix_local
        hand_ik.matrix = hand_fk.matrix @ ik_relative_to_fk
        bpy.context.view_layer.update()
        
        # Get the vector bisecting each FK control (object space)
        pv_normal = ((arm_fk.vector.normalized() + shoulder_fk.vector.normalized() * -1)).normalized()
        
        # Push the pole control in the opposite direction of the FK bisecting vector (object space)
        pv_matrix_loc = arm_fk.matrix.to_translation() + (pv_normal * -0.2)
        pv_matrix = mathutils.Matrix.LocRotScale(pv_matrix_loc, arm_ik.matrix.to_quaternion(), None)
        arm_ik.matrix = pv_matrix
        bpy.context.view_layer.update()
        
        return [hand_ik, arm_ik]
    
    def invoke(self, context, event):
        wm = context.window_manager
        return wm.invoke_props_dialog(self)
    
    def draw(self, context):
        layout = self.layout
        layout.label(text="Snap FK to match current IK pose?")
        layout.prop(self, "entire_animation")
        
        # Only show auto keyframe option if entire animation is selected
        if self.entire_animation:
            layout.prop(self, "auto_keyframe")

class SUB_OP_create_fk_ik_setup_operator(bpy.types.Operator):
    bl_idname = "sub.create_fk_ik_setup"
    bl_label = "Create FK/IK Setup"
    bl_options = {'REGISTER', 'UNDO'}

    do_arms: bpy.props.BoolProperty(
        name="Arms",
        description="Create FK/IK setup for arms",
        default=True
    )
    do_legs: bpy.props.BoolProperty(
        name="Legs",
        description="Create FK/IK setup for legs",
        default=True
    )
    align_pose: bpy.props.BoolProperty(
        name="Align Pose",
        description="After setup, align FK and IK pose (shows Snap FK to IK dialog)",
        default=False
    )

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "do_arms")
        layout.prop(self, "do_legs")
        layout.prop(self, "align_pose")

    def execute(self, context):
        armature_object = context.object
        if not armature_object or armature_object.type != 'ARMATURE':
            self.report({'ERROR'}, "No armature selected. Please select an armature in Object Mode.")
            return {'CANCELLED'}

        # Call the appropriate setup operators
        if self.do_arms and self.do_legs:
            bpy.ops.sub.create_ik_bones('INVOKE_DEFAULT')
        elif self.do_arms:
            bpy.ops.sub.create_arm_ik('INVOKE_DEFAULT')
        elif self.do_legs:
            bpy.ops.sub.create_foot_ik('INVOKE_DEFAULT')
        else:
            self.report({'WARNING'}, "No setup selected.")
            return {'CANCELLED'}

        # If align_pose, show the Snap FK to IK dialog (second popup)
        if self.align_pose:
            bpy.ops.sub.snap_fk_to_ik_all('INVOKE_DEFAULT')

        return {'FINISHED'}

# Register the new operator

def register():
    bpy.utils.register_class(SUB_OP_create_ik_bones_operator)
    bpy.utils.register_class(SUB_OP_snap_fk_to_ik_all)
    bpy.utils.register_class(SUB_OP_create_fk_ik_setup_operator)

def unregister():
    bpy.utils.unregister_class(SUB_OP_create_ik_bones_operator)
    bpy.utils.unregister_class(SUB_OP_snap_fk_to_ik_all)
    bpy.utils.unregister_class(SUB_OP_create_fk_ik_setup_operator)

if __name__ == "__main__":
    register()