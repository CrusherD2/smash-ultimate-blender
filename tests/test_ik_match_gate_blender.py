"""The gate must call a run identical to itself a pass, and a worse one a fail."""
from pathlib import Path
import importlib, os, sys

fixture = Path(__file__).with_name('test_addon_registration_blender.py')
exec(compile(fixture.read_text().split('addon_utils.disable(MODULE')[0], str(fixture), 'exec'))
sys.path.insert(0, str(Path(__file__).parent))
gate = importlib.import_module('ik_match_gate')
gate.bind(MODULE)

BASELINE = ROOT / '.tests' / 'benchmarks' / 'ik_apply' / 'out' / 'baseline.blend'
if not BASELINE.exists():
    print(f'SKIP gate test, no baseline at {BASELINE}')
    raise SystemExit(0)

# Same variant twice must be identical: zero worse, zero better, zero pose delta.
a = gate.run_variant('blender', BASELINE, 'normal', 'BOTH')
b = gate.run_variant('blender', BASELINE, 'normal', 'BOTH')
same = gate.compare(a, b, a['names'], gate.TOLERANCE)
assert same['passed'], same
assert same['frames_worse'] == 0 and same['frames_better'] == 0, same
assert same['max_pose_difference'] == 0.0, same
assert same['frames_identical'] == len(a['residuals']), same

# A synthetic degradation must fail the gate, so a pass cannot be vacuous.
worse = dict(b)
worse['residuals'] = dict(b['residuals'])
victim = sorted(worse['residuals'])[len(worse['residuals']) // 2]
worse['residuals'][victim] = worse['residuals'][victim] * 1.5 + 1.0
verdict = gate.compare(a, worse, a['names'], gate.TOLERANCE)
assert not verdict['passed'], verdict
assert verdict['frames_worse'] == 1, verdict
assert verdict['worst_relative_frame'] == victim, verdict

# The engagement requirement must fail a run that never exercised its variant.
empty = dict(a)
empty['counts'] = {}
try:
    gate.require_engaged('native', empty)
except AssertionError:
    pass
else:
    raise AssertionError('require_engaged accepted a run with no engagement')

# An empty comparison must never pass vacuously (Task 2 fix: compare() used to
# report passed=True on zero frames because every delta aggregate defaults to 0.0).
empty_a = dict(a); empty_a['residuals'] = {}
empty_b = dict(b); empty_b['residuals'] = {}
try:
    gate.compare(empty_a, empty_b, a['names'], gate.TOLERANCE)
except ValueError:
    pass
else:
    raise AssertionError('compare() passed vacuously on an empty residual set')

# The absolute floor (Task 2 fix round 2): a near-zero-residual baseline (like
# the shyguy_static fixture, ~1e-9 per frame) must not spuriously fail on pure
# float-scale noise, but must still catch a real regression, and the floor
# must not neuter the relative check on a normal-scale baseline.
frame = next(iter(a['residuals']))
names = a['names']
poses_a, poses_b = a['poses'], b['poses']  # unchanged poses -> pose_delta stays 0

def synthetic(residual_value):
    run = dict(a)
    run['residuals'] = {frame: residual_value}
    run['poses'] = {frame: poses_a[frame]}
    return run

near_zero_base = synthetic(1e-9)

# (1) Pure float-scale noise on a near-zero baseline must PASS.
near_zero_noise = synthetic(1e-9 + 1e-12)
verdict_noise = gate.compare(near_zero_base, near_zero_noise, names, gate.TOLERANCE)
assert verdict_noise['passed'], verdict_noise

# (2) A physically real perturbation on the same near-zero baseline must still FAIL.
near_zero_real = synthetic(1e-9 + 1e-6)
verdict_real = gate.compare(near_zero_base, near_zero_real, names, gate.TOLERANCE)
assert not verdict_real['passed'], verdict_real

# (3) The floor must not switch off the relative check on a normal-scale baseline:
# a delta just over the relative tolerance (but nowhere near the 1e-9 floor in
# absolute terms is irrelevant here -- it's far larger) must still FAIL. This is
# the case the floor could accidentally neuter if set carelessly.
normal_base_value = 0.16  # representative per-frame residual on the real rig
normal_base = synthetic(normal_base_value)
over_relative = normal_base_value * (gate.TOLERANCE['relative'] * 2)  # 2x the bar
normal_candidate = synthetic(normal_base_value + over_relative)
verdict_normal = gate.compare(normal_base, normal_candidate, names, gate.TOLERANCE)
assert not verdict_normal['passed'], verdict_normal
# Sanity: that delta is far above the absolute floor, so this genuinely
# exercises the relative bar, not the floor accidentally doing the work.
assert over_relative > gate.TOLERANCE['absolute'] * 100, over_relative

print('IK_MATCH_GATE_OK')
