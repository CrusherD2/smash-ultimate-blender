"""Repeatable, data-only custom rig components and versioned user presets."""

import json
import math
import uuid
from pathlib import Path
from types import SimpleNamespace

import bpy
from mathutils import Vector
from . import custom_ik, ik_channels
from .create_animation_rig import (
    find_target_armature,
    _activate_armature,
    _widget_object,
    _assign_shape,
)

TYPES = [
    (
        'EYES',
        'Bone Eyes (Captured Poses)',
        'Aim one or several eye bones at a shared target',
    ),
    ('LOOK_TARGET', 'Look Target', 'Aim bones at a movable target'),
    (
        'ISOLATED',
        'Isolated Bones',
        'Independent controls that stay still when Hip or Trans moves',
    ),
    ('IK', 'Custom IK Chain', 'A target and bend control for a connected bone chain'),
    ('MOUTH', 'Mouth Expressions', 'Capture and blend any number of mouth poses'),
    ('JAW', 'Jaw', 'Open and close selected jaw bones'),
    ('LIDS', 'Eyelids / Blink', 'One controller per saved eyelid pose'),
    ('CURL', 'Tail / Tentacle Curl', 'Distribute bending through a selected chain'),
    ('FAN', 'Wing / Feather Fan', 'Fan or fold selected bones with per-bone weights'),
    ('ROTATION', 'Rotation Slider', 'Drive any group of bones from one slider'),
]
AXES = [('X', 'Local X', ''), ('Y', 'Local Y', ''), ('Z', 'Local Z', '')]
FORMAT = 'smash_custom_components'
VERSION = 1
COLLECTION = 'Custom Components'
SHAPES = [
    (k, k.replace('_', ' ').title(), '')
    for k in (
        'circle',
        'square',
        'slider',
        'box',
        'diamond',
        'sphere',
        'crosshair',
        'arrow',
        'foot',
        'knob',
    )
]
EXTRA_DEFAULTS = {
    'control_offset': [0.0, 0.0, 0.0],
    'control_rotation': [0.0, 0.0, 0.0],
    'look_plane': 'XY',
    'show_orbit': True,
    'hide_controlled': False,
    'isolated_foot_controls': True,
    'shape': 'circle',
    'shape_scale': 1.0,
    'face_data': '{}',
    'pose_name': 'Closed',
    'pose_strength': 1.0,
    'pivot_at_cursor': False,
}


def preset_dir():
    return Path(
        bpy.utils.user_resource(
            'SCRIPTS', path='presets/smash_custom_components', create=True
        )
    )


def _update_orbit_visibility(component, context):
    obj = getattr(context.scene.sub_component_editor, 'armature', None)
    if obj is not None:
        from .face_components import set_orbit_visibility
        set_orbit_visibility(obj, component)


def _update_controlled_visibility(component, context):
    obj = context.scene.sub_component_editor.armature
    if obj:
        from .component_visibility import update
        update(obj, component)


class SUB_PG_component_bone(bpy.types.PropertyGroup):
    bone: bpy.props.StringProperty(name='Bone')
    weight: bpy.props.FloatProperty(
        name='Weight',
        default=1.0,
        min=-4.0,
        max=4.0,
        description='Negative values reverse this bone; zero leaves it still',
    )
    axis: bpy.props.EnumProperty(
        name='Axis', items=[('DEFAULT', 'Component Axis', ''), *AXES], default='DEFAULT'
    )


class SUB_PG_rig_component(bpy.types.PropertyGroup):
    isolated_foot_controls: bpy.props.BoolProperty(name='Foot Roll / Toe Controls', default=True)
    hide_controlled: bpy.props.BoolProperty(
        name='Hide Bones Controlled by Component', default=False,
        update=_update_controlled_visibility,
        description='Hide the original bones while keeping their custom controls visible',
    )
    control_offset: bpy.props.FloatVectorProperty(
        name='Control Position Offset', subtype='TRANSLATION', size=3
    )
    control_rotation: bpy.props.FloatVectorProperty(
        name='Control Orientation', subtype='EULER', size=3
    )
    look_plane: bpy.props.EnumProperty(
        name='Movement Plane',
        items=[
            ('XZ', 'Side / Up-Down (XZ)', ''),
            ('XY', 'Side / Front-Back (XY)', ''),
            ('YZ', 'Front / Up-Down (YZ)', ''),
        ],
        default='XZ',
    )
    show_orbit: bpy.props.BoolProperty(name='Show Rotation Controller', default=False, update=_update_orbit_visibility)
    shape: bpy.props.EnumProperty(name='Control Shape', items=SHAPES, default='circle')
    shape_scale: bpy.props.FloatProperty(
        name='Shape Size', default=1.0, min=0.01, max=100
    )
    face_data: bpy.props.StringProperty(default='{}')
    pose_name: bpy.props.StringProperty(name='Pose / Expression', default='Closed')
    pose_strength: bpy.props.FloatProperty(name='Save at Strength',default=1.0,min=0.01,max=1.0)
    pivot_at_cursor: bpy.props.BoolProperty(
        name='Place Eye Pivot at 3D Cursor', default=False
    )
    uid: bpy.props.StringProperty()
    name: bpy.props.StringProperty(name='Component Name', default='Component')
    kind: bpy.props.EnumProperty(name='Component', items=TYPES)
    bones: bpy.props.CollectionProperty(type=SUB_PG_component_bone)
    bone_index: bpy.props.IntProperty(default=0, min=0)
    parent: bpy.props.StringProperty(
        name='Control Parent',
        description='Optional; leave blank for an automatic parent outside the driven bones',
    )
    axis: bpy.props.EnumProperty(name='Rotation Axis', items=AXES, default='X')
    aim_axis: bpy.props.EnumProperty(
        name='Eye Forward Axis',
        items=[
            (a, a.replace('NEG_', '-'), '')
            for a in ('X', 'Y', 'Z', 'NEG_X', 'NEG_Y', 'NEG_Z')
        ],
        default='Y',
    )
    angle: bpy.props.FloatProperty(
        name='Maximum Rotation',
        default=math.radians(60),
        min=0,
        max=math.pi,
        subtype='ANGLE',
    )
    distance: bpy.props.FloatProperty(
        name='Control Distance',
        default=1.0,
        min=0.05,
        max=20,
        description='Initial placement distance relative to the selected bones; existing keyed controls keep their rest placement',
    )
    root: bpy.props.StringProperty(name='Chain Start')
    middle: bpy.props.StringProperty(name='Bend Joint')
    end: bpy.props.StringProperty(name='Chain End')
    switch_group: bpy.props.EnumProperty(
        name='IK/FK Switch',
        items=[('ARMS', 'Arms', ''), ('LEGS', 'Legs', '')],
        default='ARMS',
    )


