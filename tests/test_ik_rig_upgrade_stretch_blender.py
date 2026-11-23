"""A rig with stretch on updates; settings survive and the end lands on its control.

blender --background --factory-startup --python-exit-code 1 --python tests/test_ik_rig_upgrade_stretch_blender.py
"""
from pathlib import Path
from mathutils import Vector

fixture = Path(__file__).with_name('test_ik_detail_acceleration_blender.py')
exec(compile(fixture.read_text().split('\naudit()\nfor repeat')[0], str(fixture), 'exec'))
upgrade = importlib.import_module(MODULE + '.source.extras.ik_rig_upgrade')
del obj.data[upgrade.REVISION_KEY]
obj.data.sub_ik_stretch_legs = True
obj.data.sub_ik_stretch_chain_legs = True
setattr(obj.data.bones['KneeIKL'], ik.ARM_PULL_PROPERTY, 0.38)
foot = obj.pose.bones['FootIKL']
for frame, offset in ((1, Vector((0.2, -0.5, 1.5))), (16, Vector((-0.2, 0.4, 1.2)))):
    foot.location = offset
    foot.keyframe_insert('location', frame=frame)
scene.frame_set(1)
bpy.context.view_layer.update()
upgrade.update_in_place(bpy.context, obj)
assert not upgrade.needs_update(obj)
assert obj.data.sub_ik_stretch_legs and obj.data.sub_ik_stretch_chain_legs
assert abs(getattr(obj.data.bones['KneeIKL'], ik.ARM_PULL_PROPERTY) - 0.38) < 1e-6
for frame in range(1, 17):
    scene.frame_set(frame)
    bpy.context.view_layer.update()
    distance = (obj.pose.bones['FootL'].matrix.translation - obj.pose.bones['FootIKL'].matrix.translation).length
    assert distance < 1e-3, (frame, distance)
print('STRETCHED OLD-RIG UPDATE PUTS THE END ON ITS CONTROL AND KEEPS POLE PULL PASSED')
