"""Checked per-component graphs with detached math and a Blender fallback.

Unmodelled constraints/drivers stay on the reference evaluator. Rust handles
matrix interpolation and special inheritance without Blender math callbacks.
Supported components share one graph evaluation per candidate.
Every accepted matching frame is still checked in Blender before keying.
"""
import ast
import builtins
import ctypes as ct
import json
import math
from types import SimpleNamespace
import numpy as np
from mathutils import Matrix
from . import component_native

LAST_DIAGNOSTICS = {}


def _expression(node, names):
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return dict(op='value', value=float(node.value))
    if isinstance(node, ast.Name) and node.id in names:
        return dict(op='var', index=names.index(node.id))
    if isinstance(node,ast.Name) and node.id in {'pi','tau','e'}:
        return dict(op='value',value=getattr(math,node.id))
    if isinstance(node,ast.UnaryOp) and isinstance(node.op,ast.UAdd):
        return _expression(node.operand,names)
    if isinstance(node,ast.UnaryOp) and isinstance(node.op,ast.Not):
        return dict(op='not',args=[_expression(node.operand,names)])
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        return dict(op='neg', args=[_expression(node.operand, names)])
    if isinstance(node, ast.BinOp) and type(node.op) in (ast.Add, ast.Sub, ast.Mult, ast.Div,ast.Pow,ast.Mod,ast.FloorDiv):
        return dict(op={ast.Add:'add', ast.Sub:'sub', ast.Mult:'mul', ast.Div:'div',ast.Pow:'pow',ast.Mod:'mod',ast.FloorDiv:'floordiv'}[type(node.op)],
                    args=[_expression(node.left,names),_expression(node.right,names)])
    if isinstance(node,ast.IfExp):
        return dict(op='if',args=[_expression(arg,names) for arg in (node.test,node.body,node.orelse)])
    if isinstance(node,ast.BoolOp):
        return dict(op='and' if isinstance(node.op,ast.And) else 'or',args=[_expression(arg,names) for arg in node.values])
    if isinstance(node, ast.Compare):
        operators={ast.Eq:'eq',ast.NotEq:'ne',ast.Lt:'lt',ast.LtE:'le',ast.Gt:'gt',ast.GtE:'ge'}
        if all(type(op) in operators for op in node.ops):
            return dict(op='and',args=[dict(op=operators[type(op)],args=[_expression(a,names),_expression(b,names)])
                for op,a,b in zip(node.ops,[node.left]+node.comparators,node.comparators)])
    if isinstance(node, ast.Call) and isinstance(node.func,ast.Name) and not node.keywords:
        name=node.func.id;argc=len(node.args)
        unary={'sin','cos','tan','asin','acos','atan','sqrt','exp','log','log10','abs','floor','ceil','trunc','degrees','radians'}
        if (name in unary and argc==1) or (name in {'atan2','pow'} and argc==2) or (name in {'min','max'} and argc>=2):
            return dict(op=name,args=[_expression(arg,names) for arg in node.args])
    raise ValueError('Unsupported driver expression')


def _scalar_property(target):
    """Read scalar custom properties; never freeze a driver-computed property."""
    path=target.data_path
    if target.id is None or not (path.endswith(']') and '["' in path):
        raise ValueError('Unsupported property driver variable')
    animation=getattr(target.id,'animation_data',None)
    if animation and any(fc.data_path==path and not fc.mute for fc in animation.drivers):
        raise ValueError('Driver-computed custom property')
    value=target.id.path_resolve(path)
    if not isinstance(value,(int,float)) or not math.isfinite(value):
        raise ValueError('Driver property must be a finite scalar')
    return float(value)


