from pathlib import Path

fixture = Path(__file__).with_name('test_ik_control_orientation_blender.py')
exec(compile(fixture.read_text().split('scene = bpy.context.scene')[0], str(fixture), 'exec'))
scene = bpy.context.scene
data = bpy.data.armatures.new('KneeSides')
arm = bpy.data.objects.new('KneeSides', data)
scene.collection.objects.link(arm)
bpy.context.view_layer.objects.active = arm
arm.select_set(True)
bpy.ops.object.mode_set(mode='EDIT')
for suffix in ('L', 'R', 'L2', 'R2', 'L.001', 'R.001'):
    side = 1 if suffix.startswith('L') else -1
    parent = None
    for part, head, tail in (
        ('Leg', (side * 2, 0, 10), (side * 1.99, 0, 5)),
        ('Knee', (side * 1.99, 0, 5), (side * 2, 0, 1)),
        ('Foot', (side * 2, 0, 1), (side * 2, -1, 1)),
        ('Toe', (side * 2, -1, 1), (side * 2, -2, 1)),
    ):
        bone = data.edit_bones.new(part + suffix)
        bone.head, bone.tail, bone.parent = head, tail, parent
        parent = bone
bpy.ops.object.mode_set(mode='POSE')
assert ikc.create_controls(bpy.context, arm, 'LEGS') == 6
for suffix in ('L', 'R', 'L2', 'R2', 'L.001', 'R.001'):
    side = 1 if suffix.startswith('L') else -1
    assert data.bones['KneeIK' + suffix].head_local.x * side > 0
    assert arm.pose.bones['KneeIK' + suffix].head.x * side > 0
    for pole_head, knee_head in ((data.bones['KneeIK' + suffix].head_local, data.bones['Knee' + suffix].head_local),
                                  (arm.pose.bones['KneeIK' + suffix].head, arm.pose.bones['Knee' + suffix].head)):
        offset = pole_head - knee_head
        assert abs(offset.x) < 1e-4 and abs(offset.z) < 1e-4, (suffix, offset)
        assert offset.y < -0.5, (suffix, offset)
    for control, source, multiple in (('FootIK', 'Foot', 3), ('ToeIK', 'Toe', 2)):
        assert abs(data.bones[control + suffix].length / data.bones[source + suffix].length - multiple) < 1e-5
ikc.match(bpy.context, arm, 'LEGS', entire=False, key=False)
bpy.context.view_layer.update()
for suffix in ('L', 'R', 'L2', 'R2', 'L.001', 'R.001'):
    side = 1 if suffix.startswith('L') else -1
    assert arm.pose.bones['KneeIK' + suffix].head.x * side > 0
    for pole_head, knee_head in ((data.bones['KneeIK' + suffix].head_local, data.bones['Knee' + suffix].head_local),
                                  (arm.pose.bones['KneeIK' + suffix].head, arm.pose.bones['Knee' + suffix].head)):
        offset = pole_head - knee_head
        assert abs(offset.x) < 1e-4 and abs(offset.z) < 1e-4, (suffix, offset)
        assert offset.y < -0.5, (suffix, offset)
print('KNEE POLES STAY ON THEIR OWN SIDE AND LONGER FOOT/TOE CONTROLS PASSED')
