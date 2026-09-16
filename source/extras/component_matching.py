"""Transfer original animation to component controls and keyed residual offsets.

Original curves are sampled before mutation and retained unchanged. Input
helpers isolate the rig from those curves; output offsets retain motion that
cannot be represented by a one-dimensional slider or authored face poses.
"""
import hashlib
import json
import math
import bpy
import numpy as np
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


def _parameters(obj, control_names):
    values, dofs, bounds, bases = [], [], [], {}
    for name in control_names:
        pb = obj.pose.bones[name]
        loc, rot, scale = pb.matrix_basis.decompose()
        bases[name] = list(loc) + list(rot.to_euler('XYZ')) + list(scale)
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
                values.append(bases[name][index])
                bounds.append((low,high))
    return np.array(values), dofs, np.array(bounds).reshape((-1,2)), bases


def _fit(context, obj, control_names, targets):
    values, dofs, bounds, bases = _parameters(obj, control_names)
    names = sorted(targets)
    goal = np.array([v for n in names for row in targets[n] for v in row])
    def evaluate(x):
        transforms = {n:list(v) for n,v in bases.items()}
        for value,(name,index) in zip(x,dofs):
            transforms[name][index] = float(value)
        for name,v in transforms.items():
            obj.pose.bones[name].matrix_basis = Matrix.LocRotScale(Vector(v[:3]), Euler(v[3:6],'XYZ').to_quaternion(), Vector(v[6:]))
        ev = _update(context,obj)
        return np.array([v for n in names for row in ev.pose.bones[n].matrix for v in row])
    values = np.clip(values,bounds[:,0],bounds[:,1])
    current = evaluate(values)
    for _ in range(16):
        residual = goal-current
        if not len(values) or np.max(np.abs(residual)) < 2e-6:
            break
        jacobian = []
        for i in range(len(values)):
            plus,minus = values.copy(),values.copy()
            plus[i] = min(values[i]+1e-3,bounds[i,1])
            minus[i] = max(values[i]-1e-3,bounds[i,0])
            width = plus[i]-minus[i]
            jacobian.append((evaluate(plus)-evaluate(minus))/width if width else np.zeros_like(goal))
        jacobian = np.array(jacobian).T
        step = np.linalg.lstsq(jacobian, residual, rcond=1e-5)[0]
        # Large jumps make rotation fitting oscillate around equivalent poses.
        step = np.clip(step,-1,1)
        improved = False
        for factor in (1,.5,.25,.125):
            trial = np.clip(values+step*factor,bounds[:,0],bounds[:,1])
            output = evaluate(trial)
            if np.linalg.norm(goal-output) < np.linalg.norm(residual)-1e-8:
                values,current = trial,output
                improved=True
                break
        if not improved:
            break
    evaluate(values)


def _finger_slider_plan(obj, names):
    """Precompute the linear curl/spread mapping once, without scene probes."""
    from . import finger_sliders as fingers
    names=sorted(names)
    channels={}
    entries=[]
    for row,name in enumerate(names):
        for con in obj.pose.bones[name].constraints:
            if con.type!='TRANSFORM' or not con.name.startswith(fingers.FINGER_CON_PREFIX) or con.target!=obj:
                continue
            # A neutral cascade avoids its piecewise discontinuities. Shared
            # curl, per-finger offset, spread and thumb side are fitted together.
            if 'Cascade' in con.name: continue
            axis=fingers._slider_loc_axis(con)
            low,high=fingers._constraint_from_range(con,axis)
            if abs(high-low)<1e-8: continue
            channel=(con.subtarget,axis)
            channels.setdefault(channel,len(channels))
            for out,key in enumerate('xyz'):
                lo=getattr(con,'to_min_'+key+'_rot')
                hi=getattr(con,'to_max_'+key+'_rot')
                coefficient=(hi-lo)/(high-low)*con.influence
                if coefficient: entries.append((row*3+out,channels[channel],coefficient))
    matrix=np.zeros((len(names)*3,len(channels)))
    for row,col,value in entries: matrix[row,col]+=value
    inverse=np.linalg.pinv(matrix,rcond=1e-5) if channels else None
    return names,list(channels),matrix,inverse


