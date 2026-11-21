from pathlib import Path

fixture = Path(__file__).with_name('test_ik_detail_acceleration_blender.py')
exec(compile(fixture.read_text().split('\naudit()\nfor repeat')[0], str(fixture), 'exec'))
rig = importlib.import_module(MODULE + '.source.extras.create_animation_rig')
# Creation keys IK at the last sampled frame; exercise an action with no switch keys.
action = obj.data.animation_data.action
for curve in list(rig.get_all_action_fcurves(action, id_type='ARMATURE')):
    if curve.data_path == 'sub_use_ik_legs':
        rig.remove_fcurve(action, curve, id_type='ARMATURE')
scene.frame_set(8)
assert bpy.ops.sub.anim_rig_toggle_ik_fk(
    limbs='LEGS', set_enabled=True, enable_ik=False) == {'FINISHED'}
for frame, enabled in ((1, True), (7, True), (8, False), (16, False), (1, True)):
    scene.frame_set(frame)
    bpy.context.view_layer.update()
    assert bool(obj.data.sub_use_ik_legs) == enabled, (frame, obj.data.sub_use_ik_legs)
    for side in ('L', 'R'):
        control = obj.pose.bones['FootIK' + side]
        hidden = control.hide if hasattr(control, 'hide') else control.bone.hide
        assert hidden == (not enabled), (frame, control.name, hidden)
scene.frame_set(12)
assert bpy.ops.sub.anim_rig_toggle_ik_fk(
    limbs='LEGS', set_enabled=True, enable_ik=True) == {'FINISHED'}
for frame, enabled in ((16, True), (8, False), (7, True), (12, True), (1, True)):
    scene.frame_set(frame)
    bpy.context.view_layer.update()
    assert bool(obj.data.sub_use_ik_legs) == enabled, (frame, obj.data.sub_use_ik_legs)
    for side in ('L', 'R'):
        control = obj.pose.bones['FootIK' + side]
        hidden = control.hide if hasattr(control, 'hide') else control.bone.hide
        assert hidden == (not enabled), (frame, control.name, hidden)
print('FIRST IK/FK SWITCH PRESERVES EARLIER FRAMES AND VISIBILITY SCRUBS BOTH WAYS PASSED')

curve = rig.find_fcurve(action, 'sub_use_ik_legs', index=0, id_type='ARMATURE')
assert [(tuple(key.co), key.interpolation) for key in curve.keyframe_points] == [
    ((7.0, 1.0), 'CONSTANT'), ((8.0, 0.0), 'LINEAR'), ((12.0, 1.0), 'LINEAR')]
# Adding an earlier switch must keep the animator's later keys and interpolation.
curve.keyframe_points[-1].interpolation = 'CONSTANT'
scene.frame_set(4)
assert bpy.ops.sub.anim_rig_toggle_ik_fk(
    limbs='LEGS', set_enabled=True, enable_ik=False) == {'FINISHED'}
assert [(tuple(key.co), key.interpolation) for key in curve.keyframe_points if key.co[0] >= 7] == [
    ((7.0, 1.0), 'CONSTANT'), ((8.0, 0.0), 'LINEAR'), ((12.0, 1.0), 'CONSTANT')]
for frame, enabled in ((3, True), (4, False), (12, True), (8, False), (1, True)):
    scene.frame_set(frame)
    bpy.context.view_layer.update()
    assert bool(obj.data.sub_use_ik_legs) == enabled, (frame, obj.data.sub_use_ik_legs)
print('EXISTING SWITCH KEYS AND HOLD INTERPOLATION PRESERVED PASSED')

import tempfile
with tempfile.TemporaryDirectory(prefix='ik-switch-reload-') as directory:
    name = obj.name
    path = str(Path(directory) / 'switches.blend')
    bpy.ops.wm.save_as_mainfile(filepath=path, check_existing=False)
    bpy.ops.wm.open_mainfile(filepath=path)
    assert rig._sync_ik_fk_visibility in bpy.app.handlers.frame_change_post
    obj = bpy.data.objects[name]
    for frame, enabled in ((4, False), (12, True), (8, False), (1, True)):
        bpy.context.scene.frame_set(frame)
        bpy.context.view_layer.update()
        for side in ('L', 'R'):
            control = obj.pose.bones['FootIK' + side]
            hidden = control.hide if hasattr(control, 'hide') else control.bone.hide
            assert hidden == (not enabled), (frame, control.name, hidden)
print('ANIMATED IK/FK VISIBILITY SURVIVES SAVE AND REOPEN PASSED')
