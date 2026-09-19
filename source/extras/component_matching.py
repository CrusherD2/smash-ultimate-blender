"""Transfer original animation to component controls and keyed residual offsets.

Original curves are sampled before mutation and retained unchanged. Input
helpers isolate the rig from those curves; output offsets retain motion that
cannot be represented by a one-dimensional slider or authored face poses.
"""
import hashlib
import json
import math
import os
import time
from types import SimpleNamespace
import bpy
import numpy as np
from . import component_native
from mathutils import Matrix, Vector, Euler, Quaternion


FINGER_MATCH_ID = 'f'*32


def _prefix(uid):
    if uid == FINGER_MATCH_ID:
        from .finger_sliders import FINGER_CON_PREFIX
        return FINGER_CON_PREFIX
    return 'SUB Component '+uid


def _owned_controls(obj, components):
    ids = {c.uid for c in components}
    hidden_orbits = {c.uid for c in components if c.kind == 'EYES' and not c.show_orbit}
    explicit = [name for c in components for name in getattr(c,'controls',[])]
    return explicit + [p.name for p in obj.pose.bones
            if p.bone.get('sub_component_control')
            and (p.bone.get('sub_face_owner') in ids or p.bone.get('sub_component_id') in ids)
            and not p.bone.get('sub_face_helper')
            and p.bone.get('sub_component_id') not in hidden_orbits]


def _update(context, obj):
    obj.update_tag()
    context.view_layer.update()
    return obj.evaluated_get(context.evaluated_depsgraph_get())


def _matrix_error(actual, wanted):
    # Read each RNA matrix once, not once per matrix element.
    return max(abs(a-b) for ar,br in zip(actual,wanted) for a,b in zip(ar,br))


def _pose_error(evaluated, targets, names):
    bones=evaluated.pose.bones
    return max((_matrix_error(bones[name].matrix,targets[name]) for name in names),default=0)


def _pause_armature_meshes(context, obj):
    """Skip downstream mesh evaluation while matching pose.

    Was muting each mesh's Armature modifier, which still evaluates the rest
    of that mesh's stack every update. mesh_deferral hides the mesh instead,
    dropping it out of the dependency graph, and refuses any mesh the armature
    reads so hiding one cannot change the pose being matched.
    """
    from . import mesh_deferral
    return mesh_deferral.defer(mesh_deferral.deferrable(context, obj))


def _restore_armature_meshes(paused):
    from . import mesh_deferral
    mesh_deferral.restore(paused)


def _helpers(context, obj, owners):
    from .create_animation_rig import _activate_armature
    _activate_armature(context, obj)
    bpy.ops.object.mode_set(mode='EDIT')
    result = {}
    for name, uid in owners.items():
        token = uid[:12] + '_' + hashlib.sha1(name.encode()).hexdigest()[:10]
        names = ('BL_CC_Input_' + token, 'BL_CC_Match_' + token, 'BL_CC_Match2_' + token)
        for index, helper_name in enumerate(names):
            b = obj.data.edit_bones.get(helper_name) or obj.data.edit_bones.new(helper_name)
            b.length = max(obj.data.edit_bones[name].length, .01)
            b.matrix = obj.data.edit_bones[name].matrix if index == 0 else Matrix.Identity(4)
            b.parent = obj.data.edit_bones[name].parent if index == 0 else None
            b.use_deform = False
            b['sub_face_owner'] = uid
            b['sub_face_helper'] = True
            b['sub_match_helper'] = True
        result[name] = names
    bpy.ops.object.mode_set(mode='POSE')
    hidden = obj.data.collections.get('Custom Component Mechanism') or obj.data.collections.new('Custom Component Mechanism')
    hidden.is_visible = False
    for name, names in result.items():
        for helper_name in names:
            pb = obj.pose.bones[helper_name]
            pb.matrix_basis = Matrix.Identity(4)
            pb.bone.hide = pb.bone.hide_select = True
            if hasattr(pb, 'hide'):
                pb.hide = True
            hidden.assign(pb.bone)
        pb = obj.pose.bones[name]
        for label, target in zip(('Input', 'Match', 'Match2'), names):
            con_name = _prefix(owners[name]) + ' ' + label
            con = pb.constraints.get(con_name) or pb.constraints.new('COPY_TRANSFORMS')
            con.name = con_name
            con.target, con.subtarget = obj, target
            con.owner_space = 'POSE'
            con.target_space = 'POSE' if label == 'Input' else 'LOCAL'
            con.mix_mode = 'REPLACE' if label == 'Input' else 'AFTER_FULL'
            con.mute = False
            if label == 'Input':
                pb.constraints.move(list(pb.constraints).index(con), 0)
            else:
                pb.constraints.move(list(pb.constraints).index(con), len(pb.constraints)-1)
    return result


def _split_affine(matrix):
    # Nonuniform scale combined with rotation can require shear. Two keyed
    # TRS offsets preserve the full affine matrix without losing that motion.
    loc,rot,scale=matrix.decompose()
    trs=Matrix.LocRotScale(loc,rot,scale)
    if max(abs(trs[i][j]-matrix[i][j]) for i in range(4) for j in range(4))<1e-6:
        return trs,Matrix.Identity(4)
    u,scale,v=np.linalg.svd(np.array(matrix.to_3x3()))
    if np.linalg.det(u)<0:
        u[:,-1]*=-1
        scale[-1]*=-1
    if np.linalg.det(v)<0:
        v[-1,:]*=-1
        scale[-1]*=-1
    first=Matrix(u.tolist()).to_4x4() @ Matrix.Diagonal((*scale,1))
    first.translation=matrix.translation
    return first,Matrix(v.tolist()).to_4x4()


