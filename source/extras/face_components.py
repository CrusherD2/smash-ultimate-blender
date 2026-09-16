"""Pose-authored bone expressions evaluated entirely by Blender drivers.

Presets contain local TRS samples, never executable expressions or scripts.
A rear eye pivot parents rest-matched eye helpers, preserving a true orbital arc.
"""

import json
import math
import bpy
from mathutils import Vector, Quaternion

KINDS = {'EYES', 'LIDS', 'MOUTH'}


_expression_items_cache = {}


def expression_items(pb, context):
    raw=pb.get('sub_expression_labels','[]')
    active=pb.get('sub_expression_active',raw)
    key=(raw,active)
    if key not in _expression_items_cache:
        labels=json.loads(raw)
        enabled=set(json.loads(active))
        _expression_items_cache[key]=[('NONE','None','Neutral',0)]+[
            ('POSE_'+str(i+1),label,'',i+1) for i,label in enumerate(labels) if label in enabled]
    return _expression_items_cache[key]


def expression_get(pb):
    return int(pb.sub_face_expression)


def expression_set(pb,value):
    pb.sub_face_expression=int(value)
    pb.id_data.update_tag()


def strength_get(pb):
    return max(0.0,min(1.0,float(pb.location.y)))


def strength_set(pb,value):
    pb.location.y=max(0.0,min(1.0,float(value)))
    pb.id_data.update_tag()


class SUB_OP_face_expression_select(bpy.types.Operator):
    bl_idname='sub.face_expression_select'
    bl_label='Select Expression'
    bl_options={'UNDO'}
    armature: bpy.props.StringProperty(options={'HIDDEN','SKIP_SAVE'})
    bone: bpy.props.StringProperty(options={'HIDDEN','SKIP_SAVE'})
    value: bpy.props.IntProperty(default=0,options={'HIDDEN','SKIP_SAVE'})
    key_only: bpy.props.BoolProperty(default=False,options={'HIDDEN','SKIP_SAVE'})
    key_strength: bpy.props.BoolProperty(default=False,options={'HIDDEN','SKIP_SAVE'})

    def execute(self,context):
        obj=bpy.data.objects.get(self.armature)
        pb=obj.pose.bones.get(self.bone) if obj and obj.type=='ARMATURE' else None
        if pb is None: return {'CANCELLED'}
        if not self.key_only and not self.key_strength:
            valid={item[3] for item in expression_items(pb,context)}
            if self.value not in valid: return {'CANCELLED'}
            expression_set(pb,self.value)
        from ..anim.fcurve_compat import get_fcurves_for_assigned_slot
        path=pb.path_from_id()+'.sub_face_expression'
        animated=any(fc.data_path==path for fc in get_fcurves_for_assigned_slot(obj))
        # An evaluated enum track otherwise overwrites the menu selection during
        # the update below. Once animated, selecting a pose keys the new choice.
        if self.key_strength:
            from ..anim.fcurve_bulk import PoseKeyWriter
            writer=PoseKeyWriter(obj)
            writer.stash_channel(pb.path_from_id()+'.location',1,
                context.scene.frame_current,strength_get(pb),pb.name)
            writer.flush()
        elif self.key_only or animated or context.scene.tool_settings.use_keyframe_insert_auto:
            from ..anim.fcurve_bulk import PoseKeyWriter
            writer=PoseKeyWriter(obj,interpolation='CONSTANT')
            writer.stash_channel(path,0,context.scene.frame_current,expression_get(pb),pb.name)
            writer.flush()
            for fc in get_fcurves_for_assigned_slot(obj):
                if fc.data_path==path:
                    for point in fc.keyframe_points:
                        point.interpolation='CONSTANT'
                    fc.update()
        context.view_layer.update()
        return {'FINISHED'}


class SUB_MT_face_expression(bpy.types.Menu):
    bl_idname='SUB_MT_face_expression'
    bl_label='Expression'

    def draw(self,context):
        pb=getattr(context,'sub_expression_control',None)
        if pb is None: return
        for identifier,label,description,value in expression_items(pb,context):
            op=self.layout.operator('sub.face_expression_select',text=label,
                icon='RADIOBUT_ON' if expression_get(pb)==value else 'RADIOBUT_OFF')
            op.armature,op.bone,op.value=pb.id_data.name,pb.name,value
            op.key_only=False
            op.key_strength=False


def _bind_expression_ui(layout,pb):
    # PoseBone RNA widgets poll against context.pose_bone. Without this, the
    # Strength slider vanishes as soon as another bone is active.
    layout.context_pointer_set('sub_expression_control',pb)
    layout.context_pointer_set('pose_bone',pb)
    layout.context_pointer_set('active_pose_bone',pb)
    layout.context_pointer_set('object',pb.id_data)
    layout.context_pointer_set('active_object',pb.id_data)


