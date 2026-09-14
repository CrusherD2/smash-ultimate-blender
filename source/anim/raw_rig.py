"""Data-only rig snapshots for sparse raw animation round trips."""
import ast
import hashlib
import json
import math
import bpy
from mathutils import Matrix

SKIP={'rna_type','name','matrix','matrix_basis','matrix_world','matrix_local','matrix_parent_inverse','parent','constraints','animation_data','data','custom_shape','custom_shape_transform'}


def plain(value):
    if value is None or isinstance(value,(bool,int,float,str)):
        return value
    if hasattr(value,'to_dict'):
        return {k:plain(v) for k,v in value.to_dict().items()}
    if isinstance(value,dict):
        return {k:plain(v) for k,v in value.items()}
    return [plain(v) for v in value]


def props(owner):
    result={}
    for key in owner.keys():
        try:
            result[key]=plain(owner[key])
        except (TypeError,ValueError):
            pass
    return result


def scalar_rna(owner):
    result={}
    for prop in owner.bl_rna.properties:
        key=prop.identifier
        if key in SKIP or prop.is_readonly or prop.type not in {'BOOLEAN','INT','FLOAT','STRING','ENUM'}:
            continue
        try:
            value=getattr(owner,key)
            result[key]=sorted(value) if isinstance(value,set) else plain(value)
        except (AttributeError,TypeError,ValueError):
            pass
    return result


def set_rna(owner, values):
    for key,value in values.items():
        prop=owner.bl_rna.properties.get(key)
        if prop is None or prop.is_readonly or prop.type not in {'BOOLEAN','INT','FLOAT','STRING','ENUM'}:
            continue
        try:
            setattr(owner,key,set(value) if prop.type=='ENUM' and prop.is_enum_flag else value)
        except (AttributeError,TypeError,ValueError):
            pass


def set_props(owner, values):
    for key,value in values.items():
        try:
            owner[key]=value
        except (TypeError,ValueError):
            pass


def group_state(group):
    result=scalar_rna(group)
    if hasattr(group, "name"): result["name"]=group.name
    for prop in group.bl_rna.properties:
        key=prop.identifier
        if prop.type=='COLLECTION' and key!='rna_type':
            value=getattr(group,key)
            if hasattr(value,'add'):
                result[key]=[group_state(v) for v in value]
        elif prop.type=='POINTER' and key!='rna_type':
            value=getattr(group,key)
            if isinstance(value,bpy.types.PropertyGroup):
                result[key]=group_state(value)
    return result


def restore_group(group,values):
    set_rna(group,values)
    for key,value in values.items():
        prop=group.bl_rna.properties.get(key)
        if prop is None:
            continue
        if prop.type=='COLLECTION':
            target=getattr(group,key)
            if hasattr(target,'add'):
                target.clear()
                for item in value:
                    restore_group(target.add(),item)
        elif prop.type=='POINTER' and isinstance(getattr(group,key),bpy.types.PropertyGroup):
            restore_group(getattr(group,key),value)


def addon_state(owner):
    result={}
    for prop in owner.bl_rna.properties:
        key=prop.identifier
        if not key.startswith('sub_'):
            continue
        value=getattr(owner,key)
        if isinstance(value,bpy.types.PropertyGroup):
            result[key]=group_state(value)
        elif prop.type in {'BOOLEAN','FLOAT','INT','STRING','ENUM'} and not prop.is_readonly:
            result[key]=plain(value)
    return result


def restore_addon(owner,values):
    for key,value in values.items():
        if not key.startswith('sub_') or not hasattr(owner,key):
            continue
        target=getattr(owner,key)
        if isinstance(target,bpy.types.PropertyGroup):
            restore_group(target,value)
        else:
            try:
                setattr(owner,key,value)
            except (TypeError,ValueError,AttributeError):
                pass


