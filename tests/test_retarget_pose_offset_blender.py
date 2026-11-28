"""Match Source Pose respects Create Transforms Offset: binding afterwards doesn't move the model."""
from math import pi
from pathlib import Path

fixture = Path(__file__).with_name('test_addon_registration_blender.py')
exec(compile(fixture.read_text(encoding='utf-8').split('floor = importlib.import_module')[0], str(fixture), 'exec'))
retarget = importlib.import_module(MODULE + '.source.retargeting')
guided = importlib.import_module(MODULE + '.source.retargeting.guided')
offsets = importlib.import_module(MODULE + '.expy_kit.offsets')
preset_handler = importlib.import_module(MODULE + '.expy_kit.preset_handler')
Path(preset_handler.get_retarget_dir()).mkdir(parents=True, exist_ok=True)

scene = bpy.context.scene
SPINE = ('hips', 'spine1', 'spine2', 'neck', 'head')
ARM = ('shoulder', 'arm', 'forearm', 'hand')


def make_rig(name, arm_dir):
    data = bpy.data.armatures.new(name)
    ob = bpy.data.objects.new(name, data)
    scene.collection.objects.link(ob)
    bpy.context.view_layer.objects.active = ob
    bpy.ops.object.mode_set(mode='EDIT')
    parent = None
    for i, bone_name in enumerate(SPINE):
        bone = data.edit_bones.new(f'{name}_{bone_name}')
        bone.head, bone.tail = (0, 0, i), (0, 0, i + 1)
        bone.parent = parent
        parent = bone
    parent, start = data.edit_bones[f'{name}_spine2'], (0.0, 0.0, 2.5)
    for i, bone_name in enumerate(ARM):
        bone = data.edit_bones.new(f'{name}_{bone_name}')
        bone.head = [start[k] + arm_dir[k] * i for k in range(3)]
        bone.tail = [start[k] + arm_dir[k] * (i + 1) for k in range(3)]
        bone.parent = parent
        parent = bone
    bpy.ops.object.mode_set(mode='OBJECT')
    mapping = ob.data.expykit_retarget
    for slot in SPINE:
        setattr(mapping.spine, slot, f'{name}_{slot}')
    for slot in ARM:
        setattr(mapping.right_arm, slot, f'{name}_{slot}')
    return ob


def world_dirs(ob, posed):
    names = [f'{ob.name}_{n}' for n in SPINE + ARM]
    pairs = list(zip(names[:4], names[1:5])) + list(zip(names[5:], names[6:]))
    if posed:
        head = lambda n: ob.matrix_world @ ob.pose.bones[n].head
    else:
        head = lambda n: ob.matrix_world @ ob.data.bones[n].head_local
    return [(head(b) - head(a)).normalized() for a, b in pairs]


def select_only(ob):
    if bpy.context.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
    for other in bpy.context.selected_objects:
        other.select_set(False)
    ob.select_set(True)
    bpy.context.view_layer.objects.active = ob


driver = make_rig('anim', (1.0, 0.0, 0.0))
receiver = make_rig('model', (0.0, 0.0, -1.0))
receiver.location = (4, 0, 0)

# Offset the animation armature: turned 90 degrees, raised and scaled, like lining up a Mixamo export.
select_only(driver)
assert bpy.ops.object.expykit_create_offset() == {'FINISHED'}
settings = scene.expykit_offset
settings.rotation = (0.0, 0.0, pi / 2)
settings.location = (0.0, 0.0, 1.0)
settings.scale = 2.0
assert bpy.ops.object.expykit_apply_offset() == {'FINISHED'}
bpy.context.view_layer.update()
assert driver.parent is not None and driver.parent.name.startswith('EMP-Transforms-Offset')
offset_arm = world_dirs(driver, posed=False)[4]
assert abs(offset_arm.y - 1.0) < 1e-5, ('offset turns the T-pose arm to +Y', offset_arm)

select_only(receiver)
scene.expykit_bind_to = driver
scene.sub_retarget_apply_to = receiver
assert bpy.ops.sub.retarget_match_rest_pose() == {'FINISHED'}
bpy.context.view_layer.update()
for got, want in zip(world_dirs(receiver, posed=True), world_dirs(driver, posed=False)):
    assert got.dot(want) > 0.999, (got, want)
matched = world_dirs(receiver, posed=True)

# Binding with Match = current pose keeps the model exactly where matching left it, roll included:
# the offset's translation used to leak into the helper bones' roll and twist every bound bone.
before = {pb.name: (receiver.matrix_world @ pb.matrix).to_quaternion() for pb in receiver.pose.bones}
assert bpy.ops.object.ultimate_bind_armatures('EXEC_DEFAULT') == {'FINISHED'}
bpy.context.view_layer.update()
for got, want in zip(world_dirs(receiver, posed=True), matched):
    assert got.dot(want) > 0.999, ('bind moved the matched pose', got, want)
for pb in receiver.pose.bones:
    turned = before[pb.name].rotation_difference((receiver.matrix_world @ pb.matrix).to_quaternion()).angle
    assert turned < 1e-3, ('bind twisted the bone', pb.name, turned)

# With Match Object Transform off, bind ignores the model's own object rotation; matching must too,
# or the re-bound model ends up turned by that rotation.
receiver.rotation_euler = (0.0, 0.0, pi / 2)
scene.expykit_match_object_transform = False
assert bpy.ops.sub.retarget_match_rest_pose() == {'FINISHED'}
# Matching only lines the rigs up: the earlier bind is removed, not redone.
assert not scene.expykit_bind_is_active
assert not any(c.target == driver for pb in receiver.pose.bones for c in pb.constraints
               if c.type.startswith('COPY')), 'no bind constraints after matching'
bpy.context.view_layer.update()
space = receiver.matrix_world.inverted_safe().to_3x3()
for got, want in zip(world_dirs(receiver, posed=True), world_dirs(driver, posed=False)):
    local = (space @ got).normalized()
    assert local.dot(want) > 0.999, ('armature-space pose should line up, as bind will read it', local, want)
# Binding afterwards keeps that alignment.
assert bpy.ops.object.ultimate_bind_armatures('EXEC_DEFAULT') == {'FINISHED'}
bpy.context.view_layer.update()
for got, want in zip(world_dirs(receiver, posed=True), world_dirs(driver, posed=False)):
    assert got.dot(want) > 0.999, ('bound model should line up with the animation rest pose', got, want)
print('RETARGET_POSE_OFFSET_OK')