def draw_expression_control(layout,pb):
    # A context-bound menu avoids the shared RNA enum popup cache: each row
    # carries the actual controller, independently of the active pose bone.
    row=layout.row(align=True)
    _bind_expression_ui(row,pb)
    label=next((item[1] for item in expression_items(pb,None) if item[3]==expression_get(pb)),'None')
    row.menu('SUB_MT_face_expression',text=label)
    op=row.operator('sub.face_expression_select',text='',icon='KEY_HLT')
    op.armature,op.bone,op.key_only=pb.id_data.name,pb.name,True
    op.key_strength=False
    row=layout.row(align=True)
    _bind_expression_ui(row,pb)
    row.prop(pb,'sub_face_strength',text='Strength',slider=True)
    op=row.operator('sub.face_expression_select',text='',icon='KEY_HLT')
    op.armature,op.bone,op.key_strength=pb.id_data.name,pb.name,True
    op.key_only=False


def draw_rig_expressions(layout,obj):
    for pb in obj.pose.bones:
        if 'sub_expression_labels' in pb:
            box=layout.box()
            box.label(text=pb.get('component_name',pb.name))
            draw_expression_control(box,pb)


def validate_data(raw):
    if not isinstance(raw, str):
        raise ValueError('Invalid face pose data')
    try:
        data = json.loads(raw)
    except (ValueError, TypeError) as exc:
        raise ValueError('Invalid face pose data') from exc
    if not isinstance(data, dict) or set(data) - {'neutral', 'poses', 'steps'}:
        raise ValueError('Invalid face pose fields')
    if not isinstance(data.get('poses', {}), dict) or len(data.get('poses', {})) > 32:
        raise ValueError('Use up to 32 named expressions per component')
    step_poses=[]
    steps=data.get('steps',{})
    if not isinstance(steps,dict): raise ValueError('Invalid expression checkpoints')
    for label,checkpoints in steps.items():
        if label not in data.get('poses',{}) or not isinstance(checkpoints,dict) or len(checkpoints)>16:
            raise ValueError('Use up to 16 checkpoints per saved expression')
        for strength,pose in checkpoints.items():
            try: value=float(strength)
            except (ValueError,TypeError): raise ValueError('Invalid checkpoint strength')
            if not 0<value<1: raise ValueError('Checkpoint strength must be between 0 and 1')
            step_poses.append(pose)
    for poses in [data.get('neutral', {})] + list(data.get('poses', {}).values()) + step_poses:
        if not isinstance(poses, dict):
            raise ValueError('Invalid captured pose')
        for name, values in poses.items():
            if (
                not isinstance(name, str)
                or not isinstance(values, list)
                or len(values) != 10
                or any(
                    not isinstance(v, (float, int)) or not math.isfinite(v)
                    for v in values
                )
            ):
                raise ValueError('Invalid captured bone transform')
    return data


def expression_checkpoints(data,label):
    return [(0.0,data['neutral'])]+sorted(
        (float(strength),pose) for strength,pose in data.get('steps',{}).get(label,{}).items()
    )+[(1.0,data['poses'][label])]


def sample(pb):
    loc, rot, scale = pb.matrix_basis.decompose()
    return list(loc) + list(rot) + list(scale)


def restore(pb, value):
    from mathutils import Matrix

    pb.matrix_basis = Matrix.LocRotScale(
        Vector(value[:3]), Quaternion(value[3:7]), Vector(value[7:])
    )


def owner_prefix(c):
    return 'SUB Component ' + c.uid


def owned(obj, c):
    return [p for p in obj.pose.bones if p.bone.get('sub_face_owner') == c.uid]


def set_orbit_visibility(obj, c, force_show=False):
    if c.kind != 'EYES':
        return
    from .custom_components import control_name, COLLECTION
    from ..blender_compat import set_pose_bone_select
    pb = obj.pose.bones.get(control_name(obj, c))
    if pb is None:
        return
    hidden = not (c.show_orbit or force_show)
    pb.bone.hide = pb.bone.hide_select = hidden
    # Blender versions with per-pose visibility must hide the pose as well.
    if hasattr(pb, 'hide'):
        pb.hide = hidden
    mechanism = obj.data.collections.get('Custom Component Mechanism')
    if mechanism is None:
        mechanism = obj.data.collections.new('Custom Component Mechanism')
    mechanism.is_visible = False
    visible = obj.data.collections.get(COLLECTION) or obj.data.collections.new(COLLECTION)
    if hidden:
        if 'sub_orbit_collections' not in pb.bone:
            pb.bone['sub_orbit_collections'] = [col.name for col in pb.bone.collections]
        for col in list(pb.bone.collections):
            col.unassign(pb.bone)
        mechanism.assign(pb.bone)
        set_pose_bone_select(pb, False)
    else:
        mechanism.unassign(pb.bone)
        for name in pb.bone.get('sub_orbit_collections', [COLLECTION]):
            col = obj.data.collections.get(name)
            if col and col != mechanism:
                col.assign(pb.bone)
        visible.assign(pb.bone)
        if 'sub_orbit_collections' in pb.bone:
            del pb.bone['sub_orbit_collections']


