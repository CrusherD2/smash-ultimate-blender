from pathlib import Path

fixture = Path(__file__).with_name('test_ik_control_orientation_blender.py')
exec(compile(fixture.read_text().split('scene = bpy.context.scene')[0], str(fixture), 'exec'))
scene = bpy.context.scene
data = bpy.data.armatures.new('ArmPoles')
arm = bpy.data.objects.new('ArmPoles', data)
scene.collection.objects.link(arm)
bpy.context.view_layer.objects.active = arm
arm.select_set(True)
bpy.ops.object.mode_set(mode='EDIT')
suffixes = ('L', 'R', 'L2', 'R2', 'L.001', 'R.001')
for index, suffix in enumerate(suffixes):
    side = 1 if suffix.startswith('L') else -1
    offset = 0 if suffix in ('L2', 'R2') else .01
    elbow_height = 15 if suffix in ('L2', 'R2') else 14
    parent = None
    for part, head, tail in (
        ('Shoulder', (side * 2, 0, 15), (side * 6, offset, elbow_height)),
        ('Arm', (side * 6, offset, elbow_height), (side * 10, 0, 15)),
        ('Hand', (side * 10, 0, 15), (side * 11, 0, 15)),
    ):
        bone = data.edit_bones.new(part + suffix)
        bone.head, bone.tail, bone.parent = head, tail, parent
        bone.roll = index * .7
        parent = bone
bpy.ops.object.mode_set(mode='POSE')
import math
from mathutils import Vector
def pole_side_ok(pole, root, joint, end, forward, limb):
    """The pole sits along the joint's bend, or on the forward side when the limb is straight."""
    axis = (end - root).normalized()
    bend = joint - root - axis * (joint - root).dot(axis)
    expected = bend if bend.length >= .01 * limb else forward - axis * forward.dot(axis)
    toward = pole - root - axis * (pole - root).dot(axis)
    return toward.length > .5 and toward.normalized().dot(expected.normalized()) > math.cos(math.radians(1))


assert ikc.create_controls(bpy.context, arm, 'ARMS') == len(suffixes)
for matched in (False, True):
    if matched:
        ikc.match(bpy.context, arm, 'ARMS', entire=False, key=False)
        bpy.context.view_layer.update()
    for suffix in suffixes:
        limb = (data.bones['Arm' + suffix].head_local - data.bones['Shoulder' + suffix].head_local).length             + (data.bones['Hand' + suffix].head_local - data.bones['Arm' + suffix].head_local).length
        rest = [data.bones[name + suffix] for name in ('Shoulder', 'Arm')]
        posed = [arm.pose.bones[ikc.PREFIX + name + suffix] for name in ('Shoulder', 'Arm')]
        # Elbows point back (+Y) when straight; otherwise the pole follows the real bend.
        assert pole_side_ok(data.bones['ArmIK' + suffix].head_local, rest[0].head_local, rest[1].head_local,
                            rest[1].tail_local, Vector((0, 1, 0)), limb), (suffix, matched, 'rest')
        assert pole_side_ok(arm.pose.bones['ArmIK' + suffix].head, posed[0].head, posed[1].head,
                            posed[1].tail, Vector((0, 1, 0)), limb), (suffix, matched, 'pose')
for suffix in suffixes:
    control = arm.pose.bones['HandIK' + suffix]
    matrix = control.matrix.copy()
    matrix.translation.x -= 4 if suffix.startswith('L') else -4
    control.matrix = matrix
arm.update_tag()
bpy.context.view_layer.update()
evaluated = arm.evaluated_get(bpy.context.evaluated_depsgraph_get())
for suffix in suffixes:
    for prefix in ('', ikc.PREFIX):
        root, joint, end = [evaluated.pose.bones[prefix + part + suffix].head
                            for part in ('Shoulder', 'Arm', 'Hand')]
        pole = evaluated.pose.bones['ArmIK' + suffix].head
        axis = (end - root).normalized()
        bend = joint - root - axis * (joint - root).dot(axis)
        toward = pole - root - axis * (pole - root).dot(axis)
        assert bend.length > .5, (suffix, prefix, bend)
        assert bend.normalized().dot(toward.normalized()) > .99, (suffix, prefix)
print('ARM POLES ALIGN WITH ELBOWS AND BOTH ARMS BEND TOWARD THEIR POLES PASSED')
