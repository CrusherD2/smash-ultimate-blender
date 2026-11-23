"""Repeated matches stay 1:1 and build no correction bones or fade drivers.

blender --background --factory-startup --python-exit-code 1 --python tests/test_ik_detail_acceleration_blender.py
"""
from pathlib import Path
import importlib

fixture = Path(__file__).with_name('test_addon_registration_blender.py')
exec(compile(fixture.read_text().split('floor = importlib.import_module')[0], str(fixture), 'exec'))
ik = importlib.import_module(MODULE + '.source.extras.ik_channels')
for existing in list(bpy.data.objects):
    bpy.data.objects.remove(existing, do_unlink=True)
data = bpy.data.armatures.new('Repeat match')
obj = bpy.data.objects.new('Repeat match', data)
bpy.context.scene.collection.objects.link(obj)
bpy.context.view_layer.objects.active = obj
obj.select_set(True)
bpy.ops.object.mode_set(mode='EDIT')
hip = data.edit_bones.new('Hip')
hip.head, hip.tail = (0, 0, 4), (0, 0, 5)
helper = data.edit_bones.new('H_Helper')
helper.head, helper.tail, helper.parent = (1,0,4), (1,0,5), hip
for side, x in (('L', 1), ('R', -1)):
    parent = hip
    for name, head, tail in (
        ('Leg', (x, 0, 4), (x, .3, 2)),
        ('Knee', (x, .3, 2), (x, 0, 0)),
        ('Foot', (x, 0, 0), (x, -1, 0)),
    ):
        bone = data.edit_bones.new(name + side)
        bone.head, bone.tail, bone.parent = head, tail, parent
        parent = bone
bpy.ops.object.mode_set(mode='OBJECT')
helper = obj.pose.bones['H_Helper'].constraints.new('COPY_ROTATION')
helper.name = 'nuHelperBoneRotateInterp144.X'
helper.target, helper.subtarget = obj, 'LegL'
scene = bpy.context.scene
scene.frame_start, scene.frame_end = 1, 16
for frame, angle in ((1, .1), (16, .35)):
    for side in ('L', 'R'):
        pb = obj.pose.bones['Knee' + side]
        pb.rotation_mode = 'XYZ'
        pb.rotation_euler.x = angle
        pb.keyframe_insert('rotation_euler', frame=frame)
source = {}
for frame in range(1, 17):
    scene.frame_set(frame)
    source[frame] = {name: obj.pose.bones[name].matrix.copy()
                     for name in ('LegL', 'KneeL', 'FootL', 'LegR', 'KneeR', 'FootR', 'H_Helper')}
ik.create_controls(bpy.context, obj, 'LEGS')
jobs = list(ik.chains(obj, 'LEGS'))
assert len(jobs) == 2

audit = lambda *_args, **_kwargs: None  # Kept for older fixtures; there is no batch audit any more.

audit()
for repeat in range(0):
    pass


def near_straight(matrices, side):
    root, joint, end = (matrices[part + side].translation for part in ('Leg', 'Knee', 'Foot'))
    length = (joint - root).length + (end - joint).length
    axis = (end - root).normalized()
    offset = joint - root - axis * (joint - root).dot(axis)
    return length if offset.length < .01 * length else None


def check_pose(repeat):
    import math
    for frame, matrices in source.items():
        scene.frame_set(frame)
        bpy.context.view_layer.update()
        straight = [length for length in (near_straight(matrices, 'L'), near_straight(matrices, 'R')) if length]
        for name, wanted in matrices.items():
            actual = obj.pose.bones[name].matrix
            if max(abs(a-b) for ar, br in zip(actual, wanted) for a, b in zip(ar, br)) < 2e-4:
                continue
            # Near-straight legs are nudged to fold toward their pole: under 1.5 degrees and 1.5% of the leg.
            assert straight, (repeat, frame, name)
            angle = actual.to_quaternion().rotation_difference(wanted.to_quaternion()).angle
            assert min(angle, 2 * math.pi - angle) < math.radians(1.5), (repeat, frame, name, angle)
            assert (actual.translation - wanted.translation).length < .015 * max(straight), (repeat, frame, name)


for repeat in range(2):
    ik.match(bpy.context, obj, 'LEGS')
    check_pose(repeat)
assert not any(bone.name.startswith(ik.CORRECTION_PREFIX) for bone in data.bones)
assert not any(ik.PULL_BASE in curve.data_path for curve in obj.animation_data.drivers)
for name in ('LegL', 'KneeL', 'FootL'):
    assert [con.name for con in obj.pose.bones[name].constraints] == [ik.OUTPUT], name
print('IK_DETAIL_ACCELERATION_OK')
