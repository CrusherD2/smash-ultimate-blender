"""Fast Smash Viewport pose/mesh collection matches the per-bone math it replaced."""
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from mathutils import Euler, Matrix

fixture = Path(__file__).with_name('test_addon_registration_blender.py')
exec(compile(fixture.read_text().split('floor = importlib.import_module')[0], str(fixture), 'exec'))
viewport = importlib.import_module(MODULE + '.source.extras.smash_viewport')

scene = bpy.context.scene
data = bpy.data.armatures.new('Rig')
arm = bpy.data.objects.new('Rig', data)
scene.collection.objects.link(arm)
bpy.context.view_layer.objects.active = arm
bpy.ops.object.mode_set(mode='EDIT')
for name, head, tail, deform in (('Trans', (0, 0, 0), (0, 0, 1), True),
                                 ('Hip', (0, 0, 1), (0, .5, 2), True),
                                 ('SUB_Helper', (0, 0, 1), (1, 0, 1), True),
                                 ('NoDeform', (0, 0, 2), (0, 1, 2), False)):
    bone = data.edit_bones.new(name)
    bone.head, bone.tail, bone.use_deform = head, tail, deform
data.edit_bones['Hip'].parent = data.edit_bones['Trans']
bpy.ops.object.mode_set(mode='POSE')
arm.pose.bones['Hip'].rotation_mode = 'XYZ'
arm.pose.bones['Hip'].rotation_euler = (0.3, -0.7, 1.1)
arm.pose.bones['Trans'].location = (0.2, 0.4, -0.1)
bpy.ops.object.mode_set(mode='OBJECT')
arm.matrix_world = Matrix.Translation((3, -2, 1)) @ Euler((0.2, 0.1, -0.4)).to_matrix().to_4x4()
bpy.context.view_layer.update()

expected_names = []
expected = []
for pbone in arm.pose.bones:
    if viewport._skip_smash_bone(pbone.name) or not pbone.bone.use_deform:
        continue
    smash = viewport._Z_UP_TO_Y_UP @ (arm.matrix_world @ pbone.matrix) @ viewport._Y_MAJOR_TO_X_MAJOR
    expected_names.append(pbone.name)
    expected.extend(viewport._mat4_col_major(smash))

with patch.object(viewport, '_loaded_folder', 'C:/model'), \
     patch.object(viewport, '_iter_pose_armatures', return_value=[arm]):
    names, matrices = viewport._collect_smash_bones(None, bpy.context)
assert names == expected_names == ['Trans', 'Hip'], names
assert len(matrices) == len(expected)
assert max(abs(a - b) for a, b in zip(matrices, expected)) < 1e-5, (matrices, expected)

# Edit Mode and Rest Position show the rest mesh, not the current animation.
posed_key = viewport._armature_pose_key(arm)
for mode in ('EDIT', 'REST'):
    if mode == 'EDIT':
        bpy.ops.object.mode_set(mode='EDIT')
    else:
        data.pose_position = 'REST'
    assert viewport._armature_pose_key(arm) != posed_key
    actual = viewport.smash_bone_matrices(arm.pose, arm.matrix_world)
    for index, pbone in enumerate(arm.pose.bones):
        rest = viewport._Z_UP_TO_Y_UP @ arm.matrix_world @ pbone.bone.matrix_local @ viewport._Y_MAJOR_TO_X_MAJOR
        assert max(abs(a - b) for a, b in zip(actual[index], viewport._mat4_col_major(rest))) < 1e-5
    bpy.ops.object.mode_set(mode='OBJECT')
    data.pose_position = 'POSE'
bpy.context.view_layer.update()
assert viewport._armature_pose_key(arm) == posed_key

# Changing a bone's rest position must not deform an unposed mesh.
original_rest = {bone.name: bone.matrix_local.copy() for bone in data.bones}
bpy.ops.object.mode_set(mode='EDIT')
data.edit_bones['Hip'].head.x += 0.5
data.edit_bones['Hip'].tail.x += 0.5
bpy.ops.object.mode_set(mode='POSE')
for pbone in arm.pose.bones:
    pbone.matrix_basis = Matrix.Identity(4)
