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

print('IK_MATCH_GATE_OK')