def set_edit(obj, c, enabled):
    for pb in obj.pose.bones:
        for con in pb.constraints:
            if con.name.startswith(owner_prefix(c)):
                con.mute = enabled
    for assignment in c.bones:
        bone = obj.data.bones.get(assignment.bone)
        if bone:
            if enabled:
                bone['sub_face_was_hidden'] = bone.hide
                bone.hide = False
            elif 'sub_face_was_hidden' in bone:
                bone.hide = bool(bone['sub_face_was_hidden'])
                del bone['sub_face_was_hidden']
    from .component_visibility import edit
    edit(obj, c, enabled)
    obj['sub_face_edit_' + c.uid] = enabled
    obj.update_tag()


def _driver(pb, channel, index, value, terms, obj, strength=None, selector=None):
    if not any(abs(term[0]) >= 1e-9 for term in terms):
        pb.driver_remove(channel, index)
        getattr(pb, channel)[index] = value
        return
    fc = pb.driver_add(channel, index)
    driver = fc.driver
    driver.type = 'SCRIPTED'
    while driver.variables:
        driver.variables.remove(driver.variables[0])
    if strength:
        var = driver.variables.new()
        var.name, var.type = 'strength', 'TRANSFORMS'
        var.targets[0].id = obj
        var.targets[0].bone_target = strength
        var.targets[0].transform_type = 'LOC_Y'
        var.targets[0].transform_space = 'LOCAL_SPACE'
    if selector:
        var=driver.variables.new()
        var.name,var.type='choice','SINGLE_PROP'
        var.targets[0].id=obj
        var.targets[0].data_path=obj.pose.bones[selector].path_from_id()+'.sub_face_expression'
        if not strength:
            var=driver.variables.new()
            var.name,var.type='strength','TRANSFORMS'
            var.targets[0].id=obj
            var.targets[0].bone_target=selector
            var.targets[0].transform_type='LOC_Y'
            var.targets[0].transform_space='LOCAL_SPACE'
    expressions = [format(value, '.6g')]
    reused={}
    for i, (coefficient, source, axis, expression, shared) in enumerate(terms):
        if abs(coefficient) < 1e-9:
            continue
        key=(source,axis)
        name=reused.get(key)
        if name is None:
            name='v'+str(len(reused))
            reused[key]=name
            var = driver.variables.new()
            var.name = name
            var.type = 'TRANSFORMS'
            var.targets[0].id = obj
            var.targets[0].bone_target = source
            var.targets[0].transform_type = 'LOC_' + axis
            var.targets[0].transform_space = 'LOCAL_SPACE'
        weight = expression.replace('VALUE', name)
        if shared:
            var = driver.variables.new()
            var.name = 's' + str(i)
            var.type = 'TRANSFORMS'
            var.targets[0].id = obj
            var.targets[0].bone_target = shared
            var.targets[0].transform_type = 'LOC_Y'
            var.targets[0].transform_space = 'LOCAL_SPACE'
            weight = 'min(1,max(0,' + name + '+' + var.name + '))'
        if strength:
            weight = '(' + weight + ')*min(1,max(0,strength))'
        expressions.append(format(coefficient, '.6g') + '*(' + weight + ')')
    driver.expression = '+'.join(expressions)


