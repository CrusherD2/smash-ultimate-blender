"""Production fast-path exact outputs, guard selection, and failure cleanup."""
from pathlib import Path
import os
import json
import importlib
from contextlib import contextmanager

root = Path(__file__).resolve().parents[1]
bench = root/'tests/benchmark_position_ik_blender.py'
exec(compile(bench.read_text().split("\nfor repeat in range(int(os.environ.get('SUB_MATCH_RUNS'")[0],str(bench),'exec'))
fast = importlib.import_module(MODULE+'.source.extras.ik_match_fast')
os.environ['SUB_NATIVE_IK']='0'
counts = dict(sampled=0,isolated=0)
sample_original,isolate_original = fast.sample_fk,fast.isolated
def sample(*args):
    if os.environ.get('SUB_FAST_TEST_MODE')=='isolate':
        return None
    result = sample_original(*args)
    counts['sampled'] += int(result is not None)
    return result
@contextmanager
def isolate(context,obj,*args):
    if os.environ.get('SUB_FAST_TEST_MODE')=='sample':
        yield context,obj,context.scene
        return
    with isolate_original(context,obj,*args) as result:
        counts['isolated'] += int(result[1] != obj)
        yield result
fast.sample_fk,fast.isolated = sample,isolate
results = []
def reload():
    bpy.ops.wm.open_mainfile(filepath=str(baseline))
    obj = next(o for o in bpy.context.scene.objects if o.type=='ARMATURE')
    bpy.context.view_layer.objects.active=obj
    obj.select_set(True)
    ik.create_controls(bpy.context,obj,'BOTH')
    bpy.context.scene.frame_end=bpy.context.scene.frame_start+15
    return obj
def custom_handler(*args):
    pass
for scenario in ('normal','object_scale','object_animation','parent_scale','inheritance','stretch','arm_pull',
                 'foot_controls','animated_stretch','rematch','handler','current','no_keys'):
    if os.environ.get('SUB_FAST_CASES') and scenario not in os.environ['SUB_FAST_CASES'].split(','):
        continue
    snapshots=[]
    usages=[]
    for enabled in (False,True):
        obj=reload()
        scene=bpy.context.scene
        jobs=list(ik.chains(obj))
        if scenario=='object_scale':
            obj.scale=(1.2,.7,1.1)
            obj.rotation_euler=(.21,-.37,.14)
        elif scenario=='object_animation':
            obj.keyframe_insert('rotation_euler',frame=scene.frame_start)
            obj.rotation_euler=(.21,-.37,.14)
            obj.keyframe_insert('rotation_euler',frame=scene.frame_end)
            scene.frame_set(scene.frame_start)
        elif scenario=='parent_scale':
            pb=obj.pose.bones[ik.PREFIX+ik.limb_path(obj,jobs[0][1])[0]].parent
            pb.scale=(1.2,.7,1.1)
            for f in range(scene.frame_start,scene.frame_end+1):
                pb.keyframe_insert('scale',frame=f)
        elif scenario=='inheritance':
            for _,names,_,_ in jobs:
                for n in ik.limb_path(obj,names):
                    obj.data.bones[n].inherit_scale='ALIGNED'
                    obj.data.bones[ik.PREFIX+n].inherit_scale='ALIGNED'
        elif scenario in {'stretch','arm_pull','animated_stretch'}:
            obj.data.sub_ik_stretch_arms=True
            obj.data.sub_ik_stretch_legs=True
            obj.data.sub_ik_stretch_chain_arms=True
            obj.data.sub_ik_stretch_chain_legs=True
            if scenario=='arm_pull':
                for kind,_,_,pole in jobs:
                    if kind=='ARMS':
                        setattr(obj.data.bones[pole],ik.ARM_PULL_PROPERTY,.7)
            elif scenario=='animated_stretch':
                for f in range(scene.frame_start,scene.frame_end+1):
                    obj.data.sub_ik_stretch_arms=bool(f%2)
                    obj.data.keyframe_insert('sub_ik_stretch_arms',frame=f)
        elif scenario=='foot_controls':
            for _,names,_,_ in jobs:
                foot=ik.foot_controls(names,obj)
                if foot:
                    obj.pose.bones[foot[0]].rotation_euler.x=.3
                    obj.pose.bones[foot[1]].rotation_euler.x=-.2
        elif scenario=='rematch':
            ik.match(bpy.context,obj,_batch=True,_fast=False)
        elif scenario=='handler':
            bpy.app.handlers.frame_change_post.append(custom_handler)
        before=(len(bpy.data.scenes),len(bpy.data.objects),len(bpy.data.armatures),obj.mode,scene.frame_current)
        counts.update(sampled=0,isolated=0)
        try:
            ik.match(bpy.context,obj,_batch=True,_fast=enabled,
                     entire=scenario!='current',key=scenario!='no_keys')
            assert before==(len(bpy.data.scenes),len(bpy.data.objects),len(bpy.data.armatures),obj.mode,scene.frame_current)
            snapshots.append(fingerprint(obj))
            usages.append(dict(counts))
        finally:
            if custom_handler in bpy.app.handlers.frame_change_post:
                bpy.app.handlers.frame_change_post.remove(custom_handler)
    results.append(dict(scenario=scenario,exact=snapshots[0]==snapshots[1],usage=usages,snapshots=snapshots))
    print('FAST_CASE',results[-1],flush=True)
obj=reload()
before=(len(bpy.data.scenes),len(bpy.data.objects),len(bpy.data.armatures),obj.mode,bpy.context.scene.frame_current)
constraints=[(c,c.mute) for _,c,_ in (*ik.outputs(obj),*ik.toe_outputs(obj))]
evaluate=ik._evaluate_match_steps
def fail(*args):
    raise ValueError('injected solve failure')
ik._evaluate_match_steps=fail
try:
    try:
        ik.match(bpy.context,obj,_batch=True)
        raise AssertionError('failure was swallowed')
    except ValueError:
        pass
finally:
    ik._evaluate_match_steps=evaluate
assert before==(len(bpy.data.scenes),len(bpy.data.objects),len(bpy.data.armatures),obj.mode,bpy.context.scene.frame_current)
assert all(c.mute==mute for c,mute in constraints)
suffix = '_'+os.environ['SUB_FAST_CASES'] if os.environ.get('SUB_FAST_CASES') else ''
out=root/'.tests/benchmarks'/f'fast_cases_{bpy.app.version[0]}.{bpy.app.version[1]}{suffix}.json'
out.write_text(json.dumps(results,indent=2))
assert all(r['exact'] for r in results),results
if not os.environ.get('SUB_FAST_CASES'):
    assert results[0]['usage'][1]==dict(sampled=1,isolated=1), ('normal fast path did not run',results[0],[(f.__module__,f.__name__) for f in bpy.app.handlers.frame_change_post])
assert all(r['usage'][1]==dict(sampled=0,isolated=0) for r in results if r['scenario'] in {'handler','current','no_keys'})
print('FAST_MATCH_EXACT_AND_CLEANUP_OK')
