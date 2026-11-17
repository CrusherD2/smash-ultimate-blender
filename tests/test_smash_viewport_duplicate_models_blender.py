from pathlib import Path
from unittest.mock import patch

fixture = Path(__file__).with_name('test_addon_registration_blender.py')
exec(compile(fixture.read_text().split('floor = importlib.import_module')[0], str(fixture), 'exec'))
viewport = importlib.import_module(MODULE + '.source.extras.smash_viewport')
extra = importlib.import_module(MODULE + '.source.extras.smash_vp_extra')
scene = bpy.context.scene
arms = []
for name in ('Fighter', 'Fighter.001'):
    arm = bpy.data.objects.new(name, bpy.data.armatures.new(name))
    scene.collection.objects.link(arm)
    mesh = bpy.data.objects.new(name + 'Mesh', bpy.data.meshes.new(name + 'Mesh'))
    scene.collection.objects.link(mesh)
    mesh.parent = arm
    mesh['numshb order'] = 0
    arms.append(arm)
with patch.object(viewport, '_loaded_folder', 'same/model'), \
     patch.object(viewport, '_folder_has_numshb', return_value=True), \
     patch.object(viewport, '_folder_from_armature', return_value='same/model'), \
     patch.object(viewport, '_is_smash_armature', return_value=True), \
     patch.object(viewport, '_armature_owns_smash_mesh', return_value=True), \
     patch.object(viewport, '_object_visible', return_value=True):
    for primary, other in (arms, list(reversed(arms))):
        with patch.object(viewport, '_primary_smash_armature', return_value=primary):
            assert viewport._skip_extra_armature(primary)
            assert not viewport._skip_extra_armature(other)
            assert viewport._smash_folder_extra(other)
            assert other in list(extra.iter_extra_armatures(scene, viewport._skip_extra_armature))
    assert extra.bone_prefix(arms[0].name) != extra.bone_prefix(arms[1].name)
bpy.context.view_layer.update()
# Switching selection must not swap the base model with an already loaded extra.
with patch.object(viewport, '_loaded_folder', 'same/model'),      patch.object(viewport, '_folder_has_numshb', return_value=True),      patch.object(viewport, '_folder_from_armature', return_value='same/model'),      patch.object(viewport, '_is_smash_armature', return_value=True),      patch.object(viewport, '_primary_arm_obj', None):
    bpy.context.view_layer.objects.active = arms[0]
    assert viewport._primary_smash_armature(scene) == arms[0]
    for active in (arms[1], arms[0], arms[1]):
        bpy.context.view_layer.objects.active = active
        assert viewport._primary_smash_armature(scene) == arms[0]
        assert not viewport._skip_extra_armature(arms[1])

# Each extra uses its own edited rest skeleton, independent of the active object.
from mathutils import Matrix
original = {}
for index, arm in enumerate(arms):
    bpy.context.view_layer.objects.active = arm
    bpy.ops.object.mode_set(mode='EDIT')
    bone = arm.data.edit_bones.new('Jaw')
    bone.head, bone.tail = (0, 0, 1), (0, 1, 1)
    bpy.ops.object.mode_set(mode='OBJECT')
    original[arm.name] = {'Jaw': arm.data.bones['Jaw'].matrix_local.copy()}
    bpy.ops.object.mode_set(mode='EDIT')
    arm.data.edit_bones['Jaw'].head.x += index + 1
    arm.data.edit_bones['Jaw'].tail.x += index + 1
    bpy.ops.object.mode_set(mode='OBJECT')
    arm.pose.bones['Jaw'].rotation_mode = 'XYZ'
    arm.pose.bones['Jaw'].rotation_euler.z = 0.2 * (index + 1)
    arm.location.x = index * 5
bpy.context.view_layer.update()
for primary, other in (arms, list(reversed(arms))):
    with patch.object(viewport, '_extra_ok', True),          patch.object(viewport, '_extra_smash_arms', {other.as_pointer()}),          patch.object(extra, 'iter_extra_armatures', return_value=[other]),          patch.object(viewport, '_folder_from_armature', side_effect=lambda arm: arm.name),          patch.object(viewport, '_loaded_rest_bones', side_effect=lambda folder: original[folder]):
        for active in (primary, other):
            bpy.context.view_layer.objects.active = active
            names, matrices = viewport._collect_extra_bones(bpy.context)
            assert names == [extra.extra_bone_name(other.name, 'Jaw')]
            uploaded = Matrix([matrices[c * 4:c * 4 + 4] for c in range(4)]).transposed()
            source = original[other.name]['Jaw']
            inverse_bind = (viewport._Z_UP_TO_Y_UP @ source @ viewport._Y_MAJOR_TO_X_MAJOR).inverted()
            skin = uploaded @ inverse_bind
            pbone = other.pose.bones['Jaw']
            expected = (viewport._Z_UP_TO_Y_UP @ other.matrix_world @ pbone.matrix
                        @ pbone.bone.matrix_local.inverted() @ viewport._Y_UP_TO_Z_UP)
            assert all(abs(skin[r][c] - expected[r][c]) < 1e-5
                       for r in range(4) for c in range(4))
for arm in arms:
    bpy.data.objects.remove(arm)
print('SMASH_VIEWPORT_DUPLICATE_MODELS_OK')
