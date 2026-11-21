from pathlib import Path
import os
import time

fixture = Path(__file__).with_name('test_ik_hip_continuity_blender.py')
exec(compile(fixture.read_text().split('assert ik.create_controls')[0], str(fixture), 'exec'))
diag = importlib.import_module(MODULE + '.source.extras.ik_match_diag')
os.environ['SUB_NATIVE_IK'] = 'experimental'
os.environ['SUB_IK_DIAG'] = '1'
assert ik.create_controls(bpy.context, obj) == 4
scene = bpy.context.scene
scene.frame_end = scene.frame_start + 15
samples = []
records = []
for enabled in ('0', '1'):
    os.environ['SUB_NATIVE_CALIBRATION'] = enabled
    start = time.perf_counter()
    ik.match(bpy.context, obj, _batch=True)
    records.append(diag.record())
    print('CALIBRATION', enabled, time.perf_counter() - start, records[-1], flush=True)
    poses = []
    for frame in range(scene.frame_start, scene.frame_end + 1):
        scene.frame_set(frame)
        for shift in (0, .2):
            hip = obj.pose.bones['Hip']
            origin = hip.location.copy()
            hip.location.x += shift
            obj.update_tag()
            bpy.context.view_layer.update()
            poses.extend(value for name in names for row in obj.pose.bones[name].matrix for value in row)
            hip.location = origin
    samples.append(poses)
error = max(abs(a - b) for a, b in zip(*samples))
assert error < 2e-4, error
assert records[1]['counts'].get('native_calibrations', 0) > 0, records[1]
assert records[1]['counts']['search'] < records[0]['counts']['search'], records
print('NATIVE CALIBRATION MATCHES BLENDER WITH FEWER UPDATES PASSED', error)

from types import SimpleNamespace
from unittest.mock import patch
native = importlib.import_module(MODULE + '.source.extras.ik_native')
calibrate = native.Solver.calibrate

def mismatched(self, *args):
    found = calibrate(self, *args)
    if found is not None:
        found[1][0].translation.x += 1
    return found

for replacement in (lambda *args: None, mismatched):
    with patch.object(native.Solver, 'calibrate', replacement):
        ik.match(bpy.context, obj, _batch=True)
        record = diag.record()
        assert record['counts'].get('native_calibrations', 0) == 0, record
        assert record['counts'].get('calibration_fallbacks', 0) > 0, record
    poses = []
    for frame in range(scene.frame_start, scene.frame_end + 1):
        scene.frame_set(frame)
        for shift in (0, .2):
            hip = obj.pose.bones['Hip']
            origin = hip.location.copy()
            hip.location.x += shift
            obj.update_tag()
            bpy.context.view_layer.update()
            poses.extend(value for name in names for row in obj.pose.bones[name].matrix for value in row)
            hip.location = origin
    assert max(abs(a-b) for a,b in zip(samples[0], poses)) < 2e-4
with patch.object(native, '_dll', object()):
    assert calibrate(SimpleNamespace(fallback=False), None, None, None, 0) is None
print('REJECTED, MISMATCHED AND OLDER DLL CALIBRATION FALL BACK WITHOUT POSE LOSS PASSED')
