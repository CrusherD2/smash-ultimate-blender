from contextlib import nullcontext
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

fixture = Path(__file__).with_name('test_addon_registration_blender.py')
exec(compile(fixture.read_text().split('floor = importlib.import_module')[0], str(fixture), 'exec'))
face = importlib.import_module(MODULE + '.source.extras.face_picker')
capture = importlib.import_module(MODULE + '.source.extras.viewport_capture')
space = SimpleNamespace(region_3d=SimpleNamespace(view_perspective='PERSP'),
                        overlay=SimpleNamespace(show_overlays=True), show_gizmo=True)
area = SimpleNamespace(spaces=SimpleNamespace(active=space))
context = SimpleNamespace(scene=bpy.context.scene, window=None,
                          temp_override=lambda **kwargs: nullcontext())
with TemporaryDirectory() as folder:
    path = Path(folder) / 'thumbnail.png'
    def render(**kwargs):
        assert not space.overlay.show_overlays
        assert not space.show_gizmo
        path.write_bytes(b'test')
    with patch.object(face, 'get_picker', return_value=None), \
         patch.object(face, 'find_view3d', return_value=(area, object())), \
         patch.object(capture, '_should_use_smash_capture', return_value=False), \
         patch.object(face.bpy, 'ops', SimpleNamespace(render=SimpleNamespace(opengl=render))):
        face.capture_thumbnail(context, None, path, 32)
        assert space.overlay.show_overlays and space.show_gizmo
        path.unlink()
        def fail(**kwargs):
            render(**kwargs)
            raise RuntimeError('capture failed')
        with patch.object(face.bpy.ops.render, 'opengl', fail):
            try:
                face.capture_thumbnail(context, None, path, 32)
            except RuntimeError as error:
                assert str(error) == 'capture failed'
            else:
                raise AssertionError('Expected capture failure')
        assert space.overlay.show_overlays and space.show_gizmo
print('FACE_PICKER_CAPTURE_OVERLAYS_OK')
