from pathlib import Path
from unittest.mock import patch

fixture = Path(__file__).with_name('test_animation_rig_combined_match_blender.py')
source = fixture.read_text(encoding='utf-8')
prefix, remaining = source.split('sample_calls, solve_calls, standalone_calls = [], [], []', 1)
exec(compile(prefix, str(fixture), 'exec'))
original_steps = ik._match_chain_steps
barriers = {}

def counted_steps(obj, job, matrices, frame, key, writer, entry, previous_pole,
                  _native=None, _direct_calibration=False):
    calibrated = (entry['pole_geometry'] is not None
                  and (job[0] == 'LEGS' or (job[0] == 'ARMS' and len(entry['path']) == 3)))
    count = 0
    for value in original_steps(obj, job, matrices, frame, key, writer, entry,
                                previous_pole, _native, _direct_calibration):
        count += 1
        yield value
    if calibrated:
        assert _direct_calibration, job
        barriers.setdefault(job[2], []).append(count)

with patch.object(ik, '_match_chain_steps', counted_steps):
    exec(compile('sample_calls, solve_calls, standalone_calls = [], [], []' + remaining,
                 str(fixture), 'exec'))
assert {'HandIKL', 'FootIKL'} <= barriers.keys(), barriers
assert all(count == 1 for counts in barriers.values() for count in counts), barriers
assert original_steps.__defaults__ == (None, False)
print('CREATION CALIBRATION: ONE BARRIER, MATCHED POSES, SOURCE KEYS AND RECOVERY PASSED')