class SUB_PG_component_editor(bpy.types.PropertyGroup):
    is_open: bpy.props.BoolProperty(name="Custom Components", default=False)
    show_placement: bpy.props.BoolProperty(
        name='Advanced Placement & Behavior', default=False
    )
    show_appearance: bpy.props.BoolProperty(
        name='Selected Control Appearance', default=False
    )
    show_pose_manage: bpy.props.BoolProperty(name='Manage Saved Poses', default=False)
    show_pose_preview: bpy.props.BoolProperty(name='Preview & Animate', default=True)

    page: bpy.props.EnumProperty(
        name='Step',
        items=[
            ('BONES', '1  Bones', 'Choose a component and its bones'),
            ('CONTROLS', '2  Controls', 'Build and customize handles'),
            ('ANIMATE', '3  Animate', 'Capture poses and animate'),
        ],
        default='BONES',
    )
    appearances: bpy.props.StringProperty(default='{}')
    auto_save_appearance: bpy.props.BoolProperty(
        name='Auto-save Appearance', default=True
    )
    appearance_status: bpy.props.StringProperty()

    armature: bpy.props.PointerProperty(
        type=bpy.types.Object, poll=lambda self, obj: obj.type == 'ARMATURE'
    )
    preset_name: bpy.props.StringProperty(name='Preset Name', default='Custom Rig')
    components: bpy.props.CollectionProperty(type=SUB_PG_rig_component)
    active_index: bpy.props.IntProperty(default=0, min=0)
    save_on_build: bpy.props.BoolProperty(
        name='Save Preset When Building', default=True
    )


def active_component(context):
    editor = context.scene.sub_component_editor
    return (
        editor.components[editor.active_index]
        if 0 <= editor.active_index < len(editor.components)
        else None
    )


def editor_armature(context):
    return context.scene.sub_component_editor.armature or find_target_armature(context)


def serialize(component):
    fields = (
        *EXTRA_DEFAULTS,
        'uid',
        'name',
        'kind',
        'parent',
        'axis',
        'aim_axis',
        'angle',
        'distance',
        'root',
        'middle',
        'end',
        'switch_group',
    )
    return {
        **{
            name: (
                list(getattr(component, name))
                if name in {'control_offset', 'control_rotation'}
                else getattr(component, name)
            )
            for name in fields
        },
        'bones': [
            {'bone': b.bone, 'weight': b.weight, 'axis': b.axis}
            for b in component.bones
        ],
    }


def validate_preset(payload):
    if (
        not isinstance(payload, dict)
        or payload.get('format') != FORMAT
        or payload.get('version') != VERSION
    ):
        raise ValueError('Unsupported component preset')
    if not isinstance(payload.get('name'), str) or not isinstance(
        payload.get('components'), list
    ):
        raise ValueError('Invalid component preset')
    allowed = {v[0] for v in TYPES}
    fields = {
        'uid',
        'name',
        'kind',
        'parent',
        'axis',
        'aim_axis',
        'angle',
        'distance',
        'root',
        'middle',
        'end',
        'switch_group',
        'bones',
    }
    from .component_appearance_presets import validate as validate_appearances

    validate_appearances(payload.get('appearances', {}))
    seen = set()
    for item in payload['components']:
        if not isinstance(item, dict) or item.get('kind') not in allowed:
            raise ValueError('Unknown component type')
        for key, default in EXTRA_DEFAULTS.items():
            item.setdefault(key, default)
        if set(item) != fields | set(EXTRA_DEFAULTS):
            raise ValueError('Invalid component fields')
        if (
            item['shape'] not in {v[0] for v in SHAPES}
            or not isinstance(item['shape_scale'], (int, float))
            or not math.isfinite(item['shape_scale'])
            or item['shape_scale'] <= 0
        ):
            raise ValueError('Invalid control shape')
        for key in ('control_offset', 'control_rotation'):
            if (
                not isinstance(item[key], (list, tuple))
                or len(item[key]) != 3
                or any(
                    not isinstance(v, (int, float)) or not math.isfinite(v)
                    for v in item[key]
                )
            ):
                raise ValueError('Invalid control placement')
        if not isinstance(item['isolated_foot_controls'], bool):
            raise ValueError('Invalid isolated foot controls')
        if not isinstance(item['hide_controlled'], bool):
            raise ValueError('Invalid controlled-bone visibility')
        if item['look_plane'] not in {'XY', 'XZ', 'YZ'} or not isinstance(
            item['show_orbit'], bool
        ):
            raise ValueError('Invalid eye control settings')
        from .face_components import validate_data

        validate_data(item['face_data'])
        if not isinstance(item['pose_name'], str) or not isinstance(
            item['pivot_at_cursor'], bool
        ):
            raise ValueError('Invalid facial settings')
        for field in ('uid', 'name', 'parent', 'root', 'middle', 'end'):
            if not isinstance(item.get(field), str):
                raise ValueError('Invalid component names')
        if (
            len(item['uid']) != 32
            or any(ch not in '0123456789abcdef' for ch in item['uid'])
            or item['uid'] in seen
        ):
            raise ValueError('Duplicate or missing component ID')
        seen.add(item['uid'])
        if (
            item.get('axis') not in {'X', 'Y', 'Z'}
            or item.get('aim_axis') not in {'X', 'Y', 'Z', 'NEG_X', 'NEG_Y', 'NEG_Z'}
            or item.get('switch_group') not in {'ARMS', 'LEGS'}
        ):
            raise ValueError('Invalid component axis or switch group')
        for field in ('angle', 'distance'):
            if not isinstance(item.get(field), (int, float)) or not math.isfinite(
                item[field]
            ):
                raise ValueError('Invalid component range')
        if not isinstance(item.get('bones'), list):
            raise ValueError('Missing bone assignments')
        for bone in item['bones']:
            if (
                not isinstance(bone, dict)
                or not isinstance(bone.get('bone'), str)
                or bone.get('axis') not in {'DEFAULT', 'X', 'Y', 'Z'}
            ):
                raise ValueError('Invalid bone assignment')
            if not isinstance(bone.get('weight'), (int, float)) or not math.isfinite(
                bone['weight']
            ):
                raise ValueError('Invalid bone weight')
    return payload


