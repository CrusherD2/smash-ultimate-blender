"""Repeated matches keep native acceleration; edited fade drivers fall back.

blender --background --factory-startup --python-exit-code 1 --python tests/test_ik_detail_acceleration_blender.py
"""
from pathlib import Path
import importlib, os, time

fixture = Path(__file__).with_name('test_addon_registration_blender.py')
exec(compile(fixture.read_text().split('floor = importlib.import_module')[0], str(fixture), 'exec'))
ik = importlib.import_module(MODULE + '.source.extras.ik_channels')
diag = importlib.import_module(MODULE + '.source.extras.ik_match_diag')
os.environ['SUB_NATIVE_IK'] = 'experimental'
os.environ['SUB_IK_DIAG'] = '1'
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
states = [(con, con.mute) for _, con, _ in (*ik.outputs(obj), *ik.toe_outputs(obj))]

def audit(expected=True, contained=None):
    try:
        for con, _ in states:
            con.mute = True
        diag.reset()
        assert ik._can_batch_match(obj, jobs) == expected, diag.record()
        assert ik._is_self_contained(obj, jobs) == (expected if contained is None else contained), diag.record()
    finally:
        for con, mute in states:
            con.mute = mute

audit()
for repeat in range(2):
    started = time.perf_counter()
    ik.match(bpy.context, obj, 'LEGS', _batch=True)
    record = diag.record()
    print('REPEATED_MATCH', repeat, time.perf_counter() - started, record, flush=True)
    assert record['counts'].get('native_solves', 0) == 32, record
    assert record['reasons'].get('selfcontained') == 'ok', record
    assert record['reasons'].get('batch') == 'ok', record
    audit()

def pose_error():
    error = 0.0
    for frame, matrices in source.items():
        scene.frame_set(frame)
        bpy.context.view_layer.update()
        for name, wanted in matrices.items():
            error = max(error, max(abs(a-b) for ar, br in zip(obj.pose.bones[name].matrix, wanted)
                                   for a, b in zip(ar, br)))
    return error

error = pose_error()
assert error < 2e-4, error
# Reproduce the previous guard behavior without changing the installed source.
specs = ik._detail_driver_specs
try:
    ik._detail_driver_specs = lambda *args: {}
    started = time.perf_counter()
    ik.match(bpy.context, obj, 'LEGS', _batch=True)
    old_time = time.perf_counter() - started
    old_record = diag.record()
    assert old_record['reasons']['selfcontained'] == 'foreign_driver_expression', old_record
    assert old_record['counts'].get('native_solves', 0) == 0, old_record
    assert pose_error() < 2e-4
    print('PREVIOUS_FALLBACK', old_time, old_record, 'POSE_ERROR', error, flush=True)
finally:
    ik._detail_driver_specs = specs

audit()
# A helper following LegL is safe; feeding it back into another limb is not.
feedback = obj.pose.bones[ik.PREFIX + 'LegR'].constraints.new('COPY_ROTATION')
feedback.target, feedback.subtarget = obj, 'H_Helper'
audit(False, contained=True)
obj.pose.bones[ik.PREFIX + 'LegR'].constraints.remove(feedback)
# Nor may a helper become an upstream input to the source hierarchy.
feedback = obj.pose.bones['Hip'].constraints.new('COPY_ROTATION')
feedback.target, feedback.subtarget = obj, 'H_Helper'
audit(False)
obj.pose.bones['Hip'].constraints.remove(feedback)
extra = obj.pose.bones['H_Helper'].constraints.new('COPY_LOCATION')
extra.target, extra.subtarget = obj, 'LegR'
audit(False)
obj.pose.bones['H_Helper'].constraints.remove(extra)
audit()
curve = next(fc for fc in obj.animation_data.drivers if ik.PULL_BASE in fc.data_path)
expression = curve.driver.expression
curve.driver.expression = expression + '+0'
audit(False)
curve.driver.expression = expression
var = curve.driver.variables[0]
original_path = var.targets[0].data_path
var.targets[0].data_path = original_path.replace('L', 'R')
audit(False)
var.targets[0].data_path = original_path
outside = bpy.data.objects.new('Outside', None)
scene.collection.objects.link(outside)
var.targets[0].id = outside
audit(False)
var.targets[0].id = obj
helper.target = outside
audit(False)
helper.target = obj
curve.driver.use_self = True
audit(False)
curve.driver.use_self = False
audit()
obj.parent = outside
audit(False)
obj.parent = None
print('IK_DETAIL_ACCELERATION_OK')
