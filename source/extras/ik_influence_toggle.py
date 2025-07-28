import bpy
from bpy.types import Operator
from bpy.props import BoolProperty, FloatProperty

class SUB_OP_toggle_ik_influence(Operator):
    bl_idname = "sub.toggle_ik_influence"
    bl_label = "Toggle IK Influence"
    bl_description = "Toggle constraint influence for arms and legs"
    bl_options = {'REGISTER', 'UNDO'}
    
    influence_value: FloatProperty(
        name="Influence Value",
        description="Constraint influence (0 = off, 1 = on)",
        default=1.0,
        min=0.0,
        max=1.0
    )
    
    arms_enabled: BoolProperty(
        name="Arms",
        description="Toggle influence for arm and hand constraints",
        default=True
    )
    
    legs_enabled: BoolProperty(
        name="Legs",
        description="Toggle influence for leg and foot constraints",
        default=True
    )
    
    insert_keyframe: BoolProperty(
        name="Insert Keyframe",
        description="Insert keyframe for the influence value",
        default=True
    )
    
    @classmethod
    def poll(cls, context):
        return (context.mode == 'POSE' or context.mode == 'OBJECT') and context.active_object and context.active_object.type == 'ARMATURE'
    
    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)
    
    def draw(self, context):
        layout = self.layout
        layout.prop(self, "influence_value", slider=True)
        
        # Bone categories
        row = layout.row()
        row.prop(self, "arms_enabled")
        row.prop(self, "legs_enabled")
        
        layout.prop(self, "insert_keyframe")
    
    def execute(self, context):
        armature = context.active_object
        current_frame = context.scene.frame_current
        
        if not armature or armature.type != 'ARMATURE':
            self.report({'ERROR'}, "No armature selected")
            return {'CANCELLED'}
        
        constraints_modified = 0
        modified_types = set()
        
        # Process specific bones with our new constraint system
        sides = ["L", "R"]
        
        for side in sides:
            # Handle Arm bones - IK_Constraint
            if self.arms_enabled:
                arm_bone = armature.pose.bones.get(f"Arm{side}")
                if arm_bone:
                    for constraint in arm_bone.constraints:
                        if constraint.name == "IK_Constraint":
                            constraint.influence = self.influence_value
                            if self.insert_keyframe:
                                constraint.keyframe_insert(data_path="influence", frame=current_frame)
                            constraints_modified += 1
                            modified_types.add("arms")
                
                # Handle Hand bones - IK_Hand_Rotation
                hand_bone = armature.pose.bones.get(f"Hand{side}")
                if hand_bone:
                    for constraint in hand_bone.constraints:
                        if constraint.name == "IK_Hand_Rotation":
                            constraint.influence = self.influence_value
                            if self.insert_keyframe:
                                constraint.keyframe_insert(data_path="influence", frame=current_frame)
                            constraints_modified += 1
                            modified_types.add("arms")
            
            # Handle Knee bones - IK_Constraint
            if self.legs_enabled:
                knee_bone = armature.pose.bones.get(f"Knee{side}")
                if knee_bone:
                    for constraint in knee_bone.constraints:
                        if constraint.name == "IK_Constraint":
                            constraint.influence = self.influence_value
                            if self.insert_keyframe:
                                constraint.keyframe_insert(data_path="influence", frame=current_frame)
                            constraints_modified += 1
                            modified_types.add("legs")
                
                # Handle Foot bones - IK_Foot_Rotation
                foot_bone = armature.pose.bones.get(f"Foot{side}")
                if foot_bone:
                    for constraint in foot_bone.constraints:
                        if constraint.name == "IK_Foot_Rotation":
                            constraint.influence = self.influence_value
                            if self.insert_keyframe:
                                constraint.keyframe_insert(data_path="influence", frame=current_frame)
                            constraints_modified += 1
                            modified_types.add("legs")
        
        # Report the result
        if constraints_modified > 0:
            modified_types_str = ", ".join(modified_types)
            self.report({'INFO'}, f"Modified {constraints_modified} IK constraints on {modified_types_str} with influence {self.influence_value}")
        else:
            self.report({'WARNING'}, "No IK constraints found to modify")
        
        # Update the view
        for area in context.screen.areas:
            area.tag_redraw()
        
        return {'FINISHED'} 