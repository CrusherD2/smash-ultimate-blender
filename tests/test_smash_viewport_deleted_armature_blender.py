"""Deleting the character's armature removes its model from Smash Viewport."""
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

fixture = Path(__file__).with_name('test_addon_registration_blender.py')
exec(compile(fixture.read_text().split('floor = importlib.import_module')[0], str(fixture), 'exec'))
viewport = importlib.import_module(MODULE + '.source.extras.smash_viewport')
scene = bpy.context.scene
for obj in list(bpy.data.objects):
    bpy.data.objects.remove(obj)
arm = bpy.data.objects.new('Fighter', bpy.data.armatures.new('Fighter'))
scene.collection.objects.link(arm)
view = (None, SimpleNamespace(width=100, height=100), None)


def prepare(deleted):
    shutdowns = []
    with patch.object(viewport, '_viewport_enabled', return_value=True), \
         patch.object(viewport, '_preview_view_from_context', return_value=view), \
         patch.object(viewport, '_loaded_folder', 'C:/model/c88'), \
         patch.object(viewport, '_preview', 1), \
         patch.object(viewport, '_smash_arm_count', None), \
         patch.object(viewport, '_folder_has_numshb', return_value=True), \
         patch.object(viewport, '_folder_from_armature', return_value='C:/model/c88'), \
         patch.object(viewport, '_is_smash_armature', side_effect=lambda obj: obj.type == 'ARMATURE'), \
         patch.object(viewport, '_has_extra_candidates', return_value=False), \
         patch.object(viewport, '_ensure_preview', return_value=None), \
         patch.object(viewport, '_primary_arm_obj', None), \
         patch.object(viewport, 'shutdown_preview', side_effect=lambda: shutdowns.append(True)):
        if deleted:
            bpy.data.objects.remove(arm)
        viewport._prepare_preview_now(bpy.context)
    return shutdowns


assert prepare(deleted=False) == []
assert prepare(deleted=True) == [True]
print('SMASH_VIEWPORT_DELETED_ARMATURE_OK')

# A frame memo must not preserve the old folder's missing primary after reload.
remaining = bpy.data.objects.new('Remaining', bpy.data.armatures.new('Remaining'))
scene.collection.objects.link(remaining)
with patch.object(viewport, '_frame_memo', {}), \
     patch.object(viewport, '_lib', None), \
     patch.object(viewport, '_preview', None), \
     patch.object(viewport, '_loaded_folder', 'C:/deleted'), \
     patch.object(viewport, '_folder_has_numshb', return_value=True), \
     patch.object(viewport, '_folder_from_armature', return_value='C:/remaining'), \
     patch.object(viewport, '_is_smash_armature', side_effect=lambda obj: obj.type == 'ARMATURE'):
    assert viewport._primary_smash_armature(scene) is None
    viewport.shutdown_preview()
    with patch.object(viewport, '_model_folder', return_value='C:/remaining'):
        assert viewport._primary_smash_armature(scene) == remaining
print('SMASH_VIEWPORT_PRIMARY_RELOAD_OK')

bpy.context.view_layer.update()
