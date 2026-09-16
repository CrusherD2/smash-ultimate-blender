"""Placement, isolated controls, preset creation and component bake lifecycle."""

import json
import math
from types import SimpleNamespace
import bpy
from mathutils import Matrix, Vector, Euler


def place_controls(context, obj, c, names, plane=False):
    from .create_animation_rig import _activate_armature

    _activate_armature(context, obj)
    bpy.ops.object.mode_set(mode='EDIT')
    for name in names:
        b = obj.data.edit_bones.get(name)
        if not b:
            continue
        raw = b.get('sub_control_rest')
        if raw is None:
            raw = [v for row in b.matrix for v in row]
            b['sub_control_rest'] = raw
        base = Matrix([raw[i : i + 4] for i in range(0, 16, 4)])
        rotation = Euler(c.control_rotation).to_matrix().to_4x4()
        if plane:
            if c.look_plane == 'XZ':
                rotation = rotation @ Matrix.Rotation(math.pi / 2, 4, 'X')
            elif c.look_plane == 'YZ':
                rotation = rotation @ Matrix.Rotation(math.pi / 2, 4, 'Y')
        raw_adjust = b.get('sub_control_adjustment')
        adjust = (
            Matrix([raw_adjust[i : i + 4] for i in range(0, 16, 4)])
            if raw_adjust
            else Matrix.Identity(4)
        )
        b.matrix = (
            Matrix.Translation(Vector(c.control_offset)) @ base @ rotation @ adjust
        )
    bpy.ops.object.mode_set(mode='POSE')


