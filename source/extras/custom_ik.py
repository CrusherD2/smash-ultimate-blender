"""User-defined parent-chain IK and portable JSON presets."""

import json
from pathlib import Path

import bpy

from . import ik_channels
from .create_animation_rig import find_target_armature


def preset_dir():
    return Path(
        bpy.utils.user_resource('SCRIPTS', path='presets/smash_custom_ik', create=True)
    )


class SUB_PG_custom_ik(bpy.types.PropertyGroup):
    expanded: bpy.props.BoolProperty(default=False)
    name: bpy.props.StringProperty(name='Setup Name', default='Custom Limb')
    root: bpy.props.StringProperty(name='Root')
    middle: bpy.props.StringProperty(name='Bend Bone')
    end: bpy.props.StringProperty(name='End Bone')
    kind: bpy.props.EnumProperty(
        name='Switch Group',
        items=[('ARMS', 'Arms', ''), ('LEGS', 'Legs', '')],
    )


def definition(settings):
    return {
        key: getattr(settings, key) for key in ('name', 'root', 'middle', 'end', 'kind')
    }


def create_from_settings(context, obj, settings):
    names = ik_channels.chain_path(obj, settings.root, settings.end, settings.middle)
    if not names:
        raise ValueError(
            'Choose a root, bend and end on one parent chain, in that order'
        )
    try:
        records = json.loads(obj.get('sub_custom_ik_chains', '[]'))
    except (TypeError, ValueError):
        records = []
    for _, existing, _, _ in ik_channels.chains(obj):
        if set(names) & set(ik_channels.limb_path(obj, existing)):
            raise ValueError('This chain overlaps existing IK; remove that setup first')
    tag = bpy.path.clean_name(settings.name.strip())[:32] or 'Custom'
    target = 'SUB_Custom_' + tag + '_Target'
    pole = 'SUB_Custom_' + tag + '_Pole'
    if target in obj.data.bones or pole in obj.data.bones:
        raise ValueError(
            'Controls with this setup name already exist; choose another name'
        )
    record = definition(settings)
    record.update(target=target, pole=pole)
    records.append(record)
    obj['sub_custom_ik_chains'] = json.dumps(records)
    try:
        ik_channels.create_controls(
            context, obj, settings.kind, custom_only=True, custom_targets={target}
        )
    except Exception:
        records.pop()
        obj['sub_custom_ik_chains'] = json.dumps(records)
        raise
    from .create_animation_rig import _assign_shape, _widget_object

    for name, shape, tool in (
        (target, 'box', 'builtin.transform'),
        (pole, 'diamond', 'builtin.move'),
    ):
        pb = obj.pose.bones[name]
        pb.bone['sub_component_control'] = True
        pb.bone['sub_component_tool'] = tool
        _assign_shape(
            pb,
            _widget_object(context, shape),
            max(pb.length * 0.5, 0.1),
            'THEME01',
            False,
        )
    return record


class SUB_OP_custom_ik_create(bpy.types.Operator):
    bl_idname = 'sub.custom_ik_create'
    bl_label = 'Create Custom IK'
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        obj = find_target_armature(context)
        if obj is None:
            self.report({'ERROR'}, 'Select an armature')
            return {'CANCELLED'}
        try:
            create_from_settings(context, obj, context.scene.sub_custom_ik)
        except (ValueError, RuntimeError) as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}
        self.report({'INFO'}, 'Created custom IK; move its target to pose the chain')
        return {'FINISHED'}


class SUB_OP_custom_ik_pick(bpy.types.Operator):
    bl_idname = 'sub.custom_ik_pick'
    bl_label = 'Use Selected Bones'
    bl_options = {'REGISTER', 'UNDO'}
    field: bpy.props.EnumProperty(
        items=[
            ('CHAIN', 'Detect Chain', ''),
            ('root', 'Start', ''),
            ('middle', 'Bend', ''),
            ('end', 'End', ''),
        ]
    )

    def execute(self, context):
        obj = find_target_armature(context)
        if obj is None:
            return {'CANCELLED'}
        settings = context.scene.sub_custom_ik
        try:
            if self.field == 'CHAIN':
                from .custom_components import selected_chain
                from ..blender_compat import is_pose_bone_selected

                names = [pb.name for pb in obj.pose.bones if is_pose_bone_selected(pb)]
                settings.root, settings.middle, settings.end = selected_chain(
                    obj, names
                )
            else:
                active = obj.data.bones.active
                if active is None:
                    raise ValueError('Select an active bone in Pose Mode')
                setattr(settings, self.field, active.name)
            return {'FINISHED'}
        except ValueError as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}


