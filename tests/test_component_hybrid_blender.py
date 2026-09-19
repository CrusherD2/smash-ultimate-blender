"""Unsupported components must not require Blender updates for native probes."""
from pathlib import Path
fixture=Path(__file__).with_name('test_addon_registration_blender.py')
exec(compile(fixture.read_text(encoding='utf-8-sig').split('addon_utils.disable(MODULE')[0],str(fixture),'exec'))
from mathutils import Matrix
graph=importlib.import_module(MODULE+'.source.extras.component_graph')
data=bpy.data.armatures.new('Hybrid checks')
obj=bpy.data.objects.new('Hybrid checks',data)
bpy.context.scene.collection.objects.link(obj)
bpy.context.view_layer.objects.active=obj;obj.select_set(True)
bpy.ops.object.mode_set(mode='EDIT')
for name in ('Fast','Slow','Dependent','Target'):
    bone=data.edit_bones.new(name);bone.head=(0,0,0);bone.tail=(0,1,0)
bpy.ops.object.mode_set(mode='POSE')
for name,target in (('Fast','Target'),('Dependent','Slow')):
    con=obj.pose.bones[name].constraints.new('COPY_TRANSFORMS')
    con.target=obj;con.subtarget=target;con.owner_space=con.target_space='POSE'
external=bpy.data.objects.new('External target',None)
bpy.context.scene.collection.objects.link(external)
external.location=(2,3,4)
owners={'Fast':'fast','Slow':'slow','Dependent':'dependent'}
updates=[0]
def reference():
    updates[0]+=1
    obj.update_tag();bpy.context.view_layer.update()
    return obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
def verify():
    rig=graph.capture_for_match(obj,owners,(),set(owners),reference)
    try:
        assert 'fast' in rig.graphs and 'slow' not in rig.graphs and 'dependent' not in rig.graphs,graph.LAST_DIAGNOSTICS
        before=updates[0]
        for i in range(6):
            obj.pose.bones['Target'].location.x=i/10
            actual=rig.evaluate().pose.bones['Fast'].matrix
            assert abs(actual.translation.x-i/10)<1e-6
        assert updates[0]==before,'Unrelated reference component evaluated during fast probes'
        result=rig.evaluate()
        slow=result.pose.bones['Slow'].matrix
        dependent=result.pose.bones['Dependent'].matrix
        assert updates[0]==before+1,'Reference should be cached per evaluation'
        for name,actual in (('Slow',slow),('Dependent',dependent)):
            expected=obj.pose.bones[name].matrix
            assert max(abs(a-b) for ra,rb in zip(actual,expected) for a,b in zip(ra,rb))<2e-5
        rig.reject(['Slow'],'forced verification rejection')
        assert 'fast' in rig.graphs
    finally:
        rig.close()
slow=obj.pose.bones['Slow']
for kind in ('LIMIT_ROTATION','CHILD_OF'):
    con=slow.constraints.new(kind)
    if kind=='LIMIT_ROTATION':
        con.owner_space='CUSTOM';con.space_object=external
        con.use_limit_z=True;con.min_z=-.2;con.max_z=.2;slow.rotation_mode='XYZ';slow.rotation_euler.z=.8
    else:
        external.parent=obj
        con.target=external
    verify()
    slow.constraints.remove(con)
    external.parent=None
fc=slow.driver_add('location',0)
fc.driver.type='SCRIPTED';fc.driver.expression='sin(value)'
var=fc.driver.variables.new();var.name='value';var.type='TRANSFORMS'
var.targets[0].id=external;var.targets[0].transform_type='LOC_X'
verify()
slow.driver_remove('location',0)
# Detect a candidate-dependent cycle at capture, before recursive native calls.
for name,target in (('Slow','Dependent'),):
    con=slow.constraints.new('COPY_TRANSFORMS');con.target=obj;con.subtarget=target;con.owner_space=con.target_space='POSE'
rig=graph.capture_for_match(obj,owners,(),set(owners),reference)
try:
    assert set(rig.graphs)=={'fast'},graph.LAST_DIAGNOSTICS
    assert 'cycle' in graph.LAST_DIAGNOSTICS['components']['slow']['reason']
finally:
    rig.close()
print('HYBRID COMPONENT DEPENDENCY, LAZY FALLBACK AND CYCLE CHECKS PASSED')
