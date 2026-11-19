from pathlib import Path
from unittest.mock import patch, Mock
from contextlib import ExitStack

fixture = Path(__file__).with_name('test_addon_registration_blender.py')
exec(compile(fixture.read_text().split('floor = importlib.import_module')[0], str(fixture), 'exec'))
vp = importlib.import_module(MODULE + '.source.extras.smash_viewport')
scene = bpy.context.scene
old = ('world_rest_v2', ('smash', 10, 'Other', 'C:/fighter'))
new = ('world_rest_v2', ('smash', 20, 'Other', 'C:/fighter'))
with ExitStack() as stack:
    for name, value in {'_extra_ok': True, '_extra_fp': old, '_extra_gpu_order': [10],
                        '_extra_mesh_map': {10: ('smash', 0)}, '_extra_smash_arms': {10}}.items():
        stack.enter_context(patch.object(vp, name, value))
    stack.enter_context(patch.object(vp, '_extra_fingerprint', return_value=new))
    assert vp._reuse_undo_extra_models(scene)
    assert vp._extra_fp == new
    assert vp._extra_gpu_order == [20]
    assert vp._extra_mesh_map == {20: ('smash', 0)}
    assert vp._extra_smash_arms == {20}
    for fingerprint in (('world_rest_v2',), ('world_rest_v2', ('smash', 30, 'Other', 'C:/changed')),
                        ('world_rest_v2', ('smash', 30, 'Renamed', 'C:/fighter')),
                        ('world_rest_v2', ('build', 30, 'Other', ()))):
        with patch.object(vp, '_extra_fingerprint', return_value=fingerprint):
            assert not vp._reuse_undo_extra_models(scene)
    with patch.object(vp, '_extra_fp', ('world_rest_v2', ('build', 10, 'Other', ()))):
        assert not vp._reuse_undo_extra_models(scene)

with ExitStack() as stack:
    stack.enter_context(patch.object(vp, '_first_scene', return_value=scene))
    stack.enter_context(patch.object(vp, '_viewport_enabled', return_value=True))
    stack.enter_context(patch.object(vp, '_ignore_update', False))
    clear = stack.enter_context(patch.object(vp, '_clear_extra_models'))
    shutdown = stack.enter_context(patch.object(vp, 'shutdown_preview'))
    walk = stack.enter_context(patch.object(vp, '_smash_arm_fp'))
    stack.enter_context(patch.object(vp, '_tag_preview_redraw'))
    with patch.object(bpy.app.timers, 'is_registered', side_effect=(False, True)), patch.object(bpy.app.timers, 'register') as register:
        vp._on_undo_redo(None)
        vp._on_undo_redo(None)
        register.assert_called_once_with(vp._after_undo_viewport_refresh, first_interval=0.0)
    clear.assert_not_called()
    shutdown.assert_not_called()
    walk.assert_not_called()

for reuse in (True, False):
    with ExitStack() as stack:
        for name, value in {'_loaded_folder': 'C:/fighter', '_extra_fp': new,
                            '_first_scene': Mock(return_value=scene), '_viewport_enabled': Mock(return_value=True),
                            '_primary_smash_armature': Mock(return_value=object()),
                            '_reuse_undo_extra_models': Mock(return_value=reuse),
                            '_smash_arm_fp': Mock(return_value=('stable',)),
                            '_tag_preview_redraw': Mock()}.items():
            stack.enter_context(patch.object(vp, name, value))
        shutdown = stack.enter_context(patch.object(vp, 'shutdown_preview'))
        clear = stack.enter_context(patch.object(vp, '_clear_extra_models'))
        heal = stack.enter_context(patch.object(vp, '_heal_smash_file_viewport_state'))
        sync = stack.enter_context(patch.object(vp, '_sync_armature_mod_viewport'))
        assert vp._after_undo_viewport_refresh() is None
        assert clear.call_count == int(not reuse)
        shutdown.assert_not_called()
        heal.assert_not_called()
        sync.assert_called_once()
        assert vp._extra_fp == new

with patch.object(vp, '_first_scene', return_value=scene), patch.object(vp, '_viewport_enabled', return_value=True), patch.object(vp, '_loaded_folder', 'C:/gone'), patch.object(vp, '_primary_smash_armature', return_value=None), patch.object(vp, 'shutdown_preview') as shutdown, patch.object(bpy.app.timers, 'register'):
    vp._after_undo_viewport_refresh()
    shutdown.assert_called_once()
with patch.object(vp, '_reload_after_undo', True), patch.object(bpy.app.timers, 'is_registered', return_value=True), patch.object(vp, '_prepare_preview_now') as prepare:
    assert vp._prepare_preview(bpy.context) is None
    prepare.assert_not_called()
with patch.object(vp, '_reload_after_undo', True), patch.object(bpy.app.timers, 'is_registered', return_value=False), patch.object(vp, '_prepare_preview_now', return_value='ready') as prepare:
    assert vp._prepare_preview(bpy.context) == 'ready'
    prepare.assert_called_once()
print('UNDO RESOURCE REUSE, POINTER REBINDING, REFRESH COALESCING AND SAFE RELOAD PASSED')