def _identity_curve(fc):
    points=list(fc.keyframe_points)
    if fc.sampled_points:
        return False
    if not points:
        return True
    if fc.extrapolation!='LINEAR' or len(points)<2:
        return False
    for point in points:
        if point.co.x!=point.co.y or point.interpolation not in {'LINEAR','BEZIER'}:
            return False
        if point.interpolation=='BEZIER' and any(handle.x!=handle.y or handle.x==point.co.x for handle in (point.handle_left,point.handle_right)):
            return False
    return all(a.co.x<b.co.x for a,b in zip(points,points[1:]))


def _external_matrix(owner,con):
    """Capture independent external transforms, never candidate-driven ones."""
    target=con.target
    if con.target_space!='WORLD':
        raise ValueError('External constraint target requires world space')
    current=target;seen=set()
    while current:
        if current==owner or current.as_pointer() in seen:
            raise ValueError('External target depends on matched armature')
        seen.add(current.as_pointer())
        animation=current.animation_data
        if any(not c.mute and c.influence for c in current.constraints) or (animation and any(not fc.mute for fc in animation.drivers)):
            raise ValueError('External target has dynamic constraint/driver dependencies')
        if current.type=='ARMATURE' and any(not c.mute and c.influence for pb in current.pose.bones for c in pb.constraints):
            raise ValueError('External armature has constraint dependencies')
        current=current.parent
    matrix=target.matrix_world.copy()
    if con.subtarget:
        if target.type!='ARMATURE' or con.subtarget not in target.pose.bones:
            raise ValueError('External target is not an armature bone')
        matrix @= target.pose.bones[con.subtarget].matrix
    return [list(row) for row in matrix]