def capture(obj):
    objects={obj.name:obj}
    widgets={}
    def ref(value):
        if value==obj:
            return 'SELF'
        if value==obj.data:
            return 'DATA'
        if isinstance(value,bpy.types.Object):
            if value.type=='EMPTY': objects[value.name]=value
            return 'OBJECT:'+value.name
        if value is None:
            return None
        return None
    def constraints(owner):
        result=[]
        for con in owner.constraints:
            entry={'type':con.type,'name':con.name,'values':scalar_rna(con),'pointers':{}}
            for prop in con.bl_rna.properties:
                if prop.type=='POINTER' and not prop.is_readonly and prop.identifier!='rna_type':
                    entry['pointers'][prop.identifier]=ref(getattr(con,prop.identifier))
            result.append(entry)
        return result
    def drivers(owner):
        result=[]
        if not owner.animation_data: return result
        for fc in owner.animation_data.drivers:
            d=fc.driver
            variables=[]
            for var in d.variables:
                targets=[]
                for t in var.targets:
                    targets.append({'values':scalar_rna(t),'id':ref(t.id)})
                variables.append({'name':var.name,'type':var.type,'targets':targets})
            result.append({'path':fc.data_path,'index':fc.array_index,'type':d.type,'expression':d.expression,'use_self':d.use_self,'variables':variables,'mute':fc.mute})
        return result
    bones=[]
    for pb in obj.pose.bones:
        b=pb.bone
        shape=pb.custom_shape
        if shape and shape.type=='MESH':
            widgets[shape.name]={'vertices':[list(v.co) for v in shape.data.vertices],'edges':[list(e.vertices) for e in shape.data.edges],'faces':[list(p.vertices) for p in shape.data.polygons]}
        bones.append({'name':pb.name,'parent':b.parent.name if b.parent else None,
            'matrix':[list(row) for row in b.matrix_local],'length':b.length,
            'bone':scalar_rna(b),'bone_props':props(b),'pose':scalar_rna(pb),'pose_props':props(pb),
            'shape':shape.name if shape else None,'shape_transform':pb.custom_shape_transform.name if pb.custom_shape_transform else None,
            'color':b.color.palette,'collections':[c.name for c in b.collections], 'constraints':constraints(pb)})
    result={'bones':bones,'widgets':widgets,'collections':[{'name':c.name,'visible':c.is_visible} for c in obj.data.collections_all],
        'object_props':props(obj),'data_props':props(obj.data),'object_addon':addon_state(obj),'data_addon':addon_state(obj.data),
        'drivers':drivers(obj),'data_drivers':drivers(obj.data),'objects':{}}
    done={obj.name}
    while set(objects)-done:
        name=next(iter(set(objects)-done))
        helper=objects[name]
        result['objects'][name]={'values':scalar_rna(helper),'props':props(helper),'parent':ref(helper.parent),
            'matrix_basis':[list(row) for row in helper.matrix_basis], 'constraints':constraints(helper),'drivers':drivers(helper)}
        done.add(name)
    return result


def validate(snapshot):
    if not isinstance(snapshot,dict) or len(snapshot.get('bones',[]))>10000:
        raise ValueError('Invalid raw rig snapshot')
    allowed_calls={'min','max','abs','sin','cos','tan','asin','acos','atan','atan2','sqrt','pow','exp','log','floor','ceil','round','radians','degrees'}
    owners=[snapshot]+list(snapshot.get('objects',{}).values())
    for owner in owners:
        for entry in owner.get('drivers',[])+owner.get('data_drivers',[]):
            if entry.get('use_self'):
                raise ValueError('Raw rig drivers using self are not supported')
            if entry.get('type')!='SCRIPTED': continue
            tree=ast.parse(entry.get('expression','0'),mode='eval')
            variables={v['name'] for v in entry['variables']}
            allowed=(ast.Expression,ast.BinOp,ast.UnaryOp,ast.BoolOp,ast.Compare,ast.IfExp,ast.Call,ast.Name,ast.Load,ast.Constant,ast.operator,ast.unaryop,ast.boolop,ast.cmpop)
            for node in ast.walk(tree):
                if not isinstance(node,allowed):
                    raise ValueError('Unsupported raw rig driver expression')
                if isinstance(node,ast.Name) and node.id not in variables|allowed_calls|{'pi','e','frame'}:
                    raise ValueError('Unsupported raw rig driver name: '+node.id)
                if isinstance(node,ast.Call) and (not isinstance(node.func,ast.Name) or node.func.id not in allowed_calls):
                    raise ValueError('Unsupported raw rig driver call')