def _parameter_spec(obj, control_names):
    dofs, bounds, names = [], [], []
    for name in control_names:
        pb = obj.pose.bones[name]
        names.append(name)
        for group, locks in enumerate((pb.lock_location, pb.lock_rotation, pb.lock_scale)):
            for axis, locked in enumerate(locks):
                if locked:
                    continue
                index = group*3+axis
                low, high = (-math.inf, math.inf)
                if group == 0:
                    for con in pb.constraints:
                        if con.type == 'LIMIT_LOCATION' and con.owner_space == 'LOCAL':
                            key = 'xyz'[axis]
                            if getattr(con, 'use_min_'+key):
                                low = getattr(con, 'min_'+key)
                            if getattr(con, 'use_max_'+key):
                                high = getattr(con, 'max_'+key)
                dofs.append((name,index))
                bounds.append((low,high))
    return names, dofs, np.array(bounds).reshape((-1,2))


def _current_bases(obj, names):
    bases={}
    for name in names:
        loc, rot, scale = obj.pose.bones[name].matrix_basis.decompose()
        bases[name] = list(loc) + list(rot.to_euler('XYZ')) + list(scale)
    return bases


def _fit(context, obj, control_names, targets, spec=None, iterations=8, evaluator=None):
    if not control_names or not targets:
        return
    spec_names, dofs, bounds = spec if spec is not None else _parameter_spec(obj, control_names)
    bases = _current_bases(obj, spec_names)
    names = sorted(targets)
    goal = np.array([v for n in names for row in targets[n] for v in row])
    values = np.array([bases[name][index] for name,index in dofs], dtype=float)
    if not len(values):
        return
    def evaluate(x):
        transforms = {n:list(v) for n,v in bases.items()}
        for value,(name,index) in zip(x,dofs):
            transforms[name][index] = float(value)
        for name,v in transforms.items():
            obj.pose.bones[name].matrix_basis = Matrix.LocRotScale(Vector(v[:3]), Euler(v[3:6],'XYZ').to_quaternion(), Vector(v[6:]))
        ev = evaluator() if evaluator else _update(context,obj)
        return np.array([v for n in names for row in ev.pose.bones[n].matrix for v in row])
    values = np.clip(values,bounds[:,0],bounds[:,1])
    current = evaluate(values)
    zero = np.zeros_like(goal)
    for _ in range(iterations):
        residual = goal-current
        if np.max(np.abs(residual)) < 2e-6:
            return
        jacobian = []
        for i in range(len(values)):
            plus = values.copy()
            plus[i] = min(values[i]+1e-3,bounds[i,1])
            width = plus[i]-values[i]
            if width:
                jacobian.append((evaluate(plus)-current)/width)
                continue
            minus = values.copy()
            minus[i] = max(values[i]-1e-3,bounds[i,0])
            width = values[i]-minus[i]
            jacobian.append((current-evaluate(minus))/width if width else zero)
        jacobian = np.array(jacobian).T
        step = np.clip(component_native.lstsq(jacobian, residual),-1,1)
        improved = False
        for factor in (1,.5,.25):
            trial = np.clip(values+step*factor,bounds[:,0],bounds[:,1])
            output = evaluate(trial)
            if np.linalg.norm(goal-output) < np.linalg.norm(residual)-1e-8:
                values,current = trial,output
                improved=True
                break
        if not improved:
            evaluate(values)
            return
    evaluate(values)


def _transform_slider_plan(obj, names, allowed_controls=None):
    """Linear map from TRANSFORM-constraint slider channels to local eulers.

    Built once from constraint ranges; per-frame solve needs no depsgraph.
    Cascade finger windows are skipped (piecewise); residuals absorb them.
    """
    from . import finger_sliders as fingers
    names=sorted(names)
    channels={}
    entries=[]
    for row,name in enumerate(names):
        for con in obj.pose.bones[name].constraints:
            if con.type!='TRANSFORM' or con.target!=obj or not con.subtarget:
                continue
            if 'Cascade' in con.name:
                continue
            if allowed_controls is not None and con.subtarget not in allowed_controls:
                continue
            axis=fingers._slider_loc_axis(con)
            low,high=fingers._constraint_from_range(con,axis)
            if abs(high-low)<1e-8:
                continue
            channel=(con.subtarget,axis)
            channels.setdefault(channel,len(channels))
            for out,key in enumerate('xyz'):
                lo=getattr(con,'to_min_'+key+'_rot')
                hi=getattr(con,'to_max_'+key+'_rot')
                coefficient=(hi-lo)/(high-low)*con.influence
                if coefficient:
                    entries.append((row*3+out,channels[channel],coefficient))
    matrix=np.zeros((len(names)*3,len(channels)))
    for row,col,value in entries:
        matrix[row,col]+=value
    inverse=np.linalg.pinv(matrix,rcond=1e-5) if channels else None
    return names,list(channels),matrix,inverse


def _finger_slider_plan(obj, names):
    from . import finger_sliders as fingers
    controls={con.subtarget for pb in obj.pose.bones for con in pb.constraints
              if con.type=='TRANSFORM' and con.target==obj
              and con.name.startswith(fingers.FINGER_CON_PREFIX) and con.subtarget}
    return _transform_slider_plan(obj, names, allowed_controls=controls or None)


def _transform_goal(obj, poses, plan):
    names,channels,matrix,inverse=plan
    identity=Matrix.Identity(4)
    goal=[]
    for name in names:
        pb=obj.pose.bones[name]
        parent=poses.get(pb.parent.name,identity) if pb.parent else identity
        rest=pb.parent.bone.matrix_local if pb.parent else identity
        local=pb.bone.convert_local_to_pose(poses[name],pb.bone.matrix_local,
            parent_matrix=parent,parent_matrix_local=rest,invert=True)
        goal.extend(local.to_euler('XYZ'))
    return goal


