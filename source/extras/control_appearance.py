"""Persistent widget overrides for standard, IK and component controls."""

import json
import bpy
from . import ik_channels
from .create_animation_rig import _widget_object, _assign_shape


def apply_override(pb):
    data = json.loads(pb.bone['sub_shape_override'])
    widget = bpy.data.objects.get(data['object'])
    if widget is None:
        widget = _widget_object(bpy.context, data.get('shape', 'circle'))
    pb.custom_shape = widget
    pb.use_custom_shape_bone_size = False
    pb.custom_shape_scale_xyz = data['scale']
    pb.custom_shape_translation = data['offset']
    pb.custom_shape_rotation_euler = data['rotation']


def remember(pb, shape='circle'):
    pb.bone['sub_shape_override'] = json.dumps(
        dict(
            object=pb.custom_shape.name if pb.custom_shape else '',
            shape=shape,
            scale=list(pb.custom_shape_scale_xyz),
            offset=list(pb.custom_shape_translation),
            rotation=list(pb.custom_shape_rotation_euler),
        )
    )


def controls(obj):
    result = {}
    for kind, names, target, pole in ik_channels.chains(obj):
        result[target] = (kind, target, 'box', 'builtin.transform')
        result[pole] = (kind, target, 'diamond', 'builtin.move')
        feet = ik_channels.foot_controls(names, obj)
        toe = ik_channels.toe_articulation(obj, names)
        for name in (list(feet[:2]) if feet else []) + ([toe[0]] if toe else []):
            result[name] = (kind, target, 'circle', 'builtin.rotate')
    return {n: info for n, info in result.items() if n in obj.pose.bones}


def style_ik_controls(context, obj):
    """Assign animation-rig widgets and pose tools to IK controls."""
    collection = obj.data.collections.get('IK Controls') or obj.data.collections.new(
        'IK Controls'
    )
    for name, (kind, target, shape, tool) in controls(obj).items():
        pb = obj.pose.bones[name]
        pb.bone['sub_ik_control_target'] = target
        pb.bone['sub_ik_control_kind'] = kind
        pb.bone['sub_component_control'] = True
        pb.bone['sub_component_tool'] = tool
        collection.assign(pb.bone)
        _assign_shape(
            pb, _widget_object(context, shape), max(pb.length, 0.15), 'THEME04', False
        )


class SUB_OP_control_shape(bpy.types.Operator):
    bl_idname = 'sub.control_shape'
    bl_label = 'Apply Control Shape'
    bl_options = {'REGISTER', 'UNDO'}
    action: bpy.props.EnumProperty(
        items=[(v, v, '') for v in ('APPLY', 'SAVE', 'EDIT', 'FINISH')]
    )

    def execute(self, context):
        from .custom_components import editor_armature
        from ..blender_compat import is_pose_bone_selected

        obj = editor_armature(context)
        if self.action == 'FINISH':
            widget = context.scene.sub_shape_edit_object
            active = context.view_layer.objects.active
            if active and active.mode != 'OBJECT':
                bpy.ops.object.mode_set(mode='OBJECT')
            if widget:
                widget.hide_set(True)
                widget.hide_select = True
            from .create_animation_rig import _activate_armature

            if obj:
                _activate_armature(context, obj)
                bpy.ops.object.mode_set(mode='POSE')
            context.scene.sub_shape_edit_object = None
            return {'FINISHED'}
        selected = (
            [p for p in obj.pose.bones if is_pose_bone_selected(p)] if obj else []
        )
        if not selected:
            self.report({'ERROR'}, 'Select one or more control bones in Pose Mode')
            return {'CANCELLED'}
        if self.action == 'EDIT':
            selected = (
                [obj.pose.bones[obj.data.bones.active.name]]
                if obj.data.bones.active
                else selected[:1]
            )
            if not selected[0].custom_shape:
                self.report({'ERROR'}, 'Apply a widget shape first')
                return {'CANCELLED'}
        for pb in selected:
            if self.action == 'APPLY':
                pb.custom_shape = _widget_object(
                    context, context.scene.sub_control_shape
                )
                pb.use_custom_shape_bone_size = False
                pb.custom_shape_scale_xyz = (context.scene.sub_control_size,) * 3
            elif self.action == 'EDIT' and pb.custom_shape:
                # Independent geometry: editing this mesh never changes other controls.
                widget = pb.custom_shape.copy()
                widget.data = pb.custom_shape.data.copy()
                widget.name = pb.name + ' Editable Shape'
                context.scene.collection.objects.link(widget)
                widget.hide_viewport = False
                widget.hide_select = False
                widget.hide_set(False)
                widget.hide_render = True
                pb.custom_shape = widget
            remember(pb, context.scene.sub_control_shape)
        if self.action == 'EDIT':
            context.scene.sub_shape_edit_object = widget
            if obj.mode != 'OBJECT':
                bpy.ops.object.mode_set(mode='OBJECT')
            for other in context.selected_objects:
                other.select_set(False)
            widget.select_set(True)
            context.view_layer.objects.active = widget
            bpy.ops.object.mode_set(mode='EDIT')
            self.report(
                {'INFO'},
                'Edit the widget vertices in the viewport, then choose Finish Widget Editing',
            )
        return {'FINISHED'}


def draw_appearance(layout, context, obj):
    layout.label(text='Selected Control Appearance')
    if context.scene.sub_shape_edit_object:
        layout.operator('sub.control_shape', text='Finish Widget Editing').action = (
            'FINISH'
        )
    layout.prop(context.scene, 'sub_ik_view_buttons')
    row = layout.row(align=True)
    row.prop(context.scene, 'sub_control_shape', text='Shape')
    row.prop(context.scene, 'sub_control_size', text='Size')
    layout.operator('sub.control_shape', text='Apply to Selected Controls').action = (
        'APPLY'
    )
    pb = (
        obj.pose.bones.get(obj.data.bones.active.name)
        if obj and obj.data.bones.active
        else None
    )
    if pb:
        layout.prop(pb, 'custom_shape', text='Custom Widget')
        layout.prop(pb, 'custom_shape_scale_xyz', text='Scale')
        layout.prop(pb, 'custom_shape_translation', text='Offset')
        layout.prop(pb, 'custom_shape_rotation_euler', text='Rotation')
        layout.operator(
            'sub.control_shape', text='Keep Appearance on Rebuild'
        ).action = 'SAVE'
        layout.operator(
            'sub.control_shape', text='Make Widget Mesh Editable'
        ).action = 'EDIT'


def register():
    from .custom_components import SHAPES

    bpy.utils.register_class(SUB_OP_control_shape)
    bpy.types.Scene.sub_shape_edit_object = bpy.props.PointerProperty(
        type=bpy.types.Object
    )
    bpy.types.Scene.sub_control_shape = bpy.props.EnumProperty(
        items=SHAPES, default='circle'
    )
    bpy.types.Scene.sub_control_size = bpy.props.FloatProperty(
        default=1, min=0.001, name='Size'
    )


def unregister():
    del bpy.types.Scene.sub_shape_edit_object
    del bpy.types.Scene.sub_control_size
    del bpy.types.Scene.sub_control_shape
    bpy.utils.unregister_class(SUB_OP_control_shape)
