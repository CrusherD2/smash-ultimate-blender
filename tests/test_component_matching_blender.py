from pathlib import Path
fixture=Path(__file__).with_name('test_custom_components_blender.py')
exec(compile(fixture.read_text(encoding='utf-8').split('components = [')[0],str(fixture),'exec'))
matching=importlib.import_module(MODULE+'.source.extras.component_matching')
workflow=importlib.import_module(MODULE+'.source.extras.component_workflow')
visibility=importlib.import_module(MODULE+'.source.extras.component_visibility')
face=importlib.import_module(MODULE+'.source.extras.face_components')
editor.save_on_build=False
scene=bpy.context.scene
scene.frame_start,scene.frame_end=1,4
for frame in range(1,5):
    scene.frame_set(frame)
    for name,location,rotation in [('Trans',(frame*.1,0,0),(0,0,frame*.1)),('LidUpper',(.1*frame,0,0),(.2*frame,.05*frame,0)),('Jaw',(0,0,0),(.12*frame,0,0)),('EyeL',(0,0,0),(0,0,.08*frame)),('Tail0',(0,0,0),(.08*frame,0,0))]:
        pb=obj.pose.bones[name]
        pb.rotation_mode='XYZ'
        pb.location=location
        pb.rotation_euler=rotation
        pb.keyframe_insert('location',frame=frame)
        pb.keyframe_insert('rotation_euler',frame=frame)
source={}
for f in range(1,5):
    scene.frame_set(f)
    bpy.context.view_layer.update()
    source[f]={n:obj.pose.bones[n].matrix.copy() for n in ('LidUpper','Jaw','EyeL','Tail0','Tail1','Tail2','Tail3')}
scene.frame_set(1)
component('ISOLATED','Floating',['LidUpper'])
component('JAW','Jaw',['Jaw'])
component('LOOK_TARGET','Aim',['EyeL'])
c=component('IK','Tail IK',[])
c.root,c.middle,c.end='Tail0','Tail2','Tail3'
assert bpy.ops.sub.component_build()=={'FINISHED'}
c=editor.components[0]
c.hide_controlled=True
assert obj.data.bones['LidUpper'].hide
payload={'format':cc.FORMAT,'version':cc.VERSION,'name':'Test','components':[cc.serialize(c)]}
assert cc.validate_preset(payload)['components'][0]['hide_controlled']
c.hide_controlled=False
assert not obj.data.bones['LidUpper'].hide
c.hide_controlled=True
original_curves=[(fc.data_path,fc.array_index,[(tuple(k.co)) for k in fc.keyframe_points]) for fc in curves.get_all_action_fcurves(obj.animation_data.action)]
# Failure rolls back temporary input overrides and helper bones.
names_before=set(obj.pose.bones.keys())
original_fit=matching._fit
def fail(*args, **kwargs):
    raise RuntimeError('Injected fitting failure')
matching._fit=fail
try:
    matching.match_animation(bpy.context,obj,1,4)
    raise AssertionError('Failure injection did not run')
except RuntimeError as exc:
    assert 'Injected' in str(exc)
finally:
    matching._fit=original_fit
assert set(obj.pose.bones.keys())==names_before
assert not any(con.name.endswith(' Input') for p in obj.pose.bones for con in p.constraints)
count,extra=matching.match_animation(bpy.context,obj,1,4)
assert count==4
for f,poses in source.items():
    scene.frame_set(f)
    bpy.context.view_layer.update()
    for n,m in poses.items():
        now=obj.evaluated_get(bpy.context.evaluated_depsgraph_get()).pose.bones[n].matrix
        error=max(abs(now[i][j]-m[i][j]) for i in range(4) for j in range(4))
        assert error<2e-4,(f,n,error)
for path,index,keys in original_curves:
    fc=next(fc for fc in curves.get_all_action_fcurves(obj.animation_data.action) if fc.data_path==path and fc.array_index==index)
    if 'BL_' not in path and 'SUB_Custom_' not in path:
        assert [tuple(k.co) for k in fc.keyframe_points]==keys,(path,index)
# Remove original curves after matching: the controls and offsets are independent.
for fc in list(curves.get_all_action_fcurves(obj.animation_data.action)):
    if any(fc.data_path.startswith(obj.pose.bones[n].path_from_id()+'.') for n in ('LidUpper','Jaw','EyeL','Tail0','Tail1','Tail2','Tail3')):
        curves.remove_fcurve(obj.animation_data.action,fc,id_type='OBJECT')
for f,poses in source.items():
    scene.frame_set(f)
    bpy.context.view_layer.update()
    for n,m in poses.items():
        now=obj.evaluated_get(bpy.context.evaluated_depsgraph_get()).pose.bones[n].matrix
        error=max(abs(now[i][j]-m[i][j]) for i in range(4) for j in range(4))
        assert error<2e-4,(f,n,error)
assert any(abs(k.co.y)>.01 for fc in curves.get_all_action_fcurves(obj.animation_data.action) if 'BL_CC_' in fc.data_path and fc.data_path.endswith('location') for k in fc.keyframe_points)
workflow.bake_remove(bpy.context,obj,True)
assert not obj.data.bones['LidUpper'].hide
assert not any(p.bone.get('sub_match_helper') for p in obj.pose.bones)
for f,poses in source.items():
    scene.frame_set(f)
    bpy.context.view_layer.update()
    for n,m in poses.items():
        now=obj.pose.bones[n].matrix
        error=max(abs(now[i][j]-m[i][j]) for i in range(4) for j in range(4))
        assert error<2e-4,(f,n,error)
print('COMPONENT MATCH, SOURCE INDEPENDENCE, VISIBILITY AND BAKE PASSED')
