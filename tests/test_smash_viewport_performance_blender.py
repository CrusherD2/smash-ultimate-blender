from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch, Mock

fixture = Path(__file__).with_name('test_addon_registration_blender.py')
exec(compile(fixture.read_text().split('floor = importlib.import_module')[0], str(fixture), 'exec'))
vp = importlib.import_module(MODULE + '.source.extras.smash_viewport')

setter = Mock(return_value=0)
scene = SimpleNamespace(sub_scene_properties=SimpleNamespace(smash_vp_lightweight=False))
with patch.object(vp, '_lib', SimpleNamespace(ssbh_preview_set_lightweight=setter)), patch.object(vp, '_applied_lightweight', None):
    assert vp._apply_performance_settings(1, scene)
    assert not vp._apply_performance_settings(1, scene)
    scene.sub_scene_properties.smash_vp_lightweight = True
    assert vp._apply_performance_settings(1, scene)
    assert not vp._apply_performance_settings(1, scene)
    scene.sub_scene_properties.smash_vp_lightweight = False
    assert vp._apply_performance_settings(1, scene)
    assert [call.args for call in setter.call_args_list] == [(1, 0), (1, 1), (1, 0)]
with patch.object(vp, '_lib', SimpleNamespace()):
    assert not vp._apply_performance_settings(1, scene)
with patch.object(vp, '_lib', SimpleNamespace(ssbh_preview_set_lightweight=Mock(return_value=-1))), patch.object(vp, '_native_error', return_value='failure'), patch.object(vp, '_applied_lightweight', None):
    assert not vp._apply_performance_settings(1, scene)
    assert vp._applied_lightweight is None

prepared = (1, 1920, 1080, False, None, None, False)
for shared, covered, ready in ((False, False, True), (False, True, True), (True, False, True), (True, True, True), (False, False, False)):
    with patch.object(vp, '_viewport_enabled', return_value=True), patch.object(vp, '_prepare_preview', return_value=prepared if ready else None), patch.object(vp, '_viewport_pixel_size', return_value=(1920, 1080)), patch.object(vp, '_fill_viewport_color'), patch.object(vp, '_gpu_covers_scene', return_value=covered), patch.object(vp, '_draw_blender_meshes') as draw, patch.object(vp, 'gl_present_supported', return_value=shared), patch.object(vp, '_gpu_failed', False), patch.object(vp, '_lib', SimpleNamespace(ssbh_preview_present_gl=Mock(return_value=0))), patch.object(vp, 'render_cropped', return_value=True) as cropped:
        vp._draw_smash_overlay_inner(SimpleNamespace())
        assert draw.call_count == (0 if shared and ready and covered else 1), (shared, covered, ready, draw.call_count)
        if shared and ready:
            cropped.assert_not_called()
            vp._lib.ssbh_preview_present_gl.assert_called_once_with(1, 1920, 1080, 2)
        elif ready:
            cropped.assert_called_once_with(1, 1920, 1080, False)
import numpy as np
matrices = np.eye(4, dtype=np.float32).reshape(-1)
upload = Mock(return_value=0)
with patch.object(vp, '_lib', SimpleNamespace(ssbh_preview_set_world_transforms=upload)), patch.object(vp, '_collect_smash_bones', side_effect=lambda *args: (['Hip'], matrices.copy())), patch.object(vp, '_collect_extra_bones', return_value=([], [])), patch.object(vp, '_last_bone_upload', None):
    assert vp._set_bones(1, None, None) == 0
    assert vp._set_bones(1, None, None) == 0
    assert upload.call_count == 1
    matrices[12] = 0.25
    assert vp._set_bones(1, None, None) == 0
    assert upload.call_count == 2
    vp._reset_extra_state()
    assert vp._set_bones(1, None, None) == 0
    assert upload.call_count == 3
    matrices[12] = 0.5
    upload.return_value = -1
    assert vp._set_bones(1, None, None) == -1
    upload.return_value = 0
    assert vp._set_bones(1, None, None) == 0
    assert upload.call_count == 5
print('SMASH VIEWPORT FULL-RESOLUTION PERFORMANCE REGRESSIONS PASSED')
