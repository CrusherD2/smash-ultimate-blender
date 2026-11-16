from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import Mock, patch
import importlib

fixture = Path(__file__).with_name('test_addon_registration_blender.py')
exec(compile(fixture.read_text().split('addon_utils.disable(MODULE')[0], str(fixture), 'exec'))
face = importlib.import_module(MODULE + '.source.extras.face_picker')
# Owned windows follow their owner on minimize, without global TOPMOST status.
hwnd, owner = 2**40 + 100, 2**40 + 200
user32 = Mock()
user32.GetWindow.return_value = 0
user32.GetWindowLongPtrW.return_value = 8
with patch.object(face, '_win32_user32', return_value=user32), \
     patch.object(face, '_hwnd_is_valid', return_value=True):
    assert face._set_hwnd_owner(hwnd, owner)
user32.SetWindowLongPtrW.assert_called_once_with(hwnd, -8, owner)
args = user32.SetWindowPos.call_args.args
assert args[0].value == hwnd
assert args[1].value == face.ctypes.c_void_p(-2).value
assert args[-1] & face._SWP_NOACTIVATE
# The maintenance timer must not keep rearranging an already-owned window.
user32.reset_mock()
user32.GetWindow.return_value = owner
user32.GetWindowLongPtrW.return_value = 0
with patch.object(face, '_win32_user32', return_value=user32), \
     patch.object(face, '_hwnd_is_valid', return_value=True):
    assert face._set_hwnd_owner(hwnd, owner)
user32.SetWindowLongPtrW.assert_not_called()
user32.SetWindowPos.assert_not_called()
# Focus changes only follow a picker click, never activation of another app.
user32.GetForegroundWindow.return_value = hwnd
with patch.object(face, '_win32_user32', return_value=user32), \
     patch.object(face, 'find_face_picker_window', return_value=NS()), \
     patch.object(face, '_hwnd_from_screen', return_value=hwnd), \
     patch.object(face, '_hwnd_is_valid', return_value=True):
    face._focus_picker_owner(NS())
    assert user32.SetForegroundWindow.call_args.args[0].value == owner
    user32.SetForegroundWindow.reset_mock()
    user32.GetForegroundWindow.return_value = 999
    face._focus_picker_owner(NS())
    user32.SetForegroundWindow.assert_not_called()
# Space uses the main viewport, not the picker's Image Editor keymap.
region = NS(type='WINDOW')
area = NS(type='VIEW_3D', regions=[region])
main = NS(screen=NS(areas=[area]))
overrides = []
@contextmanager
def override(**kwargs):
    overrides.append(kwargs)
    yield
context = NS(temp_override=override)
play = Mock(return_value={'FINISHED'})
with patch.object(face, '_main_picker_window', return_value=main), \
     patch.object(face.bpy, 'ops', NS(screen=NS(animation_play=play))):
    assert face._toggle_picker_playback(context)
    play.assert_called_once()
assert overrides == [dict(window=main, area=area, region=region)]
window = NS(as_pointer=lambda: 123)
operator = NS(_generation=face._canvas_generation)
context = NS(window=window)
with patch.object(face, 'find_face_picker_window', return_value=window), \
     patch.object(face, '_toggle_picker_playback', return_value=True) as toggle:
    result = face.SUB_OP_face_picker_canvas.modal(operator, context, NS(type='SPACE', value='PRESS'))
assert result == {'RUNNING_MODAL'}
toggle.assert_called_once_with(context)
# Applying an expression restores main-window focus after applying its values.
with patch.object(face, '_canvas_armature', return_value=NS()), \
     patch.object(face, 'get_picker', return_value=NS(insert_keyframes=False)), \
     patch.object(face, 'find_expression', return_value=NS()), \
     patch.object(face, 'apply_expression') as apply, \
     patch.object(face, '_focus_picker_owner') as focus:
    assert face._apply_picker_hit(context, {'kind': 'expression', 'id': 'angry'})
    apply.assert_called_once()
    focus.assert_called_once_with(context)
print('PICKER OWNERSHIP, NON-TOPMOST, FOCUS AND SPACE PLAYBACK TEST PASSED')