def save_preset(editor):
    name = bpy.path.clean_name(editor.preset_name.strip())[:80]
    if not name:
        raise ValueError('Enter a preset name')
    from .component_appearance_presets import capture

    payload = {
        'appearances': capture(editor),
        'format': FORMAT,
        'version': VERSION,
        'name': editor.preset_name,
        'components': [serialize(c) for c in editor.components],
    }
    validate_preset(payload)
    path = preset_dir() / (name + '.json')
    temporary = path.with_suffix('.json.tmp')
    temporary.write_text(json.dumps(payload, indent=2), encoding='utf-8')
    temporary.replace(path)
    return path


def load_preset(editor, payload):
    validate_preset(payload)  # Validate completely before replacing the editor.
    editor.components.clear()
    editor.preset_name = payload['name']
    editor.appearances = json.dumps(payload.get('appearances', {}))
    editor.appearance_status = ''
    editor.page = 'BONES'
    for record in payload['components']:
        c = editor.components.add()
        for name, value in record.items():
            if name != 'bones':
                setattr(c, name, value)
        for record_bone in record['bones']:
            bone = c.bones.add()
            for name, value in record_bone.items():
                setattr(bone, name, value)
    editor.active_index = 0


def selected_chain(obj, selected):
    names = set(selected)
    if len(names) < 2:
        raise ValueError('Select the chain start and end, or all bones in the chain')
    ordered = sorted(names, key=lambda n: len(obj.data.bones[n].parent_recursive))
    path = ik_channels.chain_path(obj, ordered[0], ordered[-1])
    if not path or not names.issubset(path):
        raise ValueError(
            'Selection must lie on one parent chain with at least three bones'
        )
    return path[0], path[len(path) // 2], path[-1]


def validate_component(obj, c):
    if not c.name.strip():
        raise ValueError('Name each component')
    if c.kind == 'IK':
        path = ik_channels.chain_path(obj, c.root, c.end, c.middle)
        if not path:
            raise ValueError(
                f'{c.name}: choose a start, bend and end on one parent chain'
            )
        return list(path)
    names = [b.bone for b in c.bones]
    if not names or any(not n or n not in obj.data.bones for n in names):
        raise ValueError(f'{c.name}: assign existing bones to every row')
    if len(names) != len(set(names)):
        raise ValueError(f'{c.name}: each bone can appear only once')
    if c.kind != 'ISOLATED' and c.parent and c.parent not in obj.data.bones:
        raise ValueError(f'{c.name}: control parent does not exist')
    if any(n.startswith('BL_CC_') for n in names):
        raise ValueError('Choose skeleton bones, not component controls')
    return names


def _control_parent(obj, c, names):
    parent = (
        obj.data.bones.get(c.parent) if c.parent else obj.data.bones[names[0]].parent
    )
    while parent and (
        parent.name in names or any(p.name in names for p in parent.parent_recursive)
    ):
        if c.parent:
            raise ValueError(
                f'{c.name}: the control parent must be outside the driven hierarchy'
            )
        parent = parent.parent
    return parent.name if parent else None


def validate_build(obj, components):
    """Catch incompatible setups before the first rig mutation."""
    records = json.loads(obj.get('sub_custom_ik_chains', '[]'))
    claimed = [
        (None, set(ik_channels.limb_path(obj, names)))
        for _, names, target, _ in ik_channels.chains(obj)
        if not any(r.get('component_id') and r.get('target') == target for r in records)
    ]
    claimed.extend(
        (
            r.get('component_id'),
            set(ik_channels.chain_path(obj, r['root'], r['end'], r['middle'])),
        )
        for r in records
        if r.get('component_id')
    )
    new_names = set()
    for c in components:
        names = validate_component(obj, c)
        built_ik = next((r for r in records if r.get('component_id') == c.uid), None)
        built_control = obj.data.bones.get(control_name(obj, c))
        if built_control and built_control.get('sub_component_kind', c.kind) != c.kind:
            raise ValueError(
                f'{c.name}: remove the built component before changing its type'
            )
        if (built_ik and c.kind != 'IK') or (built_control and c.kind == 'IK'):
            raise ValueError(
                f'{c.name}: remove the built component before switching between IK and other types'
            )
        if c.kind == 'ISOLATED':
            continue
        if c.kind != 'IK':
            _control_parent(obj, c, names)
            existing = obj.data.bones.get(control_name(obj, c))
            if existing:
                requested = _control_parent(obj, c, names)
                current = existing.parent.name if existing.parent else None
                if requested != current:
                    raise ValueError(
                        f'{c.name}: an existing keyed control keeps its parent; create a new component to change it'
                    )
            continue
        previous = next((r for r in records if r.get('component_id') == c.uid), None)
        if previous and tuple(
            previous[k] for k in ('root', 'middle', 'end', 'kind')
        ) != (c.root, c.middle, c.end, c.switch_group):
            raise ValueError(
                f'{c.name}: bake/remove existing IK before changing its chain'
            )
        if any(owner != c.uid and set(names) & path for owner, path in claimed):
            raise ValueError(f'{c.name}: IK overlaps another chain')
        claimed.append((c.uid, set(names)))
        if not previous:
            target = (
                'SUB_Custom_'
                + (bpy.path.clean_name(c.name.strip())[:32] or 'Custom')
                + '_Target'
            )
            if target in obj.data.bones or target in new_names:
                raise ValueError(f'{c.name}: choose a unique IK component name')
            new_names.add(target)


def control_name(obj, c):
    existing = next(
        (b.name for b in obj.data.bones if b.get('sub_component_id') == c.uid), None
    )
    # Accept presets built by the early UUID-only naming version too.
    return existing or (
        'BL_CC_' + c.uid
        if 'BL_CC_' + c.uid in obj.data.bones
        else 'BL_CC_'
        + (bpy.path.clean_name(c.name)[:28] or 'Component')
        + '_'
        + c.uid[:8]
    )


def build_component(context, obj, c):
    result = _build_component(context, obj, c)
    from .component_visibility import update
    update(obj, c)
    return result


def _build_component(context, obj, c):
    names = validate_component(obj, c)
    if not c.uid:
        c.uid = uuid.uuid4().hex
    if c.kind == 'IK':
        records = json.loads(obj.get('sub_custom_ik_chains', '[]'))
        previous = next((r for r in records if r.get('component_id') == c.uid), None)
        if previous:
            if tuple(previous[k] for k in ('root', 'middle', 'end', 'kind')) != (
                c.root,
                c.middle,
                c.end,
                c.switch_group,
            ):
                raise ValueError(
                    f'{c.name}: existing IK chain differs; bake/remove it before changing its bones'
                )
            pb = obj.pose.bones[previous['target']]
            _assign_shape(
                pb,
                _widget_object(context, c.shape),
                max(pb.length, 0.1) * c.shape_scale,
                'THEME04',
                False,
            )
            return previous['target']
        record = custom_ik.create_from_settings(
            context,
            obj,
            SimpleNamespace(
                name=c.name,
                root=c.root,
                middle=c.middle,
                end=c.end,
                kind=c.switch_group,
            ),
        )
        records = json.loads(obj.get('sub_custom_ik_chains', '[]'))
        records[-1]['component_id'] = c.uid
        obj['sub_custom_ik_chains'] = json.dumps(records)
        pb = obj.pose.bones[record['target']]
        _assign_shape(
            pb,
            _widget_object(context, c.shape),
            max(pb.length, 0.1) * c.shape_scale,
            'THEME04',
            False,
        )
        return record['target']
    if c.kind == 'ISOLATED':
        from .component_workflow import build_isolated

        return build_isolated(context, obj, c)
    if c.kind in {'EYES', 'LIDS', 'MOUTH'}:
        from .face_components import build_face

        return build_face(context, obj, c)
    parent = _control_parent(obj, c, names)
    target_name = control_name(obj, c)
    if target_name in names:
        raise ValueError('A component cannot drive its own control')
    prefix = 'SUB Component ' + c.uid
    # Updating an existing component preserves the controller's rest frame/keys.
    fresh = target_name not in obj.data.bones
    if fresh:
        source = obj.data.bones[names[0]]
        center = sum((obj.data.bones[n].head_local for n in names), Vector()) / len(
            names
        )
        size = max(sum(obj.data.bones[n].length for n in names) / len(names), 0.1)
        direction = (
            source.matrix_local.to_3x3().col['XYZ'.index(c.aim_axis[-1])].normalized()
        )
        if c.aim_axis.startswith('NEG_'):
            direction = -direction
        bpy.ops.object.mode_set(mode='EDIT')
        control = obj.data.edit_bones.new(target_name)
        control.head = (
            center + direction * size * c.distance
            if c.kind == 'LOOK_TARGET'
            else center + Vector((0, 0, size * c.distance))
        )
        control.tail = control.head + Vector((0, size * 0.3, 0))
        control.parent = obj.data.edit_bones.get(parent) if parent else None
        control.use_deform = False
        control['sub_component_control'] = True
        control['sub_component_id'] = c.uid
        control['sub_component_travel'] = size * 0.5
        bpy.ops.object.mode_set(mode='POSE')
    pb = obj.pose.bones[target_name]
    pb.bone['sub_component_kind'] = c.kind
    pb['component_name'] = c.name
    collection = obj.data.collections.get(COLLECTION) or obj.data.collections.new(
        COLLECTION
    )
    collection.assign(pb.bone)
    collection.is_visible = True
    _assign_shape(
        pb,
        _widget_object(context, c.shape),
        max(pb.length, 0.1) * c.shape_scale,
        'THEME04',
        False,
    )
    for bone in obj.pose.bones:
        for con in list(bone.constraints):
            if con.name.startswith(prefix):
                bone.constraints.remove(con)
    for con in list(pb.constraints):
        if con.name == 'Component Slider Range':
            pb.constraints.remove(con)
    half = float(pb.bone.get('sub_component_travel', 1.0))
    if c.kind == 'LOOK_TARGET':
        pb.lock_location = (False, False, True)
        pb.lock_rotation = pb.lock_scale = (True, True, True)
    else:
        pb.lock_location = (True, False, True)
        pb.lock_rotation = pb.lock_scale = (True, True, True)
        limit = pb.constraints.new('LIMIT_LOCATION')
        limit.name = 'Component Slider Range'
        limit.owner_space = 'LOCAL'
        limit.use_min_y = limit.use_max_y = True
        limit.min_y, limit.max_y = -half, half
    for assignment in c.bones:
        bone = obj.pose.bones[assignment.bone]
        if c.kind == 'LOOK_TARGET':
            con = bone.constraints.new('DAMPED_TRACK')
            con.name = prefix
            con.target, con.subtarget = obj, target_name
            con.track_axis = 'TRACK_' + c.aim_axis
            con.influence = min(abs(assignment.weight), 1.0)
        else:
            from .finger_sliders import _ensure_finger_constraint

            axis = c.axis if assignment.axis == 'DEFAULT' else assignment.axis
            _ensure_finger_constraint(
                bone,
                prefix,
                obj,
                target_name,
                half,
                'XYZ'.index(axis),
                c.angle * assignment.weight,
            )
    from .component_workflow import place_controls

    place_controls(context, obj, c, [target_name], plane=c.kind == 'LOOK_TARGET')
    context.view_layer.update()
    return target_name


def remove_component(context, obj, c):
    """Remove only this component's generated rig, preserving skeleton keys."""
    from .component_visibility import remove
    remove(obj, c.uid)
    _activate_armature(context, obj)
    if c.kind == 'IK':
        records = json.loads(obj.get('sub_custom_ik_chains', '[]'))
        target = next(
            (r['target'] for r in records if r.get('component_id') == c.uid), None
        )
        if target:
            ik_channels.remove(context, obj, c.switch_group, targets={target})
        return
    from .face_components import remove_face_helpers

    remove_face_helpers(context, obj, c)
    name = control_name(obj, c)
    prefix = 'SUB Component ' + c.uid
    for pb in obj.pose.bones:
        for con in list(pb.constraints):
            if con.name.startswith(prefix):
                pb.constraints.remove(con)
    if name in obj.pose.bones:
        from .create_animation_rig import _iter_armature_actions
        from ..anim.fcurve_compat import get_all_action_fcurves, remove_fcurve

        path = obj.pose.bones[name].path_from_id() + '.'
        for action in _iter_armature_actions(obj):
            for fc in list(get_all_action_fcurves(action, id_type='OBJECT')):
                if fc.data_path.startswith(path):
                    remove_fcurve(action, fc, id_type='OBJECT')
        bpy.ops.object.mode_set(mode='EDIT')
        obj.data.edit_bones.remove(obj.data.edit_bones[name])
        bpy.ops.object.mode_set(mode='POSE')


class SUB_OP_component_remove(bpy.types.Operator):
    bl_idname = 'sub.component_remove'
    bl_label = 'Remove Built Component'
    bl_description = 'Remove only the active component and its controller keys; original bone animation stays'
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        c = active_component(context)
        obj = editor_armature(context)
        if c is None or obj is None:
            return {'CANCELLED'}
        from . import create_animation_rig as rig, anim_layers_compat

        with rig.defer_pose_tool_updates(), rig._disable_autokey(
            context
        ), anim_layers_compat.anim_layers_paused():
            remove_component(context, obj, c)
        records = json.loads(obj.get('sub_custom_components', '[]'))
        obj['sub_custom_components'] = json.dumps(
            [r for r in records if r.get('uid') != c.uid]
        )
        self.report(
            {'INFO'},
            'Removed the built component; its preset definition is kept for reuse',
        )
        return {'FINISHED'}


class SUB_UL_components(bpy.types.UIList):
    def draw_item(
        self, context, layout, data, item, icon, active_data, active_propname, index
    ):
        row = layout.row(align=True)
        row.prop(
            item,
            'name',
            text='',
            emboss=False,
            icon='CONSTRAINT_BONE' if item.kind == 'IK' else 'BONE_DATA',
        )
        row.label(text=dict((a, b) for a, b, _ in TYPES).get(item.kind, ''))


class SUB_UL_component_bones(bpy.types.UIList):
    def draw_item(
        self, context, layout, data, item, icon, active_data, active_propname, index
    ):
        obj = editor_armature(context)
        c = active_component(context)
        row = layout.row(align=True)
        if obj:
            row.prop_search(item, 'bone', obj.data, 'bones', text='')
        if (
            c
            and context.scene.sub_component_editor.page == 'CONTROLS'
            and c.kind not in {'EYES', 'LIDS', 'MOUTH', 'ISOLATED', 'LOOK_TARGET'}
        ):
            row.prop(item, 'weight', text='Weight')
        if (
            c
            and context.scene.sub_component_editor.page == 'CONTROLS'
            and c.kind not in {'EYES', 'LIDS', 'MOUTH', 'ISOLATED', 'LOOK_TARGET'}
        ):
            row.prop(item, 'axis', text='')


class SUB_OP_component_edit(bpy.types.Operator):
    bl_idname = 'sub.component_edit'
    bl_label = 'Edit Component'
    bl_options = {'REGISTER', 'UNDO'}
    action: bpy.props.EnumProperty(
        items=[
            (v, v, '')
            for v in (
                'ADD',
                'REMOVE',
                'BONE_ADD',
                'BONE_REMOVE',
                'SELECTED',
                'CHAIN',
                'PICK_ROOT',
                'PICK_MIDDLE',
                'PICK_END',
                'WEIGHTS',
                'SELECT_CONTROL',
            )
        ]
    )
    index: bpy.props.IntProperty(default=0)

    def execute(self, context):
        editor = context.scene.sub_component_editor
        c = active_component(context)
        obj = editor_armature(context)
        try:
            if self.action == 'ADD':
                c = editor.components.add()
                c.uid = uuid.uuid4().hex
                c.name = f'Component {len(editor.components)}'
                editor.active_index = len(editor.components) - 1
                editor.page = 'BONES'
            elif self.action == 'REMOVE' and c:
                editor.components.remove(editor.active_index)
                editor.active_index = max(0, editor.active_index - 1)
            elif c:
                if self.action == 'BONE_ADD':
                    c.bones.add()
                elif self.action == 'BONE_REMOVE' and self.index < len(c.bones):
                    c.bones.remove(self.index)
                elif self.action in {'SELECTED', 'CHAIN'}:
                    from ..blender_compat import is_pose_bone_selected

                    if not obj:
                        raise ValueError('Select an armature')
                    selected = [
                        pb.name for pb in obj.pose.bones if is_pose_bone_selected(pb)
                    ]
                    if not selected:
                        raise ValueError(
                            'Select bones in the viewport first, then reopen this editor'
                        )
                    if self.action == 'CHAIN':
                        c.root, c.middle, c.end = selected_chain(obj, selected)
                    else:
                        existing = {b.bone for b in c.bones}
                        for name in sorted(
                            selected,
                            key=lambda n: (len(obj.data.bones[n].parent_recursive), n),
                        ):
                            if name not in existing:
                                c.bones.add().bone = name
                elif self.action.startswith('PICK_'):
                    bone = obj.data.bones.active if obj else None
                    if bone is None:
                        raise ValueError('Select an active bone in Pose Mode')
                    setattr(c, self.action[5:].lower(), bone.name)
                elif self.action == 'SELECT_CONTROL':
                    from ..blender_compat import set_pose_bone_select

                    target = control_name(obj, c)
                    if c.kind == 'EYES' and target + '_Look' in obj.pose.bones:
                        target += '_Look'
                    if c.kind == 'IK':
                        records = json.loads(obj.get('sub_custom_ik_chains', '[]'))
                        target = next(
                            (
                                r['target']
                                for r in records
                                if r.get('component_id') == c.uid
                            ),
                            target,
                        )
                    if target not in obj.pose.bones:
                        raise ValueError('Build this component first')
                    _activate_armature(context, obj)
                    for pb in obj.pose.bones:
                        set_pose_bone_select(pb, pb.name == target)
                    obj.data.bones.active = obj.data.bones[target]
                elif self.action == 'WEIGHTS':
                    count = len(c.bones)
                    for i, b in enumerate(c.bones):
                        b.weight = (
                            (-1 + 2 * i / (count - 1))
                            if c.kind == 'FAN' and count > 1
                            else (i + 1) / max(count, 1)
                        )
            if context.area:
                context.area.tag_redraw()
            return {'FINISHED'}
        except ValueError as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}


