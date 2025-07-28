import bpy
from bpy.props import BoolProperty, FloatProperty

class SUB_OP_switch_ik_fk(bpy.types.Operator):
    """Switch between FK and IK control by toggling constraint influences"""
    bl_idname = "sub.switch_ik_fk"
    bl_label = "Switch between IK and FK"
    bl_options = {'REGISTER', 'UNDO'}
    
    insert_keyframe: BoolProperty(
        name="Insert Keyframe",
        description="Insert keyframe for the IK/FK switch at current frame",
        default=True
    )
    
    fk_influence: FloatProperty(
        name="FK Influence",
        description="FK constraint influence value (0 = IK, 1 = FK)",
        default=1.0,
        min=0.0,
        max=1.0
    )
    
    @classmethod
    def poll(cls, context):
        return context.object and context.object.type == 'ARMATURE'
    
    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)
    
    def draw(self, context):
        layout = self.layout
        layout.prop(self, "insert_keyframe")
        layout.prop(self, "fk_influence", slider=True)
    
    def execute(self, context):
        armature_object = context.object
        current_frame = context.scene.frame_current
        
        if not armature_object or armature_object.type != 'ARMATURE':
            self.report({'ERROR'}, "No active armature selected")
            return {'CANCELLED'}
        
        # Apply the FK influence value to all constraints
        self.apply_fk_influence(armature_object, self.fk_influence)
        
        # Insert keyframes if requested
        if self.insert_keyframe:
            self.insert_constraint_keyframes(armature_object, current_frame)
        
        # Report the current mode
        if self.fk_influence > 0.5:
            self.report({'INFO'}, f"Switched to FK control (influence: {self.fk_influence:.2f})")
        else:
            self.report({'INFO'}, f"Switched to IK control (influence: {self.fk_influence:.2f})")
        
        return {'FINISHED'}
    
    def apply_fk_influence(self, armature_object, fk_influence):
        """Apply FK influence value to all constraints"""
        sides = ["L", "R"]
        
        for side in sides:
            # Handle FK constraints on all bones
            for bone_name in [f"Shoulder{side}", f"Arm{side}", f"Hand{side}", f"Leg{side}", f"Knee{side}", f"Foot{side}"]:
                bone = armature_object.pose.bones.get(bone_name)
                if bone:
                    for constraint in bone.constraints:
                        if constraint.name == "FK_Copy":
                            constraint.influence = fk_influence
                            constraint.mute = (fk_influence < 0.5)
            
            # Handle IK constraints only on intermediate bones (Arm/Knee)
            for bone_name in [f"Arm{side}", f"Knee{side}"]:
                bone = armature_object.pose.bones.get(bone_name)
                if bone:
                    for constraint in bone.constraints:
                        if constraint.name == "IK_Constraint":
                            constraint.influence = 1.0 - fk_influence
                            constraint.mute = (fk_influence > 0.5)
            
            # Handle rotation constraints on end bones (Hand/Foot)
            for bone_name in [f"Hand{side}", f"Foot{side}"]:
                bone = armature_object.pose.bones.get(bone_name)
                if bone:
                    for constraint in bone.constraints:
                        if constraint.name in ["IK_Hand_Rotation", "IK_Foot_Rotation"]:
                            constraint.influence = 1.0 - fk_influence
                            constraint.mute = (fk_influence > 0.5)
                            
        # Force update the armature
        armature_object.update_tag()
        bpy.context.view_layer.update()
    
    def insert_constraint_keyframes(self, armature_object, frame):
        """Insert keyframes for all constraint influences"""
        sides = ["L", "R"]
        
        for side in sides:
            # Keyframe FK constraints on all bones
            for bone_name in [f"Shoulder{side}", f"Arm{side}", f"Hand{side}", f"Leg{side}", f"Knee{side}", f"Foot{side}"]:
                bone = armature_object.pose.bones.get(bone_name)
                if bone:
                    for constraint in bone.constraints:
                        if constraint.name == "FK_Copy":
                            constraint.keyframe_insert(data_path="influence", frame=frame)
            
            # Keyframe IK constraints on intermediate bones (Arm/Knee)
            for bone_name in [f"Arm{side}", f"Knee{side}"]:
                bone = armature_object.pose.bones.get(bone_name)
                if bone:
                    for constraint in bone.constraints:
                        if constraint.name == "IK_Constraint":
                            constraint.keyframe_insert(data_path="influence", frame=frame)
            
            # Keyframe rotation constraints on end bones (Hand/Foot)
            for bone_name in [f"Hand{side}", f"Foot{side}"]:
                bone = armature_object.pose.bones.get(bone_name)
                if bone:
                    for constraint in bone.constraints:
                        if constraint.name in ["IK_Hand_Rotation", "IK_Foot_Rotation"]:
                            constraint.keyframe_insert(data_path="influence", frame=frame)
    
    def get_current_mode(self, armature_object):
        """Determine current mode by checking FK constraint influence"""
        sides = ["L", "R"]
        
        for side in sides:
            # Check any arm bone for FK constraint
            arm_bone = armature_object.pose.bones.get(f"Arm{side}")
            if arm_bone:
                for constraint in arm_bone.constraints:
                    if constraint.name == "FK_Copy":
                        if constraint.influence > 0.5:
                            return "FK"
                        else:
                            return "IK"
            
            # Check leg bone if arm not found
            leg_bone = armature_object.pose.bones.get(f"Leg{side}")
            if leg_bone:
                for constraint in leg_bone.constraints:
                    if constraint.name == "FK_Copy":
                        if constraint.influence > 0.5:
                            return "FK"
                        else:
                            return "IK"
        
        return "UNKNOWN"
    
    def switch_to_fk(self, armature_object):
        """Switch to FK control by enabling FK constraints and disabling IK constraints"""
        self.apply_fk_influence(armature_object, 1.0)
    
    def switch_to_ik(self, armature_object):
        """Switch to IK control by disabling FK constraints and enabling IK constraints"""
        self.apply_fk_influence(armature_object, 0.0)
    
    def ensure_arm_ik_constraint(self, armature_object, side):
        """Create IK constraint on Arm bone targeting HandIK"""
        arm_bone = armature_object.pose.bones.get(f"Arm{side}")
        hand_ik_bone = armature_object.pose.bones.get(f"HandIK{side}")
        arm_ik_bone = armature_object.pose.bones.get(f"ArmIK{side}")
        
        if arm_bone and hand_ik_bone:
            # Check if IK constraint already exists
            has_ik = False
            for constraint in arm_bone.constraints:
                if constraint.name == "IK_Constraint":
                    has_ik = True
                    break
            
            if not has_ik:
                # Create IK constraint on Arm bone
                ik_constraint = arm_bone.constraints.new('IK')
                ik_constraint.name = "IK_Constraint"
                ik_constraint.target = armature_object
                ik_constraint.subtarget = f"HandIK{side}"
                ik_constraint.chain_count = 2
                ik_constraint.use_tail = True  # This is the correct setting
                ik_constraint.influence = 0.0  # Start with IK disabled
                
                # Add pole target
                if arm_ik_bone:
                    ik_constraint.pole_target = armature_object
                    ik_constraint.pole_subtarget = f"ArmIK{side}"
                    ik_constraint.pole_angle = 0.0

    def ensure_knee_ik_constraint(self, armature_object, side):
        """Create IK constraint on Knee bone targeting FootIK"""
        knee_bone = armature_object.pose.bones.get(f"Knee{side}")
        foot_ik_bone = armature_object.pose.bones.get(f"FootIK{side}")
        knee_ik_bone = armature_object.pose.bones.get(f"KneeIK{side}")
        
        if knee_bone and foot_ik_bone:
            # Check if IK constraint already exists
            has_ik = False
            for constraint in knee_bone.constraints:
                if constraint.name == "IK_Constraint":
                    has_ik = True
                    break
            
            if not has_ik:
                # Create IK constraint on Knee bone
                ik_constraint = knee_bone.constraints.new('IK')
                ik_constraint.name = "IK_Constraint"
                ik_constraint.target = armature_object
                ik_constraint.subtarget = f"FootIK{side}"
                ik_constraint.chain_count = 2
                ik_constraint.use_tail = True  # This is the correct setting
                ik_constraint.influence = 0.0  # Start with IK disabled
                
                # Add pole target
                if knee_ik_bone:
                    ik_constraint.pole_target = armature_object
                    ik_constraint.pole_subtarget = f"KneeIK{side}"
                    ik_constraint.pole_angle = 0.0

    def ensure_hand_rotation_constraint(self, armature_object, side):
        """Create rotation copy constraint on Hand bone to copy from HandIK"""
        hand_bone = armature_object.pose.bones.get(f"Hand{side}")
        hand_ik_bone = armature_object.pose.bones.get(f"HandIK{side}")
        
        if hand_bone and hand_ik_bone:
            # Check if rotation constraint already exists
            has_rotation = False
            for constraint in hand_bone.constraints:
                if constraint.name == "IK_Hand_Rotation":
                    has_rotation = True
                    break
            
            if not has_rotation:
                # Create rotation copy constraint on Hand bone
                rot_constraint = hand_bone.constraints.new('COPY_ROTATION')
                rot_constraint.name = "IK_Hand_Rotation"
                rot_constraint.target = armature_object
                rot_constraint.subtarget = f"HandIK{side}"
                rot_constraint.influence = 0.0  # Start with IK disabled

    def ensure_foot_rotation_constraint(self, armature_object, side):
        """Create rotation copy constraint on Foot bone to copy from FootIK"""
        foot_bone = armature_object.pose.bones.get(f"Foot{side}")
        foot_ik_bone = armature_object.pose.bones.get(f"FootIK{side}")
        
        if foot_bone and foot_ik_bone:
            # Check if rotation constraint already exists
            has_rotation = False
            for constraint in foot_bone.constraints:
                if constraint.name == "IK_Foot_Rotation":
                    has_rotation = True
                    break
            
            if not has_rotation:
                # Create rotation copy constraint on Foot bone
                rot_constraint = foot_bone.constraints.new('COPY_ROTATION')
                rot_constraint.name = "IK_Foot_Rotation"
                rot_constraint.target = armature_object
                rot_constraint.subtarget = f"FootIK{side}"
                rot_constraint.influence = 0.0  # Start with IK disabled