def _fit_finger_sliders(context,obj,poses,plan,control_names):
    names,channels,matrix,inverse=plan
    if inverse is None: return
    ev=_update(context,obj)
    goal=[]
    for name in names:
        pb=obj.pose.bones[name]
        parent=(poses.get(pb.parent.name,ev.pose.bones[pb.parent.name].matrix)
                if pb.parent else Matrix.Identity(4))
        rest=pb.parent.bone.matrix_local if pb.parent else Matrix.Identity(4)
        local=pb.bone.convert_local_to_pose(poses[name],pb.bone.matrix_local,
            parent_matrix=parent,parent_matrix_local=rest,invert=True)
        goal.extend(local.to_euler('XYZ'))
    values=inverse@np.asarray(goal)
    for name in control_names:
        obj.pose.bones[name].location=(0,0,0)
    for (name,axis),value in zip(channels,values):
        pb=obj.pose.bones[name]
        for con in pb.constraints:
            if con.type=='LIMIT_LOCATION' and con.owner_space=='LOCAL':
                key='xyz'[axis]
                if getattr(con,'use_min_'+key): value=max(value,getattr(con,'min_'+key))
                if getattr(con,'use_max_'+key): value=min(value,getattr(con,'max_'+key))
        pb.location[axis]=float(value)


def _match_expression(context,obj,component,poses):
    from .custom_components import control_name
    from .face_components import expression_set
    data=json.loads(component.face_data)
    main=obj.pose.bones.get(control_name(obj,component))
    if main is None or 'sub_expression_labels' not in main:
        return None
    names=[entry.bone for entry in component.bones]
    ev=_update(context,obj)
    base=[]
    target=[]
    references={}
    weights=[]
    for name in names:
        pb=obj.pose.bones[name]
        neutral=data['neutral'][name]
        ref=Quaternion(neutral[3:7]).to_euler('XYZ')
        references[name]=ref
        base.extend(list(neutral[:3])+list(ref)+list(neutral[7:]))
        parent=poses.get(pb.parent.name,ev.pose.bones[pb.parent.name].matrix) if pb.parent else Matrix.Identity(4)
        rest=pb.parent.bone.matrix_local if pb.parent else Matrix.Identity(4)
        local=pb.bone.convert_local_to_pose(poses[name],pb.bone.matrix_local,
            parent_matrix=parent,parent_matrix_local=rest,invert=True)
        location,rotation,scale=local.decompose()
        target.extend(list(location)+list(rotation.to_euler('XYZ',ref))+list(scale))
        # Normalize translations by bone size so model units don't dominate.
        weights.extend([1/max(pb.bone.length,.01)]*3+[1]*6)
    base=np.asarray(base)
    weights=np.asarray(weights)
    desired=(np.asarray(target)-base)*weights
    best=(float(desired@desired),0,0.0)
    labels=json.loads(main['sub_expression_labels'])
    from .face_components import expression_checkpoints
    for label in data.get('poses',{}):
        previous=np.zeros_like(desired)
        low=0.0
        for high,pose in expression_checkpoints(data,label)[1:]:
            values=[]
            for name in names:
                v=pose.get(name,data['neutral'][name])
                values.extend(list(v[:3])+list(Quaternion(v[3:7]).to_euler('XYZ',references[name]))+list(v[7:]))
            endpoint=(np.asarray(values)-base)*weights
            delta=endpoint-previous
            denominator=float(delta@delta)
            fraction=float(np.clip(((desired-previous)@delta)/denominator,0,1)) if denominator>1e-12 else 0.0
            residual=desired-previous-delta*fraction
            error=float(residual@residual)
            if error<best[0]-1e-12:
                best=(error,labels.index(label)+1,low+(high-low)*fraction)
            previous,low=endpoint,high
    # Retired individual pose tracks must not add a second expression.
    for pb in obj.pose.bones:
        if pb.bone.get('sub_face_owner')==component.uid and pb.bone.get('sub_component_control'):
            pb.location=(0,0,0)
    expression_set(main,best[1])
    main.location.y=best[2]
    return main.name,best[1],best[2]