class Graph:
    def __init__(self,obj,owners,controls,sample_names,*,fixed_samples=None):
        dll=component_native.library()
        if dll is None:
            raise ValueError('Native components disabled or unavailable')
        if dll.sub_component_graph_abi_version()!=5:
            raise ValueError('Update the native component library and restart Blender')
        dll.sub_component_graph_create.argtypes=[ct.c_char_p,ct.c_size_t]
        dll.sub_component_graph_create.restype=ct.c_void_p
        dll.sub_component_graph_eval.argtypes=[ct.c_void_p,component_native._pointer,component_native._pointer,component_native._pointer]
        dll.sub_component_graph_eval_basis.argtypes=[ct.c_void_p]+[component_native._pointer]*4
        dll.sub_component_graph_free.argtypes=[ct.c_void_p]
        dll.sub_component_graph_free.restype=None
        self.obj,self.dll,self.handle=obj,dll,None
        self.samples={}
        self._sample_cache=None
        self.external=set(sample_names)-set(owners) if fixed_samples is None else set(fixed_samples)
        from ..anim.fcurve_compat import get_all_action_fcurves
        action=obj.animation_data.action if obj.animation_data else None
        animation=list(get_all_action_fcurves(action)) if action else []
        animation+=list(obj.animation_data.drivers) if obj.animation_data else []
        animated_properties={fc.data_path.rpartition('.')[0] for fc in animation}
        driven_properties={fc.data_path.rpartition('.')[0] for fc in (obj.animation_data.drivers if obj.animation_data else []) if not fc.mute}
        self._dynamic=[]
        self._property_inputs=[]
        self._frame_inputs=[]
        paths={pb.path_from_id():pb.name for pb in obj.pose.bones}
        drivers={}
        for fc in (obj.animation_data.drivers if obj.animation_data else []):
            if fc.mute:
                continue
            prefix,sep,channel=fc.data_path.rpartition('.')
            if prefix in paths:
                drivers.setdefault(paths[prefix],[]).append((fc,channel))
        needed=set(owners)|set(controls)
        pending=list(needed)
        while pending:
            name=pending.pop()
            pb=obj.pose.bones.get(name)
            if pb is None:
                raise ValueError('Missing dependency')
            if name in self.external:
                continue
            refs=[pb.parent.name] if pb.parent else []
            for con in pb.constraints:
                if (not con.mute and con.influence) or con.path_from_id() in animated_properties:
                    if getattr(con,'target',None):
                        if con.target!=obj:
                            _external_matrix(obj,con)
                        elif not con.subtarget:
                            raise ValueError('Constraint targets the matched armature object')
                        else:
                            refs.append(con.subtarget)
            for fc,channel in drivers.get(name,[]):
                for var in fc.driver.variables:
                    target=var.targets[0]
                    if var.type=='SINGLE_PROP' and not target.data_path.endswith('.sub_face_expression'):
                        _scalar_property(target)
                        continue
                    if target.id!=obj:
                        raise ValueError('External driver dependency')
                    if var.type=='TRANSFORMS':
                        refs.append(target.bone_target)
                    elif var.type=='SINGLE_PROP' and target.data_path.endswith('.sub_face_expression'):
                        refs.append(paths[target.data_path.rpartition('.')[0]])
                    else:
                        raise ValueError('Unsupported driver variable')
            for ref in refs:
                if ref not in needed:
                    needed.add(ref);pending.append(ref)
        self.names=sorted(needed)
        self.bones=[obj.pose.bones[n] for n in self.names]
        self.indices={n:i for i,n in enumerate(self.names)}
        self.spec=[]
        for pb in self.bones:
            external=pb.name in self.external
            bone=pb.bone
            parent=None if external or not pb.parent else self.indices[pb.parent.name]
            # Blender's BKE_bone_offset_matrix uses stored relative bone_mat,
            # head and parent length. Avoid inverse-rest reconstruction rounding.
            offset=bone.matrix.to_4x4()
            offset.translation=bone.head
            if parent is not None:
                offset[1][3]+=pb.parent.bone.length
            node=dict(parent=parent,offset=[list(row) for row in offset],external=external,drivers=[],constraints=[],
                      rest=[list(row) for row in bone.matrix_local],inherit_scale=bone.inherit_scale,
                      no_inherit_rotation=not bone.use_inherit_rotation,no_local_location=not bone.use_local_location,
                      connected=bone.use_connect,
                      custom_inheritance=bone.inherit_scale!='FULL' or not bone.use_inherit_rotation or not bone.use_local_location)
            if not external:
                if drivers.get(pb.name) and pb.rotation_mode!='XYZ':
                    raise ValueError('Unsupported driven rotation mode')
                for fc,channel in drivers.get(pb.name,[]):
                    if not fc.driver.is_valid:
                        raise ValueError('Blender reports an invalid or blocked driver')
                    if channel not in {'location','rotation_euler','scale'} or fc.driver.type not in {'SCRIPTED','SUM','AVERAGE','MIN','MAX'} or (channel=='rotation_euler' and pb.rotation_mode!='XYZ'):
                        raise ValueError('Unsupported driven channel')
                    modifiers=[mod for mod in fc.modifiers if not mod.mute]
                    if any(mod.type!='GENERATOR' or mod.mode!='POLYNOMIAL' or mod.poly_order!=1 or tuple(mod.coefficients)!=(0.,1.)
                           or mod.use_additive or mod.use_restricted_range or (mod.use_influence and mod.influence!=1) for mod in modifiers):
                        raise ValueError('Driver modifiers')
                    # Blender's default replacement generator overrides the two
                    # default curve keys. Without it, keys remap driver output.
                    if not modifiers and not _identity_curve(fc):
                        raise ValueError('Driver F-Curve remapping')
                    variables=[]
                    for var in fc.driver.variables:
                        target=var.targets[0]
                        if var.type=='SINGLE_PROP' and not target.data_path.endswith('.sub_face_expression'):
                            record=dict(node=0,channel=10,value=_scalar_property(target))
                            self._property_inputs.append((target,record))
                            variables.append(record)
                            continue
                        if var.type=='TRANSFORMS':
                            channels={f'{prefix}_{axis}':offset+i for prefix,offset in (('LOC',0),('ROT',3),('SCALE',6)) for i,axis in enumerate('XYZ')}
                            channels['SCALE_AVG']=11
                            if target.transform_space not in {'LOCAL_SPACE','WORLD_SPACE'} or target.transform_type not in channels:
                                raise ValueError('Unsupported driver transform')
                            name=target.bone_target
                            axis=channels[target.transform_type]
                            orders=('XYZ','XZY','YXZ','YZX','ZXY','ZYX')
                            order=target.rotation_mode if target.rotation_mode!='AUTO' else obj.pose.bones[name].rotation_mode
                            if 3<=axis<=5 and order not in orders and target.rotation_mode!='AUTO':
                                raise ValueError('Unsupported driver rotation extraction')
                        else:
                            name=paths[target.data_path.rpartition('.')[0]];axis=9
                        if name in self.external:
                            raise ValueError('Driver reads sampled dependency channels')
                        record=dict(node=self.indices[name],channel=axis)
                        if var.type=='TRANSFORMS':
                            record.update(world=target.transform_space=='WORLD_SPACE',order=orders.index(order) if order in orders else 0,
                                          compatible=target.rotation_mode=='AUTO' and order in orders)
                        variables.append(record)
                    if fc.driver.type=='SCRIPTED':
                        import bpy
                        tree=ast.parse(fc.driver.expression,mode='eval').body
                        names=[v.name for v in fc.driver.variables]
                        if 'frame' not in names and any(isinstance(n,ast.Name) and n.id=='frame' for n in ast.walk(tree)):
                            record=dict(node=0,channel=10,value=float(bpy.context.scene.frame_current_final))
                            self._frame_inputs.append(record);variables.append(record);names.append('frame')
                        # Do not substitute built-in math for a user's replacement
                        # in Blender's Python driver namespace.
                        for name in {n.id for n in ast.walk(tree) if isinstance(n,ast.Name)}-set(names):
                            expected=getattr(math,name,getattr(builtins,name,None))
                            actual=bpy.app.driver_namespace.get(name,getattr(builtins,name,None))
                            if expected is None or actual!=expected:
                                raise ValueError('Custom driver namespace function: '+name)
                        expression=_expression(tree,names)
                    else:
                        if not variables:
                            raise ValueError('Driver without inputs')
                        expression=dict(op={'SUM':'sum','AVERAGE':'average','MIN':'min','MAX':'max'}[fc.driver.type],
                                        args=[dict(op='var',index=i) for i in range(len(variables))])
                    node['drivers'].append(dict(channel={'location':0,'rotation_euler':3,'scale':6}[channel]+fc.array_index,vars=variables,expression=expression))
                for con in pb.constraints:
                    if con.path_from_id() in driven_properties:
                        raise ValueError('Driver-controlled constraint settings')
                    if con.path_from_id() in animated_properties or (getattr(con,'target',None) and con.target!=obj):
                        if pb not in self._dynamic:
                            self._dynamic.append(pb)
                    if con.mute or con.influence==0:
                        continue
                    record=self._constraint(con,pb)
                    node['constraints'].append(record)
            self.spec.append(node)
        for node in self.spec:
            for driver in node['drivers']:
                for var in driver['vars']:
                    if var['channel']!=9 and 'value' not in var and not var.get('world'):
                        self.spec[var['node']]['driver_local']=True
        self._encoded=None
        self._world=[list(row) for row in obj.matrix_world]
        self._compile()
        self._values=np.zeros((len(self.names),10),dtype=np.float64)
        self._driver_inputs=[(i,pb) for i,pb in enumerate(self.bones) if self.spec[i]['drivers']]
        self._selector_inputs={var['node'] for node in self.spec for driver in node['drivers'] for var in driver['vars'] if var['channel']==9}
        self._rotation_inputs={var['node'] for node in self.spec for driver in node['drivers'] for var in driver['vars'] if var.get('compatible') and 3<=var['channel']<=5}
        LAST_DIAGNOSTICS['nodes']=len(self.names)
        for key in ('native_evaluations','native_frames','fallback_frames','blender_evaluations'):
            LAST_DIAGNOSTICS.setdefault(key,0)

    def _constraint(self,con,pb):
        target=self.indices.get(getattr(con,'subtarget',''),0)
        foreign=dict(target_matrix=_external_matrix(self.obj,con)) if getattr(con,'target',None) and con.target!=self.obj else {}
        spaces={'LOCAL','POSE','WORLD'}
        if con.owner_space in spaces:
            base=dict(foreign,influence=con.influence,owner_space=con.owner_space)
            if con.type=='LIMIT_ROTATION':
                order=con.euler_order if con.euler_order!='AUTO' else pb.rotation_mode
                orders=('XYZ','XZY','YXZ','YZX','ZXY','ZYX')
                return dict(base,kind='limit_rotation',low=[getattr(con,'min_'+c) for c in 'xyz'],high=[getattr(con,'max_'+c) for c in 'xyz'],
                            axes=[getattr(con,'use_limit_'+c) for c in 'xyz'],legacy=con.use_legacy_behavior,order=orders.index(order) if order in orders else 0)
            if con.type=='LIMIT_SCALE':
                return dict(base,kind='limit_scale',low=[getattr(con,'min_'+c) if getattr(con,'use_min_'+c) else -1e30 for c in 'xyz'],
                            high=[getattr(con,'max_'+c) if getattr(con,'use_max_'+c) else 1e30 for c in 'xyz'])
            if getattr(con,'target_space',None) in spaces:
                base.update(target=target,target_space=con.target_space)
                if con.type=='COPY_LOCATION' and con.head_tail==0:
                    return dict(base,kind='copy_location',axes=[getattr(con,'use_'+c) for c in 'xyz'],invert_axes=[getattr(con,'invert_'+c) for c in 'xyz'],offset=con.use_offset)
                if con.type=='COPY_ROTATION' and con.mix_mode in {'REPLACE','ADD','BEFORE','AFTER','OFFSET'}:
                    order=con.euler_order if con.euler_order!='AUTO' else pb.rotation_mode
                    orders=('XYZ','XZY','YXZ','YZX','ZXY','ZYX')
                    return dict(base,kind='copy_rotation',axes=[getattr(con,'use_'+c) for c in 'xyz'],invert_axes=[getattr(con,'invert_'+c) for c in 'xyz'],
                                mode=con.mix_mode,order=orders.index(order) if order in orders else 0)
                if con.type=='COPY_SCALE':
                    return dict(base,kind='copy_scale',axes=[getattr(con,'use_'+c) for c in 'xyz'],offset=con.use_offset,uniform=con.use_make_uniform,
                                multiply=not con.use_add,power=con.power)
                if con.type=='CHILD_OF' and con.owner_space==con.target_space=='WORLD':
                    if con.set_inverse_pending:
                        raise ValueError('Child Of inverse has not been evaluated yet')
                    orders=('XYZ','XZY','YXZ','YZX','ZXY','ZYX')
                    target_bone=con.target.pose.bones.get(con.subtarget) if con.target and con.target.type=='ARMATURE' else None
                    target_order=(target_bone or con.target).rotation_mode
                    return dict(base,kind='child_of',inverse_matrix=[list(row) for row in con.inverse_matrix],
                                channels=[getattr(con,'use_'+kind+'_'+axis) for kind in ('location','rotation','scale') for axis in 'xyz'],
                                order=orders.index(pb.rotation_mode) if pb.rotation_mode in orders else 0,
                                target_order=orders.index(target_order) if target_order in orders else 0)
        if con.type=='LIMIT_LOCATION' and con.owner_space=='LOCAL':
            return dict(kind='limit',low=[getattr(con,'min_'+c) if getattr(con,'use_min_'+c) else -1e30 for c in 'xyz'],
                        high=[getattr(con,'max_'+c) if getattr(con,'use_max_'+c) else 1e30 for c in 'xyz'],influence=con.influence)
        if con.type=='TRANSFORM' and con.owner_space==con.target_space=='LOCAL' and con.map_from=='LOCATION' and con.map_to=='ROTATION' and con.mix_mode_rot=='AFTER':
            order=con.to_euler_order if con.to_euler_order!='AUTO' else pb.rotation_mode
            orders=('XYZ','XZY','YXZ','YZX','ZXY','ZYX')
            return dict(kind='transform',target=target,low=[getattr(con,'from_min_'+c) for c in 'xyz'],high=[getattr(con,'from_max_'+c) for c in 'xyz'],
                        to_low=[getattr(con,'to_min_'+c+'_rot') for c in 'xyz'],to_high=[getattr(con,'to_max_'+c+'_rot') for c in 'xyz'],
                        mapping=['XYZ'.index(getattr(con,'map_to_'+c+'_from')) for c in 'xyz'],extrapolate=con.use_motion_extrapolate,order=orders.index(order) if order in orders else 0,influence=con.influence)
        if con.type=='COPY_TRANSFORMS' and con.owner_space=='POSE' and not con.remove_target_shear:
            modes={'REPLACE':'replace','AFTER_FULL':'after','BEFORE_FULL':'before'}
            if con.mix_mode in modes and con.target_space in {'POSE','LOCAL'}:
                return dict(kind='copy',target=target,mode=modes[con.mix_mode],target_local=con.target_space=='LOCAL',influence=con.influence)
        if con.type=='DAMPED_TRACK' and con.owner_space==con.target_space=='WORLD' and con.head_tail==0:
            return dict(foreign,kind='track',target=target,axis='XYZ'.index(con.track_axis[-1]),sign=-1 if 'NEG' in con.track_axis else 1,influence=con.influence)
        raise ValueError('Unsupported constraint '+con.type)

    def _compile(self):
        encoded=json.dumps(dict(nodes=self.spec,object_world=self._world),allow_nan=False).encode()
        if encoded==self._encoded:
            return
        # Check dependency topology ourselves before entering recursive Rust code.
        dependencies=[]
        for node in self.spec:
            refs=set()
            if not node['external']:
                if node['parent'] is not None:
                    refs.add(node['parent'])
                refs.update(con['target'] for con in node['constraints'] if 'target' in con and 'target_matrix' not in con)
                refs.update(var['node'] for driver in node['drivers'] for var in driver['vars'] if var['channel']!=9 and 'value' not in var)
            dependencies.append(refs)
        ready=[i for i,refs in enumerate(dependencies) if not refs]
        dependents=[[] for _ in dependencies]
        for i,refs in enumerate(dependencies):
            for dependency in refs:
                dependents[dependency].append(i)
        checked=0
        while ready:
            index=ready.pop();checked+=1
            for dependent in dependents[index]:
                dependencies[dependent].remove(index)
                if not dependencies[dependent]:
                    ready.append(dependent)
        if checked!=len(self.spec):
            raise ValueError('Component dependency cycle')
        handle=self.dll.sub_component_graph_create(encoded,len(encoded))
        if not handle:
            raise ValueError('Native graph rejected capture')
        self.close()
        self.handle=handle
        self._encoded=encoded

    def evaluate(self):
        world=[list(row) for row in self.obj.matrix_world]
        property_changed=False
        if self._frame_inputs:
            import bpy
            value=float(bpy.context.scene.frame_current_final)
            for record in self._frame_inputs:
                if value!=record['value']:
                    record['value']=value;property_changed=True
        for target,record in self._property_inputs:
            value=_scalar_property(target)
            if value!=record['value']:
                record['value']=value;property_changed=True
        if self._dynamic or world!=self._world or property_changed:
            self._world=world
            for pb in self._dynamic:
                self.spec[self.indices[pb.name]]['constraints']=[self._constraint(con,pb) for con in pb.constraints if not con.mute and con.influence]
            self._compile()
        # Undriven bones already supply Blender's exact basis matrix. Only
        # driven channels and expression selectors need the scalar input buffer.
        values=self._values
        for i,pb in self._driver_inputs:
            values[i,:9]=(*pb.location,*pb.rotation_euler,*pb.scale)
        for i in self._selector_inputs:
            values[i,9]=self.bones[i].sub_face_expression
        for i in self._rotation_inputs:
            values[i,3:6]=self.bones[i].rotation_euler
        bases=component_native.array([pb.matrix_basis for pb in self.bones])
        if self.samples is not self._sample_cache:
            identity=Matrix.Identity(4)
            self._external_values=component_native.array([self.samples.get(n,identity) for n in self.names])
            self._sample_cache=self.samples
        output=np.empty((len(self.names),4,4),dtype=np.float64)
        if not self.dll.sub_component_graph_eval_basis(self.handle,component_native.ptr(values),component_native.ptr(self._external_values),component_native.ptr(bases),component_native.ptr(output)):
            raise ValueError('Native graph encountered a singular transform or dependency cycle')
        LAST_DIAGNOSTICS['native_evaluations']+=1
        return SimpleNamespace(pose=SimpleNamespace(bones={n:SimpleNamespace(matrix=Matrix(m.tolist())) for n,m in zip(self.names,output)}))

    def set_pose(self,name,matrix):
        pb=self.obj.pose.bones[name]
        parent=self.evaluate().pose.bones[pb.parent.name].matrix if pb.parent else Matrix.Identity(4)
        pb.matrix_basis=pb.bone.convert_local_to_pose(matrix,pb.bone.matrix_local,parent_matrix=parent,
            parent_matrix_local=pb.parent.bone.matrix_local if pb.parent else Matrix.Identity(4),invert=True)

    def close(self):
        if getattr(self,'handle',None):
            self.dll.sub_component_graph_free(self.handle);self.handle=None

    def __del__(self):
        self.close()


