from pathlib import Path


def pose_hidden(pb):
    return pb.hide if hasattr(pb, 'hide') else pb.bone.hide

fixture = Path(__file__).with_name('test_ik_endpoint_hiding_blender.py')
exec(compile(fixture.read_text().split(chr(10) + 'assert ikc.create_controls')[0], str(fixture), 'exec'))
suffixes = ('L', 'R', 'L2', 'R2', 'L.001', 'R.001')
bpy.ops.object.mode_set(mode='EDIT')
bones = data.edit_bones
originals = [bone.name for bone in bones if bone.name.endswith('L')]
for index, suffix in enumerate(suffixes[1:], start=1):
    for original in originals:
        source = bones[original]
        bone = bones.new(original[:-1] + suffix)
        offset = Vector((index * 12, 0, 0))
        bone.head, bone.tail = source.head + offset, source.tail + offset
        bone.roll = source.roll
        if source.parent:
            name = source.parent.name
            bone.parent = bones[name[:-1] + suffix if name in originals else name]
            bone.use_connect = source.use_connect
bpy.ops.object.mode_set(mode='POSE')
# A previously used Show All setting must not defeat an explicit creation choice.
rig.set_off_mode_bones_hidden(arm, False)
assert not rig.off_mode_hiding_enabled(arm)
assert bpy.ops.sub.create_ik_bones(match_position=False, hide_affected_bones=True) == {'FINISHED'}
endpoints = [part + suffix for suffix in suffixes for part in ('Hand', 'Foot', 'Toe1', 'Toe2')]
affected = [part + suffix for suffix in suffixes for part in ('Shoulder', 'Arm', 'Hand', 'Leg', 'Knee', 'Foot', 'Toe1', 'Toe2')]
assert rig.off_mode_hiding_enabled(arm)
assert all(pose_hidden(arm.pose.bones[name]) == (name in endpoints) for name in affected)
assert all(pose_hidden(arm.pose.bones[name]) for name in endpoints), [n for n in endpoints if not pose_hidden(arm.pose.bones[n])]
assert all(not pose_hidden(arm.pose.bones['Finger'+suffix]) for suffix in suffixes)
assert all(not pose_hidden(arm.pose.bones[part+suffix]) for suffix in suffixes for part in ('HandIK', 'ArmIK', 'FootIK', 'KneeIK', 'ToeIK'))
# Existing controls also honor the saved checkbox on an explicit return to IK.
rig.set_off_mode_bones_hidden(arm, False)
assert not any(pose_hidden(arm.pose.bones[name]) for name in affected)
for frame, enabled in ((1, True), (5, False), (9, True)):
    scene.frame_set(frame)
    assert bpy.ops.sub.anim_rig_toggle_ik_fk(limbs='BOTH', set_enabled=True, enable_ik=enabled) == {'FINISHED'}
for frame, hidden in ((1, True), (5, False), (9, True), (5, False)):
    scene.frame_set(frame)
    bpy.context.view_layer.update()
    rig._sync_ik_fk_visibility(scene)
    assert all(pose_hidden(arm.pose.bones[name]) == hidden for name in endpoints), (frame, [n for n in endpoints if pose_hidden(arm.pose.bones[n]) != hidden])
    assert all(pose_hidden(arm.pose.bones[name]) == (hidden and name in endpoints) for name in affected), frame
    assert all(not pose_hidden(arm.pose.bones['Finger'+suffix]) for suffix in suffixes)
print('L/R, EXTRA LIMBS, DUPLICATE SUFFIXES, SHOW ALL OVERRIDE AND ANIMATED VISIBILITY PASSED')
