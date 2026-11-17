"""Reparenting a bone that the pose sample skips must still refresh Smash Viewport."""
from pathlib import Path
import time

fixture = Path(__file__).with_name('test_addon_registration_blender.py')
exec(compile(fixture.read_text().split('floor = importlib.import_module')[0], str(fixture), 'exec'))
viewport = importlib.import_module(MODULE + '.source.extras.smash_viewport')

scene = bpy.context.scene
data = bpy.data.armatures.new('Rig')
arm = bpy.data.objects.new('Rig', data)
scene.collection.objects.link(arm)
bpy.context.view_layer.objects.active = arm
bpy.ops.object.mode_set(mode='EDIT')
for index in range(600):
    bone = data.edit_bones.new(f'Bone{index:03}')
    bone.head, bone.tail = (index * 0.01, 0, 0), (index * 0.01, 0, 1)
data.edit_bones['Bone001'].head = (0, 0, 2)
data.edit_bones['Bone001'].tail = (0, 1, 2)
bpy.ops.object.mode_set(mode='POSE')
arm.pose.bones['Bone001'].rotation_mode = 'XYZ'
arm.pose.bones['Bone001'].rotation_euler.z = 0.8
bpy.ops.object.mode_set(mode='OBJECT')
bpy.context.view_layer.update()
before = viewport._armature_pose_key(arm)

# Bone007 is not one of the old every-15th samples; only its parent changes.
bpy.ops.object.mode_set(mode='EDIT')
data.edit_bones['Bone007'].parent = data.edit_bones['Bone001']
bpy.ops.object.mode_set(mode='OBJECT')
bpy.context.view_layer.update()
assert viewport._armature_pose_key(arm) != before

start = time.perf_counter()
for _ in range(200):
    viewport._armature_pose_key(arm)
print(f'POSE_KEY_MS {(time.perf_counter() - start) / 200 * 1000:.3f}')
bpy.data.objects.remove(arm)
print('SMASH_VIEWPORT_REPARENT_KEY_OK')

# Reparenting reorders pose bones; uploaded names must follow the new order.
data = bpy.data.armatures.new('Order')
arm = bpy.data.objects.new('Order', data)
scene.collection.objects.link(arm)
bpy.context.view_layer.objects.active = arm
bpy.ops.object.mode_set(mode='EDIT')
for name, parent in (('Root', None), ('LegL', 'Root'), ('LegR', 'Root'), ('KneeR', 'LegR'), ('H_FootR', 'KneeR')):
    bone = data.edit_bones.new(name)
    bone.head, bone.tail = (0, 0, 0), (0, 0, 1)
    if parent:
        bone.parent = data.edit_bones[parent]
bpy.ops.object.mode_set(mode='OBJECT')
bpy.context.view_layer.update()
viewport._smash_bone_selection(arm.pose)
before = list(arm.pose.bones.keys())
bpy.ops.object.mode_set(mode='EDIT')
data.edit_bones['H_FootR'].parent = data.edit_bones['LegL']
bpy.ops.object.mode_set(mode='OBJECT')
bpy.context.view_layer.update()
assert list(arm.pose.bones.keys()) != before
indices, names = viewport._smash_bone_selection(arm.pose)
assert names == [arm.pose.bones[i].name for i in indices], names
start = time.perf_counter()
for _ in range(200):
    viewport._smash_bone_selection(arm.pose)
print(f'SELECTION_MS {(time.perf_counter() - start) / 200 * 1000:.3f}')
bpy.data.objects.remove(arm)
print('SMASH_VIEWPORT_REPARENT_ORDER_OK')
