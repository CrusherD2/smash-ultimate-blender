"""Paste a clipboard bitmap (or copied image path) as a packed image empty."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

import bpy


def _clipboard_bitmap(destination):
    """Read the OS clipboard without changing it or requiring Python packages."""
    kwargs = dict(check=True, timeout=15, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if sys.platform == 'win32':
        # STA is required by Windows Forms. Pass the path as data, not shell code.
        script = """$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
$picture = [System.Windows.Forms.Clipboard]::GetImage()
if ($null -eq $picture) {
    $files = [System.Windows.Forms.Clipboard]::GetFileDropList()
    if ($files.Count -gt 0) { $picture = [System.Drawing.Image]::FromFile($files[0]) }
}
if ($null -eq $picture) { exit 2 }
try { $picture.Save($env:SUB_CLIPBOARD_IMAGE, [System.Drawing.Imaging.ImageFormat]::Png) }
finally { $picture.Dispose() }
"""
        env = os.environ.copy()
        env['SUB_CLIPBOARD_IMAGE'] = str(destination)
        subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-STA',
                        '-Command', script], env=env,
                       creationflags=subprocess.CREATE_NO_WINDOW, **kwargs)
    elif sys.platform == 'darwin':
        subprocess.run(['osascript', '-e', '''on run argv
set imageData to the clipboard as «class PNGf»
set outputFile to open for access POSIX file (item 1 of argv) with write permission
try
set eof outputFile to 0
write imageData to outputFile
close access outputFile
on error messageText
close access outputFile
error messageText
end try
end run''', str(destination)], **kwargs)
    else:
        if os.environ.get('WAYLAND_DISPLAY') and shutil.which('wl-paste'):
            command = ['wl-paste', '--no-newline', '--type', 'image/png']
        elif shutil.which('xclip'):
            command = ['xclip', '-selection', 'clipboard', '-t', 'image/png', '-o']
        else:
            raise RuntimeError('Clipboard images require wl-paste or xclip on Linux; you can also copy an image file path')
        result = subprocess.run(command, **kwargs)
        destination.write_bytes(result.stdout)


def load_clipboard_image(context):
    # Blender exposes clipboard text but not bitmap pixels.
    text = context.window_manager.clipboard.strip().strip('"')
    try:
        path = Path(bpy.path.abspath(text)) if text else None
        if path is not None and path.is_file():
            image = bpy.data.images.load(str(path), check_existing=False)
            try:
                image.pack()
            except Exception:
                bpy.data.images.remove(image)
                raise
            return image
    except (OSError, ValueError):
        pass
    with tempfile.TemporaryDirectory(prefix='sub_clipboard_') as directory:
        path = Path(directory) / 'Clipboard Image.png'
        _clipboard_bitmap(path)
        image = bpy.data.images.load(str(path), check_existing=False)
        try:
            image.pack()
            image.filepath = '//Clipboard Image.png'
        except Exception:
            bpy.data.images.remove(image)
            raise
        return image


class SUB_OP_image_from_clipboard(bpy.types.Operator):
    """Add the clipboard image as a packed reference at the 3D cursor"""
    bl_idname = 'sub.image_from_clipboard'
    bl_label = 'From Clipboard'
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.mode == 'OBJECT' and context.collection is not None

    def execute(self, context):
        try:
            image = load_clipboard_image(context)
        except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as exc:
            message = ('No readable image on the clipboard. Copy an image or image file path.'
                       if isinstance(exc, subprocess.CalledProcessError) else str(exc))
            self.report({'ERROR'}, message)
            return {'CANCELLED'}
        obj = None
        try:
            obj = bpy.data.objects.new('Clipboard Image', None)
            obj.empty_display_type = 'IMAGE'
            obj.data = image
            obj.empty_display_size = 5.0
            obj.location = context.scene.cursor.location
            if context.region_data is not None:
                obj.rotation_euler = context.region_data.view_rotation.to_euler()
            context.collection.objects.link(obj)
            for selected in context.selected_objects:
                selected.select_set(False)
            obj.select_set(True)
            context.view_layer.objects.active = obj
        except Exception:
            if obj is not None:
                bpy.data.objects.remove(obj, do_unlink=True)
            bpy.data.images.remove(image)
            raise
        return {'FINISHED'}


def menu_func(self, context):
    self.layout.operator(SUB_OP_image_from_clipboard.bl_idname, text='From Clipboard', icon='PASTEDOWN')


def register():
    bpy.utils.register_class(SUB_OP_image_from_clipboard)
    bpy.types.VIEW3D_MT_image_add.append(menu_func)


def unregister():
    bpy.types.VIEW3D_MT_image_add.remove(menu_func)
    bpy.utils.unregister_class(SUB_OP_image_from_clipboard)