class SUB_OP_component_preset(bpy.types.Operator):
    bl_idname = 'sub.component_preset'
    bl_label = 'Component Preset'
    bl_options = {'REGISTER', 'UNDO'}
    action: bpy.props.EnumProperty(items=[('SAVE', 'Save', ''), ('LOAD', 'Load', '')])
    filename: bpy.props.StringProperty()

    def execute(self, context):
        try:
            editor = context.scene.sub_component_editor
            if self.action == 'SAVE':
                path = save_preset(editor)
                self.report({'INFO'}, f'Saved {path}')
            else:
                if Path(
                    self.filename
                ).name != self.filename or not self.filename.endswith('.json'):
                    raise ValueError('Invalid preset filename')
                load_preset(
                    editor,
                    json.loads(
                        (preset_dir() / self.filename).read_text(encoding='utf-8')
                    ),
                )
                if editor.armature:
                    from .component_appearance_presets import apply

                    apply(context, editor.armature, json.loads(editor.appearances))
            return {'FINISHED'}
        except (OSError, ValueError, TypeError, KeyError) as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}


class SUB_MT_component_presets(bpy.types.Menu):
    bl_idname = 'SUB_MT_component_presets'
    bl_label = 'Custom Component Presets'

    def draw(self, context):
        files = sorted(preset_dir().glob('*.json'))
        for path in files:
            op = self.layout.operator('sub.component_preset', text=path.stem)
            op.action, op.filename = 'LOAD', path.name
        if not files:
            self.layout.label(text='No saved presets')


