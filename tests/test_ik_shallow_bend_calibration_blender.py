from pathlib import Path
import math

fixture = Path(__file__).with_name('test_ik_control_orientation_blender.py')
exec(compile(fixture.read_text().split('scene = bpy.context.scene')[0], str(fixture), 'exec'))
scene = bpy.context.scene
data = bpy.data.armatures.new('Shallow bends')
arm = bpy.data.objects.new('Shallow bends', data)
scene.collection.objects.link(arm)
bpy.context.view_layer.objects.active = arm
arm.select_set(True)
bpy.ops.object.mode_set(mode='EDIT')
for index, suffix in enumerate(('L', 'R', 'L2', 'R2', 'L.001', 'R.001')):
    sign = 1 if suffix.startswith('L') else -1
    scale = (0.1, 1.0, 10.0)[index // 2]
    for parts, points in (
        (('Shoulder', 'Arm', 'Hand'), ((sign * 2, 0, 15), (sign * 6, -.05, 15),
                                     (sign * 10, 0, 15), (sign * 11, 0, 15))),
        (('Leg', 'Knee', 'Foot'), ((sign * 2, 0, 10), (sign * 1.99, 0, 5),
                                 (sign * 2, 0, 1), (sign * 2, -1, 1))),
    ):
        parent = None
        for part, head, tail in zip(parts, points, points[1:]):
            bone = data.edit_bones.new(part + suffix)
            bone.head = tuple(value * scale for value in head)
            bone.tail = tuple(value * scale for value in tail)
            bone.roll = index * .7
            bone.parent = parent
            parent = bone
bpy.ops.object.mode_set(mode='POSE')
bpy.context.view_layer.update()
rest = {bone.name: (bone.matrix_local.copy(), bone.parent.name if bone.parent else None)
        for bone in data.bones}
original = {bone.name: bone.matrix.copy() for bone in arm.pose.bones}
assert ikc.create_controls(bpy.context, arm) == 12
for repeat in range(2):
    if repeat:
        ikc.match(bpy.context, arm, entire=False, key=False)
        bpy.context.view_layer.update()
    for name, wanted in original.items():
        actual = arm.pose.bones[name].matrix
        assert max(abs(a - b) for row, reference in zip(actual, wanted)
                   for a, b in zip(row, reference)) < 2e-4, (repeat, name)
for kind, names, target, pole in ikc.chains(arm):
    control = arm.pose.bones[target]
    origin = control.matrix.copy()
    root = arm.pose.bones[names[0]].head.copy()
    previous = {}
    for step in range(41):
        matrix = origin.copy()
        matrix.translation = origin.translation.lerp(root, step / 80)
        control.matrix = matrix
        arm.update_tag()
        bpy.context.view_layer.update()
        for name in names[:-1]:
            rotation = arm.pose.bones[name].matrix.to_quaternion()
            if name in previous:
                angle = rotation.rotation_difference(previous[name]).angle
                assert min(angle, 2 * math.pi - angle) < .3, (target, step, name, angle)
            previous[name] = rotation
    for prefix in ('', ikc.PREFIX):
        start, joint, finish = [arm.pose.bones[prefix + name].head for name in names]
        axis = (finish - start).normalized()
        bend = joint - start - axis * (joint - start).dot(axis)
        toward = arm.pose.bones[pole].head - start
        toward -= axis * toward.dot(axis)
        assert bend.normalized().dot(toward.normalized()) > .99, (target, prefix)
    control.matrix = origin
    arm.update_tag()
    bpy.context.view_layer.update()
for name, (matrix, parent) in rest.items():
    bone = data.bones[name]
    assert bone.matrix_local == matrix, name
    assert (bone.parent.name if bone.parent else None) == parent, name
print('SHALLOW BENDS PRESERVE POSES AND ORIGINAL RIG, ALIGN POLES, AND MOVE SMOOTHLY AT THREE SCALES PASSED')
