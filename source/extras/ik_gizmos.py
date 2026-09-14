"""Small viewport buttons anchored beside the selected IK control."""

import bpy
from mathutils import Matrix, Vector, Euler
import blf
from bpy_extras.view3d_utils import location_3d_to_region_2d
from .control_appearance import controls


def selected(context):
    obj = context.object
    pb = context.active_pose_bone
    if not obj or obj.type != 'ARMATURE' or obj.mode != 'POSE' or not pb:
        return None
    from .create_animation_rig import armature_has_animation_rig
    from ..blender_compat import is_pose_bone_selected
    if not armature_has_animation_rig(obj) or not is_pose_bone_selected(pb) or pb.bone.hide:
        return None
    kind = pb.bone.get('sub_ik_control_kind')
    target = pb.bone.get('sub_ik_control_target')
    info = (kind, target, '', '') if kind and target else controls(obj).get(pb.name)
    return (obj, pb, info) if info else None


def button_layout(context):
    found = selected(context)
    if not found or not context.region or context.region.type != 'WINDOW':
        return []
    obj, pb, info = found
    evaluated = obj.evaluated_get(context.evaluated_depsgraph_get())
    pose = evaluated.pose.bones[pb.name]
    shape_pose = evaluated.pose.bones.get(pb.custom_shape_transform.name) if pb.custom_shape_transform else pose
    matrix = evaluated.matrix_world @ shape_pose.matrix
    if pb.custom_shape:
        scale = Vector(pb.custom_shape_scale_xyz)
        if pb.use_custom_shape_bone_size:
            scale *= pb.length
        matrix = matrix @ Matrix.Translation(pb.custom_shape_translation) @ Euler(pb.custom_shape_rotation_euler).to_matrix().to_4x4() @ Matrix.Diagonal((*scale, 1))
        corners = [matrix @ Vector(v) for v in pb.custom_shape.bound_box]
    else:
        corners = [matrix.translation]
    projected = [location_3d_to_region_2d(context.region, context.space_data.region_3d, p) for p in corners]
    if not projected or any(p is None for p in projected):
        return []
    center_x = (min(p.x for p in projected) + max(p.x for p in projected)) / 2
    bottom = min(p.y for p in projected)
    # Disappear offscreen instead of piling up against the viewport edge.
    if center_x < 0 or center_x > context.region.width or bottom > context.region.height or max(p.y for p in projected) < 0:
        return []
    contact = any(l.control == info[1] for l in obj.sub_floor_contact.limbs)
    indexes = [0, 1, 2] if contact else [2]
    ui_scale = context.preferences.system.ui_scale
    spacing, radius = 66 * ui_scale, 18 * ui_scale
    half_width = (len(indexes)-1) * spacing / 2
    x = min(max(center_x, half_width + radius), context.region.width-half_width-radius)
    y = min(max(bottom - 44 * ui_scale, radius), context.region.height - 42 * ui_scale)
    return [(index, x + (i-(len(indexes)-1)/2)*spacing, y) for i,index in enumerate(indexes)]


def draw_labels():
    context = bpy.context
    if not getattr(context.scene, 'sub_ik_view_buttons', False):
        return
    if not context.space_data or context.space_data.type != 'VIEW_3D' or not context.space_data.show_gizmo:
        return
    blf.size(0, 11 * context.preferences.system.ui_scale)
    blf.color(0, 0.95, 0.95, 0.95, 1)
    blf.enable(0, blf.SHADOW)
    blf.shadow(0, 3, 0, 0, 0, 0.8)
    for index, x, y in button_layout(context):
        label = ('Plant', 'Release', 'Switch FK')[index]
        width, _ = blf.dimensions(0, label)
        blf.position(0, x-width/2, y + 20 * context.preferences.system.ui_scale, 0)
        blf.draw(0, label)
    blf.disable(0, blf.SHADOW)


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
        positions = {index:(x,y) for index,x,y in button_layout(context)}
        for index, gizmo in enumerate(self.buttons):
            gizmo.hide = index not in positions
            if index in positions:
                x, y = positions[index]
                gizmo.matrix_basis = Matrix.Translation((x, y, 0))


_label_handler = None


def register():
    global _label_handler
    bpy.types.Scene.sub_ik_view_buttons = bpy.props.BoolProperty(
        name='IK Buttons in Viewport', default=True
    )
    bpy.utils.register_class(SUB_OP_ik_view_button)
    bpy.utils.register_class(SUB_GGT_ik_buttons)
    _label_handler = bpy.types.SpaceView3D.draw_handler_add(draw_labels, (), 'WINDOW', 'POST_PIXEL')


def unregister():
    global _label_handler
    if _label_handler is not None:
        bpy.types.SpaceView3D.draw_handler_remove(_label_handler, 'WINDOW')
        _label_handler = None
    bpy.utils.unregister_class(SUB_GGT_ik_buttons)
    bpy.utils.unregister_class(SUB_OP_ik_view_button)
    del bpy.types.Scene.sub_ik_view_buttons