class SUB_OP_component_build(bpy.types.Operator):
    bl_idname = 'sub.component_build'
    bl_label = 'Build Custom Components'
    active_only: bpy.props.BoolProperty(default=False)
    advance: bpy.props.BoolProperty(default=False)
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        editor = context.scene.sub_component_editor
        obj = editor_armature(context)
        if obj is None or not editor.components:
            self.report({'ERROR'}, 'Select an armature and add a component')
            return {'CANCELLED'}
        try:
            # Validate every assignment before building anything.
            components = (
                [active_component(context)]
                if self.active_only
                else list(editor.components)
            )
            validate_build(obj, components)
            from . import create_animation_rig as rig, anim_layers_compat

            with rig.defer_pose_tool_updates(), rig._disable_autokey(
                context
            ), anim_layers_compat.anim_layers_paused():
                _activate_armature(context, obj)
                for c in components:
                    build_component(context, obj, c)
                from .component_appearance_presets import apply

                apply(context, obj, json.loads(editor.appearances))
            updated = {c.uid for c in components}
            existing = json.loads(obj.get('sub_custom_components', '[]'))
            obj['sub_custom_components'] = json.dumps(
                [r for r in existing if r['uid'] not in updated]
                + [serialize(c) for c in components]
            )
            if self.advance:
                editor.page = 'ANIMATE'
            if editor.save_on_build:
                save_preset(editor)
            self.report(
                {'INFO'},
                f'Built {len(components)} components'
                + (' and saved preset' if editor.save_on_build else ''),
            )
            return {'FINISHED'}
        except (OSError, ValueError, RuntimeError) as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}


