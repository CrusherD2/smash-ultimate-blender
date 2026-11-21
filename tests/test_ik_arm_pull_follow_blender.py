"""ArmIK Pull keeps the shoulder tail on the pulled elbow; Follow Parent/Child places the bend.

blender --background --factory-startup --python-exit-code 1 --python tests/test_ik_arm_pull_follow_blender.py
"""
import importlib
import sys
from pathlib import Path

import bpy
from mathutils import Vector

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))
addon = importlib.import_module(ROOT.name)
addon.register()
ik = importlib.import_module(ROOT.name + '.source.extras.ik_channels')

data = bpy.data.armatures.new('PullFollow')
obj = bpy.data.objects.new('PullFollow', data)
bpy.context.collection.objects.link(obj)
bpy.context.view_layer.objects.active = obj
obj.select_set(True)
bpy.ops.object.mode_set(mode='EDIT')
previous = None
for name, head, tail in (('ShoulderL', (0, 0, 0), (0, 3, 0)), ('ArmL', (0, 3, 0), (0, 5, 0)),
                         ('HandL', (0, 5, 0), (0, 6, 0))):
    bone = data.edit_bones.new(name)
    bone.head, bone.tail = head, tail
    bone.parent, bone.use_connect = previous, previous is not None
    previous = bone
bpy.ops.object.mode_set(mode='POSE')
assert ik.create_controls(bpy.context, obj, 'ARMS') == 1
_kind, names, target, pole = next(ik.chains(obj, 'ARMS'))
pb = obj.pose.bones
data.sub_ik_stretch_arms = True
data.sub_ik_stretch_chain_arms = True
assert abs(data.sub_ik_stretch_follow_arms - 0.5) < 1e-9


def head(name):
    bpy.context.view_layer.update()
    return pb[name].head.copy()


def tail_gap():
    bpy.context.view_layer.update()
    shoulder = pb['ShoulderL']
    direction = (shoulder.tail - shoulder.head).normalized()
    to_arm = (pb['ArmL'].head - shoulder.head).normalized()
    return direction.angle(to_arm)


# Without pull the stretch leaves the limb straight and the aim untouched.
pb[target].location.y += 4.0
straight = tail_gap()
assert straight < 1e-4, straight
reach = 6.0
hand = head('HandL')
# Default follow keeps the rest proportion: the elbow sits at 3/5 of the stretched line.
assert abs((head('ArmL') - pb['ShoulderL'].head).length / (hand - pb['ShoulderL'].head).length - 0.6) < 1e-3
data.sub_ik_stretch_follow_arms = 0.0
near_root = (head('ArmL') - pb['ShoulderL'].head).length
data.sub_ik_stretch_follow_arms = 1.0
near_end = (head('HandL') - head('ArmL')).length
data.sub_ik_stretch_follow_arms = 0.5
default = (head('ArmL') - pb['ShoulderL'].head).length
assert near_root < default - 0.5 and abs(near_root - 3.0) < 1e-3, (near_root, default)
assert abs(near_end - 2.0) < 1e-3, near_end
# The hand stays on its control at every follow value.
assert (head('HandL') - pb[target].head).length < 1e-3

# A full pull moves the elbow onto ArmIK and the shoulder now points at it.
pb[pole].location += Vector((2.0, 0.0, 0.0))
pb[pole].bone.sub_ik_arm_pull = 1.0
for follow in (0.0, 0.5, 1.0):
    data.sub_ik_stretch_follow_arms = follow
    assert (head('ArmL') - pb[pole].head).length < 1e-3, (follow, head('ArmL'), pb[pole].head)
    assert tail_gap() < 1e-4, (follow, tail_gap())
    assert (head('HandL') - pb[target].head).length < 1e-3
pb[pole].bone.sub_ik_arm_pull = 0.0
assert tail_gap() < 1e-4
print('ARM PULL AIMS THE SHOULDER AND FOLLOW PARENT/CHILD PLACES THE BEND PASSED')
