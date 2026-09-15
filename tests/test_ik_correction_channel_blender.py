"""Upstream rig additions must not silently degrade the accelerated match.

blender --background --factory-startup --python-exit-code 1 --python tests/test_ik_correction_channel_blender.py

Two integration failures this guards, both of which were silent -- correct or
plausible-looking output, no error, and no other failing test in the suite:

1. `wire()` adds a `SUB IK Progressive Scale` driver per chain link whose
   expression embeds that link's fraction of the chain length. The dependency
   audit whitelists driver expressions by exact text, so an unrecognised one
   rejects the whole rig and turns off batching, mesh deferral, direct
   sampling, isolation and the native backend at once. The match stays
   correct, it just quietly costs what it cost before any of that existed.

2. `_match_chain_steps` keys the FK residual into the BL_SUB_IK_MATCH_ bones,
   which is what makes the match exact rather than approximate. They are
   children of the solve bones, and the isolation closure only walks parents
   and constraint targets, so pruning drops them -- and the write is guarded
   by `if correction is not None`, so it simply stops happening. That is worse
   than absent: stale residuals from an earlier match stay in the action.

Requires the IK benchmark baseline (.tests/benchmarks/ik_apply/out/baseline.blend).
"""
from pathlib import Path
import importlib
import os

root = Path(__file__).resolve().parents[1]
bench = root / 'tests/benchmark_position_ik_blender.py'
exec(compile(bench.read_text().split("for repeat in range(int(os.environ.get('SUB_MATCH_RUNS'")[0], str(bench), 'exec'))

if not baseline.exists():
    print(f'SKIP ik correction channel, no baseline at {baseline}')
    raise SystemExit(0)

diag = importlib.import_module(MODULE + '.source.extras.ik_match_diag')
fast = importlib.import_module(MODULE + '.source.extras.ik_match_fast')
curves = importlib.import_module(MODULE + '.source.anim.fcurve_compat')


def build(frames=32):
    """Fresh controls on the baseline rig over a range the fast path accepts."""
    bpy.ops.wm.open_mainfile(filepath=str(baseline))
    obj = next(o for o in bpy.context.scene.objects if o.type == 'ARMATURE')
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    ik.create_controls(bpy.context, obj, 'BOTH')
    bpy.context.scene.frame_end = bpy.context.scene.frame_start + frames - 1
    return obj


obj = build()
jobs = list(ik.chains(obj))
assert len(jobs) >= 2, jobs

# The progressive-scale drivers must actually be on this rig. Without this the
# audit assertions below would pass vacuously if the feature were renamed.
progressive = [fc for fc in obj.animation_data.drivers
               if 'SUB IK Progressive Scale' in fc.data_path]
assert progressive, 'no SUB IK Progressive Scale drivers; has wire() changed?'
for fc in progressive:
    target = fc.driver.variables[0].targets[0]
    assert target.id == obj.data, fc.data_path
    assert target.data_path.startswith('sub_ik_progressive_scale_'), target.data_path

# ...and the audit must accept them rather than rejecting the rig outright.
diag.reset()
assert ik._can_batch_match(obj, jobs), diag.record()['reasons']
assert diag.record()['reasons']['batch'] == 'ok', diag.record()
diag.reset()
assert ik._is_self_contained(obj, jobs), diag.record()['reasons']
assert diag.record()['reasons']['selfcontained'] == 'ok', diag.record()

# Correction bones exist, and the isolated solve scene keeps every one of them.
corrections = [b.name for b in obj.data.bones if b.name.startswith(ik.CORRECTION_PREFIX)]
assert corrections, 'no correction bones; ensure() should create them at version 4'
assert obj.data[ik.VERSION] >= 4, obj.data[ik.VERSION]
assert fast.can_isolate(obj, jobs, ik), diag.record()['reasons']
with fast.isolated(bpy.context, obj, jobs, ik) as (_context, clone, _scene):
    assert clone is not obj, 'isolation fell back; this test would prove nothing'
    kept = {b.name for b in clone.data.bones if b.name.startswith(ik.CORRECTION_PREFIX)}
missing = sorted(set(corrections) - kept)
assert not missing, f'isolation pruned {len(missing)} correction bones: {missing[:4]}'

# End to end: a whole-animation match on the accelerated path must leave a
# keyed channel on every correction bone. This is the assertion that fails if
# the residual write is bypassed for any reason, not only by pruning.
obj = build()
os.environ['SUB_IK_DIAG'] = '1'
ik.match(bpy.context, obj, 'BOTH', entire=True, key=True, _batch=True)
reasons = diag.record()['reasons']
assert reasons.get('isolate') == 'ok', f'fast path did not engage: {reasons}'
action = obj.animation_data.action
prefix = 'pose.bones["' + ik.CORRECTION_PREFIX
keyed = {fc.data_path.split('"')[1]
         for fc in curves.get_all_action_fcurves(action, id_type='OBJECT')
         if fc.data_path.startswith(prefix)}
unkeyed = sorted(n for n in corrections if n not in keyed)
assert not unkeyed, f'{len(unkeyed)} correction bones never keyed: {unkeyed[:4]}'

print('IK_CORRECTION_CHANNEL_OK')
