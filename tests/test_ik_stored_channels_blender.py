"""Matched solver keys live on the IK controls, so deleting control keys deletes them too.

Also covers moving an older rig's hidden keys onto the controls with Update IK Rig.

blender --background --factory-startup --python-exit-code 1 --python tests/test_ik_stored_channels_blender.py
"""
import importlib
import sys
from pathlib import Path

import bpy

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))
addon = importlib.import_module(ROOT.name)
addon.register()
ik = importlib.import_module(ROOT.name + '.source.extras.ik_channels')
rig = importlib.import_module(ROOT.name + '.source.extras.create_animation_rig')
upgrade = importlib.import_module(ROOT.name + '.source.extras.ik_rig_upgrade')
compat = importlib.import_module(ROOT.name + '.source.anim.fcurve_compat')

SIDES = 'LR'
FRAMES = range(1, 21)


def build(name):
    data = bpy.data.armatures.new(name)
    obj = bpy.data.objects.new(name, data)
    bpy.context.scene.collection.objects.link(obj)
    for other in bpy.context.selected_objects:
        other.select_set(False)
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    bpy.ops.object.mode_set(mode='EDIT')
    hip = data.edit_bones.new('Hip')
    hip.head, hip.tail = (0, 0, 4), (0, 0, 5)
    for side, x in (('L', 1), ('R', -1)):
        parent = hip
        for bone_name, head, tail in (('Shoulder', (x * 1.2, 0, 4.6), (x * 2.8, .2, 4.6)),
                                      ('Arm', (x * 2.8, .2, 4.6), (x * 4.4, 0, 4.6)),
                                      ('Hand', (x * 4.4, 0, 4.6), (x * 5, 0, 4.6))):
            bone = data.edit_bones.new(bone_name + side)
            bone.head, bone.tail, bone.parent = head, tail, parent
            parent = bone
    bpy.ops.object.mode_set(mode='POSE')
    pb = obj.pose.bones
    for frame in (1, 5, 10, 15, 20):
        t = frame / 20
        for side in SIDES:
            for bone_name in ('Shoulder', 'Arm', 'Hand'):
                pb[bone_name + side].rotation_mode = 'XYZ'
            # A big swing between 5 and 15, so the matched keys there differ a lot from their neighbours.
            swing = 1.4 if frame == 10 else 0.0
            pb['Shoulder' + side].rotation_euler = (0.3 * t + swing, 0.2, 0.4 * t)
            pb['Arm' + side].rotation_euler = (0.1, 0.0, 1.1 + 0.3 * t)
            pb['Hand' + side].rotation_euler = (0.2 * t, 0.1, 0.0)
            for bone_name in ('Shoulder', 'Arm', 'Hand'):
                pb[bone_name + side].keyframe_insert('rotation_euler', frame=frame)
    return obj


def matrices(obj, names):
    result = {}
    for frame in FRAMES:
        bpy.context.scene.frame_set(frame)
        bpy.context.view_layer.update()
        result[frame] = {name: obj.pose.bones[name].matrix.copy() for name in names}
    return result


def worst(obj, wanted):
    error = 0.0
    for frame, mats in wanted.items():
        bpy.context.scene.frame_set(frame)
        bpy.context.view_layer.update()
        for name, matrix in mats.items():
            actual = obj.pose.bones[name].matrix
            error = max(error, max(abs(a - b) for row, other in zip(actual, matrix) for a, b in zip(row, other)))
    return error


def curves(obj):
    return list(compat.get_all_action_fcurves(obj.animation_data.action, id_type='OBJECT'))


def stored_hidden(obj):
    return {pb.name for pb in obj.pose.bones if pb.bone.get(ik.STORE_KEY)}


scene = bpy.context.scene
scene.frame_start, scene.frame_end = FRAMES[0], FRAMES[-1]
watch = [name + side for side in SIDES for name in ('Shoulder', 'Arm', 'Hand')]

# New rigs: matched 1:1, nothing keyed on the hidden bones.
obj = build('StoredRig')
fk = matrices(obj, watch)
ik.create_controls(bpy.context, obj, 'ARMS')
rig._set_ik_enabled(bpy.context, obj, True, limbs='ARMS')
ik.match(bpy.context, obj, 'ARMS', entire=True, key=True)
error = worst(obj, fk)
assert error < 2e-4, ('match', error)
hidden = stored_hidden(obj)
assert {ik.PREFIX + 'ArmL', ik.POSE_PREFIX + 'ArmL', ik.OFFSET_PREFIX + 'ArmL'} <= hidden, hidden
assert not any(fc.data_path.startswith(tuple(f'pose.bones["{n}"]' for n in hidden)) for fc in curves(obj))
assert not any(fc.data_path.endswith('pole_angle') for fc in curves(obj))
for side in SIDES:
    hand = obj.pose.bones['HandIK' + side].path_from_id()
    pole = obj.pose.bones['ArmIK' + side].path_from_id()
    owned = [fc for fc in curves(obj) if fc.data_path.startswith(hand + '["_IK ')]
    assert owned and all(fc.group and fc.group.name == 'HandIK' + side and fc.hide for fc in owned)
    assert any(fc.data_path == pole + f'["{ik.POLE_ANGLE_PROP}"]' for fc in curves(obj))