class SUB_OP_component_step(bpy.types.Operator):
    bl_idname = 'sub.component_step'
    bl_label = 'Next Setup Step'
    page: bpy.props.StringProperty()

    def execute(self, context):
        context.scene.sub_component_editor.page = self.page
        return {'FINISHED'}


def disclosure(layout, editor, property_name, label):
    # Explicit state keeps Properties search from expanding every advanced panel.
    expanded = getattr(editor, property_name)
    row = layout.row()
    row.prop(
        editor,
        property_name,
        text=label,
        icon='TRIA_DOWN' if expanded else 'TRIA_RIGHT',
        emboss=False,
    )
    return layout.column() if expanded else None


def draw_editor(layout, context):
    editor = context.scene.sub_component_editor
    obj = editor_armature(context)
    layout.use_property_split = False
    row = layout.row(align=True)
    layout.prop(editor, 'preset_name', text='Preset')
    row.menu('SUB_MT_component_presets', text='Load', icon='FILE_FOLDER')
    row.operator(
        'sub.component_preset', text='Save', icon='FILE_TICK'
    ).action = 'SAVE'
    row = layout.row()
    row.template_list(
        'SUB_UL_components', '', editor, 'components', editor, 'active_index', rows=3
    )
    buttons = row.column(align=True)
    buttons.operator('sub.component_edit', text='', icon='ADD').action = 'ADD'
    buttons.operator('sub.component_edit', text='', icon='REMOVE').action = 'REMOVE'
    c = active_component(context)
    if c is None:
        layout.label(text='Add a component to get started.', icon='INFO')
        layout.operator(
            'sub.component_edit', text='Add Component', icon='ADD'
        ).action = 'ADD'
        return
    layout.prop(editor, 'page', expand=True)
    layout.separator()
    if editor.page == 'BONES':
        layout.prop(editor, 'armature', text='Rig')
        layout.prop(c, 'name', text='Name')
        layout.prop(c, 'kind', text='Component Type')
        if obj is None:
            layout.label(text='Choose the armature to continue.', icon='INFO')
            return
        if c.kind == 'IK':
            layout.label(text='Select start and end bones.')
            layout.operator(
                'sub.component_edit', text='Use Selected Chain', icon='EYEDROPPER'
            ).action = 'CHAIN'
            for field, label in (('root', 'Start'), ('middle', 'Bend'), ('end', 'End')):
                row = layout.row(align=True)
                row.prop_search(c, field, obj.data, 'bones', text=label)
                row.operator(
                    'sub.component_edit', text='', icon='EYEDROPPER'
                ).action = ('PICK_' + field.upper())
        else:
            layout.label(text='Choose bones to control:')
            row = layout.row(align=True)
            row.operator(
                'sub.component_edit', text='Use Selected', icon='EYEDROPPER'
            ).action = 'SELECTED'
            row.operator(
                'sub.component_edit', text='Add Bone', icon='ADD'
            ).action = 'BONE_ADD'
            row = layout.row()
            row.template_list(
                'SUB_UL_component_bones', '', c, 'bones', c, 'bone_index', rows=3
            )
            op = row.column().operator('sub.component_edit', text='', icon='REMOVE')
            op.action, op.index = 'BONE_REMOVE', c.bone_index
        valid = False
        try:
            names = validate_component(obj, c)
            valid = True
            layout.label(text=f'{len(names)} bones assigned', icon='CHECKMARK')
        except ValueError:
            layout.label(text='Assign the bones above to continue.', icon='INFO')
        row = layout.row()
        row.enabled = valid
        row.operator(
            'sub.component_step', text='Next: Create Controls', icon='FORWARD'
        ).page = 'CONTROLS'
        return
    if obj is None:
        layout.label(text='Choose a rig in the Bones step.', icon='INFO')
        return
    if editor.page == 'CONTROLS':
        layout.label(text=c.name, icon='BONE_DATA')
        layout.prop(c, 'shape', text='Shape')
        layout.prop(c, 'shape_scale', text='Size')
        layout.prop(c, 'hide_controlled', text='Hide Controlled Bones')
        if c.kind == 'ISOLATED':
            layout.prop(c, 'isolated_foot_controls')
        if c.kind in {'EYES', 'LOOK_TARGET'}:
            layout.prop(c, 'look_plane')
            layout.prop(c, 'aim_axis')
        if c.kind == 'EYES':
            layout.prop(c, 'show_orbit')
        elif c.kind == 'IK':
            layout.prop(c, 'switch_group')
        elif c.kind not in {'LIDS', 'MOUTH', 'LOOK_TARGET', 'ISOLATED'}:
            row = layout.row(align=True)
            row.prop(c, 'axis')
            row.prop(c, 'angle')
        body = disclosure(
            layout, editor, 'show_placement', 'Placement & Behavior'
        )
        if body is not None:
            if c.kind not in {'ISOLATED', 'IK'}:
                body.prop_search(c, 'parent', obj.data, 'bones')
                body.prop(c, 'distance')
            if c.kind != 'IK':
                body.prop(c, 'control_offset')
                body.prop(c, 'control_rotation')
            if c.kind == 'EYES':
                body.prop(c, 'pivot_at_cursor')
            if c.kind not in {'EYES', 'LIDS', 'MOUTH', 'ISOLATED', 'LOOK_TARGET', 'IK'}:
                body.template_list(
                    'SUB_UL_component_bones',
                    'weights',
                    c,
                    'bones',
                    c,
                    'bone_index',
                    rows=3,
                )
            if c.kind in {'CURL', 'FAN'}:
                body.operator(
                    'sub.component_edit', text='Distribute Bone Weights'
                ).action = 'WEIGHTS'
            body.prop(editor, 'save_on_build')
        op = layout.operator(
            'sub.component_build', text='Build & Continue', icon='MOD_BUILD'
        )
        op.active_only, op.advance = True, True
        layout.operator(
            'sub.component_edit',
            text='Select Built Control',
            icon='RESTRICT_SELECT_OFF',
        ).action = 'SELECT_CONTROL'
        body = disclosure(
            layout, editor, 'show_appearance', 'Selected Control Appearance'
        )
        if body is not None:
            from .control_appearance import draw_appearance

            draw_appearance(body, context, obj)
        layout.operator(
            'sub.component_step', text='Back to Bones', icon='BACK'
        ).page = 'BONES'
        return
    layout.operator(
        'sub.component_edit',
        text='Select Control in Viewport',
        icon='RESTRICT_SELECT_OFF',
    ).action = 'SELECT_CONTROL'
    if c.kind in {'EYES', 'LIDS', 'MOUTH'}:
        from .face_components import draw_face

        draw_face(layout, context, obj, c)
    else:
        text = (
            'Move handles, then insert keyframes.'
            if c.kind == 'ISOLATED'
            else 'Pose controls, then insert keyframes.'
        )
        layout.label(text=text, icon='INFO')
    layout.operator('sub.component_step', text='Adjust Controls', icon='BACK').page = (
        'CONTROLS'
    )


