"""Whole-animation FK->IK match: wall time, evaluations and FK fidelity.

Runs on both the pre-merge and post-merge trees, so the same numbers can be
compared directly. Prints one MATCH line per repeat plus a MATCH_SUMMARY.

SUB_MATCH_RUNS repeats (default 3). Native mode comes from SUB_NATIVE_IK as
usual; unset is the shipped default.
"""
from pathlib import Path
import importlib
import json
import os
import time

fixture = Path(__file__).with_name('test_addon_registration_blender.py')
exec(compile(fixture.read_text().split('addon_utils.disable(MODULE')[0], str(fixture), 'exec'))

ik = importlib.import_module(MODULE + '.source.extras.ik_channels')
diag = importlib.import_module(MODULE + '.source.extras.ik_match_diag')
try:
    native = importlib.import_module(MODULE + '.source.extras.ik_native')
    MODE = native.mode()
except Exception:
    MODE = os.environ.get('SUB_NATIVE_IK', 'n/a')

BASELINE = Path(os.environ.get('SUB_BASELINE_BLEND',
                               ROOT / '.tests/benchmarks/ik_apply/out/baseline.blend'))
if not BASELINE.exists():
    print('SKIP match benchmark, no baseline at ' + str(BASELINE))
    raise SystemExit(0)

RUNS = int(os.environ.get('SUB_MATCH_RUNS', '3'))
LABEL = os.environ.get('SUB_MATCH_LABEL', 'unlabelled')
HAS_CORRECTIONS = hasattr(ik, 'CORRECTION_PREFIX')


def active():
    obj = next(o for o in bpy.context.scene.objects if o.type == 'ARMATURE')
    bpy.context.view_layer.objects.active = obj
    for other in bpy.context.scene.objects:
        other.select_set(other is obj)
    return obj


def limb_names(obj):
    names = []
    for _kind, chain, _target, _pole in ik.chains(obj, 'BOTH'):
        names.extend(ik.limb_path(obj, chain))
    return list(dict.fromkeys(names))


def open_baseline():
    bpy.ops.wm.open_mainfile(filepath=str(BASELINE))
    obj = active()
    if bpy.context.object.mode != 'POSE':
        bpy.ops.object.mode_set(mode='POSE')
    return obj


def capture(obj, names):
    scene = bpy.context.scene
    out = {}
    for frame in range(scene.frame_start, scene.frame_end + 1):
        scene.frame_set(frame)
        bpy.context.view_layer.update()
        out[frame] = {n: obj.pose.bones[n].matrix.copy() for n in names}
    return out


def worst_drift(before, after, names):
    worst = 0.0
    values = []
    for frame, reference in before.items():
        current = after[frame]
        for name in names:
            a, b = reference[name], current[name]
            rotation = max(abs(a[r][c] - b[r][c]) for r in range(3) for c in range(3))
            translation = max(abs(a[r][3] - b[r][3]) for r in range(3))
            e = max(rotation, translation)
            values.append(e)
            worst = max(worst, e)
    values.sort()
    return worst, values[len(values) // 2]


obj = open_baseline()
ik.create_controls(bpy.context, obj, 'BOTH')
NAMES = limb_names(obj)

obj = open_baseline()
FRAMES = (bpy.context.scene.frame_start, bpy.context.scene.frame_end)
fk = capture(obj, NAMES)

os.environ['SUB_IK_DIAG'] = '1'
rows = []
for run in range(RUNS):
    obj = open_baseline()
    ik.create_controls(bpy.context, obj, 'BOTH')
    start = time.perf_counter()
    ik.match(bpy.context, obj, 'BOTH', entire=True, key=True, _batch=True)
    elapsed = time.perf_counter() - start
    record = diag.record()
    worst, median = worst_drift(fk, capture(obj, NAMES), NAMES)
    rows.append({'run': run, 'seconds': round(elapsed, 4),
                 'evaluations': record['counts'].get('search', 0),
                 'candidates': record['counts'].get('candidates', 0),
                 'drift_worst': worst, 'drift_median': median,
                 'guards': record['reasons']})
    print('MATCH %-10s run=%d %7.3fs evals=%5d drift_worst=%.3e drift_median=%.3e' % (
        LABEL, run, elapsed, rows[-1]['evaluations'], worst, median))

best = min(r['seconds'] for r in rows)
mean = sum(r['seconds'] for r in rows) / len(rows)
print('MATCH_SUMMARY ' + json.dumps({
    'label': LABEL,
    'blender': '%d.%d.%d' % bpy.app.version,
    'native_mode': MODE,
    'correction_bones': HAS_CORRECTIONS,
    'frames': FRAMES,
    'limb_bones': len(NAMES),
    'runs': RUNS,
    'best_seconds': round(best, 4),
    'mean_seconds': round(mean, 4),
    'evaluations': rows[0]['evaluations'],
    'candidates': rows[0]['candidates'],
    'drift_worst': rows[0]['drift_worst'],
    'drift_median': rows[0]['drift_median'],
    'guards': rows[0]['guards'],
}))