bpy.ops.object.mode_set(mode='OBJECT')
bpy.context.view_layer.update()
for posed in (False, True):
    if posed:
        arm.pose.bones['Hip'].rotation_euler.z = 0.4
        bpy.context.view_layer.update()
    actual = viewport.smash_bone_matrices(arm.pose, arm.matrix_world, original_rest)
    for index, pbone in enumerate(arm.pose.bones):
        rest = original_rest[pbone.name]
        uploaded = Matrix([actual[index][c * 4:c * 4 + 4] for c in range(4)]).transposed()
        inverse_bind = (viewport._Z_UP_TO_Y_UP @ rest @ viewport._Y_MAJOR_TO_X_MAJOR).inverted()
        skin = uploaded @ inverse_bind
        expected_skin = (viewport._Z_UP_TO_Y_UP @ arm.matrix_world @ pbone.matrix
                         @ pbone.bone.matrix_local.inverted() @ viewport._Y_UP_TO_Z_UP)
        assert all(abs(skin[r][c] - expected_skin[r][c]) < 1e-5
                   for r in range(4) for c in range(4)), pbone.name
print('SMASH_VIEWPORT_EDITED_REST_OK')

# Nested meshes are still found after replacing the per-object children walk.
mesh = bpy.data.objects.new('Body', bpy.data.meshes.new('Body'))
nested = bpy.data.objects.new('Nested', bpy.data.meshes.new('Nested'))
empty = bpy.data.objects.new('Group', None)
for obj in (mesh, nested, empty):
    scene.collection.objects.link(obj)
mesh.parent = arm
empty.parent = arm
nested.parent = empty
assert sorted(obj.name for obj in viewport._iter_armature_meshes(arm)) == ['Body', 'Nested']
for obj in (nested, empty, mesh, arm):
    bpy.data.objects.remove(obj)
print('SMASH_VIEWPORT_POSE_UPLOAD_OK')

# Within one preview update, repeated lookups reuse the first answer and
# outside of it they are always fresh.
rig2 = bpy.data.objects.new('Rig2', bpy.data.armatures.new('Rig2'))
scene.collection.objects.link(rig2)
body = bpy.data.objects.new('Body2', bpy.data.meshes.new('Body2'))
scene.collection.objects.link(body)
body.parent = rig2
calls = []
real = viewport._mesh_hidden_now
with patch.object(viewport, '_mesh_hidden_now', side_effect=lambda *a: calls.append(a) or real(*a)):
    viewport._frame_memo = {}
    try:
        assert viewport._mesh_hidden(body, None) is False
        assert viewport._mesh_hidden(body, None) is False
        assert [o.name for o in viewport._iter_armature_meshes(rig2)] == ['Body2']
    finally:
        viewport._frame_memo = None
    assert len(calls) == 1, calls
    body.hide_set(True)
    assert viewport._mesh_hidden(body, None) is True
    assert len(calls) == 2
bpy.data.objects.remove(body)
assert list(viewport._iter_armature_meshes(rig2)) == []
bpy.data.objects.remove(rig2)
print('SMASH_VIEWPORT_FRAME_MEMO_OK')

# Mesh transforms are skipped while nothing moves, and re-sent once something does.
rig3 = bpy.data.objects.new('Rig3', bpy.data.armatures.new('Rig3'))
scene.collection.objects.link(rig3)
part = bpy.data.objects.new('Part', bpy.data.meshes.new('Part'))
scene.collection.objects.link(part)
part.parent = rig3
part.modifiers.new('Armature', 'ARMATURE').object = rig3
bpy.context.view_layer.update()
sent = []
fake_lib = SimpleNamespace(ssbh_preview_set_mesh_transforms=lambda *a: sent.append(a[-1]) or 0)
depsgraph = bpy.context.evaluated_depsgraph_get()
with patch.object(viewport, '_lib', fake_lib), \
     patch.object(viewport, '_primary_smash_armature', return_value=rig3), \
     patch.object(viewport, '_last_mesh_transform_state', None), \
     patch.object(viewport, '_last_mesh_transform_fp', None):
    assert viewport._sync_mesh_transforms(1, bpy.context, depsgraph) is True
    assert viewport._last_mesh_transform_fp is not None
    with patch.object(viewport, '_mesh_armature', side_effect=AssertionError('rebuilt unchanged transforms')):
        assert viewport._sync_mesh_transforms(1, bpy.context, depsgraph) is False
    part.location.x += 1.0
    bpy.context.view_layer.update()
    depsgraph = bpy.context.evaluated_depsgraph_get()
    assert viewport._sync_mesh_transforms(1, bpy.context, depsgraph) is True
assert sent == [1, 1], sent
for obj in (part, rig3):
    bpy.data.objects.remove(obj)

# Mesh ids are reused, and refreshed after a rename.
named = bpy.data.objects.new('HairShape', bpy.data.meshes.new('HairShape'))
scene.collection.objects.link(named)
assert viewport.smash_gpu_id_cached(named) == ('HairShape', 0)
with patch.object(viewport, '_smash_gpu_id', side_effect=AssertionError('not cached')):
    assert viewport.smash_gpu_id_cached(named) == ('HairShape', 0)
