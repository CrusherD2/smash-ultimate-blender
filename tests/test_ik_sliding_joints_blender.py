"""FK that slides the elbow/hand with location keys: IK matches 1:1, the hand control sits on
the visible hand, and moving the control moves the hand by the same amount.

blender --background --factory-startup --python-exit-code 1 --python tests/test_ik_sliding_joints_blender.py
"""
import importlib
import math
import sys
from pathlib import Path

import bpy
from mathutils import Euler, Vector

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))
addon = importlib.import_module(ROOT.name)
addon.register()
ik = importlib.import_module(ROOT.name + '.source.extras.ik_channels')
rig = importlib.import_module(ROOT.name + '.source.extras.create_animation_rig')

data = bpy.data.armatures.new('SlideRig')
obj = bpy.data.objects.new('SlideRig', data)
bpy.context.scene.collection.objects.link(obj)
bpy.context.view_layer.objects.active = obj
obj.select_set(True)
bpy.ops.object.mode_set(mode='EDIT')
hip = data.edit_bones.new('Hip')
hip.head, hip.tail = (0, 0, 4), (0, 0, 5)
for side, x in (('L', 1), ('R', -1)):
    parent = hip
    for name, head, tail in (('Shoulder', (x * 1.2, 0, 4.6), (x * 2.8, .2, 4.6)),
                             ('Arm', (x * 2.8, .2, 4.6), (x * 4.4, 0, 4.6)),
                             ('Hand', (x * 4.4, 0, 4.6), (x * 5, 0, 4.6))):
        bone = data.edit_bones.new(name + side)
        bone.head, bone.tail, bone.parent = head, tail, parent
        parent = bone
bpy.ops.object.mode_set(mode='POSE')
scene = bpy.context.scene
scene.frame_start, scene.frame_end = 1, 9
pb = obj.pose.bones
for frame in (1, 5, 9):
    t = frame / 9
    for side in 'LR':
        pb['Shoulder' + side].rotation_mode = 'XYZ'
        pb['Shoulder' + side].rotation_euler = (0.2 * t, 0.3, 0.5 * t)
        pb['Arm' + side].rotation_mode = 'XYZ'
        pb['Arm' + side].rotation_euler = (0.1, 0.0, 0.9 * t + 0.3)
        # Smash-style slides: the elbow and hand move away from where their parent ends.
        pb['Arm' + side].location = (0.4 * t, 0.9 * t, -0.3)
        pb['Hand' + side].location = (0.0, 0.5 * t, 0.2)
        for name in ('Shoulder', 'Arm'):
            pb[name + side].keyframe_insert('rotation_euler', frame=frame)
        for name in ('Arm', 'Hand'):
            pb[name + side].keyframe_insert('location', frame=frame)
ik.create_controls(bpy.context, obj, 'ARMS')
rig._set_ik_enabled(bpy.context, obj, True, limbs='ARMS')
watch = [name + side for side in 'LR' for name in ('Shoulder', 'Arm', 'Hand')]
outputs = [con for _, con, _ in ik.outputs(obj)]
fk = {}
for con in outputs:
    con.mute = True
for frame in range(1, 10):
    scene.frame_set(frame)
    fk[frame] = {name: pb[name].matrix.copy() for name in watch}
for con in outputs:
    con.mute = False
ik.match(bpy.context, obj, 'ARMS', entire=True, key=True)
for frame in range(1, 10):
    scene.frame_set(frame)
    for name in watch:
        error = max(abs(a - b) for row, wanted in zip(pb[name].matrix, fk[frame][name]) for a, b in zip(row, wanted))
        assert error < 2e-4, ('match', frame, name, error)
    for side in 'LR':
        gap = (pb['HandIK' + side].matrix.translation - pb['Hand' + side].matrix.translation).length
        assert gap < 1e-3, ('control off the visible hand', frame, side, gap)

scene.frame_set(5)
bpy.context.view_layer.update()
for side in 'LR':
    hand, control, shoulder = pb['Hand' + side], pb['HandIK' + side], pb['Shoulder' + side]
    before = hand.matrix.translation.copy()
    # Toward the shoulder is always reachable, so the hand must follow exactly.
    step = (shoulder.matrix.translation - before).normalized() * 0.5
    saved = control.matrix.copy()
    moved = saved.copy()
    moved.translation += step
    control.matrix = moved
    bpy.context.view_layer.update()
    travel = (hand.matrix.translation - before).length
    gap = (hand.matrix.translation - control.matrix.translation).length
    assert abs(travel - 0.5) < 5e-3 and gap < 5e-3, (side, travel, gap)
    control.matrix = saved
    bpy.context.view_layer.update()
assert not any(math.isnan(v) for name in watch for row in pb[name].matrix for v in row)
print('SLIDING JOINTS: 1:1 MATCH, CONTROL ON THE VISIBLE HAND, EDITS FOLLOW PASSED')