class SUB_OP_quick_switch_ik_fk(bpy.types.Operator):
    """Quickly switch between FK and IK control with automatic keyframing"""
    bl_idname = "sub.quick_switch_ik_fk"
    bl_label = "Quick Switch IK/FK"
    bl_options = {'REGISTER', 'UNDO'}
    
    @classmethod
    def poll(cls, context):
        return context.object and context.object.type == 'ARMATURE'
    
    def execute(self, context):
        armature_object = context.object
        current_frame = context.scene.frame_current
        
        if not armature_object or armature_object.type != 'ARMATURE':
            self.report({'ERROR'}, "No active armature selected")
            return {'CANCELLED'}
        
        # Check current state by looking at FK constraint influence on the first available bone
        current_mode = self.get_current_mode(armature_object)
        
        if current_mode == "FK":
            # Switch to IK
            self.switch_to_ik(armature_object, current_frame)
            self.report({'INFO'}, "Switched to IK control")
        elif current_mode == "IK":
            # Switch to FK  
            self.switch_to_fk(armature_object, current_frame)
            self.report({'INFO'}, "Switched to FK control")
        else:
            # If no constraints found, report error
            self.report({'ERROR'}, "No FK/IK constraints found. Please create FK/IK setup first.")
        
        return {'FINISHED'}
    
    def get_current_mode(self, armature_object):
        """Determine current mode by checking FK constraint influence"""
        sides = ["L", "R"]
        
        for side in sides:
            # Check any arm bone for FK constraint
            arm_bone = armature_object.pose.bones.get(f"Arm{side}")
            if arm_bone:
                for constraint in arm_bone.constraints:
                    if constraint.name == "FK_Copy":
                        if constraint.influence > 0.5:
                            return "FK"
                        else:
                            return "IK"
            
            # Check leg bone if arm not found
            leg_bone = armature_object.pose.bones.get(f"Leg{side}")
            if leg_bone:
                for constraint in leg_bone.constraints:
                    if constraint.name == "FK_Copy":
                        if constraint.influence > 0.5:
                            return "FK"
                        else:
                            return "IK"
        
        return "UNKNOWN"
    
    def switch_to_fk(self, armature_object, frame):
        """Switch to FK control by enabling FK constraints and disabling IK constraints"""
        sides = ["L", "R"]
        
        for side in sides:
            # Handle FK constraints on all bones
            for bone_name in [f"Shoulder{side}", f"Arm{side}", f"Hand{side}", f"Leg{side}", f"Knee{side}", f"Foot{side}"]:
                bone = armature_object.pose.bones.get(bone_name)
                if bone:
                    for constraint in bone.constraints:
                        if constraint.name == "FK_Copy":
                            constraint.influence = 1.0
                            constraint.mute = False
                            constraint.keyframe_insert(data_path="influence", frame=frame)
            
            # Handle IK constraints only on intermediate bones (Arm/Knee)
            for bone_name in [f"Arm{side}", f"Knee{side}"]:
                bone = armature_object.pose.bones.get(bone_name)
                if bone:
                    for constraint in bone.constraints:
                        if constraint.name == "IK_Constraint":
                            constraint.influence = 0.0
                            constraint.mute = True
                            constraint.keyframe_insert(data_path="influence", frame=frame)
            
            # Handle rotation constraints on end bones (Hand/Foot)
            for bone_name in [f"Hand{side}", f"Foot{side}"]:
                bone = armature_object.pose.bones.get(bone_name)
                if bone:
                    for constraint in bone.constraints:
                        if constraint.name in ["IK_Hand_Rotation", "IK_Foot_Rotation"]:
                            constraint.influence = 0.0
                            constraint.mute = True
                            constraint.keyframe_insert(data_path="influence", frame=frame)
                            
        # Force update the armature
        armature_object.update_tag()
        bpy.context.view_layer.update()

    def switch_to_ik(self, armature_object, frame):
        """Switch to IK control by disabling FK constraints and enabling IK constraints"""
        sides = ["L", "R"]
        
        for side in sides:
            # Handle FK constraints on all bones
            for bone_name in [f"Shoulder{side}", f"Arm{side}", f"Hand{side}", f"Leg{side}", f"Knee{side}", f"Foot{side}"]:
                bone = armature_object.pose.bones.get(bone_name)
                if bone:
                    for constraint in bone.constraints:
                        if constraint.name == "FK_Copy":
                            constraint.influence = 0.0
                            constraint.mute = True
                            constraint.keyframe_insert(data_path="influence", frame=frame)
            
            # Handle IK constraints only on intermediate bones (Arm/Knee)
            for bone_name in [f"Arm{side}", f"Knee{side}"]:
                bone = armature_object.pose.bones.get(bone_name)
                if bone:
                    for constraint in bone.constraints:
                        if constraint.name == "IK_Constraint":
                            constraint.influence = 1.0
                            constraint.mute = False
                            constraint.keyframe_insert(data_path="influence", frame=frame)
            
            # Handle rotation constraints on end bones (Hand/Foot)
            for bone_name in [f"Hand{side}", f"Foot{side}"]:
                bone = armature_object.pose.bones.get(bone_name)
                if bone:
                    for constraint in bone.constraints:
                        if constraint.name in ["IK_Hand_Rotation", "IK_Foot_Rotation"]:
                            constraint.influence = 1.0
                            constraint.mute = False
                            constraint.keyframe_insert(data_path="influence", frame=frame)
            
            # Create IK constraints on intermediate bones (Arm/Knee)
            self.ensure_arm_ik_constraint(armature_object, side)
            self.ensure_knee_ik_constraint(armature_object, side)
            
            # Create rotation constraints on end bones (Hand/Foot)
            self.ensure_hand_rotation_constraint(armature_object, side)
            self.ensure_foot_rotation_constraint(armature_object, side)
                                
        # Force update the armature
        armature_object.update_tag()
        bpy.context.view_layer.update()
    
    def ensure_arm_ik_constraint(self, armature_object, side):
        """Create IK constraint on Arm bone targeting HandIK"""
        arm_bone = armature_object.pose.bones.get(f"Arm{side}")
        hand_ik_bone = armature_object.pose.bones.get(f"HandIK{side}")
        arm_ik_bone = armature_object.pose.bones.get(f"ArmIK{side}")
        
        if arm_bone and hand_ik_bone:
            # Check if IK constraint already exists
            has_ik = False
            for constraint in arm_bone.constraints:
                if constraint.name == "IK_Constraint":
                    has_ik = True
                    break
            
            if not has_ik:
                # Create IK constraint on Arm bone
                ik_constraint = arm_bone.constraints.new('IK')
                ik_constraint.name = "IK_Constraint"
                ik_constraint.target = armature_object
                ik_constraint.subtarget = f"HandIK{side}"
                ik_constraint.chain_count = 2
                ik_constraint.use_tail = True  # This is the correct setting
                ik_constraint.influence = 1.0  # Enable IK
                
                # Add pole target
                if arm_ik_bone:
                    ik_constraint.pole_target = armature_object
                    ik_constraint.pole_subtarget = f"ArmIK{side}"
                    ik_constraint.pole_angle = 0.0

    def ensure_knee_ik_constraint(self, armature_object, side):
        """Create IK constraint on Knee bone targeting FootIK"""
        knee_bone = armature_object.pose.bones.get(f"Knee{side}")
        foot_ik_bone = armature_object.pose.bones.get(f"FootIK{side}")
        knee_ik_bone = armature_object.pose.bones.get(f"KneeIK{side}")
        
        if knee_bone and foot_ik_bone:
            # Check if IK constraint already exists
            has_ik = False
            for constraint in knee_bone.constraints:
                if constraint.name == "IK_Constraint":
                    has_ik = True
                    break
            
            if not has_ik:
                # Create IK constraint on Knee bone
                ik_constraint = knee_bone.constraints.new('IK')
                ik_constraint.name = "IK_Constraint"
                ik_constraint.target = armature_object
                ik_constraint.subtarget = f"FootIK{side}"
                ik_constraint.chain_count = 2
                ik_constraint.use_tail = True  # This is the correct setting
                ik_constraint.influence = 1.0  # Enable IK
                
                # Add pole target
                if knee_ik_bone:
                    ik_constraint.pole_target = armature_object
                    ik_constraint.pole_subtarget = f"KneeIK{side}"
                    ik_constraint.pole_angle = 0.0

    def ensure_hand_rotation_constraint(self, armature_object, side):
        """Create rotation copy constraint on Hand bone to copy from HandIK"""
        hand_bone = armature_object.pose.bones.get(f"Hand{side}")
        hand_ik_bone = armature_object.pose.bones.get(f"HandIK{side}")
        
        if hand_bone and hand_ik_bone:
            # Check if rotation constraint already exists
            has_rotation = False
            for constraint in hand_bone.constraints:
                if constraint.name == "IK_Hand_Rotation":
                    has_rotation = True
                    break
            
            if not has_rotation:
                # Create rotation copy constraint on Hand bone
                rot_constraint = hand_bone.constraints.new('COPY_ROTATION')
                rot_constraint.name = "IK_Hand_Rotation"
                rot_constraint.target = armature_object
                rot_constraint.subtarget = f"HandIK{side}"
                rot_constraint.influence = 1.0  # Enable IK

    def ensure_foot_rotation_constraint(self, armature_object, side):
        """Create rotation copy constraint on Foot bone to copy from FootIK"""
        foot_bone = armature_object.pose.bones.get(f"Foot{side}")
        foot_ik_bone = armature_object.pose.bones.get(f"FootIK{side}")
        
        if foot_bone and foot_ik_bone:
            # Check if rotation constraint already exists
            has_rotation = False
            for constraint in foot_bone.constraints:
                if constraint.name == "IK_Foot_Rotation":
                    has_rotation = True
                    break
            
            if not has_rotation:
                # Create rotation copy constraint on Foot bone
                rot_constraint = foot_bone.constraints.new('COPY_ROTATION')
                rot_constraint.name = "IK_Foot_Rotation"
                rot_constraint.target = armature_object
                rot_constraint.subtarget = f"FootIK{side}"
                rot_constraint.influence = 1.0  # Enable IK


