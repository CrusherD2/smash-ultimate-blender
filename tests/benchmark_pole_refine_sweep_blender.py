"""How far the pole refinement can be cut when output exactness is the bar.

With BL_SUB_IK_MATCH_ corrections active the deform bones land on FK exactly
regardless of pole angle, and the pole CONTROL is placed arithmetically, so
neither the posed character nor any visible control moves when the search is
cut. What the search still buys is a smaller residual for the corrections to
absorb -- and that residual is frozen into a local offset, so it is what the
animator feels the moment they drag the IK target away from the matched pose.

Measured per refinement budget: output exactness (the hard requirement),
correction magnitude (the quality that actually degrades), pole-angle curve
roughness, and cost.

Writes .tests/benchmarks/pole-refine-sweep-<blender>.json
"""
from pathlib import Path
import importlib
import json
import math
import os
import time

fixture = Path(__file__).with_name('test_addon_registration_blender.py')
exec(compile(fixture.read_text().split('addon_utils.disable(MODULE')[0], str(fixture), 'exec'))

ik = importlib.import_module(MODULE + '.source.extras.ik_channels')
diag = importlib.import_module(MODULE + '.source.extras.ik_match_diag')
curves = importlib.import_module(MODULE + '.source.anim.fcurve_compat')

BASELINE = Path(os.environ.get('SUB_BASELINE_BLEND',
                               ROOT / '.tests/benchmarks/ik_apply/out/baseline.blend'))
if not BASELINE.exists():
    print('SKIP pole refine sweep, no baseline at ' + str(BASELINE))
    raise SystemExit(0)

BUDGETS = [int(v) for v in os.environ.get('SUB_SWEEP_STEPS', '12,10,8,6,4,3,2,1,0').split(',')]
FRAMES = int(os.environ.get('SUB_SWEEP_FRAMES', '0'))
# Label by the mode ik_native actually resolves, not by the raw variable:
# unset is 'experimental' (native search, the shipped default), '1' is
# verification (one native solve per candidate, each checked against Blender),
# and '0' is Blender only. Only 'experimental' resolves the search in the DLL,
# so only there does the budget cost no Blender evaluations.
native = importlib.import_module(MODULE + '.source.extras.ik_native')
TAG = {'experimental': 'native-search', '1': 'native-verify', '0': 'blender'}.get(
    native.mode(), native.mode())


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
    if FRAMES:
        bpy.context.scene.frame_end = bpy.context.scene.frame_start + FRAMES - 1
    return obj


def capture(obj, names):
    scene = bpy.context.scene
    out = {}
    for frame in range(scene.frame_start, scene.frame_end + 1):
        scene.frame_set(frame)
        bpy.context.view_layer.update()
        out[frame] = {n: obj.pose.bones[n].matrix.copy() for n in names}
    return out


def drift(before, after, names):
    values = []
    for frame, reference in before.items():
        current = after[frame]
        for name in names:
            a, b = reference[name], current[name]
            rotation = max(abs(a[r][c] - b[r][c]) for r in range(3) for c in range(3))
            translation = max(abs(a[r][3] - b[r][3]) for r in range(3))
            values.append(max(rotation, translation))
    return values


def correction_magnitudes(obj):
    """Per-frame translation length and rotation angle of each correction basis."""
    scene = bpy.context.scene
    names = [b.name for b in obj.data.bones if b.name.startswith(ik.CORRECTION_PREFIX)]
    translation, rotation = [], []
    for frame in range(scene.frame_start, scene.frame_end + 1):
        scene.frame_set(frame)
        bpy.context.view_layer.update()
        for name in names:
            basis = obj.pose.bones[name].matrix_basis
            translation.append(basis.to_translation().length)
            rotation.append(abs(basis.to_quaternion().angle))
    return translation, rotation


