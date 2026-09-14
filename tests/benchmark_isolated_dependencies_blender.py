"""Time each isolated-clone dependency reduction against the exact baseline.

Measurement only. Exactness is recorded, never asserted: a reduction that
changes output is a result for Task 6's gate, not a test failure here.

REMOVED MACHINERY, KEPT HARNESS (2026-09-13): all three reductions this
benchmark drives (`action`, `pin`, `bbone`, and the ``SUB_IK_REDUCE`` flag
that selected them) were measured here, found not worth adopting, and
deleted from ``source/extras/ik_match_fast.py`` and ``ik_channels.py`` --
see docs/benchmarks/isolated-dependencies-2026-09-13.md for the results and
its "Adopted" section for the final call. Setting ``SUB_IK_REDUCE`` now does
nothing: there is no ``_reductions()`` left to read it, so every variant
below runs the same unmodified code path and the five rows this script
prints will read as identical (module the harness's own timing noise), not
as five different measurements. This script is NOT a runnable benchmark of
the reductions any more. To reproduce the original measurement, first
re-apply
docs/benchmarks/isolated-dependencies-2026-09-13-reductions.patch, which
restores the deleted helpers and call sites this file drives.
"""
from pathlib import Path
import os, importlib, json, time, hashlib, statistics

fixture = Path(__file__).with_name('test_addon_registration_blender.py')
exec(compile(fixture.read_text().split('addon_utils.disable(MODULE')[0], str(fixture), 'exec'))
os.environ['SUB_NATIVE_IK'] = '0'
os.environ['SUB_IK_DIAG'] = '1'
ik = importlib.import_module(MODULE+'.source.extras.ik_channels')
diag = importlib.import_module(MODULE+'.source.extras.ik_match_diag')
curves = importlib.import_module(MODULE+'.source.anim.fcurve_compat')
out = ROOT/'.tests/benchmarks/shyguy_ik_repro'
report = ROOT/'docs/benchmarks/isolated-dependencies-2026-09-13.json'
assert (out/'matched_wait.blend').exists(), 'missing fixture %s' % (out/'matched_wait.blend')


def fingerprint(obj):
    keys = sorted((f.data_path, f.array_index,
                   [(tuple(k.co), k.interpolation) for k in f.keyframe_points])
                  for f in curves.get_all_action_fcurves(obj.animation_data.action, id_type='OBJECT'))
    digest = hashlib.sha256()
    for f in range(bpy.context.scene.frame_start, bpy.context.scene.frame_end+1):
        bpy.context.scene.frame_set(f)
        digest.update(json.dumps([[tuple(r) for r in b.matrix] for b in obj.pose.bones]).encode())
    return dict(keys=hashlib.sha256(json.dumps(keys).encode()).hexdigest(), poses=digest.hexdigest())


def run(flags):
    os.environ['SUB_IK_REDUCE'] = flags
    bpy.ops.wm.open_mainfile(filepath=str(out/'matched_wait.blend'))
    obj = next(o for o in bpy.context.scene.objects if o.type == 'ARMATURE')
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    bones = len(obj.data.bones)
    start = time.perf_counter()
    assert bpy.ops.sub.fk_to_ik_transfer('EXEC_DEFAULT', cleanup_mode='LEGS',
                                         entire_animation=True) == {'FINISHED'}
    elapsed = time.perf_counter() - start
    snap = diag.record()
    return dict(flags=flags or 'baseline', seconds=elapsed, stages=snap['stages'],
                counts=snap['counts'], reasons=snap['reasons'], bones=bones,
                **fingerprint(obj))


variants = ('', 'action', 'pin', 'bbone', 'action,pin,bbone')
rows = []
for repeat in range(3):
    for flags in variants:
        row = run(flags)
        row['repeat'] = repeat
        rows.append(row)
        print('ISOLATED_REDUCTION', row, flush=True)
        report.write_text(json.dumps(rows, indent=2))

base_group = [r for r in rows if r['flags'] == 'baseline']
base = base_group[0]
summary = []
for flags in variants:
    group = [r for r in rows if r['flags'] == (flags or 'baseline')]
    exact = all(r['keys'] == base['keys'] and r['poses'] == base['poses'] for r in group)
    median = statistics.median(r['seconds'] for r in group)
    search = statistics.median(r['stages'].get('search', 0.0) for r in group)
    updates = statistics.median(r['counts'].get('search', 0) for r in group)
    line = dict(flags=flags or 'baseline', exact=exact, median=median,
                search=search, updates=updates,
                pin=group[-1]['reasons'].get('pin'),
                isolate=group[-1]['reasons'].get('isolate'))
    summary.append(line)
    print('ISOLATED_SUMMARY', line, flush=True)
report.write_text(json.dumps(dict(rows=rows, summary=summary), indent=2))
print('ISOLATED_REDUCTIONS_DONE', len(rows), flush=True)
