"""Mirror Bone names, parents, and X positions in armature edit mode.

blender --background --factory-startup --python-exit-code 1 --python tests/test_mirror_bone_blender.py
"""
import importlib.util
from pathlib import Path

import bpy
from mathutils import Vector

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    'mirror_bone', ROOT / 'source' / 'extras' / 'mirror_bone.py')
mirror_bone = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mirror_bone)


def new_armature():
    if bpy.context.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
    bpy.ops.object.armature_add(enter_editmode=True)
    armature = bpy.context.object
    bones = armature.data.edit_bones
    bones.remove(bones[0])
    return armature


def add_bone(bones, name, head, tail, parent=None, roll=0.0, use_connect=False, use_deform=True):
    bone = bones.new(name)
    bone.head = Vector(head)
    bone.tail = Vector(tail)
    bone.roll = roll
    bone.use_deform = use_deform
    bone.parent = parent
    bone.use_connect = use_connect
    bone.select = False
    bone.select_head = False
    bone.select_tail = False
    return bone


def select(bones, *names):
    for bone in bones:
        chosen = bone.name in names
        bone.select = chosen
        bone.select_head = chosen
        bone.select_tail = chosen


def close(a, b, tol=1e-5):
    return (Vector(a) - Vector(b)).length <= tol


armature = new_armature()
bones = armature.data.edit_bones
hand_r = add_bone(bones, 'HandR', (1, 0, 0), (1, 0.4, 0))
hand_l = add_bone(bones, 'HandL', (-1, 0, 0), (-1, 0.4, 0))
have_r = add_bone(
    bones, 'HaveR', (1, 0.4, 0), (1.5, 0.8, 0.3),
    parent=hand_r, roll=0.35, use_connect=True, use_deform=False,
)
select(bones, 'HaveR')
mirrored, skipped, warnings = mirror_bone.mirror_selected_bones(armature)
assert mirrored == [('HaveR', 'HaveL')], mirrored
assert not skipped and not warnings
have_l = bones['HaveL']
assert have_l.parent == bones['HandL']
assert have_l.use_connect
assert not have_l.use_deform
assert close(have_l.head, (-1, 0.4, 0))
assert close(have_l.tail, (-1.5, 0.8, 0.3))
assert abs(have_l.roll - (-0.35)) < 1e-5
assert close(have_r.head, (1, 0.4, 0))
# Mirroring the copy returns the original side.
select(bones, 'HaveL')
mirrored, skipped, warnings = mirror_bone.mirror_selected_bones(armature)
assert mirrored == [('HaveL', 'HaveR')]
assert close(bones['HaveR'].head, (1, 0.4, 0))
assert abs(bones['HaveR'].roll - 0.35) < 1e-5

# An unsided bone takes its side from the parent, then parents the copy to the other side.
item = add_bone(bones, 'Item', (1.1, 0.2, 0), (1.1, 0.6, 0), parent=bones['HandR'], roll=-0.2)
select(bones, 'Item')
mirrored, skipped, warnings = mirror_bone.mirror_selected_bones(armature)
assert mirrored == [('ItemR', 'ItemL')], mirrored
assert bones['ItemR'].parent == bones['HandR']
assert bones['ItemL'].parent == bones['HandL']
assert close(bones['ItemL'].head, (-1.1, 0.2, 0))
assert abs(bones['ItemL'].roll - 0.2) < 1e-5

# Side walks up through an unsided parent, and a selected chain parents to the mirrored parent.
socket = add_bone(bones, 'Socket', (1, 1, 0), (1, 1.2, 0), parent=bones['HandR'])
gem = add_bone(bones, 'Gem', (1, 1.5, 0), (1, 1.8, 0.2), parent=socket, roll=0.1)
select(bones, 'Socket', 'Gem')
mirrored, skipped, warnings = mirror_bone.mirror_selected_bones(armature)
assert dict(mirrored) == {'SocketR': 'SocketL', 'GemR': 'GemL'}
assert bones['SocketL'].parent == bones['HandL']
assert bones['GemL'].parent == bones['SocketL']
assert bones['GemR'].parent == bones['SocketR']
assert close(bones['GemL'].tail, (-1, 1.8, 0.2))