def _fit_transform_sliders(obj, poses, plan, control_names, values=None):
    names,channels,matrix,inverse=plan
    if inverse is None:
        return
    if values is None:
        values=component_native.project(inverse,_transform_goal(obj,poses,plan))
    for name in control_names:
        obj.pose.bones[name].location=(0,0,0)
    for (name,axis),value in zip(channels,values):
        pb=obj.pose.bones[name]
        for con in pb.constraints:
            if con.type=='LIMIT_LOCATION' and con.owner_space=='LOCAL':
                key='xyz'[axis]
                if getattr(con,'use_min_'+key):
                    value=max(value,getattr(con,'min_'+key))
                if getattr(con,'use_max_'+key):
                    value=min(value,getattr(con,'max_'+key))
        pb.location[axis]=float(value)


def _fit_finger_sliders(context,obj,poses,plan,control_names):
    _fit_transform_sliders(obj,poses,plan,control_names)


def _eyes_plan(obj, component):
    from .custom_components import control_name
    data=json.loads(component.face_data)
    poses=data.get('poses',{})
    if not poses:
        return None
    main=control_name(obj,component)
    look=obj.pose.bones.get(main+'_Look') or obj.pose.bones.get(main)
    if look is None:
        return None
    names=[entry.bone for entry in component.bones]
    references={}
    base=[]
    weights=[]
    for name in names:
        pb=obj.pose.bones[name]
        neutral=data['neutral'][name]
        ref=Quaternion(neutral[3:7]).to_euler('XYZ')
        references[name]=ref
        base.extend(list(neutral[:3])+list(ref)+list(neutral[7:]))
        weights.extend([1/max(pb.bone.length,.01)]*3+[1]*6)
    base=np.asarray(base,dtype=float)
    weights=np.asarray(weights,dtype=float)
    columns=[]
    for label in ('Right','Left','Up','Down'):
        pose=poses.get(label)
        if not pose:
            columns.append(np.zeros(len(base)))
            continue
        values=[]
        for name in names:
            v=pose.get(name,data['neutral'][name])
            values.extend(list(v[:3])+list(Quaternion(v[3:7]).to_euler('XYZ',references[name]))+list(v[7:]))
        columns.append((np.asarray(values,dtype=float)-base)*weights)
    matrix=np.column_stack(columns)
    orbit=obj.pose.bones.get(main) if look.name!=main else None
    return look,orbit,names,references,base,weights,matrix


def _match_eyes(obj, poses, plan):
    look,orbit,names,references,base,weights,matrix=plan
    identity=Matrix.Identity(4)
    target=[]
    for name in names:
        pb=obj.pose.bones[name]
        parent=poses.get(pb.parent.name,identity) if pb.parent else identity
        rest=pb.parent.bone.matrix_local if pb.parent else identity
        local=pb.bone.convert_local_to_pose(poses[name],pb.bone.matrix_local,
            parent_matrix=parent,parent_matrix_local=rest,invert=True)
        location,rotation,scale=local.decompose()
        target.extend(list(location)+list(rotation.to_euler('XYZ',references[name]))+list(scale))
    desired=(np.asarray(target,dtype=float)-base)*weights
    best=(float(desired@desired),0.0,0.0)
    for sx,col_x in ((1,0),(-1,1)):
        for sy,col_y in ((1,2),(-1,3)):
            A=np.column_stack((matrix[:,col_x],matrix[:,col_y]))
            if float(np.linalg.norm(A))<1e-12:
                continue
            sol=np.clip(component_native.lstsq(A,desired),0,1)
            residual=desired-A@sol
            error=float(residual@residual)
            if error<best[0]-1e-12:
                best=(error,sx*float(sol[0]),sy*float(sol[1]))
    if orbit is not None and orbit.name!=look.name:
        orbit.location=(0,0,0)
    look.location=(best[1],best[2],0.0)
    for con in look.constraints:
        if con.type!='LIMIT_LOCATION' or con.owner_space!='LOCAL':
            continue
        for axis,key in enumerate('xyz'):
            value=look.location[axis]
            if getattr(con,'use_min_'+key):
                value=max(value,getattr(con,'min_'+key))
            if getattr(con,'use_max_'+key):
                value=min(value,getattr(con,'max_'+key))
            look.location[axis]=value
    return look.name


def _look_target_jobs(obj, components):
    from .custom_components import control_name
    jobs=[]
    for c in components:
        if c.kind!='LOOK_TARGET':
            continue
        name=control_name(obj,c)
        if name not in obj.pose.bones:
            continue
        bones=[(b.bone,abs(getattr(b,'weight',1.0) or 1.0)) for b in c.bones if b.bone in obj.pose.bones]
        if bones:
            jobs.append((name,bones,c.aim_axis))
    return jobs


def _match_look_target(obj, control_name, bones, aim_axis, poses, setter=None):
    axis=Vector((0.0,0.0,0.0))
    axis['XYZ'.index(aim_axis[-1])]=-1.0 if aim_axis.startswith('NEG_') else 1.0
    points=[]
    weights=[]
    for bone_name,weight in bones:
        if weight<1e-8 or bone_name not in poses:
            continue
        matrix=poses[bone_name]
        direction=(matrix.to_3x3()@axis)
        if direction.length<1e-12:
            continue
        direction.normalize()
        rest=max((obj.data.bones[control_name].head_local-obj.data.bones[bone_name].head_local).length,
                 obj.data.bones[bone_name].length,1e-3)
        points.append(matrix.translation+direction*rest)
        weights.append(weight)
    if not points:
        return
    target=Vector(component_native.project(np.asarray(weights,dtype=float).reshape(1,-1)/sum(weights),np.asarray(points).T)[:,0])
    pb=obj.pose.bones[control_name]
    orient=(pb.bone.matrix_local.to_3x3()).to_quaternion()
    wanted=Matrix.LocRotScale(target,orient,Vector((1.0,1.0,1.0)))
    if setter:
        setter(control_name,wanted)
    else:
        pb.matrix=wanted


