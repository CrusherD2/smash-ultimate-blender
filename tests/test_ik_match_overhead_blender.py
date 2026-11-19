from pathlib import Path
import importlib
from unittest.mock import patch

fixture = Path(__file__).with_name('test_ik_detail_acceleration_blender.py')
exec(compile(fixture.read_text().split('\naudit()\nfor repeat')[0], str(fixture), 'exec'))
native = importlib.import_module(MODULE + '.source.extras.ik_native')
compat = importlib.import_module(MODULE + '.source.anim.fcurve_compat')
assign = importlib.import_module(MODULE + '.source.blender_compat').assign_action
assert hasattr(native._dll, 'sub_ik_create_packed')
library = native._dll
baseline_action = obj.animation_data.action.copy()
original_frame = scene.frame_current

class Library:
    def __init__(self, packed):
        self.packed = packed
        self.calls = 0
    def __getattr__(self, name):
        if name == 'sub_ik_create_packed':
            if not self.packed:
                raise AttributeError(name)
            return self.capture
        return getattr(library, name)
    def capture(self, *args):
        self.calls += 1
        return library.sub_ik_create_packed(*args)

def fingerprint():
    keys = sorted((fc.data_path, fc.array_index,
                   [(tuple(k.co), k.interpolation) for k in fc.keyframe_points])
                  for fc in compat.get_all_action_fcurves(obj.animation_data.action))
    poses = []
    for frame in range(1, 17):
        scene.frame_set(frame)
        bpy.context.view_layer.update()
        poses.append([tuple(tuple(row) for row in obj.pose.bones[name].matrix)
                      for name in ('LegL', 'KneeL', 'FootL', 'LegR', 'KneeR', 'FootR')])
    scene.frame_set(original_frame)
    return keys, poses

for targets, count in ((None, 32), ({jobs[0][2]}, 16)):
    results = []
    for packed in (False, True):
        assign(obj.animation_data, baseline_action.copy())
        scene.frame_set(original_frame)
        proxy = Library(packed)
        with patch.object(native, '_dll', proxy):
            ik.match(bpy.context, obj, 'LEGS', _batch=True, _targets=targets)
        assert scene.frame_current == original_frame
        assert diag.record()['counts'].get('native_solves', 0) == count, diag.record()
        assert proxy.calls == (count if packed else 0), (packed, proxy.calls)
        assert all(not con.mute for _, con, _ in ik.outputs(obj, 'LEGS'))
        results.append(fingerprint())
    assert results[0] == results[1], targets

assign(obj.animation_data, baseline_action.copy())
with patch.object(native, 'get_factory', return_value=None):
    ik.match(bpy.context, obj, 'LEGS', _batch=True, _targets={jobs[0][2]})
assert diag.record()['counts'].get('native_solves', 0) == 0
for frame, matrices in source.items():
    scene.frame_set(frame)
    bpy.context.view_layer.update()
    for name in ('LegL', 'KneeL', 'FootL'):
        actual = obj.pose.bones[name].matrix
        assert max(abs(actual[r][c] - matrices[name][r][c]) for r in range(4) for c in range(4)) < 2e-4
print('PACKED/JSON EXACT KEYS AND POSES, SINGLE-LIMB NATIVE AND MISSING-DLL FALLBACK PASSED')