def capture(obj,owners,controls,sample_names):
    LAST_DIAGNOSTICS.clear()
    try:
        return Graph(obj,owners,controls,sample_names)
    except (ValueError,AttributeError,KeyError,RuntimeError,SyntaxError) as exc:
        LAST_DIAGNOSTICS['declined']=str(exc)
        return None


class _LazyBones:
    """Read each requested component once; callers consume before changing controls."""
    def __init__(self, graph):
        self.graph=graph
        self.cache={}
        self.reference=None
        self.batch_result=None

    def __getitem__(self, name):
        group=self.graph.by_bone.get(name)
        native=self.graph.graphs.get(group)
        if native is not None:
            batch=self.graph.batch
            if batch is not None:
                if self.batch_result is None:
                    batch.samples=self.graph.samples
                    try:
                        self.batch_result=batch.evaluate().pose.bones
                    except ValueError:
                        # Isolate a rejected graph using the component checks;
                        # don't penalize unrelated components for the failure.
                        batch.close();self.graph.batch=None
                if self.batch_result is not None:
                    return self.batch_result[name]
            if group not in self.cache:
                native.samples=self.graph.samples
                try:
                    self.cache[group]=native.evaluate().pose.bones
                except ValueError as exc:
                    self.graph.disable({group},str(exc))
                    native=None
            if native is not None:
                return self.cache[group][name]
        if self.reference is None:
            evaluated=self.graph.reference()
            # Copy matrices: Blender's evaluated RNA changes on subsequent updates.
            self.reference={pb.name:SimpleNamespace(matrix=pb.matrix.copy()) for pb in evaluated.pose.bones}
            LAST_DIAGNOSTICS['blender_evaluations']+=1
        return self.reference[name]

    def get(self,name,default=None):
        if name not in self.graph.obj.pose.bones:
            return default
        return self[name]