def restore(context,obj,snapshot):
    validate(snapshot)
    from ..extras.create_animation_rig import _activate_armature,_ensure_widget_object
    _activate_armature(context,obj)
    mode=obj.mode
    bpy.ops.object.mode_set(mode='EDIT')
    for record in snapshot['bones']:
        b=obj.data.edit_bones.get(record['name']) or obj.data.edit_bones.new(record['name'])
        b.use_connect=False
        b.length=max(record['length'],1e-5)
        b.matrix=Matrix(record['matrix'])
        set_props(b,record.get('bone_props',{}))
    for record in snapshot['bones']:
        b=obj.data.edit_bones[record['name']]
        b.parent=obj.data.edit_bones.get(record['parent']) if record['parent'] else None
    bpy.ops.object.mode_set(mode='POSE')
    widgets={}
    for name,geometry in snapshot.get('widgets',{}).items():
        digest=hashlib.sha256(json.dumps(geometry,sort_keys=True).encode()).hexdigest()[:16]
        widget=_ensure_widget_object(context,'Raw_'+digest,geometry['vertices'],geometry['edges'])
        if geometry.get('faces') and not widget.data.polygons:
            widget.data.clear_geometry()
            widget.data.from_pydata(geometry['vertices'],geometry['edges'],geometry['faces'])
            widget.data.update()
        widgets[name]=widget
    helpers={}
    for name in snapshot.get('objects',{}):
        helper=next((o for o in bpy.data.objects if o.get('sub_raw_owner')==obj.name and o.get('sub_raw_source')==name),None)
        if helper is None:
            helper=bpy.data.objects.new(name,None)
            context.collection.objects.link(helper)
        helper['sub_raw_owner'],helper['sub_raw_source']=obj.name,name
        helpers[name]=helper
    def resolve(value):
        if value=='SELF': return obj
        if value=='DATA': return obj.data
        if value and value.startswith('OBJECT:'):
            name=value[7:]
            return helpers.get(name) or bpy.data.objects.get(name)
        return None
    def constraints(owner,entries):
        for con in list(owner.constraints): owner.constraints.remove(con)
        for entry in entries:
            con=owner.constraints.new(entry['type'])
            con.name=entry['name']
            set_rna(con,entry['values'])
            for key,value in entry.get('pointers',{}).items():
                try: setattr(con,key,resolve(value))
                except (TypeError,AttributeError): pass
    def drivers(owner,entries):
        owner.animation_data_create()
        for fc in list(owner.animation_data.drivers): owner.animation_data.drivers.remove(fc)
        for entry in entries:
            try: fc=owner.driver_add(entry['path'],entry['index'])
            except TypeError: fc=owner.driver_add(entry['path'])
            d=fc.driver
            d.type=entry['type']
            for var in list(d.variables): d.variables.remove(var)
            for data in entry['variables']:
                var=d.variables.new()
                var.name,var.type=data['name'],data['type']
                for target,values in zip(var.targets,data['targets']):
                    set_rna(target,values['values'])
                    target.id=resolve(values['id'])
            d.expression=entry['expression']
            fc.mute=entry.get('mute',False)
    for record in snapshot.get('collections',[]):
        col=obj.data.collections.get(record['name']) or obj.data.collections.new(record['name'])
        col.is_visible=record['visible']
    for record in snapshot['bones']:
        pb=obj.pose.bones[record['name']]
        set_rna(pb.bone,record['bone'])
        set_rna(pb,record['pose'])
        set_props(pb,record.get('pose_props',{}))
        pb.custom_shape=widgets.get(record.get('shape'))
        pb.custom_shape_transform=obj.pose.bones.get(record.get('shape_transform','')) if record.get('shape_transform') else None
        pb.bone.color.palette=record.get('color','DEFAULT')
        for col in list(pb.bone.collections): col.unassign(pb.bone)
        for name in record.get('collections',[]):
            col=obj.data.collections.get(name) or obj.data.collections.new(name)
            col.assign(pb.bone)
        constraints(pb,record.get('constraints',[]))
    set_props(obj,snapshot.get('object_props',{}))
    set_props(obj.data,snapshot.get('data_props',{}))
    restore_addon(obj,snapshot.get('object_addon',{}))
    restore_addon(obj.data,snapshot.get('data_addon',{}))
    for name,record in snapshot.get('objects',{}).items():
        helper=helpers[name]
        set_rna(helper,record['values'])
        set_props(helper,record['props'])
        helper.parent=resolve(record['parent'])
        helper.matrix_basis=Matrix(record['matrix_basis'])
        constraints(helper,record['constraints'])
        drivers(helper,record['drivers'])
    drivers(obj,snapshot.get('drivers',[]))
    drivers(obj.data,snapshot.get('data_drivers',[]))
    if mode in {'OBJECT','POSE'}: bpy.ops.object.mode_set(mode=mode)