def stat(values):
    if not values:
        return {'worst': 0.0, 'median': 0.0, 'p99': 0.0, 'mean': 0.0}
    ordered = sorted(values)
    return {'worst': ordered[-1],
            'median': ordered[len(ordered) // 2],
            'p99': ordered[min(len(ordered) - 1, int(len(ordered) * 0.99))],
            'mean': sum(ordered) / len(ordered)}


def pole_curves(obj):
    """Keyed pole_angle per solver constraint as {bone: [[frame, value], ...]}."""
    action = obj.animation_data.action
    out = {}
    for fc in curves.get_all_action_fcurves(action, id_type='OBJECT'):
        if fc.data_path.endswith('.pole_angle'):
            bone = fc.data_path.split('"')[1]
            out[bone] = [[round(kp.co.x, 3), round(kp.co.y, 6)] for kp in fc.keyframe_points]
    return out


def roughness(series):
    """RMS second difference -- how much the keyed curve zig-zags frame to frame."""
    values = [point[1] for point in series]
    if len(values) < 3:
        return 0.0
    second = [values[i + 1] - 2 * values[i] + values[i - 1] for i in range(1, len(values) - 1)]
    return math.sqrt(sum(v * v for v in second) / len(second))


# Chain names come from a throwaway build; the FK reference needs a clean file.
obj = open_baseline()
ik.create_controls(bpy.context, obj, 'BOTH')
NAMES = limb_names(obj)
assert NAMES, 'no IK limb chains on the baseline rig'

obj = open_baseline()
FRAME_RANGE = (bpy.context.scene.frame_start, bpy.context.scene.frame_end)
fk = capture(obj, NAMES)
print('SWEEP_SETUP frames=%s bones=%d backend=%s' % (FRAME_RANGE, len(NAMES), TAG))

os.environ['SUB_IK_DIAG'] = '1'
results = []
for steps in BUDGETS:
    obj = open_baseline()
    ik.create_controls(bpy.context, obj, 'BOTH')
    original = ik._POLE_REFINE_STEPS
    ik._POLE_REFINE_STEPS = steps
    try:
        start = time.perf_counter()
        ik.match(bpy.context, obj, 'BOTH', entire=True, key=True, _batch=True)
        elapsed = time.perf_counter() - start
    finally:
        ik._POLE_REFINE_STEPS = original
    record = diag.record()
    translation, rotation = correction_magnitudes(obj)
    poles = pole_curves(obj)
    results.append({
        'steps': steps,
        'seconds': round(elapsed, 4),
        'evaluations': record['counts'].get('search', 0),
        'candidates': record['counts'].get('candidates', 0),
        'native_solves': record['counts'].get('native_solves', 0),
        'native_declined': record['counts'].get('native_declined', 0),
        'guards': record['reasons'],
        'drift': stat(drift(fk, capture(obj, NAMES), NAMES)),
        'correction_translation': stat(translation),
        'correction_rotation': stat(rotation),
        'pole_roughness': dict(sorted((k, roughness(v)) for k, v in poles.items())),
        'pole_curves': dict(sorted(poles.items())),
    })
    row = results[-1]
    print('SWEEP steps=%2d %7.3fs evals=%5d drift=%.2e corr_trans=%.4f corr_rot=%.2fdeg' % (
        steps, elapsed, row['evaluations'], row['drift']['worst'],
        row['correction_translation']['worst'],
        math.degrees(row['correction_rotation']['worst'])))

out = ROOT / '.tests/benchmarks' / ('pole-refine-sweep-%s-%d.%d.json' % (
    (TAG,) + bpy.app.version[:2]))
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(json.dumps({
    'blender': '%d.%d.%d' % bpy.app.version,
    'search_backend': TAG,
    'native_mode': native.mode(),
    'native_enabled': native.enabled(),
    'native_verifying': native.verifying(),
    'baseline': BASELINE.name,
    'frame_range': FRAME_RANGE,
    'limb_bones': NAMES,
    'results': results,
}, indent=2), encoding='utf-8')
print('SWEEP_WROTE ' + str(out))
print('SWEEP_DONE')