class HybridGraph:
    """Partition by component; retain Blender evaluation for unsupported stacks."""
    def __init__(self,obj,owners,controls,sample_names,reference):
        self.obj,self.reference=obj,reference
        self.samples={}
        self.graphs={}
        self.batch=None
        self.by_bone={}
        self.owners=dict(owners)
        self.groups={}
        self.sample_names=set(sample_names)
        self.fixed_samples=self.sample_names-set(owners)
        self.disabled=set()
        for name,uid in owners.items():
            self.groups.setdefault(uid,set()).add(name)
        LAST_DIAGNOSTICS.clear()
        LAST_DIAGNOSTICS.update(native_evaluations=0,native_frames=0,fallback_frames=0,blender_evaluations=0,components={})
        self._capture()

    def _capture(self):
        self.close()
        self.by_bone={}
        for uid,names in self.groups.items():
            if uid in self.disabled:
                continue
            try:
                native=Graph(self.obj,names,(),self.sample_names,fixed_samples=self.fixed_samples)
            except (ValueError,AttributeError,KeyError,RuntimeError,SyntaxError) as exc:
                LAST_DIAGNOSTICS['components'][uid]={'mode':'Blender','reason':str(exc),'bones':sorted(names)}
                continue
            self.graphs[uid]=native
            LAST_DIAGNOSTICS['components'][uid]={'mode':'native','bones':sorted(names)}
            for name in native.names:
                self.by_bone.setdefault(name,uid)
        # An unsupported owner's overlapping parent/helper closure must not hide
        # its need for reference evaluation behind another component's graph.
        self.by_bone.update(self.owners)
        LAST_DIAGNOSTICS['nodes']=sum(len(g.names) for g in self.graphs.values())
        self._batch()

    def _batch(self):
        if self.batch:
            self.batch.close();self.batch=None
        if len(self.graphs)>1:
            names={name for uid in self.graphs for name in self.groups[uid]}
            try:
                self.batch=Graph(self.obj,names,(),self.sample_names,fixed_samples=self.fixed_samples)
            except (ValueError,AttributeError,KeyError,RuntimeError,SyntaxError) as exc:
                LAST_DIAGNOSTICS['batch_declined']=str(exc)
        LAST_DIAGNOSTICS['batched_components']=len(self.graphs) if self.batch else 0
        LAST_DIAGNOSTICS['unique_nodes']=len(self.batch.names) if self.batch else sum(len(g.names) for g in self.graphs.values())

    def evaluate(self):
        return SimpleNamespace(pose=SimpleNamespace(bones=_LazyBones(self)))

    def set_pose(self,name,matrix):
        pb=self.obj.pose.bones[name]
        parent=self.evaluate().pose.bones[pb.parent.name].matrix if pb.parent else Matrix.Identity(4)
        pb.matrix_basis=pb.bone.convert_local_to_pose(matrix,pb.bone.matrix_local,parent_matrix=parent,
            parent_matrix_local=pb.parent.bone.matrix_local if pb.parent else Matrix.Identity(4),invert=True)

    def disable(self,groups,reason):
        # Also disable graphs depending on the rejected component's outputs.
        rejected={n for uid in groups for n in self.groups.get(uid,())}
        affected=set(groups)|{uid for uid,g in self.graphs.items() if rejected.intersection(g.names)}
        for uid in affected:
            graph=self.graphs.pop(uid,None)
            if graph:
                graph.close()
            self.disabled.add(uid)
            LAST_DIAGNOSTICS['components'][uid]={'mode':'Blender','reason':reason,'bones':sorted(self.groups.get(uid,()))}
        self._batch()

    def reject(self,names,reason):
        groups={self.owners[n] for n in names if n in self.owners}
        self.disable(groups or set(self.graphs),reason)

    def close(self):
        if self.batch:
            self.batch.close();self.batch=None
        for graph in self.graphs.values():
            graph.close()
        self.graphs.clear()


def capture_for_match(obj,owners,controls,sample_names,reference):
    return HybridGraph(obj,owners,controls,sample_names,reference)