def match_animation(context, obj, start, end, include_fingers=False, match_ik=True, fingers_only=False):
    from .component_workflow import definitions
    from . import ik_channels, anim_layers_compat
    from .create_animation_rig import _activate_armature, _disable_autokey, defer_pose_tool_updates, ProgressCursor
    from ..anim.fcurve_bulk import PoseKeyWriter
    from ..anim.fcurve_compat import get_all_action_fcurves
    components = [] if fingers_only else definitions(obj)
    if include_fingers:
        from . import finger_sliders as fingers
        from types import SimpleNamespace
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
    try:
        with ProgressCursor(context) as progress, _disable_autokey(context), defer_pose_tool_updates(), anim_layers_compat.anim_layers_paused(), anim_layers_compat.bind_driving_action_for_bake(obj,context):
            samples={}
            for con,_ in muted:
                con.mute=True
            try:
                for f in range(start,end+1):
                    scene.frame_set(f)
                    ev=_update(context,obj)
                    samples[f]={n:ev.pose.bones[n].matrix.copy() for n in all_owners}
                    progress.update(.15*(f-start+1)/max(1,end-start+1))
            finally:
                for con,state in muted:
                    con.mute=state
            targets={r['target'] for r in json.loads(obj.get('sub_custom_ik_chains','[]')) if r.get('component_id') in {c.uid for c in components if c.kind=='IK'}}
            if targets and match_ik:
                old_range=(scene.frame_start,scene.frame_end)
                try:
                    scene.frame_start,scene.frame_end=start,end
                    ik_channels.match(context,obj,entire=True,key=True,_targets=targets)
                finally:
                    scene.frame_start,scene.frame_end=old_range
            # Isolated controls have a full transform: match them directly.
            # Old residual offsets must not move the foot away from its handle.
            obsolete=set()
            for n,uid in isolated.items():
                for con in obj.pose.bones[n].constraints:
                    if con.name.startswith(_prefix(uid)) and con.name != _prefix(uid):
                        con.mute=True
                        obsolete.add(con.as_pointer())
            fit_controls=[n for n in controls if obj.data.bones[n].get('sub_face_owner') not in isolated_ids]
            for n in finger_names:
                for con in obj.pose.bones[n].constraints:
                    if con.name in {_prefix(FINGER_MATCH_ID)+' '+label for label in ('Input','Match','Match2')}:
                        con.mute=True
                        obsolete.add(con.as_pointer())
            finger_controls={name for c in non_ik if c.uid==FINGER_MATCH_ID for name in c.controls}
            finger_plan=_finger_slider_plan(obj,finger_names) if finger_names else None
            fit_controls=[n for n in fit_controls if n not in finger_controls]
            helpers=_helpers(context,obj,owners)
            expressions=[c for c in non_ik if c.kind in {'LIDS','MOUTH'}]
            expression_ids={c.uid for c in expressions}
            expression_names={b.bone for c in expressions for b in c.bones}
            fit_controls=[n for n in fit_controls if obj.data.bones[n].get('sub_face_owner') not in expression_ids]
            selector_curves=[]
            for fc in get_all_action_fcurves(obj.animation_data.action,id_type='OBJECT'):
                if any(fc.data_path.startswith(obj.pose.bones[n].path_from_id()+'.') for n in controls
                       if obj.data.bones[n].get('sub_face_owner') in expression_ids):
                    selector_curves.append((fc,fc.mute))
                    fc.mute=True
            writer=PoseKeyWriter(obj)
            choices=PoseKeyWriter(obj,interpolation='CONSTANT')
            # Parent-first offsets: child targets must see the corrected parent.
            ordered=sorted(owners,key=lambda n:len(obj.pose.bones[n].parent_recursive))
            for f,poses in samples.items():
                scene.frame_set(f)
                for pair in helpers.values():
                    for name in pair:
                        obj.pose.bones[name].matrix_basis=Matrix.Identity(4)
                for n in finger_names:
                    obj.pose.bones[n].matrix_basis=Matrix.Identity(4)
                for component in expressions:
                    choice=_match_expression(context,obj,component,poses)
                    if choice:
                        name,index,strength=choice
                        path=obj.pose.bones[name].path_from_id()
                        choices.stash_channel(path+'.sub_face_expression',0,f,index,name)
                        writer.stash_channel(path+'.location',1,f,strength,name)
                fit_names=set(owners)-expression_names
                if fit_names:
                    _fit(context,obj,fit_controls,{n:poses[n] for n in fit_names})
                if finger_plan:
                    _fit_finger_sliders(context,obj,poses,finger_plan,finger_controls)
                # Evaluate the neutral circles with the fitted sliders once.
                # Desired parent matrices are already sampled, so every joint's
                # local correction can be calculated before changing the scene.
                if finger_names:
                    ev=_update(context,obj)
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
                        corrections[n]=local(poses[n],wanted_parent) @ contribution.inverted_safe()
                    for n,basis in corrections.items():
                        obj.pose.bones[n].matrix_basis=basis
                    ev=_update(context,obj)
                    # Verify all joints together. Unusual constraint stacks or
                    # non-TRS transforms retain the existing precise fallback.
                    for n in sorted(finger_names,key=lambda n:len(obj.pose.bones[n].parent_recursive)):
                        if max(abs(ev.pose.bones[n].matrix[i][j]-poses[n][i][j]) for i in range(4) for j in range(4))<=2e-6:
                            continue
                        pb=obj.pose.bones[n]
                        locks=(tuple(pb.lock_location),tuple(pb.lock_rotation),tuple(pb.lock_scale))
                        try:
                            pb.lock_location=pb.lock_rotation=pb.lock_scale=(False,False,False)
                            _fit(context,obj,[n],{n:poses[n]})
                            ev=_update(context,obj)
                        finally:
                            pb.lock_location,pb.lock_rotation,pb.lock_scale=locks
                for n,uid in isolated.items():
                    con=obj.pose.bones[n].constraints.get(_prefix(uid))
                    if not con or con.type!='COPY_TRANSFORMS':
                        raise ValueError('Rebuild the isolated component before matching')
                    output=obj.pose.bones[con.subtarget]
                    root=output
                    while root.parent and root.bone.get('sub_face_owner')==uid:
                        root=root.parent
                    # Roll and toe handles start neutral for an FK transfer.
                    child=output
                    while child!=root:
                        child.matrix_basis=Matrix.Identity(4)
                        child=child.parent
                    ev=_update(context,obj)
                    offset=ev.pose.bones[root.name].matrix.inverted_safe() @ ev.pose.bones[output.name].matrix
                    root.matrix=poses[n] @ offset.inverted_safe()
                    _update(context,obj)
                extra=False
                for name in ordered:
                    ev=_update(context,obj)
                    delta=ev.pose.bones[name].matrix.inverted_safe() @ poses[name]
                    first,second=_split_affine(delta)
                    obj.pose.bones[helpers[name][1]].matrix_basis=first
                    obj.pose.bones[helpers[name][2]].matrix_basis=second
                    extra |= max(abs(delta[i][j]-(1 if i==j else 0)) for i in range(4) for j in range(4))>1e-4
                ev=_update(context,obj)
                error=max((abs(ev.pose.bones[n].matrix[i][j]-poses[n][i][j]) for n in all_owners for i in range(4) for j in range(4)),default=0)
                if error>2e-4:
                    raise ValueError(f'Matching cannot preserve the pose at frame {f} (error {error:.5g}, bone {max(all_owners,key=lambda n:max(abs(ev.pose.bones[n].matrix[i][j]-poses[n][i][j]) for i in range(4) for j in range(4)))})')
                residual_frames += int(extra)
                progress.update(.2+.75*(f-start+1)/max(1,end-start+1))
                for name in controls+sorted(finger_names)+[n for pair in helpers.values() for n in pair]:
                    writer.stash_pose_bone(obj.pose.bones[name],f)
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
    return len(components),residual_frames


class SUB_OP_components_match(bpy.types.Operator):
    bl_idname='sub.components_match'
    bl_label='Match Custom Components to Animation'
    bl_description='Transfer the original bone animation to custom controls; preserve extra motion in hidden keyed offsets'
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

    def execute(self,context):
        from .create_animation_rig import find_target_armature
        obj=find_target_armature(context)
        if not obj or self.end<self.start:
            self.report({'ERROR'},'Select a rig and a valid frame range')
            return {'CANCELLED'}
        try:
            count,extra=match_animation(context,obj,self.start,self.end,include_fingers=True)
        except (ValueError,RuntimeError) as exc:
            self.report({'ERROR'},str(exc))
            return {'CANCELLED'}
        self.report({'INFO'},f'Matched {count} components. Extra motion preserved on {extra} frames.')
        return {'FINISHED'}


def register():
    bpy.utils.register_class(SUB_OP_components_match)


def unregister():
    bpy.utils.unregister_class(SUB_OP_components_match)