class SUB_OP_custom_components(bpy.types.Operator):
    bl_idname = 'sub.custom_components'
    bl_label = 'Make Custom Components'
    bl_description = 'Create reusable bone eye, face, IK, tail and wing components'

    def invoke(self, context, event):
        return self.execute(context)

    def execute(self, context):
        editor = context.scene.sub_component_editor
        if editor.is_open:
            editor.is_open = False
            return {'FINISHED'}
        obj = find_target_armature(context)
        if obj:
            editor.armature = obj
        if not editor.components and obj and obj.get('sub_custom_components'):
            try:
                load_preset(
                    editor,
                    {
                        'format': FORMAT,
                        'version': VERSION,
                        'name': obj.name + ' Components',
                        'components': json.loads(obj['sub_custom_components']),
                    },
                )
            except (ValueError, TypeError):
                pass
        if not editor.components:
            c = editor.components.add()
            c.uid = uuid.uuid4().hex
            c.name = 'Eye Look'
        editor.is_open = True
        if context.area:
            context.area.tag_redraw()
        return {'FINISHED'}


class SUB_PT_component_window(bpy.types.Panel):
    bl_label = 'Custom Rig Components'
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = 'data'
    bl_order = -100

    @classmethod
    def poll(cls, context):
        return bool(context.screen and context.screen.get('sub_components_window'))

    def draw(self, context):
        draw_editor(self.layout, context)