def build_face(context, obj, c):
    from .custom_components import (
        validate_component,
        control_name,
        _control_parent,
        COLLECTION,
    )
    from .create_animation_rig import _activate_armature, _widget_object, _assign_shape

    names = validate_component(obj, c)
    data = validate_data(c.face_data)
    if not data.get('neutral'):
        data['neutral'] = {n: sample(obj.pose.bones[n]) for n in names}
    # Adding an assignment should extend the pose library, not invalidate it.
    # Existing snapshots remain intact; new bones start unchanged in saved poses.
    # Retain unassigned snapshots so removing/re-adding a bone is non-destructive.
    for name in names:
        if name not in data['neutral']:
            data['neutral'][name] = sample(obj.pose.bones[name])
    poses = data.setdefault('poses', {})
    if c.kind == 'EYES' and set(poses) - {'Left', 'Right', 'Up', 'Down'}:
        raise ValueError('Eye limits must be named Left, Right, Up or Down')
    c.face_data = json.dumps(data)
    main = control_name(obj, c)
    parent = _control_parent(obj, c, names)
    center = sum((obj.data.bones[n].head_local for n in names), Vector()) / len(names)
    size = max(sum(obj.data.bones[n].length for n in names) / len(names), 0.1)
    source = obj.data.bones[names[0]]
    direction = (
        source.matrix_local.to_3x3().col['XYZ'.index(c.aim_axis[-1])].normalized()
    )
    if c.aim_axis.startswith('NEG_'):
        direction = -direction
    pivot = (
        obj.matrix_world.inverted() @ context.scene.cursor.location
        if c.pivot_at_cursor
        else center - direction * size * c.distance
    )
    _activate_armature(context, obj)
    bpy.ops.object.mode_set(mode='EDIT')

    def make(name, head, parent_name=None, matrix=None, helper=False):
        b = obj.data.edit_bones.get(name)
        if b is None:
            b = obj.data.edit_bones.new(name)
            b.head, b.tail = head, head + Vector((0, size * 0.3, 0))
            b.parent = obj.data.edit_bones.get(parent_name) if parent_name else None
            if matrix is not None:
                b.matrix = matrix
        b.use_deform = False
        b['sub_component_travel'] = 1.0
        b['sub_face_owner'] = c.uid
        b['sub_component_control'] = not helper
        b['sub_face_helper'] = helper
        b['sub_component_tool'] = (
            'builtin.rotate' if name == main and c.kind == 'EYES' else 'builtin.move'
        )
        return b

    control = make(
        main,
        pivot if c.kind == 'EYES' else center + Vector((0, 0, size * c.distance)),
        parent,
    )
    control['sub_component_id'] = c.uid
    control['sub_component_kind'] = c.kind
    sliders = {}
    if c.kind == 'EYES':
        look = main + '_Look'
        make(look, center + direction * size * c.distance, parent)
        pivot_limit = main + '_Orbit'
        make(pivot_limit, control.head.copy(), main, control.matrix.copy(), True)
        for label in poses:
            sliders[label] = look
    else:
        for i, label in enumerate(poses):
            # Stable names survive expression reordering and preset round trips.
            import hashlib

            name = main[:42] + '_' + hashlib.sha1(label.encode()).hexdigest()[:10]
            make(
                name,
                center + Vector(((i + 1) * size * 0.5, 0, size * c.distance)),
                parent,
            )
            sliders[label] = name
    helpers = {}
    for n in names:
        source = obj.data.edit_bones[n]
        import hashlib

        name = (
            'BL_CC_MCH_' + c.uid[:12] + '_' + hashlib.sha1(n.encode()).hexdigest()[:10]
        )
        helper_parent = (
            pivot_limit
            if c.kind == 'EYES'
            else (source.parent.name if source.parent else None)
        )
        b = make(name, source.head.copy(), helper_parent, source.matrix.copy(), True)
        b.length = source.length
        helpers[n] = name
    bpy.ops.object.mode_set(mode='POSE')
    expected = {*helpers.values(), *sliders.values()}
    expected.add(main)
    if c.kind == 'EYES':
        expected.update({look, pivot_limit})
    stale = {p.name for p in owned(obj, c)} - expected
    if stale:
        for pb in obj.pose.bones:
            for con in list(pb.constraints):
                if con.name.startswith(owner_prefix(c)) and con.subtarget in stale:
                    pb.constraints.remove(con)
        remove_generated(context, obj, stale)
    visible = obj.data.collections.get(COLLECTION) or obj.data.collections.new(
        COLLECTION
    )
    hidden = obj.data.collections.get(
        'Custom Component Mechanism'
    ) or obj.data.collections.new('Custom Component Mechanism')
    hidden.is_visible = False
    for pb in owned(obj, c):
        expression_track = c.kind != 'EYES' and pb.name in sliders.values()
        if pb.bone.get('sub_face_helper') or expression_track:
            for col in list(pb.bone.collections): col.unassign(pb.bone)
            hidden.assign(pb.bone)
            pb.bone.hide = True
            pb.bone.hide_select = True
        else:
            visible.assign(pb.bone)
            _assign_shape(
                pb,
                _widget_object(
                    context,
                    (
                        c.shape
                        if pb.name == main
                        else ('knob' if c.kind == 'EYES' else 'slider')
                    ),
                ),
                size * c.shape_scale,
                'THEME04',
                False,
            )
            pb['component_name'] = c.name
            pb.lock_scale = (True,) * 3
            for con in list(pb.constraints):
                if con.name == 'Component Slider Range':
                    pb.constraints.remove(con)
            if c.kind == 'EYES' and pb.name == main:
                pb.lock_location = (True,) * 3
                pb.lock_rotation = (False,) * 3
            else:
                pb.lock_rotation = (True,) * 3
                pb.lock_location = (c.kind != 'EYES', False, True)
                limit = pb.constraints.new('LIMIT_LOCATION')
                limit.name = 'Component Slider Range'
                limit.owner_space = 'LOCAL'
                limit.use_transform_limit = True
                limit.use_min_y = limit.use_max_y = True
                limit.min_y, limit.max_y = (-1 if c.kind == 'EYES' else 0), 1
                if c.kind == 'EYES':
                    limit.use_min_x = limit.use_max_x = True
                    limit.min_x, limit.max_x = -1, 1
    for label, name in sliders.items():
        obj.pose.bones[name]['expression'] = label if c.kind != 'EYES' else 'Look X / Y'
    if c.kind == 'EYES':
        obj.pose.bones[main]['expression'] = 'Eye Orbit Pivot'
    if c.kind != 'EYES':
        main_pb=obj.pose.bones[main]
        labels=json.loads(main_pb.get('sub_expression_labels','[]'))
        labels.extend(label for label in poses if label not in labels)
        main_pb['sub_expression_labels']=json.dumps(labels)
        main_pb['sub_expression_active']=json.dumps(list(poses))
        main_pb['expression']='Selected Expression'
        if 'sub_expression_choice' not in main_pb: main_pb['sub_expression_choice']=0
        if 'sub_expression_strength_initialized' not in main_pb:
            main_pb.location.y=0
            main_pb['sub_expression_strength_initialized']=True
    driver_jobs = dict(helpers)
    if c.kind == 'EYES':
        driver_jobs['@pivot'] = pivot_limit
    for n, helper in driver_jobs.items():
        pb = obj.pose.bones[helper]
        pb.rotation_mode = 'XYZ'
        neutral = data['neutral'].get(n, [0, 0, 0, 1, 0, 0, 0, 1, 1, 1])
        euler = Quaternion(neutral[3:7]).to_euler('XYZ')
        base = list(neutral[:3]) + list(euler) + list(neutral[7:])
        deltas = []
        for label, pose in poses.items():
            v = pose.get(n, neutral)
            rotation = Quaternion(v[3:7]).to_euler('XYZ', euler)
            values = list(v[:3]) + list(rotation) + list(v[7:])
            if c.kind == 'EYES':
                axis = 'X' if label in {'Left', 'Right'} else 'Y'
                expr = (
                    'min(1,max(0,'
                    + ('-' if label in {'Left', 'Down'} else '')
                    + 'VALUE))'
                )
            else:
                axis, expr = 'Y', 'min(1,max(0,VALUE))'
            deltas.append((values, sliders[label], axis, expr))
        for j in range(9):
            channel = ('location', 'rotation_euler', 'scale')[j // 3]
            terms = [
                (v[j] - base[j], slider, axis, expr, None)
                for v, slider, axis, expr in deltas
            ]
            if c.kind != 'EYES':
                terms=[]
                for label in poses:
                    previous=base[j]
                    low=0.0
                    index=labels.index(label)+1
                    for high,checkpoint in expression_checkpoints(data,label)[1:]:
                        v=checkpoint.get(n,neutral)
                        values=list(v[:3])+list(Quaternion(v[3:7]).to_euler('XYZ',euler))+list(v[7:])
                        span=max(high-low,1e-9)
                        # Hidden tracks and the selected Strength slider share one
                        # term so extra expressions stay inside driver limits.
                        ramp=(f'min(1,max(0,(VALUE+strength*(choice=={index})'
                             f'-{low:.6g})/{span:.6g}))')
                        coefficient=values[j]-previous
                        terms.append((coefficient,sliders[label],'Y',ramp,None))
                        previous,low=values[j],high
            _driver(
                pb,
                channel,
                j % 3,
                base[j],
                terms,
                obj,
                None,
                selector=main if c.kind != 'EYES' else None,
            )
        if n == '@pivot':
            continue
        original = obj.pose.bones[n]
        for con in list(original.constraints):
            if con.name.startswith(owner_prefix(c)):
                original.constraints.remove(con)
        con = original.constraints.new('COPY_TRANSFORMS')
        con.name = owner_prefix(c)
        con.target, con.subtarget = obj, helper
        con.target_space = con.owner_space = 'POSE'
    from .component_workflow import place_controls

    handles = (
        [look]
        if c.kind == 'EYES'
        else [main]
    )
    place_controls(context, obj, c, handles, plane=c.kind == 'EYES')
    if c.kind == 'EYES':
        set_orbit_visibility(obj, c)
    set_edit(obj, c, False)
    context.view_layer.update()
    return main


def remove_face_helpers(context, obj, c):
    from .custom_components import control_name

    main = control_name(obj, c)
    for pb in obj.pose.bones:
        for con in list(pb.constraints):
            if con.name.startswith(owner_prefix(c)):
                pb.constraints.remove(con)
    names = {p.name for p in owned(obj, c) if p.name != main}
    if not names:
        return
    remove_generated(context, obj, names)
    for key in ('sub_face_edit_', 'sub_face_before_', 'sub_face_orbit_'):
        if key + c.uid in obj:
            del obj[key + c.uid]


def remove_generated(context, obj, names):
    paths = tuple(obj.pose.bones[n].path_from_id() for n in names)
    if obj.animation_data:
        for fc in list(obj.animation_data.drivers):
            if fc.data_path.startswith(paths):
                obj.animation_data.drivers.remove(fc)
    from .create_animation_rig import _iter_armature_actions
    from ..anim.fcurve_compat import get_all_action_fcurves, remove_fcurve

    for action in _iter_armature_actions(obj):
        for fc in list(get_all_action_fcurves(action, id_type='OBJECT')):
            if fc.data_path.startswith(paths):
                remove_fcurve(action, fc, id_type='OBJECT')
    bpy.ops.object.mode_set(mode='EDIT')
    for n in names:
        obj.data.edit_bones.remove(obj.data.edit_bones[n])
    bpy.ops.object.mode_set(mode='POSE')


class SUB_OP_face_pose(bpy.types.Operator):
    bl_idname = 'sub.face_pose'
    bl_label = 'Facial Pose'
    bl_options = {'REGISTER', 'UNDO'}
    action: bpy.props.EnumProperty(
        items=[
            (v, v, '')
            for v in ('NEUTRAL', 'NEW', 'EDIT', 'ORBIT', 'CAPTURE', 'CANCEL', 'DELETE', 'DELETE_STEP')
        ]
    )
    label: bpy.props.StringProperty()
    strength: bpy.props.FloatProperty(default=1.0,min=.01,max=1.0)

    def execute(self, context):
        from .custom_components import (
            active_component,
            editor_armature,
            validate_component,
            serialize,
        )
        from .create_animation_rig import _disable_autokey

        c, obj = active_component(context), editor_armature(context)
        if not c or not obj:
            return {'CANCELLED'}
        try:
            names = validate_component(obj, c)
            data = validate_data(c.face_data)
            label = self.label or c.pose_name.strip()
            if self.action=='EDIT' and self.label:
                c.pose_name=self.label
                c.pose_strength=self.strength
            with _disable_autokey(context):
                if self.action == 'NEUTRAL':
                    data = {
                        'neutral': {n: sample(obj.pose.bones[n]) for n in names},
                        'poses': {},
                    }
                elif not data.get('neutral'):
                    raise ValueError('Capture Neutral first')
                elif self.action in {'NEW', 'EDIT', 'ORBIT'}:
                    if self.action == 'NEW':
                        base='Expression'
                        label=base
                        number=2
                        while label in data.get('poses',{}):
                            label=f'{base} {number}'
                            number+=1
                        c.pose_name=label
                        c.pose_strength=1.0
                    if obj.get('sub_face_edit_' + c.uid) or obj.get(
                        'sub_face_orbit_' + c.uid
                    ):
                        raise ValueError(
                            'Capture or cancel the current pose edit first'
                        )
                    from .custom_components import control_name

                    if (
                        self.action == 'ORBIT'
                        and control_name(obj, c) not in obj.pose.bones
                    ):
                        build_face(context, obj, c)
                    snapshot = {n: sample(obj.pose.bones[n]) for n in names}
                    main = obj.pose.bones.get(control_name(obj, c))
                    if main and c.kind == 'EYES':
                        snapshot['@pivot'] = sample(main)
                        from mathutils import Matrix

                        main.matrix_basis = Matrix.Identity(4)
                    obj['sub_face_before_' + c.uid] = json.dumps(snapshot)
                    obj['sub_face_orbit_' + c.uid] = self.action == 'ORBIT'
                    from .create_animation_rig import _activate_armature
                    from ..blender_compat import set_pose_bone_select

                    _activate_armature(context, obj)
                    bpy.ops.object.mode_set(mode='POSE')
                    if self.action == 'ORBIT' and main:
                        set_orbit_visibility(obj, c, force_show=True)
                    selected_names = (
                        {main.name} if self.action == 'ORBIT' and main else set(names)
                    )
                    for pb in obj.pose.bones:
                        set_pose_bone_select(pb, pb.name in selected_names)
                    obj.data.bones.active = obj.data.bones[next(iter(selected_names))]
                    set_edit(obj, c, self.action != 'ORBIT')
                    if self.action == 'ORBIT':
                        for pb in owned(obj, c):
                            if pb.get('expression') == 'Look X / Y':
                                pb.location = (0, 0, 0)
                    for n in names:
                        restore(obj.pose.bones[n], data['neutral'][n])
                elif self.action == 'CAPTURE':
                    if not label:
                        raise ValueError('Name the pose')
                    if c.kind == 'EYES' and label not in {
                        'Left',
                        'Right',
                        'Up',
                        'Down',
                    }:
                        raise ValueError('Choose Left, Right, Up or Down')
                    captured={n:sample(obj.pose.bones[n]) for n in names}
                    strength=c.pose_strength if c.kind!='EYES' else 1.0
                    if strength<1.0:
                        data.setdefault('poses',{}).setdefault(label,captured)
                        data.setdefault('steps',{}).setdefault(label,{})[format(strength,'.6g')]=captured
                    else:
                        data.setdefault('poses',{})[label]=captured
                    from .custom_components import control_name

                    main = obj.pose.bones.get(control_name(obj, c))
                    if c.kind == 'EYES' and main and obj.get('sub_face_orbit_' + c.uid):
                        data['poses'][label]['@pivot'] = sample(main)
                    before = json.loads(obj.get('sub_face_before_' + c.uid, '{}'))
                    for n in names:
                        restore(obj.pose.bones[n], before.get(n, data['neutral'][n]))
                    if main and '@pivot' in before:
                        restore(main, before['@pivot'])
                elif self.action == 'CANCEL':
                    from .custom_components import control_name

                    before = json.loads(obj.get('sub_face_before_' + c.uid, '{}'))
                    for n in names:
                        restore(obj.pose.bones[n], before.get(n, data['neutral'][n]))
                    main = obj.pose.bones.get(control_name(obj, c))
                    if main and '@pivot' in before:
                        restore(main, before['@pivot'])
                    set_edit(obj, c, False)
                elif self.action == 'DELETE_STEP':
                    data.get('steps',{}).get(label,{}).pop(format(self.strength,'.6g'),None)
                elif self.action == 'DELETE':
                    data.setdefault('poses', {}).pop(label, None)
                    data.get('steps',{}).pop(label,None)
                c.face_data = json.dumps(data)
                if self.action in {'NEUTRAL', 'CAPTURE', 'DELETE', 'DELETE_STEP'}:
                    build_face(context, obj, c)
                if self.action in {'CAPTURE', 'CANCEL', 'NEUTRAL'}:
                    for key in ('sub_face_before_', 'sub_face_orbit_'):
                        if key + c.uid in obj:
                            del obj[key + c.uid]
                records = json.loads(obj.get('sub_custom_components', '[]'))
                obj['sub_custom_components'] = json.dumps(
                    [r for r in records if r['uid'] != c.uid] + [serialize(c)]
                )
                if (
                    self.action in {'NEUTRAL', 'CAPTURE', 'DELETE', 'DELETE_STEP'}
                    and context.scene.sub_component_editor.save_on_build
                ):
                    from .custom_components import save_preset

                    save_preset(context.scene.sub_component_editor)
            obj.update_tag()
            context.view_layer.update()
        except (ValueError, RuntimeError, KeyError, OSError) as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}
        return {'FINISHED'}


