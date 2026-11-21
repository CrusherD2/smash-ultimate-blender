from pathlib import Path

fixture = Path(__file__).with_name('test_ik_detail_acceleration_blender.py')
exec(compile(fixture.read_text().split('\naudit()\nfor repeat')[0], str(fixture), 'exec'))
rig = importlib.import_module(MODULE + '.source.extras.create_animation_rig')
for frame, enabled in ((22, False), (43, True)):
    scene.frame_set(frame)
    assert bpy.ops.sub.anim_rig_toggle_ik_fk(
        limbs='LEGS', set_enabled=True, enable_ik=enabled) == {'FINISHED'}
curve = rig.find_fcurve(obj.data.animation_data.action, 'sub_use_ik_legs', index=0, id_type='ARMATURE')
original = [(tuple(key.co), key.interpolation) for key in curve.keyframe_points]
for frame in list(range(1, 51)) + list(range(50, 0, -1)):
    scene.frame_set(frame)
    bpy.context.view_layer.update()
    for side in ('L', 'R'):
        control = obj.pose.bones['FootIK' + side]
        hidden = control.hide if hasattr(control, 'hide') else control.bone.hide
        assert hidden == (22 <= frame < 43), (frame, control.name, hidden)
assert original == [(tuple(key.co), key.interpolation) for key in curve.keyframe_points]
print('IK VISIBILITY HOLDS BETWEEN SWITCHES IN BOTH SCRUB DIRECTIONS PASSED')