def _expression_plan(obj,component):
    from .custom_components import control_name
    from .face_components import expression_checkpoints
    data=json.loads(component.face_data)
    main=obj.pose.bones.get(control_name(obj,component))
    if main is None or 'sub_expression_labels' not in main:
        return None
    names=[entry.bone for entry in component.bones]
    references={}
    base=[]
    weights=[]
    for name in names:
        pb=obj.pose.bones[name]
        neutral=data['neutral'][name]
        ref=Quaternion(neutral[3:7]).to_euler('XYZ')
        references[name]=ref
        base.extend(list(neutral[:3])+list(ref)+list(neutral[7:]))
        weights.extend([1/max(pb.bone.length,.01)]*3+[1]*6)
    labels=json.loads(main['sub_expression_labels'])
    segments=[]
    for label in data.get('poses',{}):
        previous=np.zeros(len(base))
        low=0.0
        index=labels.index(label)+1
        for high,pose in expression_checkpoints(data,label)[1:]:
            values=[]
            for name in names:
                v=pose.get(name,data['neutral'][name])
                values.extend(list(v[:3])+list(Quaternion(v[3:7]).to_euler('XYZ',references[name]))+list(v[7:]))
            endpoint=(np.asarray(values)-np.asarray(base))*np.asarray(weights)
            segments.append((index,low,high,previous.copy(),endpoint.copy()))
            previous,low=endpoint,high
    controls=[p for p in obj.pose.bones
              if p.bone.get('sub_face_owner')==component.uid and p.bone.get('sub_component_control')]
    return main,names,references,np.asarray(base),np.asarray(weights),segments,controls


def _expression_goal(obj, poses, plan):
    main,names,references,base,weights,segments,controls=plan
    identity=Matrix.Identity(4)
    target=[]
    for name in names:
        pb=obj.pose.bones[name]
        parent=poses.get(pb.parent.name,identity) if pb.parent else identity
        rest=pb.parent.bone.matrix_local if pb.parent else identity
        local=pb.bone.convert_local_to_pose(poses[name],pb.bone.matrix_local,
            parent_matrix=parent,parent_matrix_local=rest,invert=True)
        location,rotation,scale=local.decompose()
        target.extend(list(location)+list(rotation.to_euler('XYZ',references[name]))+list(scale))
    desired=(np.asarray(target)-base)*weights
    return desired


def _match_expression(context,obj,component,poses,plan=None,solution=None):
    from .face_components import expression_set
    plan=_expression_plan(obj,component) if plan is None else plan
    if plan is None:
        return None
    main,names,references,base,weights,segments,controls=plan
    error,index,strength=component_native.expressions(segments,_expression_goal(obj,poses,plan)) if solution is None else solution
    best=(float(error),int(index),float(strength))
    for pb in controls:
        pb.location=(0,0,0)
    expression_set(main,best[1])
    main.location.y=best[2]
    return main.name,best[1],best[2]


def _match_slice_seconds():
    # bpy and the depsgraph are not thread-safe. Yield often enough that
    # Windows still pumps the UI, without starving the match of CPU.
    cores=os.cpu_count() or 4
    return 0.04 if cores>=8 else 0.05


def match_animation(context, obj, start, end, include_fingers=False, match_ik=True, fingers_only=False):
    result=None
    for event in match_animation_steps(context,obj,start,end,include_fingers,match_ik,fingers_only):
        if event[0]=='done':
            result=event[1]
    return result


