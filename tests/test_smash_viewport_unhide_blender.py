"""Outliner hierarchy eye toggles restore native visibility and CPU deformation."""
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

fixture = Path(__file__).with_name('test_addon_registration_blender.py')
exec(compile(fixture.read_text().split('floor = importlib.import_module')[0], str(fixture), 'exec'))
viewport = importlib.import_module(MODULE + '.source.extras.smash_viewport')
scene = bpy.context.scene
arm = bpy.data.objects.new('Fighter', bpy.data.armatures.new('Fighter'))
scene.collection.objects.link(arm)
mesh = bpy.data.objects.new('Body', bpy.data.meshes.new('Body'))
scene.collection.objects.link(mesh)
mesh.parent = arm
mod = mesh.modifiers.new('Armature', 'ARMATURE')
mod.object = arm
bpy.context.view_layer.update()
native = Mock(return_value=0)
with patch.object(viewport, '_lib', SimpleNamespace(ssbh_preview_set_model_visible=native)), \
     patch.object(viewport, '_preview', 1), \
     patch.object(viewport, '_loaded_folder', 'C:/fighter'), \
     patch.object(viewport, '_primary_smash_armature', return_value=arm), \
     patch.object(viewport, '_preview_space', return_value=None), \
     patch.object(viewport, '_viewport_enabled', return_value=True), \
     patch.object(viewport, '_gpu_pose_armature_ptrs', return_value={arm.as_pointer()}), \
     patch.object(viewport, '_is_smash_deform_mesh', side_effect=lambda obj, *args: obj == mesh), \
     patch.object(viewport, '_vis_cache', {}), \
     patch.object(viewport, '_frame_memo', None), \
     patch.object(viewport, '_last_model_vis_state', None), \
     patch.object(viewport, '_mod_show_saved', {}), \
     patch.object(viewport, '_schedule_mesh_draw_sync') as schedule:
    for hidden in (False, True, False, True, False):
        before = viewport.visibility_key(bpy.context, None)
        arm.hide_set(hidden)
        mesh.hide_set(hidden)
        after = viewport.visibility_key(bpy.context, None)
        if native.call_count:
            assert before != after
        viewport._last_pose_fp = 'stale pose'
        viewport._last_vis_state = 'stale visibility'
        assert viewport._sync_gpu_model_visibility(bpy.context)
        native.assert_called_with(1, 0, int(not hidden))
        assert viewport._last_pose_fp is None
        assert viewport._last_vis_state is None
        assert schedule.call_count == native.call_count
        viewport._sync_armature_mod_viewport(bpy.context)
        assert mod.show_viewport == (not hidden)
        assert not viewport._sync_gpu_model_visibility(bpy.context)
print('SMASH_VIEWPORT_UNHIDE_OK')
