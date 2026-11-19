from pathlib import Path

fixture = Path(__file__).with_name('test_ik_knee_side_blender.py')
setup, checks = fixture.read_text().split("bpy.ops.object.mode_set(mode='POSE')", 1)
exec(compile(setup, str(fixture), 'exec'))
for suffix, roll in (('L', 0.0), ('R', .7), ('L2', 1.4), ('R2', -1.2), ('L.001', 2.7), ('R.001', -2.4)):
    data.edit_bones['Leg' + suffix].roll = roll
    data.edit_bones['Knee' + suffix].roll = -roll
    if suffix in ('L2', 'R2'):
        side = 1 if suffix.startswith('L') else -1
        data.edit_bones['Leg' + suffix].tail.x = side * 2
        data.edit_bones['Knee' + suffix].head.x = side * 2
exec(compile("bpy.ops.object.mode_set(mode='POSE')" + checks, str(fixture), 'exec'))
for suffix in ('L', 'R', 'L2', 'R2', 'L.001', 'R.001'):
    control = arm.pose.bones['FootIK' + suffix]
    matrix = control.matrix.copy()
    matrix.translation.z += 5.0
    control.matrix = matrix
arm.update_tag()
bpy.context.view_layer.update()
evaluated = arm.evaluated_get(bpy.context.evaluated_depsgraph_get())
for suffix in ('L', 'R', 'L2', 'R2', 'L.001', 'R.001'):
    for prefix in ('', ikc.PREFIX):
        root, knee, foot = [evaluated.pose.bones[prefix + part + suffix].head for part in ('Leg', 'Knee', 'Foot')]
        pole = evaluated.pose.bones['KneeIK' + suffix].head
        axis = (foot - root).normalized()
        bend = knee - root - axis * (knee - root).dot(axis)
        toward = pole - root - axis * (pole - root).dot(axis)
        assert bend.length > .5, (suffix, prefix, bend)
        alignment = bend.normalized().dot(toward.normalized())
        assert alignment > .99, (suffix, prefix, alignment)
print('LIFTED FOOT CONTROLS BEND BOTH KNEES TOWARD THEIR POLES PASSED')
