"""Updating an old rig on a posed frame leaves the new rig in its rest calibration.

blender --background --factory-startup --python-exit-code 1 --python tests/test_ik_rig_upgrade_posed_blender.py
"""
from pathlib import Path
from mathutils import Vector

fixture = Path(__file__).with_name('test_ik_detail_acceleration_blender.py')
exec(compile(fixture.read_text().split('\naudit()\nfor repeat')[0], str(fixture), 'exec'))
upgrade = importlib.import_module(MODULE + '.source.extras.ik_rig_upgrade')
compat = importlib.import_module(MODULE + '.source.anim.fcurve_compat')
del obj.data[upgrade.REVISION_KEY]
# Animate the old controls so the old IK, not the FK keys, decides the leg pose.
foot = obj.pose.bones['FootIKL']
pole = obj.pose.bones['KneeIKL']
for frame, offset in ((1, Vector((0.3, -0.6, 0.8))), (16, Vector((-0.2, 0.4, 0.5)))):
    scene.frame_set(frame)
    foot.location = offset
    foot.keyframe_insert('location', frame=frame)
    pole.location = offset * 0.5
    pole.keyframe_insert('location', frame=frame)
scene.frame_set(1)
bpy.context.view_layer.update()
old_feet = {}
for frame in range(1, 17):
    scene.frame_set(frame)
    bpy.context.view_layer.update()
    old_feet[frame] = obj.pose.bones['FootL'].matrix.translation.copy()
scene.frame_set(1)
upgrade.update_in_place(bpy.context, obj)
assert not upgrade.needs_update(obj)
for frame, position in old_feet.items():
    scene.frame_set(frame)
    bpy.context.view_layer.update()
    assert (obj.pose.bones['FootL'].matrix.translation - position).length < 0.05, frame
# Re-solved limbs must not key seeds or residuals from the posed frames.
path = ik.limb_path(obj, ('LegL', 'KneeL', 'FootL'))
internal = {prefix + name for name in path for prefix in (ik.PREFIX, ik.CORRECTION_PREFIX)}
keyed = {fc.data_path.split('"')[1] for fc in compat.get_all_action_fcurves(obj.animation_data.action)
         if fc.data_path.startswith('pose.bones["')}
assert not internal & keyed, sorted(internal & keyed)
assert {'FootIKL', 'KneeIKL'} <= keyed
_angles, seeds = upgrade._rest_calibration(bpy.context, obj, 'LEGS', {'FootIKL'})
for name in internal:
    assert upgrade._matrix_error(obj.pose.bones[name].matrix_basis, seeds[name]) < 1e-5, name
print('POSED OLD-RIG UPDATE KEEPS CONTROL ANIMATION AND REST SOLVER CALIBRATION PASSED')
