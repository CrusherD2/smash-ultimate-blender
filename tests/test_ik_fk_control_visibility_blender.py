from pathlib import Path

fixture = Path(__file__).with_name('test_ik_endpoint_hiding_bilateral_blender.py')
exec(compile(fixture.read_text(), str(fixture), 'exec'))
frame = 20
for preference in (True, False):
    rig.set_ik_endpoint_hiding(arm, preference)
    for limbs in ('ARMS', 'LEGS', 'BOTH'):
        parts = {'ARMS': ('Hand',), 'LEGS': ('Foot', 'Toe1', 'Toe2'),
                 'BOTH': ('Hand', 'Foot', 'Toe1', 'Toe2')}[limbs]
        originals = {part + suffix for part in parts for suffix in suffixes}
        controls = set(rig._ik_control_bone_names(arm, limbs))
        assert controls
        for enabled in (False, True, False, True):
            # Both buttons must override Show All, even with endpoint hiding disabled.
            rig.set_off_mode_bones_hidden(arm, False)
            scene.frame_set(frame)
            frame += 1
            assert bpy.ops.sub.anim_rig_toggle_ik_fk(
                limbs=limbs, set_enabled=True, enable_ik=enabled) == {'FINISHED'}
            assert rig.off_mode_hiding_enabled(arm)
            for mode in ('OBJECT', 'POSE'):
                bpy.ops.object.mode_set(mode=mode)
                assert all(arm.pose.bones[name].hide == (not enabled) for name in controls), (limbs, mode, enabled)
                assert all(arm.pose.bones[name].hide == (enabled and preference) for name in originals), (limbs, mode, enabled)
                assert not any(arm.pose.bones[part + suffix].hide for part in ('Leg', 'Knee', 'Shoulder', 'Arm') for suffix in suffixes)
                if mode == 'POSE':
                    visible = {bone.name for bone in bpy.context.visible_pose_bones}
                    assert (controls <= visible) if enabled else not controls.intersection(visible)
                    if not enabled or not preference:
                        assert originals <= visible
print('FK HIDES IK CONTROLS AND REVEALS ORIGINALS; IK RESTORES CONTROLS, BOTH SIDES AND LIMB TYPES PASSED')
