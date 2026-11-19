from pathlib import Path
from types import SimpleNamespace
import importlib

fixture = Path(__file__).with_name('test_ik_endpoint_hiding_bilateral_blender.py')
exec(compile(fixture.read_text(), str(fixture), 'exec'))
compat = importlib.import_module(MODULE + '.source.blender_compat')
# Legacy API fallback and Blender 5's separate Edit/Pose flags.
legacy = SimpleNamespace(bone=SimpleNamespace(hide=False))
compat.set_pose_bone_hidden(legacy, True)
assert legacy.bone.hide and compat.is_pose_bone_hidden(legacy)
modern = SimpleNamespace(hide=False, bone=SimpleNamespace(hide=True))
compat.set_pose_bone_hidden(modern, True)
assert modern.hide and modern.bone.hide
compat.set_pose_bone_hidden(modern, False)
assert not modern.hide and modern.bone.hide

assert hasattr(arm.pose.bones['FootR'], 'hide'), 'This regression targets Blender 5 PoseBone visibility'
# Simulate a saved rig affected by the previous incorrect Bone.hide implementation.
data['sub_ik_pose_visibility_migrated'] = False
for name in affected:
    data.bones[name].hide = True
    arm.pose.bones[name].hide = False
scene.frame_set(12)
assert bpy.ops.sub.anim_rig_toggle_ik_fk(limbs='BOTH', set_enabled=True, enable_ik=True) == {'FINISHED'}
controls = [part + suffix for suffix in suffixes for part in ('HandIK', 'ArmIK', 'FootIK', 'KneeIK', 'ToeIK')]
for mode in ('OBJECT', 'POSE'):
    bpy.ops.object.mode_set(mode=mode)
    assert all(arm.pose.bones[name].hide == (name in endpoints) for name in affected), mode
    assert not any(data.bones[name].hide for name in affected), (mode, [name for name in affected if data.bones[name].hide])
    assert not any(arm.pose.bones[name].hide for name in controls), mode
    if mode == 'POSE':
        visible = {bone.name for bone in bpy.context.visible_pose_bones}
        assert not visible.intersection(endpoints)
        assert set(affected) - set(endpoints) <= visible
        assert set(controls) <= visible
bpy.ops.object.mode_set(mode='EDIT')
assert not any(data.edit_bones[name].hide for name in affected)
assert set(affected) <= {bone.name for bone in bpy.context.visible_bones}
bpy.ops.object.mode_set(mode='POSE')
scene.frame_set(13)
assert bpy.ops.sub.anim_rig_toggle_ik_fk(limbs='BOTH', set_enabled=True, enable_ik=False) == {'FINISHED'}
for mode in ('OBJECT', 'POSE'):
    bpy.ops.object.mode_set(mode=mode)
    assert not any(arm.pose.bones[name].hide for name in affected), mode
    assert not any(data.bones[name].hide for name in affected), (mode, [name for name in affected if data.bones[name].hide])
    assert all(arm.pose.bones[name].hide for name in controls), mode
# An intentional later Edit Mode hide must not be reset by ordinary IK/FK switching.
bpy.ops.object.mode_set(mode='EDIT')
data.edit_bones['FootR'].hide = True
bpy.ops.object.mode_set(mode='POSE')
scene.frame_set(14)
assert bpy.ops.sub.anim_rig_toggle_ik_fk(limbs='BOTH', set_enabled=True, enable_ik=True) == {'FINISHED'}
assert data.bones['FootR'].hide
assert arm.pose.bones['FootR'].hide
ikc.remove(bpy.context, arm, 'BOTH')
assert not any(arm.pose.bones[name].hide for name in affected)
assert data.bones['FootR'].hide
print('ACTUAL POSE/OBJECT HIDING, EDIT VISIBILITY, OLD-RIG REPAIR AND REMOVAL PASSED')
