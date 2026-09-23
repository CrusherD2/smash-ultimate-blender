"""Clipboard import packs pixels, places the empty, and cleans temporary files."""
from pathlib import Path
import importlib
import shutil
import tempfile
from unittest.mock import patch
fixture = Path(__file__).with_name('test_addon_registration_blender.py')
exec(compile(fixture.read_text().split('addon_utils.disable(MODULE')[0], str(fixture), 'exec'))
clipboard = importlib.import_module(MODULE + '.source.extras.clipboard_image')
with tempfile.TemporaryDirectory() as directory:
    source = Path(directory) / 'source.png'
    image = bpy.data.images.new('source', width=2, height=2, alpha=True)
    image.pixels[:] = [1, 0, 0, 1] * 4
    image.filepath_raw = str(source)
    image.file_format = 'PNG'
    image.save()
    bpy.data.images.remove(image)
    if clipboard.sys.platform == 'win32':
        # Exercise the real PowerShell/.NET PNG encoder with a synthetic bitmap.
        # Only the clipboard read is substituted; no system clipboard mutation.
        run = clipboard.subprocess.run
        def synthetic_bitmap(command, **kwargs):
            command = list(command)
            command[-1] = command[-1].replace(
                '[System.Windows.Forms.Clipboard]::GetImage()',
                '[System.Drawing.Bitmap]::new(2, 2)')
            return run(command, **kwargs)
        native_path = Path(directory) / 'native.png'
        with patch.object(clipboard.subprocess, 'run', synthetic_bitmap):
            clipboard._clipboard_bitmap(native_path)
        assert native_path.read_bytes().startswith(b'\x89PNG\r\n\x1a\n')
    paths = []
    def capture(path):
        paths.append(path)
        shutil.copyfile(source, path)
    # Stand in for the OS clipboard, leaving the user's clipboard untouched.
    from types import SimpleNamespace
    context = SimpleNamespace(window_manager=SimpleNamespace(clipboard=''))
    with patch.object(clipboard, '_clipboard_bitmap', capture):
        image = clipboard.load_clipboard_image(context)
    assert image.packed_file and tuple(image.size) == (2, 2)
    assert not paths[0].exists()
    bpy.context.scene.cursor.location = (1, 2, 3)
    with patch.object(clipboard, 'load_clipboard_image', return_value=image):
        assert bpy.ops.sub.image_from_clipboard() == {'FINISHED'}
    obj = bpy.context.object
    assert obj.type == 'EMPTY' and obj.empty_display_type == 'IMAGE'
    assert obj.data == image and tuple(obj.location) == (1, 2, 3)
    context.window_manager.clipboard = str(source)
    copied = clipboard.load_clipboard_image(context)
    assert copied.packed_file and tuple(copied.size) == (2, 2)
    count = len(bpy.data.objects)
    operator = SimpleNamespace(report=lambda *args: None)
    with patch.object(clipboard, 'load_clipboard_image', side_effect=RuntimeError('Empty clipboard')):
        assert clipboard.SUB_OP_image_from_clipboard.execute(operator, bpy.context) == {'CANCELLED'}
    assert len(bpy.data.objects) == count
addon_utils.disable(MODULE, default_set=False, handle_error=on_error)
assert not errors, errors
print('CLIPBOARD IMAGE PASSED')