def draw_face(layout, context, obj, c):
    from .custom_components import disclosure

    editor = context.scene.sub_component_editor
    try:
        data = validate_data(c.face_data)
    except ValueError:
        data = {}
    if not data.get('neutral'):
        layout.label(text='Pose the assigned bones in their neutral position.')
        layout.operator(
            'sub.face_pose', text='Capture Neutral & Create Controls', icon='ADD'
        ).action = 'NEUTRAL'
        return
    editing = obj and (
        obj.get('sub_face_edit_' + c.uid) or obj.get('sub_face_orbit_' + c.uid)
    )
    if editing:
        layout.label(
            text='Pose the bones in the viewport, then save the result.',
            icon='EDITMODE_HLT',
        )
        if c.kind == 'EYES':
            row = layout.row(align=True)
            for label in ('Left', 'Right', 'Up', 'Down'):
                op = row.operator('sub.face_pose', text='Save ' + label)
                op.action, op.label = 'CAPTURE', label
        else:
            layout.prop(c, 'pose_name', text='Expression Name')
            layout.prop(c, 'pose_strength')
            layout.operator(
                'sub.face_pose', text='Save Expression', icon='CHECKMARK'
            ).action = 'CAPTURE'
        layout.operator('sub.face_pose', text='Cancel Pose Edit').action = 'CANCEL'
        return
    poses = data.get('poses', {})
    layout.label(
        text=(
            f'{len(poses)} poses saved'
            if poses
            else 'Create your first expression or eye limit.'
        ),
        icon='INFO',
    )
    row = layout.row(align=True)
    row.operator('sub.face_pose', text='Create Eye Limit' if c.kind=='EYES' else 'New Expression', icon='ADD').action = (
        'EDIT' if c.kind=='EYES' else 'NEW'
    )
    if c.kind == 'EYES':
        row.operator('sub.face_pose', text='Create Orbit Limit').action = 'ORBIT'
    if c.kind == 'LIDS' and not poses:
        layout.label(
            text='Save separate eyelid poses or a combined blink expression.'
        )
    if poses:
        body = disclosure(layout, editor, 'show_pose_preview', 'Preview & Animate')
        if body is not None and obj:
            if c.kind != 'EYES':
                from .custom_components import control_name
                pb=obj.pose.bones.get(control_name(obj,c))
                if pb: draw_expression_control(body,pb)
            for pb in owned(obj, c):
                if c.kind != 'EYES': continue
                if pb.bone.get('sub_face_helper') or not pb.get('expression'):
                    continue
                if c.kind == 'EYES' and pb.bone.get('sub_component_id') == c.uid:
                    continue
                body.prop(pb, 'location', index=1, text=pb['expression'], slider=True)
                if c.kind == 'EYES':
                    body.prop(
                        pb, 'location', index=0, text='Look Left / Right', slider=True
                    )
    body = disclosure(layout, editor, 'show_pose_manage', 'Manage Saved Poses')
    if body is not None:
        for label in poses:
            row = body.row(align=True)
            row.label(text=label)
            op=row.operator('sub.face_pose',text='',icon='GREASEPENCIL')
            op.action,op.label='EDIT',label
            op = row.operator('sub.face_pose', text='', icon='X')
            op.action, op.label = 'DELETE', label
            if c.kind!='EYES':
                row=body.row(align=True)
                op=row.operator('sub.face_pose',text='Add Checkpoint',icon='ADD')
                op.action,op.label,op.strength='EDIT',label,.5
                for strength,_pose in expression_checkpoints(data,label)[1:-1]:
                    row=body.row(align=True)
                    op=row.operator('sub.face_pose',text=f'Edit at {strength:g}')
                    op.action,op.label,op.strength='EDIT',label,strength
                    op=row.operator('sub.face_pose',text='',icon='X')
                    op.action,op.label,op.strength='DELETE_STEP',label,strength
        body.operator(
            'sub.face_pose', text='Recapture Neutral (clears poses)'
        ).action = 'NEUTRAL'


