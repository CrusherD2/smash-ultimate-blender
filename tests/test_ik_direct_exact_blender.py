"""Detached FK sampling must match Blender exactly across channel types."""
from pathlib import Path
import importlib
import random
import json

fixture=Path(__file__).with_name('test_addon_registration_blender.py')
exec(compile(fixture.read_text().split('addon_utils.disable(MODULE')[0],str(fixture),'exec'))
fast=importlib.import_module(MODULE+'.source.extras.ik_match_fast')
compat=importlib.import_module(MODULE+'.source.anim.fcurve_compat')
bpy.ops.wm.read_factory_settings(use_empty=True)
rng=random.Random(91317)
data=bpy.data.armatures.new('Direct sample fixture')
obj=bpy.data.objects.new('Direct sample fixture',data)
bpy.context.scene.collection.objects.link(obj)
bpy.context.view_layer.objects.active=obj
obj.select_set(True)
bpy.ops.object.mode_set(mode='EDIT')
for i in range(6):
    b=data.edit_bones.new('bone'+str(i))
    b.head=(rng.uniform(-1,1),i*1.4,rng.uniform(-1,1))
    b.tail=(rng.uniform(-1,1),i*1.4+1,rng.uniform(-1,1))
    b.roll=rng.uniform(-2,2)
    if i:
        b.parent=data.edit_bones['bone'+str(i-1)]
bpy.ops.object.mode_set(mode='OBJECT')
names=list(obj.pose.bones.keys())
results=[]
for mode in ('QUATERNION','XYZ','ZYX','AXIS_ANGLE'):
    obj.animation_data_clear()
    for pb in obj.pose.bones:
        pb.rotation_mode=mode
        for f in (1,7,13,20):
            pb.location=[rng.uniform(-.4,.4) for _ in range(3)]
            pb.scale=[rng.uniform(.5,1.5) for _ in range(3)]
            if mode=='QUATERNION':
                prop='rotation_quaternion'
                pb.rotation_quaternion=[rng.uniform(-1,1) for _ in range(4)]
            elif mode=='AXIS_ANGLE':
                prop='rotation_axis_angle'
                pb.rotation_axis_angle=[rng.uniform(-2,2),.3,.5,.7]
            else:
                prop='rotation_euler'
                pb.rotation_euler=[rng.uniform(-1,1) for _ in range(3)]
            for p in ('location','scale',prop):
                pb.keyframe_insert(p,frame=f)
    curves=list(compat.get_all_action_fcurves(obj.animation_data.action,id_type='OBJECT'))
    for i,fc in enumerate(curves):
        for key in fc.keyframe_points:
            key.interpolation='LINEAR' if i%2 else 'BEZIER'
        if i%11==0:
            fc.modifiers.new('NOISE').strength=.1
    frames=list(range(1,21))
    expected={}
    for f in frames:
        bpy.context.scene.frame_set(f)
        bpy.context.view_layer.update()
        expected[f]={n:tuple(tuple(r) for r in obj.pose.bones[n].matrix) for n in names}
    actual=fast.sample_fk(obj,frames,names,curves)
    assert actual is not None,mode
    failures=[dict(frame=f,bone=n) for f in frames for n in names
              if tuple(tuple(r) for r in actual[f][n])!=expected[f][n]]
    results.append(dict(mode=mode,matrices=len(frames)*len(names),failures=failures))
    print('DIRECT_EXACT_CASE',results[-1],flush=True)
bpy.ops.object.mode_set(mode='EDIT')
data.edit_bones[names[1]].use_connect=True
bpy.ops.object.mode_set(mode='OBJECT')
assert fast.sample_fk(obj,frames,names,curves) is None
bpy.ops.object.mode_set(mode='EDIT')
data.edit_bones[names[1]].use_connect=False
bpy.ops.object.mode_set(mode='OBJECT')
data.bones[names[1]].inherit_scale='ALIGNED'
assert fast.sample_fk(obj,frames,names,curves) is None
data.bones[names[1]].inherit_scale='FULL'
obj.animation_data.action_influence=.5
assert fast.sample_fk(obj,frames,names,curves) is None
out=ROOT/'.tests/benchmarks'/f'direct_exact_cases_{bpy.app.version[0]}.{bpy.app.version[1]}.json'
out.write_text(json.dumps(results,indent=2))
assert all(not r['failures'] for r in results),results
print('DIRECT_EXACT_AND_GUARDS_OK')