# Numbered suffixes swap the letter and keep the digits.
finger = add_bone(bones, 'FingerL11', (-0.4, 0.2, 0), (-0.4, 0.5, 0), parent=bones['HandL'])
select(bones, 'FingerL11')
mirrored, skipped, warnings = mirror_bone.mirror_selected_bones(armature)
assert mirrored == [('FingerL11', 'FingerR11')]
assert bones['FingerR11'].parent == bones['HandR']
assert close(bones['FingerR11'].head, (0.4, 0.2, 0))

# No L/R ancestor: leave the bone alone.
hip = add_bone(bones, 'Hip', (0, 0, 1), (0, 0.2, 1))
center = add_bone(bones, 'Badge', (0, 0.1, 1), (0, 0.3, 1), parent=hip)
select(bones, 'Badge')
mirrored, skipped, warnings = mirror_bone.mirror_selected_bones(armature)
assert mirrored == []
assert skipped == [('Badge', 'could not tell L or R from its parents')]
assert 'BadgeL' not in bones and 'BadgeR' not in bones

# The other parent is missing: still create the bone and say why it has no parent.
lone = new_armature()
lone_bones = lone.data.edit_bones
only_r = add_bone(lone_bones, 'HandR', (1, 0, 0), (1, 0.4, 0))
add_bone(lone_bones, 'HaveR', (1, 0.5, 0), (1, 0.9, 0), parent=only_r)
select(lone_bones, 'HaveR')
mirrored, skipped, warnings = mirror_bone.mirror_selected_bones(lone)
assert mirrored == [('HaveR', 'HaveL')]
assert lone_bones['HaveL'].parent is None
assert warnings == ['HaveL was not parented because HandL does not exist']

# Selecting both sides mirrors each original onto the other.
both = new_armature()
both_bones = both.data.edit_bones
add_bone(both_bones, 'HaveR', (1, 0, 0), (1, 0.5, 0), roll=0.25)
add_bone(both_bones, 'HaveL', (-2, 0.1, 0), (-2, 0.7, 0), roll=-0.1)
select(both_bones, 'HaveR', 'HaveL')
mirrored, skipped, warnings = mirror_bone.mirror_selected_bones(both)
assert dict(mirrored) == {'HaveR': 'HaveL', 'HaveL': 'HaveR'}
assert close(both_bones['HaveL'].head, (-1, 0, 0))
assert close(both_bones['HaveR'].head, (2, 0.1, 0))
assert abs(both_bones['HaveL'].roll - (-0.25)) < 1e-5
assert abs(both_bones['HaveR'].roll - 0.1) < 1e-5

# A rename cannot take a name that already belongs to another bone.
clash = new_armature()
clash_bones = clash.data.edit_bones
held = add_bone(clash_bones, 'HandR', (1, 0, 0), (1, 0.3, 0))
add_bone(clash_bones, 'Item', (1, 0.4, 0), (1, 0.6, 0), parent=held)
add_bone(clash_bones, 'ItemR', (2, 0, 0), (2, 0.2, 0))
select(clash_bones, 'Item')
mirrored, skipped, warnings = mirror_bone.mirror_selected_bones(clash)
assert mirrored == []
assert skipped == [('Item', 'ItemR already exists')]
assert 'Item' in clash_bones

assert mirror_bone.mirrored_vertex_group_map([
    'ClavicleR', 'HaveR', 'SwordL', 'Hip', 'FingerL11', 'Item', 'WingR2',
]) == {
    'ClavicleR': 'ClavicleL',
    'HaveR': 'HaveL',
    'SwordL': 'SwordR',
    'FingerL11': 'FingerR11',
    'WingR2': 'WingL2',
}

print('MIRROR BONE PASSED')