CLASSES = (
    SUB_PG_component_bone,
    SUB_PG_rig_component,
    SUB_PG_component_editor,
    SUB_UL_components,
    SUB_UL_component_bones,
    SUB_OP_component_edit,
    SUB_OP_component_remove,
    SUB_OP_component_preset,
    SUB_MT_component_presets,
    SUB_OP_component_build,
    SUB_OP_component_step,
    SUB_OP_custom_components,
    SUB_PT_component_window,
)


def register():
    from . import (
        face_components,
        control_appearance,
        ik_gizmos,
        component_workflow,
        component_appearance_presets,
    )

    for cls in CLASSES:
        bpy.utils.register_class(cls)
    from . import component_appearance_presets

    component_workflow.register()
    component_appearance_presets.register()
    face_components.register()
    control_appearance.register()
    ik_gizmos.register()
    bpy.types.Scene.sub_component_editor = bpy.props.PointerProperty(
        type=SUB_PG_component_editor
    )


def unregister():
    from . import (
        face_components,
        control_appearance,
        ik_gizmos,
        component_workflow,
        component_appearance_presets,
    )

    from . import component_appearance_presets

    component_appearance_presets.unregister()
    component_workflow.unregister()
    ik_gizmos.unregister()
    control_appearance.unregister()
    face_components.unregister()
    del bpy.types.Scene.sub_component_editor
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