def match_animation_steps(context, obj, start, end, include_fingers=False, match_ik=True, fingers_only=False):
    from .component_workflow import definitions
    from . import ik_channels, anim_layers_compat, ik_match_fast
    from .create_animation_rig import _activate_armature, _disable_autokey, defer_pose_tool_updates, ProgressCursor
    from ..anim.fcurve_bulk import PoseKeyWriter
    from ..anim.fcurve_compat import get_all_action_fcurves
    components = [] if fingers_only else definitions(obj)
    if include_fingers:
        from . import finger_sliders as fingers
        pairs=list(fingers._iter_finger_slider_constraints(obj))
        names={pb.name for pb,con in pairs}
        control_names={con.subtarget for pb,con in pairs
                       if con.type == 'TRANSFORM' and con.target == obj}
        if names and control_names:
            components.append(SimpleNamespace(uid=FINGER_MATCH_ID, kind='FINGERS',
                bones=[SimpleNamespace(bone=n) for n in sorted(names)],
                controls=sorted(control_names)))
    if not components:
        raise ValueError('Build custom components first')
    if anim_layers_compat.viewport_driving_action(obj)[0] is None:
        raise ValueError('Select the original animation action first')
    non_ik = [c for c in components if c.kind != 'IK']
    all_owners = {b.bone:c.uid for c in non_ik for b in c.bones}
    isolated_ids={c.uid for c in non_ik if c.kind=='ISOLATED'}
    isolated={n:uid for n,uid in all_owners.items() if uid in isolated_ids}
    finger_names={n for n,uid in all_owners.items() if uid==FINGER_MATCH_ID}
    owners={n:uid for n,uid in all_owners.items() if uid not in isolated_ids and uid!=FINGER_MATCH_ID}
    controls = _owned_controls(obj,non_ik)
    if owners and not controls:
        raise ValueError('Rebuild the custom components before matching')
    if any(n not in obj.pose.bones for n in all_owners):
        raise ValueError('A controlled bone is missing; update the component assignments')
    scene, frame = context.scene, context.scene.frame_current
    _activate_armature(context,obj)
    muted = [(con,con.mute) for pb in obj.pose.bones for con in pb.constraints
             if any(con.name.startswith(_prefix(c.uid)) for c in non_ik)]
    residual_frames=0
    bone_names=set(obj.data.bones.keys())
    constraints={p.name:{con.as_pointer() for con in p.constraints} for p in obj.pose.bones}
    old_bases={p.name:p.matrix_basis.copy() for p in obj.pose.bones}
    old_helpers={p.name:p.bone.matrix_local.copy() for p in obj.pose.bones if p.bone.get('sub_match_helper')}
    source_action=anim_layers_compat.viewport_driving_action(obj)[0]
    backup=source_action.copy()
    success=False
    paused=[]
    native_graph=None
    try:
        with ProgressCursor(context) as progress, _disable_autokey(context), defer_pose_tool_updates(), anim_layers_compat.anim_layers_paused(), anim_layers_compat.bind_driving_action_for_bake(obj,context), ik_match_fast.suspend_viewport_handlers():
            paused=_pause_armature_meshes(context, obj)
            sample_names=set(all_owners)
            for name in list(sample_names):
                pb=obj.pose.bones.get(name)
                while pb and pb.parent:
                    sample_names.add(pb.parent.name)
                    pb=pb.parent
            samples={}
            for con,_ in muted:
                con.mute=True
            try:
                frames=range(start,end+1)
                detached=None
                if all_owners and end>start:
                    from ..anim.fcurve_compat import get_fcurves_for_assigned_slot
                    detached=ik_match_fast.sample_fk(obj,frames,sample_names,
                        get_fcurves_for_assigned_slot(obj))
                if detached is not None:
                    samples=detached
                    progress.update(.15)
                else:
                    for f in frames:
                        scene.frame_set(f)
                        ev=_update(context,obj)
                        samples[f]={n:ev.pose.bones[n].matrix.copy() for n in sample_names}
                        progress.update(.15*(f-start+1)/max(1,end-start+1))
            finally:
                for con,state in muted:
                    con.mute=state
            targets={r['target'] for r in json.loads(obj.get('sub_custom_ik_chains','[]')) if r.get('component_id') in {c.uid for c in components if c.kind=='IK'}}
            if targets and match_ik:
                _restore_armature_meshes(paused)
                paused=[]
                old_range=(scene.frame_start,scene.frame_end)
                try:
                    scene.frame_start,scene.frame_end=start,end
                    ik_channels.match(context,obj,entire=True,key=True,_targets=targets)
                finally:
                    scene.frame_start,scene.frame_end=old_range
                paused=_pause_armature_meshes(context, obj)
            yield ('progress',.2,'Matching components')
            # Isolated controls have a full transform: match them directly.
            # Old residual offsets must not move the foot away from its handle.
            obsolete=set()
            for n,uid in isolated.items():
                for con in obj.pose.bones[n].constraints:
                    if con.name.startswith(_prefix(uid)) and con.name != _prefix(uid):
                        con.mute=True
                        obsolete.add(con.as_pointer())
            for n in finger_names:
                for con in obj.pose.bones[n].constraints:
                    if con.name in {_prefix(FINGER_MATCH_ID)+' '+label for label in ('Input','Match','Match2')}:
                        con.mute=True
                        obsolete.add(con.as_pointer())
            finger_controls={name for c in non_ik if c.uid==FINGER_MATCH_ID for name in c.controls}
            finger_plan=_finger_slider_plan(obj,finger_names) if finger_names else None
            helpers=_helpers(context,obj,owners)
            expressions=[c for c in non_ik if c.kind in {'LIDS','MOUTH'}]
            eyes=[c for c in non_ik if c.kind=='EYES']
            expression_ids={c.uid for c in expressions}
            eyes_ids={c.uid for c in eyes}
            expression_names={b.bone for c in expressions for b in c.bones}
            eyes_names={b.bone for c in eyes for b in c.bones}
            look_ids={c.uid for c in non_ik if c.kind=='LOOK_TARGET'}
            look_names={b.bone for c in non_ik if c.kind=='LOOK_TARGET' for b in c.bones}
            look_jobs=_look_target_jobs(obj,non_ik)
            look_controls={name for name,_,_ in look_jobs}
            expression_plans=[_expression_plan(obj,c) for c in expressions]
            eyes_plans=[plan for plan in (_eyes_plan(obj,c) for c in eyes) if plan]
            # TRANSFORM sliders (jaw/rotation/etc): same closed-form path as fingers.
            transform_names=(set(owners)-expression_names-eyes_names-look_names-finger_names)
            transform_controls=[n for n in controls
                if n not in finger_controls and n not in look_controls
                and obj.data.bones[n].get('sub_face_owner') not in isolated_ids
                and obj.data.bones[n].get('sub_face_owner') not in expression_ids
                and obj.data.bones[n].get('sub_face_owner') not in eyes_ids
                and obj.data.bones[n].get('sub_component_id') not in look_ids]
            transform_plan=_transform_slider_plan(obj,transform_names,allowed_controls=set(transform_controls)) if transform_names and transform_controls else None
            covered={name for name,_ in (transform_plan[1] if transform_plan and transform_plan[3] is not None else [])}
            # Jacobian only for controls the linear TRANSFORM map cannot drive.
            fit_controls=[n for n in transform_controls if n not in covered]
            fit_names_fallback=set(transform_names) if fit_controls else set()
            fit_spec=_parameter_spec(obj,fit_controls) if fit_controls else None
            selector_curves=[]
            face_control_ids=expression_ids|eyes_ids
            for fc in get_all_action_fcurves(obj.animation_data.action,id_type='OBJECT'):
                if any(fc.data_path.startswith(obj.pose.bones[n].path_from_id()+'.') for n in controls
                       if obj.data.bones[n].get('sub_face_owner') in face_control_ids):
                    selector_curves.append((fc,fc.mute))
                    fc.mute=True
            isolated_jobs=[]
            for n,uid in isolated.items():
                con=obj.pose.bones[n].constraints.get(_prefix(uid))
                if not con or con.type!='COPY_TRANSFORMS':
                    raise ValueError('Rebuild the isolated component before matching')
                output=obj.pose.bones[con.subtarget]
                root=output
                while root.parent and root.bone.get('sub_face_owner')==uid:
                    root=root.parent
                chain=[]
                child=output
                while child!=root:
                    chain.append(child)
                    child=child.parent
                isolated_jobs.append((n,output,root,chain))
            for n,output,root,chain in isolated_jobs:
                for child in chain:
                    child.matrix_basis=Matrix.Identity(4)
            isolated_offsets={}
            if isolated_jobs:
                ev=_update(context,obj)
                for n,output,root,chain in isolated_jobs:
                    isolated_offsets[n]=component_native.relative(ev.pose.bones[root.name].matrix,ev.pose.bones[output.name].matrix)
            writer=PoseKeyWriter(obj)
            choices=PoseKeyWriter(obj,interpolation='CONSTANT')
            # Parent-first offsets: child targets must see the corrected parent.
            ordered=sorted(owners,key=lambda n:len(obj.pose.bones[n].parent_recursive))
            levels={}
            for n in ordered:
                levels.setdefault(len(obj.pose.bones[n].parent_recursive),[]).append(n)
            # Solve detached targets in bounded frame batches. Rayon only sees
            # numbers; each batch yields before Blender control writes resume.
            finger_solutions={}
            transform_solutions={}
            expression_solutions={}
            sample_items=list(samples.items())
            for offset in range(0,len(sample_items),128):
                batch=sample_items[offset:offset+128]
                for plan,cache in ((finger_plan,finger_solutions),(transform_plan,transform_solutions)):
                    if plan and plan[3] is not None:
                        goals=[_transform_goal(obj,poses,plan) for _,poses in batch]
                        solved=component_native.project(plan[3],goals)
                        cache.update((f,value) for (f,_),value in zip(batch,solved))
                for component,plan in zip(expressions,expression_plans):
                    if plan:
                        goals=[_expression_goal(obj,poses,plan) for _,poses in batch]
                        solved=component_native.expressions(plan[5],goals)
                        expression_solutions.update(((component.uid,f),value) for (f,_),value in zip(batch,solved))
                yield ('progress',.2,'Solving component targets')
            from . import component_graph
            native_graph=component_graph.capture_for_match(obj,all_owners,controls,sample_names,lambda: _update(context,obj))
            for f,poses in samples.items():
                scene.frame_set(f)
                if native_graph:
                    native_graph.samples=poses
                retry_bases={n:obj.pose.bones[n].matrix_basis.copy() for n in
                    set(controls)|finger_names|{n for pair in helpers.values() for n in pair}} if native_graph else {}
                for attempt in range(len(set(all_owners.values()))+2):
                    evaluate=native_graph.evaluate if native_graph else lambda: _update(context,obj)
                    failed_names=[]
                    try:
                        for pair in helpers.values():
                            for name in pair:
                                obj.pose.bones[name].matrix_basis=Matrix.Identity(4)
                        for n in finger_names:
                            obj.pose.bones[n].matrix_basis=Matrix.Identity(4)
                        frame_choices=[]
                        for component,plan in zip(expressions,expression_plans):
                            choice=_match_expression(context,obj,component,poses,plan,expression_solutions.get((component.uid,f)))
                            if choice:
                                name,index,strength=choice
                                frame_choices.append((name,index,strength))
                        for plan in eyes_plans:
                            _match_eyes(obj,poses,plan)
                        if transform_plan:
                            _fit_transform_sliders(obj,poses,transform_plan,transform_controls,transform_solutions.get(f))
                        for control,bones,aim in look_jobs:
                            _match_look_target(obj,control,bones,aim,poses,setter=native_graph.set_pose if native_graph else None)
                        if fit_controls and fit_names_fallback:
                            _fit(context,obj,fit_controls,{n:poses[n] for n in fit_names_fallback},spec=fit_spec,evaluator=evaluate)
                        if finger_plan:
                            _fit_transform_sliders(obj,poses,finger_plan,finger_controls,finger_solutions.get(f))
                        # Evaluate the neutral circles with the fitted sliders once.
                        # Desired parent matrices are already sampled, so every joint's
                        # local correction can be calculated before changing the scene.
                        if finger_names:
                            ev=evaluate()
                            corrections={}
                            for n in finger_names:
                                pb=obj.pose.bones[n]
                                parent=ev.pose.bones[pb.parent.name].matrix if pb.parent else Matrix.Identity(4)
                                wanted_parent=poses.get(pb.parent.name,parent) if pb.parent else parent
                                rest_parent=pb.parent.bone.matrix_local if pb.parent else Matrix.Identity(4)
                                def local(m,parent_matrix):
                                    return pb.bone.convert_local_to_pose(m,pb.bone.matrix_local,
                                        parent_matrix=parent_matrix,parent_matrix_local=rest_parent,invert=True)
                                contribution=local(ev.pose.bones[n].matrix,parent)
                                wanted=local(poses[n],wanted_parent)
                                active=[c for c in pb.constraints if not c.mute and c.influence]
                                if active and all(c.type=='TRANSFORM' and c.map_to=='ROTATION'
                                        and c.mix_mode_rot=='AFTER' and c.influence==1.0
                                        and c.owner_space=='LOCAL' for c in active):
                                    # AFTER rotates the normalized basis and restores its
                                    # scale. A full matrix inverse incorrectly rotates
                                    # nonuniform scale, forcing iterative fitting per joint.
                                    location,rotation,scale=wanted.decompose()
                                    rotation=rotation @ contribution.to_quaternion().inverted()
                                    corrections[n]=Matrix.LocRotScale(location,rotation,scale)
                                else:
                                    corrections[n]=wanted @ contribution.inverted_safe()
                            for n,basis in corrections.items():
                                obj.pose.bones[n].matrix_basis=basis
                            ev=evaluate()
                            # Verify all joints together. Unusual constraint stacks or
                            # non-TRS transforms retain the existing precise fallback.
                            # Keep a margin below the final 2e-4 pose check, but do not
                            # iteratively fit float32 noise at the old 2e-6 threshold.
                            for n in sorted(finger_names,key=lambda n:len(obj.pose.bones[n].parent_recursive)):
                                if _matrix_error(ev.pose.bones[n].matrix,poses[n])<=1e-4:
                                    continue
                                pb=obj.pose.bones[n]
                                locks=(tuple(pb.lock_location),tuple(pb.lock_rotation),tuple(pb.lock_scale))
                                try:
                                    pb.lock_location=pb.lock_rotation=pb.lock_scale=(False,False,False)
                                    _fit(context,obj,[n],{n:poses[n]},evaluator=evaluate)
                                    ev=evaluate()
                                finally:
                                    pb.lock_location,pb.lock_rotation,pb.lock_scale=locks
                        for n,output,root,chain in isolated_jobs:
                            for child in chain:
                                child.matrix_basis=Matrix.Identity(4)
                            wanted=poses[n] @ isolated_offsets[n].inverted_safe()
                            if native_graph:
                                native_graph.set_pose(root.name,wanted)
                            else:
                                root.matrix=wanted
                        extra=False
                        # One eval after analytic controls. Parent residuals are applied in
                        # math so children see corrected parents without per-level updates.
                        if not finger_names or isolated_jobs:
                            ev=evaluate()
                        corrected={}
                        # Consume the evaluation before changing any residuals.
                        # Hybrid graphs evaluate a component only when requested.
                        if owners:
                            residual_names=set(all_owners)|{obj.pose.bones[n].parent.name for n in owners if obj.pose.bones[n].parent}
                            ev=SimpleNamespace(pose=SimpleNamespace(bones={
                                n:SimpleNamespace(matrix=ev.pose.bones[n].matrix.copy()) for n in residual_names}))
                        for depth in sorted(levels):
                            for name in levels[depth]:
                                pb=obj.pose.bones[name]
                                if pb.parent and pb.parent.name in corrected:
                                    rest_parent=pb.parent.bone.matrix_local
                                    parent_ev=ev.pose.bones[pb.parent.name].matrix
                                    def _local(matrix,parent_matrix,bone=pb,rest=rest_parent):
                                        return bone.bone.convert_local_to_pose(matrix,bone.bone.matrix_local,
                                            parent_matrix=parent_matrix,parent_matrix_local=rest,invert=True)
                                    contribution=_local(ev.pose.bones[name].matrix,parent_ev)
                                    current=pb.bone.convert_local_to_pose(contribution,pb.bone.matrix_local,
                                        parent_matrix=corrected[pb.parent.name],parent_matrix_local=rest_parent,invert=False)
                                    delta=component_native.relative(current,poses[name])
                                else:
                                    delta=component_native.relative(ev.pose.bones[name].matrix,poses[name])
                                first,second=_split_affine(delta)
                                obj.pose.bones[helpers[name][1]].matrix_basis=first
                                obj.pose.bones[helpers[name][2]].matrix_basis=second
                                corrected[name]=poses[name]
                                extra |= max(abs(delta[i][j]-(1 if i==j else 0)) for i in range(4) for j in range(4))>1e-4
                        if helpers:
                            ev=evaluate()
                        error=_pose_error(ev,poses,all_owners)
                        if error>2e-4:
                            # Parent-propagated residuals missed a constraint coupling; fall back.
                            for pair in helpers.values():
                                for name in pair[1:]:
                                    obj.pose.bones[name].matrix_basis=Matrix.Identity(4)
                            for depth in sorted(levels):
                                ev=evaluate()
                                for name in levels[depth]:
                                    delta=component_native.relative(ev.pose.bones[name].matrix,poses[name])
                                    first,second=_split_affine(delta)
                                    obj.pose.bones[helpers[name][1]].matrix_basis=first
                                    obj.pose.bones[helpers[name][2]].matrix_basis=second
                            ev=evaluate()
                            error=_pose_error(ev,poses,all_owners)
                            if error>2e-4:
                                raise ValueError(f'Matching cannot preserve the pose at frame {f} (error {error:.5g}, bone {max(all_owners,key=lambda n:max(abs(ev.pose.bones[n].matrix[i][j]-poses[n][i][j]) for i in range(4) for j in range(4)))})')
                        if native_graph and native_graph.graphs:
                            actual=_update(context,obj)
                            error=_pose_error(actual,poses,all_owners)
                            if error>2e-4:
                                failed_names=[n for n in all_owners if _matrix_error(actual.pose.bones[n].matrix,poses[n])>2e-4]
                                raise ValueError(f'Native graph pose verification failed: {error:.6g}')
                            component_graph.LAST_DIAGNOSTICS['native_frames']+=1
                        else:
                            component_graph.LAST_DIAGNOSTICS['reference_frames']=component_graph.LAST_DIAGNOSTICS.get('reference_frames',0)+1
                        break
                    except ValueError as exc:
                        if native_graph is None or not native_graph.graphs:
                            raise
                        component_graph.LAST_DIAGNOSTICS['fallback_frames']+=1
                        component_graph.LAST_DIAGNOSTICS['fallback_reason']=str(exc)
                        native_graph.reject(failed_names,str(exc))
                        # Reset animated state before the reference path retries.
                        for name,basis in retry_bases.items():
                            obj.pose.bones[name].matrix_basis=basis
                        scene.frame_set(f)
                for name,index,strength in frame_choices:
                    path=obj.pose.bones[name].path_from_id()
                    choices.stash_channel(path+'.sub_face_expression',0,f,index,name)
                    writer.stash_channel(path+'.location',1,f,strength,name)
                residual_frames += int(extra)
                progress.update(.2+.75*(f-start+1)/max(1,end-start+1))
                for name in controls+sorted(finger_names)+[n for pair in helpers.values() for n in pair]:
                    writer.stash_pose_bone(obj.pose.bones[name],f)
                yield ('progress',.2+.75*(f-start+1)/max(1,end-start+1),f'Matching frame {f}')
            # Existing control modifiers must not be applied again to sampled keys.
            paths={obj.pose.bones[n].path_from_id()+'.' for n in controls+sorted(finger_names)+[n for pair in helpers.values() for n in pair]}
            action=obj.animation_data.action
            for fc in get_all_action_fcurves(action,id_type='OBJECT'):
                if any(fc.data_path.startswith(path) for path in paths):
                    for mod in list(fc.modifiers):
                        fc.modifiers.remove(mod)
            writer.flush()
            choices.flush()
            progress.update(1)
            success=True
            yield ('done',(len(components),residual_frames))
    except GeneratorExit:
        from ..blender_compat import assign_action
        for pb in obj.pose.bones:
            old=constraints.get(pb.name,set())
            for con in list(pb.constraints):
                if con.as_pointer() not in old:
                    pb.constraints.remove(con)
        try:
            bpy.ops.object.mode_set(mode='EDIT')
            for n in set(obj.data.edit_bones.keys())-bone_names:
                obj.data.edit_bones.remove(obj.data.edit_bones[n])
            for n,matrix in old_helpers.items():
                obj.data.edit_bones[n].matrix=matrix
            bpy.ops.object.mode_set(mode='POSE')
            for n,matrix in old_bases.items():
                obj.pose.bones[n].matrix_basis=matrix
            backup.name=source_action.name+'_Recovered'
            assign_action(obj.animation_data,backup)
        except Exception:
            pass
        raise
    except Exception:
        # A failed fit must not leave an unkeyed input override on the skeleton.
        from ..blender_compat import assign_action
        for pb in obj.pose.bones:
            old=constraints.get(pb.name,set())
            for con in list(pb.constraints):
                if con.as_pointer() not in old:
                    pb.constraints.remove(con)
        bpy.ops.object.mode_set(mode='EDIT')
        for n in set(obj.data.edit_bones.keys())-bone_names:
            obj.data.edit_bones.remove(obj.data.edit_bones[n])
        for n,matrix in old_helpers.items():
            obj.data.edit_bones[n].matrix=matrix
        bpy.ops.object.mode_set(mode='POSE')
        for n,matrix in old_bases.items():
            obj.pose.bones[n].matrix_basis=matrix
        # IK may already have written keys. Restore an untouched action copy.
        backup.name=source_action.name+'_Recovered'
        assign_action(obj.animation_data,backup)
        raise
    finally:
        if native_graph:
            native_graph.close()
        _restore_armature_meshes(paused)
        for fc,state in locals().get('selector_curves',[]):
            try: fc.mute=state
            except ReferenceError: pass
        if success:
            bpy.data.actions.remove(backup)
        for con,state in muted:
            try:
                con.mute=True if success and con.as_pointer() in locals().get('obsolete',set()) else state
            except ReferenceError:
                pass
        scene.frame_set(frame)


