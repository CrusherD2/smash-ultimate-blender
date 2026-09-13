"""Small viewport buttons anchored beside the selected IK control."""

import bpy
from mathutils import Matrix
from bpy_extras.view3d_utils import location_3d_to_region_2d
from .control_appearance import controls


def selected(context):
    obj = context.object
    pb = context.active_pose_bone
    if not obj or obj.type != 'ARMATURE' or obj.mode != 'POSE' or not pb:
        return None
    kind = pb.bone.get('sub_ik_control_kind')
    target = pb.bone.get('sub_ik_control_target')
    info = (kind, target, '', '') if kind and target else controls(obj).get(pb.name)
    return (obj, pb, info) if info else None


class SUB_OP_ik_view_button(bpy.types.Operator):
    bl_idname = 'sub.ik_view_button'
    bl_label = 'Selected IK Control'
    bl_options = {'REGISTER', 'UNDO'}
    action: bpy.props.EnumProperty(
        items=[
            ('PLANT', 'Plant', ''),
            ('RELEASE', 'Release', ''),
            ('FK', 'Switch to FK', ''),
        ]
    )

    @classmethod
    def description(cls, context, properties):
        return {
            'PLANT': 'Plant this IK control and key the contact',
            'RELEASE': 'Release this IK control and key the contact',
            'FK': 'Switch this limb group to FK and key the switch',
        }[properties.action]

    def execute(self, context):
        found = selected(context)
        if not found:
            return {'CANCELLED'}
        obj, pb, (kind, target, shape, tool) = found
        if self.action == 'FK':
            return bpy.ops.sub.anim_rig_toggle_ik_fk(
                limbs=kind, set_enabled=True, enable_ik=False
            )
        return bpy.ops.sub.floor_contact(action=self.action, control=target)


class SUB_GGT_ik_buttons(bpy.types.GizmoGroup):
    bl_idname = 'SUB_GGT_ik_buttons'
    bl_label = 'IK Actions'
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'WINDOW'
    bl_options = {'PERSISTENT'}

    @classmethod
    def poll(cls, context):
        return bool(context.scene.sub_ik_view_buttons and selected(context))

    def setup(self, context):
        self.buttons = []
        for action, icon in [
            ('PLANT', 'PINNED'),
            ('RELEASE', 'UNPINNED'),
            ('FK', 'CON_KINEMATIC'),
        ]:
            gizmo = self.gizmos.new('GIZMO_GT_button_2d')
            gizmo.icon = icon
            gizmo.draw_options = {'BACKDROP', 'OUTLINE'}
            gizmo.scale_basis = 0.5
            gizmo.color = (0.12, 0.24, 0.36)
            gizmo.alpha = 0.85
            gizmo.color_highlight = (0.3, 0.65, 1)
            gizmo.alpha_highlight = 1
            gizmo.target_set_operator('sub.ik_view_button').action = action
            self.buttons.append(gizmo)

    def draw_prepare(self, context):
        found = selected(context)
        if not found:
            return
        obj, pb, info = found
        xy = location_3d_to_region_2d(
            context.region, context.space_data.region_3d, obj.matrix_world @ pb.head
        )
        contact = any(l.control == info[1] for l in obj.sub_floor_contact.limbs)
        for i, gizmo in enumerate(self.buttons):
            gizmo.hide = xy is None or (i < 2 and not contact)
            if xy is not None:
                x = min(max(xy.x + 48 + i * 36, 20), context.region.width - 20)
                y = min(max(xy.y - 32, 20), context.region.height - 20)
                gizmo.matrix_basis = Matrix.Translation((x, y, 0))


def register():
    bpy.types.Scene.sub_ik_view_buttons = bpy.props.BoolProperty(
        name='IK Buttons in Viewport', default=True
    )
    bpy.utils.register_class(SUB_OP_ik_view_button)
    bpy.utils.register_class(SUB_GGT_ik_buttons)


def unregister():
    bpy.utils.unregister_class(SUB_GGT_ik_buttons)
    bpy.utils.unregister_class(SUB_OP_ik_view_button)
    del bpy.types.Scene.sub_ik_view_buttons