def build_isolated(context, obj, c):
    from .custom_components import validate_component, control_name, COLLECTION
    from .create_animation_rig import _activate_armature, _assign_shape, _widget_object

    names = validate_component(obj, c)
    _activate_armature(context, obj)
    context.view_layer.update()
    visuals = {n: obj.pose.bones[n].matrix.copy() for n in names}
    main = control_name(obj, c)
    # Rebuilding legacy controls repairs their zero-length edit-bone roll.
    # Read the original pose without this component's output constraint, then
    # compensate its helper for the control's current animated transform.
    legacy = any(p.bone.get('sub_face_owner') == c.uid
                 and p.bone.get('sub_component_control')
                 and not p.bone.get('sub_isolated_version') for p in obj.pose.bones)
    legacy_controls = {}
    if legacy:
        muted = [(con, con.mute) for pb in obj.pose.bones for con in pb.constraints
                 if con.name.startswith('SUB Component ' + c.uid)]
        for con, _ in muted:
            con.mute = True
        context.view_layer.update()
        visuals = {n: obj.pose.bones[n].matrix.copy() for n in names}
        legacy_controls = {p.name: p.matrix.copy() for p in obj.pose.bones
                           if p.bone.get('sub_face_owner') == c.uid
                           and p.bone.get('sub_component_control')}
        for con, was_muted in muted:
            con.mute = was_muted
        context.view_layer.update()
    controls = {}
    fresh = set()
    bpy.ops.object.mode_set(mode='EDIT')
    for i, n in enumerate(names):
        import hashlib

        name = (
            main
            if i == 0
            else main[:40] + '_' + hashlib.sha1(n.encode()).hexdigest()[:10]
        )
        b = obj.data.edit_bones.get(name)
        if b is None:
            b = obj.data.edit_bones.new(name)
            b.length = obj.data.edit_bones[n].length
            b.matrix = visuals[n]
            fresh.add(name)
        b.parent = None
        b.use_deform = False
        b['sub_face_owner'] = c.uid
        b['sub_component_control'] = True
        b['sub_component_tool'] = 'builtin.transform'
        b['sub_component_kind'] = c.kind
        b['sub_isolated_version'] = 2
        b['sub_isolated_role'] = 'ROOT'
        b['sub_isolated_source'] = n
        if i == 0:
            b['sub_component_id'] = c.uid
        controls[n] = name
    bpy.ops.object.mode_set(mode='POSE')
    place_controls(context, obj, c, list(controls.values()))
    collection = obj.data.collections.get(COLLECTION) or obj.data.collections.new(
        COLLECTION
    )
    for n, name in controls.items():
        pb = obj.pose.bones[name]
        collection.assign(pb.bone)
        _assign_shape(
            pb,
            _widget_object(context, c.shape),
            max(pb.length, 0.1) * c.shape_scale,
            'THEME04',
            False,
        )
        pb.lock_location = pb.lock_rotation = pb.lock_scale = (False, False, False)
        if name in fresh:
            # COPY_TRANSFORMS uses a rest-matched offset helper so repositioning
            # the control changes its handle origin without moving the foot.
            pb['sub_isolated_reference'] = [
                v for row in pb.bone.matrix_local for v in row
            ]
        original = obj.pose.bones[n]
        prefix = 'SUB Component ' + c.uid
        for con in list(original.constraints):
            if con.name.startswith(prefix):
                original.constraints.remove(con)
    # Keep each output offset in a helper parented only to its independent handle.
    bpy.ops.object.mode_set(mode='EDIT')
    helpers = {}
    foot_handles = {}
    for n, name in controls.items():
        parent_name = name
        if getattr(c,'isolated_foot_controls',True):
            for role, factor in (('Heel',-.25),('Toe',1.0)):
                extra_name=name[:42]+'_'+role
                extra=obj.data.edit_bones.get(extra_name)
                if extra is None:
                    extra=obj.data.edit_bones.new(extra_name)
                    extra.length=max(obj.data.edit_bones[n].length*.35,.05)
                    extra.matrix=visuals[n]
                    pivot=visuals[n].copy()
                    pivot.translation=visuals[n].translation + visuals[n].to_3x3().col[1].normalized()*obj.data.edit_bones[n].length*factor
                    extra.matrix=pivot
                extra.parent=obj.data.edit_bones[parent_name]
                extra.use_deform=False
                extra['sub_face_owner']=c.uid
                extra['sub_component_control']=True
                extra['sub_component_kind']='ISOLATED'
                extra['sub_component_tool']='builtin.rotate'
                extra['sub_isolated_role']=role.upper()
                extra['sub_isolated_target']=name
                foot_handles[extra_name]=role
                parent_name=extra_name
        helper = name[:49] + '_Output'
        b = obj.data.edit_bones.get(helper)
        if b is None:
            b = obj.data.edit_bones.new(helper)
            b.length = obj.data.edit_bones[n].length
            b.matrix = visuals[n]
        b.parent = obj.data.edit_bones[parent_name]
        if legacy and name in legacy_controls:
            b.matrix = (obj.data.edit_bones[name].matrix
                        @ legacy_controls[name].inverted_safe() @ visuals[n])
        b.use_deform = False
        b['sub_face_owner'] = c.uid
        b['sub_face_helper'] = True
        helpers[n] = helper
    bpy.ops.object.mode_set(mode='POSE')
    for pb in obj.pose.bones:
        for con in list(pb.constraints):
            if con.name.startswith('SUB Component ' + c.uid):
                pb.constraints.remove(con)
    for name,role in foot_handles.items():
        pb=obj.pose.bones[name]
        collection.assign(pb.bone)
        pb.lock_location=pb.lock_scale=(True,True,True)
        pb.lock_rotation=(False,False,False)
        pb['component_name']=c.name+' '+role+' Roll'
        _assign_shape(pb,_widget_object(context,'circle'),max(pb.length,.1)*c.shape_scale,'THEME04',False)
    expected = set(controls.values()) | set(helpers.values()) | set(foot_handles)
    stale = {
        p.name for p in obj.pose.bones if p.bone.get('sub_face_owner') == c.uid
    } - expected
    if stale:
        from .face_components import remove_generated

        remove_generated(context, obj, stale)
    for n, helper in helpers.items():
        pb = obj.pose.bones[helper]
        pb.bone.hide = pb.bone.hide_select = True
        con = obj.pose.bones[n].constraints.new('COPY_TRANSFORMS')
        con.name = 'SUB Component ' + c.uid
        con.target, con.subtarget = obj, helper
        con.target_space = con.owner_space = 'POSE'
    context.view_layer.update()
    return main


def definitions(obj):
    from .custom_components import EXTRA_DEFAULTS

    result = []
    for record in json.loads(obj.get('sub_custom_components', '[]')):
        r = {**EXTRA_DEFAULTS, **record}
        r['bones'] = [SimpleNamespace(**b) for b in r['bones']]
        result.append(SimpleNamespace(**r))
    return result


def has_components(obj):
    return bool(
        obj
        and (
            any(b.get('sub_component_id') for b in obj.data.bones)
            or any(
                r.get('component_id')
                for r in json.loads(obj.get('sub_custom_ik_chains', '[]'))
            )
        )
    )