class SUB_OP_components_match(bpy.types.Operator):
    bl_idname='sub.components_match'
    bl_label='Match Custom Components to Animation'
    bl_description='Transfer the original bone animation to custom controls; preserve extra motion in hidden keyed offsets. Esc cancels.'
    bl_options={'REGISTER','UNDO'}
    start: bpy.props.IntProperty(name='Start Frame')
    end: bpy.props.IntProperty(name='End Frame')

    def invoke(self,context,event):
        self.start,self.end=context.scene.frame_start,context.scene.frame_end
        return context.window_manager.invoke_props_dialog(self,width=320)

    def draw(self,context):
        self.layout.label(text='Match the current action to all components.')
        self.layout.prop(self,'start')
        self.layout.prop(self,'end')
        self.layout.label(text='Original bone keyframes are kept.')
        self.layout.label(text='Esc cancels. The UI stays responsive while matching.')

    def execute(self,context):
        from .create_animation_rig import find_target_armature
        obj=find_target_armature(context)
        if not obj or self.end<self.start:
            self.report({'ERROR'},'Select a rig and a valid frame range')
            return {'CANCELLED'}
        self._steps=match_animation_steps(context,obj,self.start,self.end,include_fingers=True)
        wm=context.window_manager
        self._timer=wm.event_timer_add(0.0,window=context.window)
        wm.modal_handler_add(self)
        try:
            context.window.cursor_modal_set('WAIT')
        except Exception:
            pass
        return {'RUNNING_MODAL'}

    def modal(self,context,event):
        if event.type in {'ESC','RIGHTMOUSE'}:
            self._cancel(context)
            self.report({'WARNING'},'Component matching cancelled')
            return {'CANCELLED'}
        if event.type!='TIMER':
            return {'RUNNING_MODAL'}
        deadline=time.perf_counter()+_match_slice_seconds()
        try:
            while time.perf_counter()<deadline:
                item=next(self._steps)
                if item[0]=='progress':
                    try:
                        context.workspace.status_text_set(item[2])
                    except Exception:
                        pass
                elif item[0]=='done':
                    count,extra=item[1]
                    try:
                        while True:
                            next(self._steps)
                    except StopIteration:
                        pass
                    self._finish(context,close=False)
                    self.report({'INFO'},f'Matched {count} components. Extra motion preserved on {extra} frames.')
                    return {'FINISHED'}
        except StopIteration:
            self._finish(context,close=False)
            return {'FINISHED'}
        except (ValueError,RuntimeError) as exc:
            self._finish(context,close=False)
            self.report({'ERROR'},str(exc))
            return {'CANCELLED'}
        return {'RUNNING_MODAL'}

    def _cancel(self,context):
        steps=getattr(self,'_steps',None)
        if steps is not None:
            try:
                steps.close()
            except Exception:
                pass
        self._finish(context,close=False)

    def _finish(self,context,close=True):
        wm=context.window_manager
        if getattr(self,'_timer',None) is not None:
            wm.event_timer_remove(self._timer)
            self._timer=None
        if close:
            steps=getattr(self,'_steps',None)
            if steps is not None:
                try:
                    steps.close()
                except Exception:
                    pass
        self._steps=None
        try:
            context.window.cursor_modal_restore()
            context.workspace.status_text_set(None)
        except Exception:
            pass


def register():
    bpy.utils.register_class(SUB_OP_components_match)


def unregister():
    bpy.utils.unregister_class(SUB_OP_components_match)