assert not ik.unmatched(obj, obj.animation_data.action)

# Deleting the controls' keys on 6-14 deletes the solver keys with them.
controls = tuple(obj.pose.bones[name + side].path_from_id() for side in SIDES for name in ('HandIK', 'ArmIK'))
for fc in curves(obj):
    if fc.data_path.startswith(controls):
        for key in reversed(list(fc.keyframe_points)):
            if 6 <= key.co.x <= 14:
                fc.keyframe_points.remove(key, fast=True)
        fc.update()
scene.frame_set(10)
bpy.context.view_layer.update()
solver = obj.pose.bones[ik.PREFIX + 'ShoulderL']
rotation = next(fc for fc in curves(obj) if fc.data_path.endswith('["_IK Solve ShoulderL Rotation"]')
                and fc.array_index == 0)
assert not any(6 <= key.co.x <= 14 for key in rotation.keyframe_points)
assert abs(solver.rotation_quaternion[0] - rotation.evaluate(10)) < 1e-6
for side in SIDES:
    root, joint, end = (obj.pose.bones[name + side].head for name in ('Shoulder', 'Arm', 'Hand'))
    axis = (end - root).normalized()
    bend = joint - root
    bend -= axis * bend.dot(axis)
    toward = obj.pose.bones['ArmIK' + side].head - root
    toward -= axis * toward.dot(axis)
    assert bend.normalized().dot(toward.normalized()) > 0.9, ('elbow bends away from its pole', side)
    gap = (end - obj.pose.bones['HandIK' + side].head).length
    assert gap < 1e-3, ('hand left its control', side, gap)

# Removing IK leaves no drivers or stored curves behind.
ik.remove(bpy.context, obj, 'ARMS')
assert not [d.data_path for d in obj.animation_data.drivers if 'BL_SUB_IK_' in d.data_path]
assert not any('["_IK ' in fc.data_path for fc in curves(obj))

# Older rigs keyed the hidden bones; Update IK Rig moves those keys without re-solving.
bpy.data.objects.remove(obj)
old = build('OldRig')
fk = matrices(old, watch)
install = ik.install_store
ik.install_store = lambda *_args: None
try:
    ik.create_controls(bpy.context, old, 'ARMS')
    rig._set_ik_enabled(bpy.context, old, True, limbs='ARMS')
    ik.match(bpy.context, old, 'ARMS', entire=True, key=True)
finally:
    ik.install_store = install
action = old.animation_data.action
records = ik.json.loads(action[ik.MATCH_KEY])
action[ik.MATCH_KEY] = ik.json.dumps({kind: [s[:-2] + ':4' for s in value] for kind, value in records.items()})
assert any(fc.data_path.startswith('pose.bones["BL_SUB_IK_ArmL"]') for fc in curves(old))
old.data[upgrade.REVISION_KEY] = 3
before = matrices(old, watch)
keys_before = sum(len(fc.keyframe_points) for fc in curves(old) if 'BL_SUB_IK_' in fc.data_path)
assert upgrade.needs_update(old)
upgrade.update_in_place(bpy.context, old)
assert old.get(upgrade.BACKUP_KEY) in bpy.data.objects
assert not upgrade.needs_update(old)
assert worst(old, before) < 1e-6, worst(old, before)
assert worst(old, fk) < 2e-4
hidden = tuple(f'pose.bones["{n}"]' for n in stored_hidden(old))
assert not any(fc.data_path.startswith(hidden) for fc in curves(old))
assert not any(fc.data_path.endswith('pole_angle') for fc in curves(old))
moved = [fc for fc in curves(old) if '["_IK ' in fc.data_path]
assert moved and all(fc.hide for fc in moved)
assert not [g.name for g in old.animation_data.action.layers[0].strips[0].channelbags[0].groups
            if g.name.startswith('BL_SUB_IK_') and not g.channels]
assert keys_before > 0
assert not ik.unmatched(old, old.animation_data.action)
print('IK STORED CHANNELS PASSED')
