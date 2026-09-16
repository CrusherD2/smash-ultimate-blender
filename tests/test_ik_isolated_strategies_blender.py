"""Exact keys/whole-rig comparisons for non-default isolated-solver inputs."""
from pathlib import Path
import os
import json
import sys

root = Path(__file__).resolve().parents[1]
bench = root/'tests/benchmark_ik_strategies_blender.py'
os.environ['SUB_STRATEGIES'] = 'baseline,isolate_minimal,isolate_minimal_direct_exact'
setup = bench.read_text().split("\nfor repeat in range(int(os.environ.get('SUB_MATCH_RUNS'")[0]
exec(compile(setup,str(bench),'exec'))
results = []
for scenario in ('normal','object_scale','parent_scale','inheritance','stretch','arm_pull','foot_controls','animated_stretch','rematch'):
    snapshots = []
    for variant in variants:
        exec(compile(sources[variant],variant,'exec'),ik.__dict__)
        bpy.ops.wm.open_mainfile(filepath=str(baseline))
        obj = next(o for o in bpy.context.scene.objects if o.type=='ARMATURE')
        bpy.context.view_layer.objects.active = obj
        obj.select_set(True)
        ik.create_controls(bpy.context,obj,'BOTH')
        bpy.context.scene.frame_end = bpy.context.scene.frame_start+4
        jobs = list(ik.chains(obj))
        if scenario=='object_scale':
            obj.scale = (1.2,.7,1.1)
            obj.rotation_euler = (.21,-.37,.14)
        elif scenario=='parent_scale':
            pb = obj.pose.bones[ik.PREFIX+ik.limb_path(obj,jobs[0][1])[0]].parent
            pb.scale = (1.2,.7,1.1)
            # Ensure the modified scale survives frame changes.
            for f in range(bpy.context.scene.frame_start,bpy.context.scene.frame_end+1):
                pb.keyframe_insert('scale',frame=f)
        elif scenario=='inheritance':
            for _,names,_,_ in jobs:
                for n in ik.limb_path(obj,names):
                    obj.data.bones[ik.PREFIX+n].inherit_scale = 'ALIGNED'
        elif scenario=='stretch':
            obj.data.sub_ik_stretch_arms = True
            obj.data.sub_ik_stretch_legs = True
            obj.data.sub_ik_stretch_chain_arms = True
            obj.data.sub_ik_stretch_chain_legs = True
        elif scenario=='arm_pull':
            obj.data.sub_ik_stretch_arms = True
            obj.data.sub_ik_stretch_chain_arms = True
            for kind,_,_,pole in jobs:
                if kind=='ARMS':
                    setattr(obj.data.bones[pole],ik.ARM_PULL_PROPERTY,.7)
        elif scenario=='foot_controls':
            for _,names,_,_ in jobs:
                foot = ik.foot_controls(names,obj)
                if foot:
                    obj.pose.bones[foot[0]].rotation_euler.x = .3
                    obj.pose.bones[foot[1]].rotation_euler.x = -.2
        elif scenario=='animated_stretch':
            obj.data.sub_ik_stretch_chain_arms = True
            for f in range(bpy.context.scene.frame_start,bpy.context.scene.frame_end+1):
                obj.data.sub_ik_stretch_arms = bool(f % 2)
                obj.data.keyframe_insert('sub_ik_stretch_arms',frame=f)
        elif scenario=='rematch':
            # Previous destination curves must not alter the isolated search.
            exec(compile(sources['baseline'],'baseline','exec'),ik.__dict__)
            ik.match(bpy.context,obj,'BOTH',_batch=True)
            exec(compile(sources[variant],variant,'exec'),ik.__dict__)
        before = (len(bpy.data.scenes),len(bpy.data.objects),len(bpy.data.armatures))
        ik.match(bpy.context,obj,'BOTH',_batch=True)
        assert before==(len(bpy.data.scenes),len(bpy.data.objects),len(bpy.data.armatures))
        snapshots.append(fingerprint(obj))
    results.append(dict(scenario=scenario,exact=[s==snapshots[0] for s in snapshots],snapshots=snapshots))
out = root/'.tests/benchmarks'/f'isolated_cases_{bpy.app.version[0]}.{bpy.app.version[1]}.json'
out.write_text(json.dumps(results,indent=2))
print('ISOLATED_CASES',results)

# One combination is expected to diverge, and it is the reason a guard exists in
# production. ik_match_fast.sample_fk refuses a transformed object outright
# ('transformed_object', see the note there about Blender's object-space round
# trips) and falls back to evaluated sampling, so the shipped fast path stays
# exact under object_scale. ik_direct_exact_prototype is forty lines with no
# such guard, so under a non-uniformly scaled and rotated object it samples
# directly and drifts. That is a property of the prototype, not a regression.
#
# Asserted in both directions on purpose: a NEW divergence fails, and so does
# this one going away, because the prototype being fixed -- or the production
# guard being relaxed -- is worth hearing about rather than silently passing.
KNOWN_DIVERGENCE = {('object_scale', 'isolate_minimal_direct_exact')}
unexpected, no_longer = [], []
for r in results:
    for variant, exact in zip(variants, r['exact']):
        pair = (r['scenario'], variant)
        if not exact and pair not in KNOWN_DIVERGENCE:
            unexpected.append(pair)
        if exact and pair in KNOWN_DIVERGENCE:
            no_longer.append(pair)
assert not unexpected, f'new strategy divergence: {unexpected}'
assert not no_longer, (f'{no_longer} no longer diverges -- the prototype or the '
                       'transformed-object guard changed; update KNOWN_DIVERGENCE')
print(f'ISOLATED_STRATEGIES_OK scenarios={len(results)} '
      f'variants={len(variants)} known={sorted(KNOWN_DIVERGENCE)}')