def bake_remove(context, obj, bake=True):
    from . import custom_components as cc, ik_channels, anim_layers_compat
    from .create_animation_rig import (
        _activate_armature,
        _disable_autokey,
        defer_pose_tool_updates,
    )
    from ..anim.fcurve_bulk import PoseKeyWriter
    from ..anim.fcurve_compat import get_all_action_fcurves

    components = definitions(obj)
    names = set()
    for c in components:
        if c.kind == 'IK':
            names.update(ik_channels.chain_path(obj, c.root, c.end, c.middle))
            names.update(
                ik_channels.connected_toe_bones(obj, (c.root, c.middle, c.end))
            )
        else:
            names.update(b.bone for b in c.bones)
    names.intersection_update(obj.pose.bones.keys())
    _activate_armature(context, obj)
    scene = context.scene
    frame = scene.frame_current
    try:
        with _disable_autokey(
            context
        ), defer_pose_tool_updates(), anim_layers_compat.anim_layers_paused(), anim_layers_compat.bind_driving_action_for_bake(
            obj, context
        ):
            frames = []
            if bake:
                for f in range(scene.frame_start, scene.frame_end + 1):
                    scene.frame_set(f)
                    context.view_layer.update()
                    evaluated = obj.evaluated_get(context.evaluated_depsgraph_get())
                    frames.append(
                        (f, {p.name: p.matrix.copy() for p in evaluated.pose.bones})
                    )
            for c in components:
                cc.remove_component(context, obj, c)
            obj['sub_custom_components'] = '[]'
            if bake:
                writer = PoseKeyWriter(obj)
                for f, poses in frames:
                    for name in names:
                        pb = obj.pose.bones[name]
                        kwargs = {}
                        if pb.parent:
                            kwargs = dict(
                                parent_matrix=poses[pb.parent.name],
                                parent_matrix_local=pb.parent.bone.matrix_local,
                            )
                        basis = pb.bone.convert_local_to_pose(
                            poses[name], pb.bone.matrix_local, invert=True, **kwargs
                        )
                        writer.stash_matrix_basis(pb, f, basis)
                action = obj.animation_data.action if obj.animation_data else None
                if action:
                    paths = {
                        obj.pose.bones[n].path_from_id() + '.' + ch
                        for n in names
                        for ch in (
                            'location',
                            'rotation_euler',
                            'rotation_quaternion',
                            'rotation_axis_angle',
                            'scale',
                        )
                    }
                    for fc in get_all_action_fcurves(action, id_type='OBJECT'):
                        if fc.data_path in paths:
                            for mod in list(fc.modifiers):
                                fc.modifiers.remove(mod)
                writer.flush()
    finally:
        scene.frame_set(frame)
    return len(names)


_preset_items = []


def preset_items(self, context):
    from .custom_components import preset_dir

    global _preset_items
    _preset_items = [('NONE', 'Choose a Component Preset', '')] + [
        (p.name, p.stem, '') for p in sorted(preset_dir().glob('*.json'))
    ]
    return _preset_items


def read_preset(name):
    from .custom_components import preset_dir, validate_preset

    if name == 'NONE' or not name:
        raise ValueError('Choose a custom component preset')
    path = preset_dir() / name
    if path.parent.resolve() != preset_dir().resolve():
        raise ValueError('Invalid preset path')
    return validate_preset(json.loads(path.read_text(encoding='utf-8')))


def validate_preset_for_object(obj, name):
    from .custom_components import validate_build

    payload = read_preset(name)
    components = []
    for record in payload['components']:
        item = dict(record)
        item['bones'] = [SimpleNamespace(**b) for b in item['bones']]
        components.append(SimpleNamespace(**item))
    validate_build(obj, components)
    return payload


def build_preset(context, obj, name):
    from .custom_components import (
        load_preset,
        validate_build,
        build_component,
        serialize,
    )

    editor = context.scene.sub_component_editor
    payload = validate_preset_for_object(obj, name)
    load_preset(editor, payload)
    editor.armature = obj
    validate_build(obj, editor.components)
    for c in editor.components:
        build_component(context, obj, c)
    from .component_appearance_presets import apply

    apply(context, obj, json.loads(editor.appearances))
    updated = {c.uid for c in editor.components}
    existing = json.loads(obj.get('sub_custom_components', '[]'))
    obj['sub_custom_components'] = json.dumps(
        [r for r in existing if r['uid'] not in updated]
        + [serialize(c) for c in editor.components]
    )


class SUB_OP_components_bake_remove(bpy.types.Operator):
    bl_idname = 'sub.components_bake_remove'
    bl_label = 'Custom Components: Bake / Remove'
    bl_options = {'REGISTER', 'UNDO'}
    bake: bpy.props.BoolProperty(name='Bake First', default=True)

    def execute(self, context):
        from .create_animation_rig import find_target_armature

        obj = find_target_armature(context)
        if not obj:
            return {'CANCELLED'}
        try:
            count = bake_remove(context, obj, self.bake)
        except (ValueError, RuntimeError) as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}
        self.report(
            {'INFO'},
            f'Removed custom components ({count} bones'
            + (' baked)' if self.bake else ')'),
        )
        return {'FINISHED'}


def register():
    from . import component_matching, component_selection
    component_matching.register()
    component_selection.register()
    bpy.utils.register_class(SUB_OP_components_bake_remove)


def unregister():
    from . import component_matching, component_selection
    component_selection.unregister()
    component_matching.unregister()
    bpy.utils.unregister_class(SUB_OP_components_bake_remove)