@bpy.app.handlers.persistent
def migrate_expression_storage(_dummy=None):
    # Older saves kept the enum value in a separate custom property. Native
    # storage prevents drivers from entering Python getters on worker threads.
    # Addon enable still has restricted bpy.data, so skip until it is live.
    try:
        objects = bpy.data.objects
    except AttributeError:
        return None
    for obj in objects:
        if obj.type!='ARMATURE': continue
        for pb in obj.pose.bones:
            if 'sub_expression_labels' in pb and 'sub_face_expression' not in pb:
                pb.sub_face_expression=int(pb.get('sub_expression_choice',0))
        if obj.animation_data:
            for fc in obj.animation_data.drivers:
                expr=getattr(fc.driver,'expression','')
                if ' if choice==' in expr:
                    fc.driver.expression=expr.replace(' if choice==',')*(choice==').replace(' else 0)',')')
    return None


def register():
    bpy.types.PoseBone.sub_face_expression=bpy.props.IntProperty(
        name='Expression',default=0,min=0,options={'ANIMATABLE'})
    bpy.types.PoseBone.sub_face_strength=bpy.props.FloatProperty(
        name='Strength',min=0.0,max=1.0,soft_min=0.0,soft_max=1.0,
        get=strength_get,set=strength_set)
    bpy.utils.register_class(SUB_OP_face_expression_select)
    bpy.utils.register_class(SUB_MT_face_expression)
    bpy.utils.register_class(SUB_OP_face_pose)
    if migrate_expression_storage not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(migrate_expression_storage)
    if not bpy.app.timers.is_registered(migrate_expression_storage):
        bpy.app.timers.register(migrate_expression_storage, first_interval=0.0)


def unregister():
    if bpy.app.timers.is_registered(migrate_expression_storage):
        bpy.app.timers.unregister(migrate_expression_storage)
    if migrate_expression_storage in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(migrate_expression_storage)
    bpy.utils.unregister_class(SUB_MT_face_expression)
    bpy.utils.unregister_class(SUB_OP_face_expression_select)
    del bpy.types.PoseBone.sub_face_strength
    del bpy.types.PoseBone.sub_face_expression
    bpy.utils.unregister_class(SUB_OP_face_pose)
