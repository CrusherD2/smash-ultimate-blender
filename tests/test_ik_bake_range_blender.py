"""Bake and remove must preserve the full pose despite cropped playback ranges."""
from pathlib import Path
fixture = Path(__file__).with_name('test_ik_workflow_regressions_blender.py')
exec(compile(fixture.read_text().split('# Full IK hides')[0], str(fixture), 'exec'))
action = obj.animation_data.action
action.use_frame_range = True
action.frame_start, action.frame_end = 2, 3
scene.frame_start, scene.frame_end = 40, 45
scene.use_preview_range = True
scene.frame_preview_start, scene.frame_preview_end = 41, 42
scene.frame_set(43)
assert apply._action_frame_range(obj, scene) == (1, 5)
assert bpy.ops.sub.apply_ik_animation('EXEC_DEFAULT') == {'FINISHED'}
assert scene.frame_current == 43
assert (scene.frame_start, scene.frame_end) == (40, 45)
assert 'HandIKL' not in obj.pose.bones
compare(matched, capture(), 'cropped playback bake')

# Fractional endpoints, including negative frames, round outwards.
pb = obj.pose.bones['HandL']
pb.keyframe_insert('location', frame=-2.25)
pb.keyframe_insert('location', frame=7.25)
assert apply._action_frame_range(obj, scene) == (-3, 8)
print('IK BAKE RANGE PASSED')
