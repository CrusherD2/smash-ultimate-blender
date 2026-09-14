"""One selected chain reaches direct sampling and isolated solving, exactly."""
from pathlib import Path
from contextlib import contextmanager
import os, json, importlib

root = Path(__file__).resolve().parents[1]
bench = root/'tests/benchmark_position_ik_blender.py'
exec(compile(bench.read_text().split("\nfor repeat in range(int(os.environ.get('SUB_MATCH_RUNS'")[0], str(bench), 'exec'))
os.environ['SUB_NATIVE_IK'] = '0'
fast = importlib.import_module(MODULE+'.source.extras.ik_match_fast')
compat = importlib.import_module(MODULE+'.source.anim.fcurve_compat')

counts = dict(sampled=0, isolated=0)
sample_original, isolate_original = fast.sample_fk, fast.isolated

def sample(*args):
    result = sample_original(*args)
    counts['sampled'] += int(result is not None)
    return result

@contextmanager
def isolate(context, obj, *args):
    with isolate_original(context, obj, *args) as result:
        counts['isolated'] += int(result[1] != obj)
        yield result

fast.sample_fk, fast.isolated = sample, isolate

def reload():
    bpy.ops.wm.open_mainfile(filepath=str(baseline))
    obj = next(o for o in bpy.context.scene.objects if o.type == 'ARMATURE')
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    ik.create_controls(bpy.context, obj, 'BOTH')
    bpy.context.scene.frame_end = bpy.context.scene.frame_start + 19
    return obj

def snapshot(obj):
    keys = sorted((f.data_path, f.array_index,
                   [(tuple(k.co), k.interpolation) for k in f.keyframe_points])
                  for f in compat.get_all_action_fcurves(obj.animation_data.action, id_type='OBJECT'))
    poses = []
    for frame in range(bpy.context.scene.frame_start, bpy.context.scene.frame_end+1):
        bpy.context.scene.frame_set(frame)
        poses.append([[tuple(r) for r in b.matrix] for b in obj.pose.bones])
    return json.dumps([keys, poses])

# match() reads its jobs from chains(); one job is the case under test.
#
# Two defects in the naive version of this test (patch ik.chains globally to
# always return one job, wrap it around the whole loop including reload(),
# and call match() with the default limbs='BOTH'):
#
# 1. reload() calls ik.create_controls(bpy.context, obj, 'BOTH'), which builds
#    the rig from chains(). A truncated chains() during rig construction would
#    generate controls for one limb only -- testing a one-limb *rig* instead
#    of a one-limb *match* on a multi-limb rig, which is the case under test.
#    Fix: reload() runs with chains() unpatched, building the full rig; the
#    patch is scoped to the ik.match() call only.
#
# 2. _dependency_audit() (which both _is_self_contained and _can_batch_match
#    call) does not use its own `jobs` parameter -- it always recomputes
#    `chains(obj, 'BOTH')` internally to see the whole rig, deliberately
#    including limbs the caller did not select (see its docstring: "Include
#    unselected limbs: their solvers also evaluate, but do not make otherwise
#    independent selected chains unsafe to schedule together"). A patch that
#    truncates chains() for every call -- including that internal 'BOTH'
#    query -- corrupts the audit itself: it can no longer see the other
#    limbs' already-keyframed pole-angle constraints and IK bones, so it
#    rejects the rig as not self-contained (reason: animated_constraint),
#    and the fast paths never engage regardless of this task's change.
#    Fix: truncate only the 'LEGS' query (what jobs/ensure/outputs use for
#    this match, since it is called with limbs='LEGS'), and leave the
#    hardcoded 'BOTH' query the audit uses untouched, so it audits the real,
#    complete rig -- exactly like production does for any caller that
#    matches a subset of limbs.
real_chains = ik.chains
results = []
for enabled in (False, True):
    obj = reload()                       # UNPATCHED: builds the full multi-limb rig
    counts.update(sampled=0, isolated=0)
    try:
        ik.chains = lambda obj, limbs='BOTH': (list(real_chains(obj, limbs))[:1]
                                                if limbs == 'LEGS' else list(real_chains(obj, limbs)))
        assert len(list(ik.chains(obj, 'LEGS'))) == 1
        ik.match(bpy.context, obj, limbs='LEGS', _batch=True, _fast=enabled)
    finally:
        ik.chains = real_chains
    results.append((snapshot(obj), dict(counts)))

assert results[0][0] == results[1][0], 'single-chain fast path changed the output'
assert results[0][1] == dict(sampled=0, isolated=0), results[0][1]
assert results[1][1] == dict(sampled=1, isolated=1), results[1][1]
print('IK_SINGLE_CHAIN_FAST_OK')
