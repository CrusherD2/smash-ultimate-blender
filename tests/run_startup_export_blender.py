"""Test saved-addon GUI startup and synchronous exports in a disposable profile.

Run with ordinary Python and --blender /path/to/blender. The GUI child exits
automatically; no existing Blender process or user preferences are touched.
"""
import argparse
import os
from pathlib import Path
import subprocess
import tempfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--blender', required=True)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    root = args.root.resolve()
    with tempfile.TemporaryDirectory(prefix='sub_startup_export_') as folder:
        profile = Path(folder)
        env = os.environ.copy()
        env['BLENDER_USER_RESOURCES'] = str(profile)
        for kind in ('CONFIG', 'SCRIPTS', 'EXTENSIONS', 'DATAFILES'):
            path = profile / kind.lower()
            path.mkdir()
            env['BLENDER_USER_' + kind] = str(path)
        shim = profile / 'scripts' / 'addons' / 'startup_export_test'
        shim.mkdir(parents=True)
        # Import the real add-on from its source tree, suppressing only unrelated
        # network and shared-library setup (as in the registration fixture).
        (shim / '__init__.py').write_text(f'''
from pathlib import Path
import importlib
ROOT = Path({str(root)!r})
__path__ = [str(ROOT)]
exec(compile((ROOT / '__init__.py').read_text(), str(ROOT / '__init__.py'), 'exec'))
__time__ = (ROOT / '__init__.py').stat().st_mtime
updater = importlib.import_module(__name__ + '.source.updater.version_check')
updater.check_for_newer_version = lambda: None
labels = importlib.import_module(__name__ + '.source.param_labels')
labels.ensure_param_labels = lambda: ROOT / 'ParamLabels.csv'
labels.load_param_labels = lambda: ROOT / 'ParamLabels.csv'
presets = importlib.import_module(__name__ + '.expy_kit.preset_handler')
presets.install_presets = lambda: None
''', encoding='utf-8')
        setup = profile / 'setup.py'
        setup.write_text('''
import addon_utils, bpy
addon = addon_utils.enable('startup_export_test', default_set=True)
assert addon is not None
bpy.ops.wm.save_userpref()
''', encoding='utf-8')
        result_file = profile / 'passed.txt'
        exercise = profile / 'exercise.py'
        exercise.write_text(f'''
import addon_utils, bpy, importlib, time, traceback, os
from pathlib import Path
assert addon_utils.check('startup_export_test') == (True, True)
export = importlib.import_module('startup_export_test.source.anim.export_anim')
doctor = importlib.import_module('startup_export_test.source.doctor')
doctor.preflight = lambda *args, **kwargs: True
folder = Path({str(profile)!r})
started = time.monotonic()
completed = 0

def tick():
    global completed
    try:
        assert time.monotonic() - started < 30, 'Export test timed out'
        if completed:
            assert (folder / f'camera_{{completed}}.nuanmb').is_file()
            assert bpy.context.scene.frame_current == 7
            assert bpy.context.scene.tool_settings.use_keyframe_insert_auto
        if completed == 2:
            Path({str(result_file)!r}).write_text('GUI STARTUP AND TWO SYNCHRONOUS EXPORTS PASSED')
            bpy.ops.wm.quit_blender()
            return None
        if not completed:
            bpy.ops.object.camera_add()
            obj = bpy.context.object
            for frame in (1, 30):
                obj.location.x = frame / 10
                obj.keyframe_insert('location', frame=frame)
            bpy.context.scene.frame_set(7)
            bpy.context.scene.tool_settings.use_keyframe_insert_auto = True
        completed += 1
        result = bpy.ops.sub.anim_export(filepath=str(folder / f'camera_{{completed}}.nuanmb'),
            first_blender_frame=1, last_blender_frame=30)
        assert result == {{'FINISHED'}}, result
        return 0.05
    except BaseException:
        traceback.print_exc()
        os._exit(1)

bpy.app.timers.register(tick, first_interval=1.0)
''', encoding='utf-8')
        startupinfo = None
        if os.name == 'nt':
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = 0
        for flags, script in ((['--background'], setup), ([], exercise)):
            result = subprocess.run([args.blender, *flags, '--python-exit-code', '1',
                                     '--python', str(script)], env=env, startupinfo=startupinfo,
                                    capture_output=True, text=True, encoding='utf-8',
                                    errors='replace', timeout=60)
            if result.returncode:
                print(result.stdout)
                print(result.stderr)
                raise RuntimeError(f'Blender failed with exit code {result.returncode}')
        assert result_file.is_file(), 'GUI did not finish its exports'
        print(result_file.read_text())


if __name__ == '__main__':
    main()
