from pathlib import Path

fixture = Path(__file__).with_name('test_ik_detail_acceleration_blender.py')
exec(compile(fixture.read_text().split('\naudit()\nfor repeat')[0], str(fixture), 'exec'))
rig = importlib.import_module(MODULE + '.source.extras.create_animation_rig')
scene.frame_set(16)
curve = rig.find_fcurve(obj.data.animation_data.action, 'sub_use_ik_legs', index=0, id_type='ARMATURE')
assert [tuple(key.co) for key in curve.keyframe_points] == [(16.0, 1.0)]
assert bpy.ops.sub.anim_rig_toggle_ik_fk(
    limbs='LEGS', set_enabled=True, enable_ik=False) == {'FINISHED'}
for frame, enabled in ((1, True), (15, True), (16, False), (20, False), (1, True)):
    scene.frame_set(frame)
    bpy.context.view_layer.update()
    assert bool(obj.data.sub_use_ik_legs) == enabled, (frame, obj.data.sub_use_ik_legs)
    for side in ('L', 'R'):
        control = obj.pose.bones['FootIK' + side]
        hidden = control.hide if hasattr(control, 'hide') else control.bone.hide
        assert hidden == (not enabled), (frame, control.name, hidden)
assert [tuple(key.co) for key in curve.keyframe_points] == [(15.0, 1.0), (16.0, 0.0)]
print('REPLACING THE FIRST SWITCH KEY PRESERVES THE EARLIER MODE PASSED')