named.name = 'BodyShape'
assert viewport.smash_gpu_id_cached(named) == ('BodyShape', 0)
bpy.data.objects.remove(named)
print('SMASH_VIEWPORT_CHANGE_SKIPS_OK')

# Visibility work is reused while only unrelated things change, and redone when
# a mesh's hide_viewport changes (drivers) or the scene is edited.
rig4 = bpy.data.objects.new('Rig4', bpy.data.armatures.new('Rig4'))
scene.collection.objects.link(rig4)
shape = bpy.data.objects.new('ShoeShape', bpy.data.meshes.new('ShoeShape'))
scene.collection.objects.link(shape)
shape.parent = rig4
viewport._vis_cache.clear()
assert viewport.visibility_key(bpy.context, None) is not None, 'bulk hide_viewport read failed'
real_now = viewport._collect_mesh_visibility_now
with patch.object(viewport, '_iter_folder_smash_armatures', return_value=[rig4]), \
     patch.object(viewport, '_collect_mesh_visibility_now', wraps=real_now) as rebuilt:
    first = viewport._collect_mesh_visibility(bpy.context)
    assert viewport._collect_mesh_visibility(bpy.context) == first
    assert rebuilt.call_count == 1
    shape.hide_viewport = True
    hidden_state = viewport._collect_mesh_visibility(bpy.context)
    assert rebuilt.call_count == 2
    assert dict(zip(zip(hidden_state[0], hidden_state[1]), hidden_state[2]))[('ShoeShape', 0)] == 0
    shape.hide_viewport = False
    viewport._scene_edit_serial += 1  # what a depsgraph update (eye toggle, reparent) does
    viewport._collect_mesh_visibility(bpy.context)
    assert rebuilt.call_count == 3
# The mesh list follows reparenting once the serial moves.
assert [o.name for o in viewport._iter_armature_meshes(rig4)] == ['ShoeShape']
shape.parent = None
viewport._scene_edit_serial += 1
assert list(viewport._iter_armature_meshes(rig4)) == []
for obj in (shape, rig4):
    bpy.data.objects.remove(obj)
viewport._vis_cache.clear()
print('SMASH_VIEWPORT_VIS_CACHE_OK')

# A moved mesh is sent relative to its armature, so a moved/rotated armature
# with an unmoved mesh sends identity and a moved mesh sends only its own offset.
rig5 = bpy.data.objects.new('Rig5', bpy.data.armatures.new('Rig5'))
scene.collection.objects.link(rig5)
hand = bpy.data.objects.new('HandShape', bpy.data.meshes.new('HandShape'))
scene.collection.objects.link(hand)
hand.parent = rig5
hand.modifiers.new('Armature', 'ARMATURE').object = rig5
rig5.matrix_world = Matrix.Translation((4, -3, 2)) @ Euler((0, 0, 1.2)).to_matrix().to_4x4()
bpy.context.view_layer.update()
sent = []
fake_lib = SimpleNamespace(ssbh_preview_set_mesh_transforms=lambda p, idx, names, subs, mats, count: sent.append([mats[i] for i in range(16 * count)]) or 0)
with patch.object(viewport, '_lib', fake_lib), \
     patch.object(viewport, '_primary_smash_armature', return_value=rig5), \
     patch.object(viewport, '_last_mesh_transform_state', None), \
     patch.object(viewport, '_last_mesh_transform_fp', None):
    viewport._sync_mesh_transforms(1, bpy.context, bpy.context.evaluated_depsgraph_get())
    identity = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]
    assert max(abs(a - b) for a, b in zip(sent[-1], identity)) < 1e-5, sent[-1]
    hand.matrix_world = rig5.matrix_world @ Matrix.Translation((1, 0, 0))  # dragged 1 unit along the rig's X
    bpy.context.view_layer.update()
    viewport._sync_mesh_transforms(1, bpy.context, bpy.context.evaluated_depsgraph_get())
    moved = Matrix([sent[-1][c * 4:c * 4 + 4] for c in range(4)]).transposed()
    expected = viewport._Z_UP_TO_Y_UP @ Matrix.Translation((1, 0, 0)) @ viewport._Y_UP_TO_Z_UP
    assert all(abs(moved[r][c] - expected[r][c]) < 1e-5 for r in range(4) for c in range(4)), moved
for obj in (hand, rig5):
    bpy.data.objects.remove(obj)
print('SMASH_VIEWPORT_MESH_OFFSET_OK')