class SUB_OP_advanced_ik_fk_control(bpy.types.Operator):
    """Advanced IK/FK control with fine-tuned influence slider and automatic keyframing"""
    bl_idname = "sub.advanced_ik_fk_control"
    bl_label = "Advanced IK/FK Control"
    bl_options = {'REGISTER', 'UNDO'}
    
    fk_influence: FloatProperty(
        name="FK Influence",
        description="FK constraint influence value (0 = IK, 1 = FK)",
        default=1.0,
        min=0.0,
        max=1.0
    )
    
    @classmethod
    def poll(cls, context):
        return context.object and context.object.type == 'ARMATURE'
    
    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)
    
    def draw(self, context):
        layout = self.layout
        layout.prop(self, "fk_influence", slider=True)
        
        # Show current mode
        if self.fk_influence > 0.5:
            layout.label(text="Mode: FK Control", icon="BONE_DATA")
        else:
            layout.label(text="Mode: IK Control", icon="CONSTRAINT_BONE")
        
        # Show blend percentage
        fk_percent = int(self.fk_influence * 100)
        ik_percent = 100 - fk_percent
        layout.label(text=f"FK: {fk_percent}% | IK: {ik_percent}%")
    
    def execute(self, context):
        armature_object = context.object
        current_frame = context.scene.frame_current
        
        if not armature_object or armature_object.type != 'ARMATURE':
            self.report({'ERROR'}, "No active armature selected")
            return {'CANCELLED'}
        
        # Apply the FK influence value to all constraints
        self.apply_fk_influence(armature_object, self.fk_influence)
        
        # Always insert keyframes for advanced control
        self.insert_constraint_keyframes(armature_object, current_frame)
        
        # Report the current mode
        if self.fk_influence > 0.5:
            self.report({'INFO'}, f"Set to FK control (influence: {self.fk_influence:.2f})")
        else:
            self.report({'INFO'}, f"Set to IK control (influence: {self.fk_influence:.2f})")
        
        return {'FINISHED'}
    
    def apply_fk_influence(self, armature_object, fk_influence):
        """Apply FK influence value to all constraints"""
        sides = ["L", "R"]
        
        for side in sides:
            # Handle FK constraints on all bones
            for bone_name in [f"Shoulder{side}", f"Arm{side}", f"Hand{side}", f"Leg{side}", f"Knee{side}", f"Foot{side}"]:
                bone = armature_object.pose.bones.get(bone_name)
                if bone:
                    for constraint in bone.constraints:
                        if constraint.name == "FK_Copy":
                            constraint.influence = fk_influence
                            constraint.mute = (fk_influence < 0.5)
            
            # Handle IK constraints only on intermediate bones (Arm/Knee)
            for bone_name in [f"Arm{side}", f"Knee{side}"]:
                bone = armature_object.pose.bones.get(bone_name)
                if bone:
                    for constraint in bone.constraints:
                        if constraint.name == "IK_Constraint":
                            constraint.influence = 1.0 - fk_influence
                            constraint.mute = (fk_influence > 0.5)
            
            # Handle rotation constraints on end bones (Hand/Foot)
            for bone_name in [f"Hand{side}", f"Foot{side}"]:
                bone = armature_object.pose.bones.get(bone_name)
                if bone:
                    for constraint in bone.constraints:
                        if constraint.name in ["IK_Hand_Rotation", "IK_Foot_Rotation"]:
                            constraint.influence = 1.0 - fk_influence
                            constraint.mute = (fk_influence > 0.5)
                            
        # Force update the armature
        armature_object.update_tag()
        bpy.context.view_layer.update()
    
    def insert_constraint_keyframes(self, armature_object, frame):
        """Insert keyframes for all constraint influences"""
        sides = ["L", "R"]
        
        for side in sides:
            # Keyframe FK constraints on all bones
            for bone_name in [f"Shoulder{side}", f"Arm{side}", f"Hand{side}", f"Leg{side}", f"Knee{side}", f"Foot{side}"]:
                bone = armature_object.pose.bones.get(bone_name)
                if bone:
                    for constraint in bone.constraints:
                        if constraint.name == "FK_Copy":
                            constraint.keyframe_insert(data_path="influence", frame=frame)
            
            # Keyframe IK constraints on intermediate bones (Arm/Knee)
            for bone_name in [f"Arm{side}", f"Knee{side}"]:
                bone = armature_object.pose.bones.get(bone_name)
                if bone:
                    for constraint in bone.constraints:
                        if constraint.name == "IK_Constraint":
                            constraint.keyframe_insert(data_path="influence", frame=frame)
            
            # Keyframe rotation constraints on end bones (Hand/Foot)
            for bone_name in [f"Hand{side}", f"Foot{side}"]:
                bone = armature_object.pose.bones.get(bone_name)
                if bone:
                    for constraint in bone.constraints:
                        if constraint.name in ["IK_Hand_Rotation", "IK_Foot_Rotation"]:
                            constraint.keyframe_insert(data_path="influence", frame=frame)


def register():
    bpy.utils.register_class(SUB_OP_switch_ik_fk)
    bpy.utils.register_class(SUB_OP_quick_switch_ik_fk)
    bpy.utils.register_class(SUB_OP_advanced_ik_fk_control)

def unregister():
    bpy.utils.unregister_class(SUB_OP_switch_ik_fk)
    bpy.utils.unregister_class(SUB_OP_quick_switch_ik_fk)
    bpy.utils.unregister_class(SUB_OP_advanced_ik_fk_control)

if __name__ == "__main__":
    register() 