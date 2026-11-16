"""Meshes deleted in Blender are hidden in the Smash Viewport instead of staying loaded."""
from pathlib import Path
from unittest.mock import patch

fixture = Path(__file__).with_name('test_addon_registration_blender.py')
exec(compile(fixture.read_text().split('floor = importlib.import_module')[0], str(fixture), 'exec'))
viewport = importlib.import_module(MODULE + '.source.extras.smash_viewport')

scene = bpy.context.scene
arm = bpy.data.objects.new('Rig', bpy.data.armatures.new('Rig'))
scene.collection.objects.link(arm)
kept = bpy.data.objects.new('BodyShape', bpy.data.meshes.new('BodyShape'))
scene.collection.objects.link(kept)
kept.parent = arm
kept.modifiers.new('Armature', 'ARMATURE').object = arm
folder_meshes = [('BodyShape', 0), ('HairShape', 0), ('HairShape', 1)]
with patch.object(viewport, '_loaded_folder', 'C:/model'), \
     patch.object(viewport, '_numshb_objects', return_value=folder_meshes), \
     patch.object(viewport, '_iter_folder_smash_armatures', return_value=[arm]), \
     patch.object(viewport, '_iter_armature_meshes', return_value=[kept]), \
     patch.object(viewport, '_gpu_mesh_hidden', return_value=False):
    state = dict(((name, sub), vis) for name, sub, vis in zip(*viewport._collect_mesh_visibility(bpy.context)))
    assert state == {('BodyShape', 0): 1, ('HairShape', 0): 0, ('HairShape', 1): 0}, state
    # A rig whose meshes cannot be matched must not blank the whole model.
    viewport._scene_edit_serial += 1  # a scene edit, as the depsgraph handler records
    with patch.object(viewport, '_iter_armature_meshes', return_value=[]):
        names, _subs, _vis = viewport._collect_mesh_visibility(bpy.context)
        assert names == [], names
bpy.data.objects.remove(kept)
bpy.data.objects.remove(arm)
print('SMASH_VIEWPORT_DELETED_MESHES_OK')