class SUB_OP_custom_ik_save(bpy.types.Operator):
    bl_idname = 'sub.custom_ik_save'
    bl_label = 'Save Custom IK Preset'

    def execute(self, context):
        settings = context.scene.sub_custom_ik
        name = bpy.path.clean_name(settings.name.strip())[:64]
        if not name:
            self.report({'ERROR'}, 'Enter a setup name')
            return {'CANCELLED'}
        path = preset_dir() / (name + '.json')
        try:
            path.write_text(
                json.dumps({'version': 1, **definition(settings)}, indent=2),
                encoding='utf-8',
            )
        except OSError as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}
        self.report({'INFO'}, f'Saved {path}')
        return {'FINISHED'}


class SUB_OP_custom_ik_load(bpy.types.Operator):
    bl_idname = 'sub.custom_ik_load'
    bl_label = 'Load Custom IK Preset'
    bl_options = {'UNDO'}

    filename: bpy.props.StringProperty()

    def execute(self, context):
        try:
            if Path(self.filename).name != self.filename:
                raise ValueError('Invalid preset filename')
            data = json.loads(
                (preset_dir() / self.filename).read_text(encoding='utf-8')
            )
            if data.get('version') != 1 or data.get('kind') not in {'ARMS', 'LEGS'}:
                raise ValueError('Unsupported preset')
            if not all(
                isinstance(data.get(key), str)
                for key in ('name', 'root', 'middle', 'end')
            ):
                raise ValueError('Invalid bone names')
            for key in ('name', 'root', 'middle', 'end', 'kind'):
                setattr(context.scene.sub_custom_ik, key, data[key])
        except (OSError, ValueError, TypeError) as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}
        return {'FINISHED'}


class SUB_MT_custom_ik_presets(bpy.types.Menu):
    bl_label = 'Custom IK Presets'
    bl_idname = 'SUB_MT_custom_ik_presets'

    def draw(self, context):
        files = sorted(preset_dir().glob('*.json'))
        for path in files:
            self.layout.operator('sub.custom_ik_load', text=path.stem).filename = (
                path.name
            )
        if not files:
            self.layout.label(text='No saved presets')


def draw(layout, context, obj):
    settings = context.scene.sub_custom_ik
    box = layout.box()
    row = box.row()
    row.prop(
        settings,
        'expanded',
        text='Custom IK Bones',
        icon='TRIA_DOWN' if settings.expanded else 'TRIA_RIGHT',
        emboss=False,
    )
    if not settings.expanded:
        return
    box.prop(settings, 'name')
    if obj:
        box.label(text='Select the chain start and end in Pose Mode.')
        box.operator(
            'sub.custom_ik_pick',
            text='Detect from Selection',
            icon='RESTRICT_SELECT_OFF',
        ).field = 'CHAIN'
        for key, label in (
            ('root', '1. Chain Start'),
            ('middle', '2. Bend Joint'),
            ('end', '3. Chain End'),
        ):
            row = box.row(align=True)
            row.prop_search(settings, key, obj.data, 'bones', text=label)
            row.operator('sub.custom_ik_pick', text='', icon='EYEDROPPER').field = key
        path = ik_channels.chain_path(obj, settings.root, settings.end, settings.middle)
        box.label(
            text=(
                f'{len(path)} bones, including intermediate joints'
                if path
                else 'Choose a start, bend and end on one parent chain'
            ),
            icon='CHECKMARK' if path else 'INFO',
        )
    box.prop(settings, 'kind')
    box.operator('sub.custom_ik_create')
    row = box.row(align=True)
    row.operator('sub.custom_ik_save', text='Save Preset')
    row.menu('SUB_MT_custom_ik_presets', text='Load Preset')
    box.operator(
        'sub.custom_components', text='More Custom Components', icon='PREFERENCES'
    )


CLASSES = (
    SUB_PG_custom_ik,
    SUB_OP_custom_ik_create,
    SUB_OP_custom_ik_pick,
    SUB_OP_custom_ik_save,
    SUB_OP_custom_ik_load,
    SUB_MT_custom_ik_presets,
)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.Scene.sub_custom_ik = bpy.props.PointerProperty(type=SUB_PG_custom_ik)


def unregister():
    del bpy.types.Scene.sub_custom_ik
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
