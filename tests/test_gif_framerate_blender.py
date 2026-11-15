from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import importlib

fixture = Path(__file__).with_name('test_addon_registration_blender.py')
exec(compile(fixture.read_text().split('addon_utils.disable(MODULE')[0], str(fixture), 'exec'))
capture = importlib.import_module(MODULE + '.source.extras.viewport_capture')
for fps, step, count, delay in ((24, 2.5, 25, 42), (30, 2, 31, 33), (60, 1, 61, 17)):
    operator = SimpleNamespace(gif_fps=str(fps), _gif_status=lambda *args: None)
    wm = SimpleNamespace(progress_begin=lambda *args: None,
                         event_timer_add=lambda *args, **kwargs: object(),
                         modal_handler_add=lambda *args: None)
    context = SimpleNamespace(scene=SimpleNamespace(frame_start=1, frame_end=61, frame_current=7),
                              window_manager=wm, window=None)
    with patch.object(capture, '_new_temp_path', return_value='unused.gif'), \
         patch.object(capture, '_new_gif_encoder', return_value=object()) as encoder:
        assert capture.SUB_OP_gif_or_photo._begin_gif(operator, context) == {'RUNNING_MODAL'}
        encoder.assert_called_once_with('unused.gif', delay_ms=delay)
        assert operator._gif_step == step
        assert operator._gif_total == count
    with patch.object(capture, 'NativeGifEncoder') as encoder:
        capture._new_gif_encoder('unused.gif', delay_ms=delay)
        encoder.assert_called_once_with('unused.gif', delay_ms=delay)
    with patch.object(capture, 'NativeGifEncoder', side_effect=RuntimeError('unavailable')), \
         patch.object(capture, 'PillowGifEncoder') as encoder:
        capture._new_gif_encoder('unused.gif', delay_ms=delay)
        encoder.assert_called_once_with('unused.gif', delay_ms=delay)
print('GIF framerate selection and encoder tests passed (24/30/60)')
