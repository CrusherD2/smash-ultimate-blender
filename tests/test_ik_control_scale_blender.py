"""Scaling HandIK, FootIK or FootRollIK scales the hand/foot and its children; matching keeps FK scale 1:1.

blender --background --factory-startup --python-exit-code 1 --python tests/test_ik_control_scale_blender.py
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

data = bpy.data.armatures.new('ScaleRig')
obj = bpy.data.objects.new('ScaleRig', data)
bpy.context.scene.collection.objects.link(obj)
bpy.context.view_layer.objects.active = obj
obj.select_set(True)
bpy.ops.object.mode_set(mode='EDIT')
hip = data.edit_bones.new('Hip')
hip.head, hip.tail = (0, 0, 4), (0, 0, 5)
for side, x in (('L', 1), ('R', -1)):
    for chain in (
        (('Leg', (x, 0, 4), (x, -.3, 2)), ('Knee', (x, -.3, 2), (x, 0, 0)),
         ('Foot', (x, 0, 0), (x, -1, 0)), ('Toe', (x, -1, 0), (x, -1.5, 0))),
        (('Shoulder', (x * 1.2, 0, 4.6), (x * 2.8, .2, 4.6)), ('Arm', (x * 2.8, .2, 4.6), (x * 4.4, 0, 4.6)),
         ('Hand', (x * 4.4, 0, 4.6), (x * 5, 0, 4.6)), ('Finger', (x * 5, 0, 4.6), (x * 5.4, 0, 4.6))),
    ):
        parent = hip
        for name, head, tail in chain:
            bone = data.edit_bones.new(name + side)
            bone.head, bone.tail, bone.parent = head, tail, parent
            parent = bone
bpy.ops.object.mode_set(mode='POSE')
scene = bpy.context.scene
scene.frame_start, scene.frame_end = 1, 3
pb = obj.pose.bones
for frame in (1, 3):
    pb['HandL'].scale = (1.3,) * 3
    pb['FootL'].scale = (0.7,) * 3
    pb['HandL'].keyframe_insert('scale', frame=frame)
    pb['FootL'].keyframe_insert('scale', frame=frame)
ik.create_controls(bpy.context, obj, 'BOTH')
rig._set_ik_enabled(bpy.context, obj, True, limbs='LEGS')
rig._set_ik_enabled(bpy.context, obj, True, limbs='ARMS')
watch = ('LegL', 'KneeL', 'FootL', 'ToeL', 'ShoulderL', 'ArmL', 'HandL', 'FingerL')
outputs = [con for _, con, _ in (*ik.outputs(obj), *ik.toe_outputs(obj))]
scene.frame_set(2)
for con in outputs:
    con.mute = True
bpy.context.view_layer.update()
fk = {name: pb[name].matrix.copy() for name in watch}
for con in outputs:
    con.mute = False
ik.match(bpy.context, obj, 'BOTH', entire=True, key=True)
scene.frame_set(2)
bpy.context.view_layer.update()
for name in watch:
    error = max(abs(a - b) for row, wanted in zip(pb[name].matrix, fk[name]) for a, b in zip(row, wanted))
    assert error < 2e-4, ('match', name, error)


def scales():
    bpy.context.view_layer.update()
    return {name: pb[name].matrix.to_scale().x for name in watch}


base = scales()
for control, grown in (('HandIKL', ('HandL', 'FingerL')), ('FootIKL', ('FootL', 'ToeL')),
                       ('FootRollIKL', ('FootL', 'ToeL'))):
    # Matching already put the FK scale on the control, so double what it has.
    before = pb[control].scale.copy()
    pb[control].scale = before * 2.0
    now = scales()
    for name in watch:
        expected = base[name] * (2.0 if name in grown else 1.0)
        assert abs(now[name] - expected) < 1e-3, (control, name, now[name], expected)
    pb[control].scale = before
print('IK CONTROL SCALE REACHES THE HAND/FOOT AND MATCHING KEEPS FK SCALE PASSED')
