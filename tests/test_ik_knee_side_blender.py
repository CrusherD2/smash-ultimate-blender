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
import math
from mathutils import Vector
def pole_side_ok(pole, root, joint, end, forward, limb):
    """The pole sits along the joint's bend, or on the forward side when the limb is straight."""
    axis = (end - root).normalized()
    bend = joint - root - axis * (joint - root).dot(axis)
    expected = bend if bend.length >= .01 * limb else forward - axis * forward.dot(axis)
    toward = pole - root - axis * (pole - root).dot(axis)
    return toward.length > .5 and toward.normalized().dot(expected.normalized()) > math.cos(math.radians(1))


assert ikc.create_controls(bpy.context, arm, 'LEGS') == 6
for suffix in ('L', 'R', 'L2', 'R2', 'L.001', 'R.001'):
    side = 1 if suffix.startswith('L') else -1
    assert data.bones['KneeIK' + suffix].head_local.x * side > 0
    assert arm.pose.bones['KneeIK' + suffix].head.x * side > 0
    limb = (data.bones['Knee' + suffix].head_local - data.bones['Leg' + suffix].head_local).length         + (data.bones['Foot' + suffix].head_local - data.bones['Knee' + suffix].head_local).length
    rest = [data.bones[name + suffix] for name in ('Leg', 'Knee')]
    posed = [arm.pose.bones[ikc.PREFIX + name + suffix] for name in ('Leg', 'Knee')]
    # Knees point forward (-Y) when straight; otherwise the pole follows the real bend.
    assert pole_side_ok(data.bones['KneeIK' + suffix].head_local, rest[0].head_local, rest[1].head_local,
                        rest[1].tail_local, Vector((0, -1, 0)), limb), (suffix, 'rest')
    assert pole_side_ok(arm.pose.bones['KneeIK' + suffix].head, posed[0].head, posed[1].head,
                        posed[1].tail, Vector((0, -1, 0)), limb), (suffix, 'pose')
    for control, source, multiple in (('FootIK', 'Foot', 3), ('ToeIK', 'Toe', 2)):
        assert abs(data.bones[control + suffix].length / data.bones[source + suffix].length - multiple) < 1e-5
ikc.match(bpy.context, arm, 'LEGS', entire=False, key=False)
bpy.context.view_layer.update()
for suffix in ('L', 'R', 'L2', 'R2', 'L.001', 'R.001'):
    side = 1 if suffix.startswith('L') else -1
    assert arm.pose.bones['KneeIK' + suffix].head.x * side > 0
    limb = (data.bones['Knee' + suffix].head_local - data.bones['Leg' + suffix].head_local).length         + (data.bones['Foot' + suffix].head_local - data.bones['Knee' + suffix].head_local).length
    rest = [data.bones[name + suffix] for name in ('Leg', 'Knee')]
    posed = [arm.pose.bones[ikc.PREFIX + name + suffix] for name in ('Leg', 'Knee')]
    # Knees point forward (-Y) when straight; otherwise the pole follows the real bend.
    assert pole_side_ok(data.bones['KneeIK' + suffix].head_local, rest[0].head_local, rest[1].head_local,
                        rest[1].tail_local, Vector((0, -1, 0)), limb), (suffix, 'rest')
    assert pole_side_ok(arm.pose.bones['KneeIK' + suffix].head, posed[0].head, posed[1].head,
                        posed[1].tail, Vector((0, -1, 0)), limb), (suffix, 'pose')
print('KNEE POLES STAY ON THEIR OWN SIDE AND LONGER FOOT/TOE CONTROLS PASSED')
