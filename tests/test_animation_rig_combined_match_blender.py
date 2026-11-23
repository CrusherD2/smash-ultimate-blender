from pathlib import Path
import os
import time

fixture = Path(__file__).with_name('test_finger_creation_match_blender.py')
exec(compile(fixture.read_text(encoding='utf-8-sig').split('expected=snapshot()')[0], str(fixture), 'exec'))
matching = importlib.import_module(MODULE + '.source.extras.component_matching')
creation = importlib.import_module(MODULE + '.source.extras.rig_creation_match')
fast = importlib.import_module(MODULE + '.source.extras.ik_match_fast')
bpy.ops.object.mode_set(mode='EDIT')
bone('ShoulderL', (-3, 0, 2), 'Trans')
bone('ArmL', (-1.5, .2, 2), 'ShoulderL')
data.edit_bones['ShoulderL'].tail = data.edit_bones['ArmL'].head
data.edit_bones['ArmL'].tail = data.edit_bones['HandL'].head
data.edit_bones['HandL'].parent = data.edit_bones['ArmL']
bpy.ops.object.mode_set(mode='POSE')
names = sorted(obj.pose.bones.keys())
scene.frame_end = int(os.environ.get('SUB_COMBINED_TEST_FRAMES', '24'))
for frame in range(1, scene.frame_end + 1):
    scene.frame_set(frame)
    for i, name in enumerate(names):
        pb = obj.pose.bones[name]
        pb.rotation_mode = 'XYZ'
        pb.rotation_euler = (.03 * frame + .01 * i, .01 * frame, .02 * frame)
        pb.keyframe_insert('rotation_euler', frame=frame)

def snapshots():
    poses = {}
    for frame in range(1, scene.frame_end + 1):
        scene.frame_set(frame)
        bpy.context.view_layer.update()
        ev = obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
        poses[frame] = {name: ev.pose.bones[name].matrix.copy() for name in names}
    return poses

def channels():
    return {(fc.data_path, fc.array_index): [tuple(k.co) for k in fc.keyframe_points]
            for fc in curves.get_all_action_fcurves(obj.animation_data.action)}

expected = snapshots()
original_channels = channels()
component('ISOLATED', 'Floating Wing', ['WingL'])
component('JAW', 'Jaw', ['Jaw'])
component('EYES', 'Eyes', ['EyeL', 'EyeR'])
custom_ik = component('IK', 'Tail IK', [])
custom_ik.root, custom_ik.middle, custom_ik.end = 'Tail0', 'Tail2', 'Tail3'
editor.save_on_build = False
scene.sub_scene_properties.clean_keyframes_after_rig = False
sample_calls, solve_calls, standalone_calls = [], [], []
original_sample, original_solve, original_match = fast.sample_fk, creation.CreationIKMatch.solve, ik.match

def sample(*args, **kwargs):
    sample_calls.append(set(args[2]))
    return original_sample(*args, **kwargs)

def solve(self, context, matrices, frame, writer):
    solve_calls.append(frame)
    return original_solve(self, context, matrices, frame, writer)

def standalone(*args, **kwargs):
    standalone_calls.append(True)
    return original_match(*args, **kwargs)

fast.sample_fk, creation.CreationIKMatch.solve, ik.match = sample, solve, standalone
start = time.perf_counter()
try:
    with tempfile.TemporaryDirectory() as folder:
        cc.preset_dir = lambda: Path(folder)
        preset = cc.save_preset(editor)
        assert bpy.ops.sub.create_animation_rig(setup_ik=True, setup_eye_look=False,
            setup_finger_sliders=True, setup_custom_components=True,
            custom_component_preset=preset.name) == {'FINISHED'}
finally:
    fast.sample_fk, creation.CreationIKMatch.solve, ik.match = original_sample, original_solve, original_match
print('COMBINED_CREATION_SECONDS', time.perf_counter() - start, flush=True)
assert not standalone_calls, standalone_calls
assert len(sample_calls) == 1, sample_calls
assert {'ShoulderL', 'ArmL', 'HandL', 'LegL', 'KneeL', 'FootL', 'FingerL11', 'WingL', 'EyeL', 'Tail3'} <= sample_calls[0]
assert set(solve_calls) == set(range(1, scene.frame_end + 1)), solve_calls
actual = snapshots()
for frame, poses in expected.items():
    for name, wanted in poses.items():
        error = max(abs(a-b) for row, target in zip(actual[frame][name], wanted) for a, b in zip(row, target))
        assert error < 3e-4, (frame, name, error)
now = channels()
residual_paths = tuple(pb.path_from_id() + '.' for pb, _ in fingers._iter_finger_slider_constraints(obj))
for key, points in original_channels.items():
    # Finger circles retain residual motion in their basis, as in the existing matcher.
    if not key[0].startswith(residual_paths):
        assert now[key] == points, key
assert any('HandIKL' in path for path, _ in now)
assert any('FootIKL' in path for path, _ in now)
assert any('BL_CC_' in path for path, _ in now)
assert not any(ik.CORRECTION_PREFIX in path for path, _ in now)
# A failure after one solved frame must restore the action, helpers and IK state.
original_channels = channels()
original_bones = set(obj.pose.bones.keys())
original_states = {con.as_pointer(): con.mute for pb in obj.pose.bones for con in pb.constraints}
original_sync = rig._IK_FK_MUTE_SYNC_PAUSED
original_frame = scene.frame_current

def fail(self, context, matrices, frame, writer):
    original_solve(self, context, matrices, frame, writer)
    if frame == 2:
        raise RuntimeError('Injected combined match failure')

creation.CreationIKMatch.solve = fail
try:
    try:
        matching.match_animation(bpy.context, obj, 1, scene.frame_end, include_fingers=True,
                                 _creation_limbs='BOTH')
        raise AssertionError('Failure injection did not run')
    except RuntimeError as exc:
        assert 'Injected combined' in str(exc), exc
finally:
    creation.CreationIKMatch.solve = original_solve
assert channels() == original_channels
assert set(obj.pose.bones.keys()) == original_bones
assert scene.frame_current == original_frame
assert rig._IK_FK_MUTE_SYNC_PAUSED == original_sync
assert all(con.mute == original_states[con.as_pointer()] for pb in obj.pose.bones for con in pb.constraints)
steps = matching.match_animation_steps(bpy.context, obj, 1, scene.frame_end,
    include_fingers=True, _creation_limbs='BOTH')
try:
    for event in steps:
        if event[0] == 'progress' and event[2] == 'Matching frame 1':
            break
    else:
        raise AssertionError('Cancellation did not reach a solved frame')
finally:
    steps.close()
assert channels() == original_channels
assert set(obj.pose.bones.keys()) == original_bones
assert scene.frame_current == original_frame
assert rig._IK_FK_MUTE_SYNC_PAUSED == original_sync
assert all(con.mute == original_states[con.as_pointer()] for pb in obj.pose.bones for con in pb.constraints)
recovered = snapshots()
for frame, poses in actual.items():
    for name, wanted in poses.items():
        error = max(abs(a-b) for row, target in zip(recovered[frame][name], wanted) for a, b in zip(row, target))
        assert error < 3e-4, ('recovery', frame, name, error)
print('COMBINED IK, FINGERS, FACE, CUSTOM IK, SOURCE KEYS, ROLLBACK AND CANCEL PASSED')
