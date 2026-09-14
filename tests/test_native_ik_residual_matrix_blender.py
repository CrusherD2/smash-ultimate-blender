"""Widen the native-vs-Blender residual comparison across rig configurations.

tests/test_native_ik_residual_blender.py establishes the property on one plain
rig. This runs the same two comparisons across the configurations that
test_ik_match_fast_blender.py constructs -- object and parent scale, scale
inheritance, stretch, arm pull, foot controls, animated stretch -- plus limb
subsets, so the evidence is not confined to a single well-behaved case.

Two things are checked per configuration:
  * per frame, the native residual against the FK source is never worse than
    Blender's, and
  * the solved pose matrices from the two backends, compared element by element.

A configuration where the per-frame guards decline native matching is recorded
with native_solvers == 0 and reported rather than silently counted as a pass.

This drives tests/ik_match_gate.py rather than inlining its own comparison --
see that module for the (unchanged) residual and pose comparison logic. The
'native_solvers' count below is still gathered with a local Factory.__call__
wrap (as the original single-file harness did), rather than through
ik_match_diag: gate.run_variant()'s own diag snapshot only reflects the final
top-level ik.match() call under test, while ik.create_controls() performs a
brief internal match() of its own to seat the freshly-created IK controls --
one native solve per limb -- before that. The published count in
docs/benchmarks/native-ik-residual-criterion-2026-09-12.md includes both, so
this wrap is kept to reproduce it exactly.
"""
from pathlib import Path
import importlib
import json
import os
import sys

fixture = Path(__file__).with_name('test_addon_registration_blender.py')
exec(compile(fixture.read_text().split('addon_utils.disable(MODULE')[0], str(fixture), 'exec'))
sys.path.insert(0, str(Path(__file__).parent))
gate = importlib.import_module('ik_match_gate')
gate.bind(MODULE)

BASELINE = Path(os.environ.get(
    'SUB_BASELINE_BLEND',
    ROOT / '.tests' / 'benchmarks' / 'ik_apply' / 'out' / 'baseline.blend'))
NATIVE_MODE = os.environ.get('SUB_NATIVE_RESIDUAL_MODE', 'experimental')

if not BASELINE.exists():
    print(f'SKIP native residual matrix, no baseline at {BASELINE}')
    raise SystemExit(0)

# Honour SUB_NATIVE_RESIDUAL_MODE (e.g. '1' for verification mode) the way the
# original single-file harness did. gate.VARIANTS['native'] hardcodes
# 'experimental'; overwrite it once, before any run, so run('native', ...)
# below actually uses NATIVE_MODE and the native_mode field in the published
# report matches what ran.
gate.VARIANTS['native']['env']['SUB_NATIVE_IK'] = NATIVE_MODE

solvers = {'count': 0}
_factory_call = gate.ik_native.Factory.__call__


def counting_call(self, *args, **kwargs):
    solver = _factory_call(self, *args, **kwargs)
    solvers['count'] += int(solver is not None)
    return solver


gate.ik_native.Factory.__call__ = counting_call


def run(variant, scenario, limbs):
    solvers['count'] = 0
    run_ = gate.run_variant(variant, BASELINE, scenario, limbs)
    return run_, solvers['count']


CONFIGURATIONS = [
    ('normal', 'BOTH'),
    ('normal', 'ARMS'),
    ('normal', 'LEGS'),
    ('object_scale', 'BOTH'),
    ('parent_scale', 'BOTH'),
    ('inheritance', 'BOTH'),
    ('stretch', 'BOTH'),
    ('arm_pull', 'BOTH'),
    ('animated_stretch', 'BOTH'),
    ('foot_controls', 'BOTH'),
]

rows = []
failures = []
for scenario, limbs in CONFIGURATIONS:
    base, base_solvers = run('blender', scenario, limbs)
    native, native_solvers = run('native', scenario, limbs)
    assert base_solvers == 0, f'{scenario}/{limbs} used {base_solvers} native solvers on the Blender pass'

    verdict = gate.compare(base, native, base['names'], gate.TOLERANCE)

    worse = []
    for frame, a in base['residuals'].items():
        b = native['residuals'][frame]
        if b > a:
            worse.append((frame, b - a))
    worse.sort(key=lambda row: -row[1])

    row = dict(scenario=scenario, limbs=limbs, native_solvers=native_solvers,
               frames=len(base['residuals']), bones=len(base['names']),
               frames_worse=len(worse), max_pose_difference=verdict['max_pose_difference'],
               max_pose_difference_at=verdict['max_pose_difference_at'],
               worst_residual_delta=worse[0][1] if worse else 0.0,
               total_residual_blender=sum(base['residuals'].values()),
               total_residual_native=sum(native['residuals'].values()))
    rows.append(row)
    print('RESIDUAL_ROW ' + json.dumps(row), flush=True)
    if worse:
        failures.append(row)

engaged = [r for r in rows if r['native_solvers'] > 0]
declined = [r for r in rows if r['native_solvers'] == 0]
report = dict(blender=bpy.app.version_string, native_mode=NATIVE_MODE, rows=rows,
              configurations=len(rows), native_engaged=len(engaged),
              guards_declined=[f"{r['scenario']}/{r['limbs']}" for r in declined],
              bit_identical=[f"{r['scenario']}/{r['limbs']}" for r in engaged
                             if r['max_pose_difference'] == 0.0])
path = ROOT / '.tests/benchmarks/native_ik' / f'residual_matrix_{bpy.app.version[0]}.{bpy.app.version[1]}.json'
path.parent.mkdir(parents=True, exist_ok=True)
path.write_text(json.dumps(report, indent=2))
print('NATIVE_RESIDUAL_MATRIX ' + json.dumps({k: v for k, v in report.items() if k != 'rows'}))

assert engaged, 'no configuration engaged the native solver; nothing was compared'
assert not failures, failures
print('NATIVE_RESIDUAL_MATRIX_OK', flush=True)
