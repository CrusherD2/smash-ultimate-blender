"""Drop real Smash files through the drag-and-drop operator in factory Blender.

Needs the gitignored Shy Guy fixture in .tests/benchmarks/shyguy-export/after-1.
python tests/run_blender_test.py --blender <blender.exe> tests/test_drag_drop_blender.py
"""
import importlib
import importlib.util
import os
from pathlib import Path
import sys
import tempfile

import addon_utils
import bpy

profile = tempfile.TemporaryDirectory(prefix='sub_drag_drop_test_')
for variable, leaf in (('BLENDER_USER_SCRIPTS', 'scripts'), ('BLENDER_USER_CONFIG', 'config')):
    path = Path(profile.name) / leaf
    path.mkdir()
    os.environ[variable] = str(path)

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / '.tests' / 'benchmarks' / 'shyguy-export' / 'after-1'
MODEL = FIXTURE / 'model'
ANIMS = FIXTURE / 'animations'
assert (MODEL / 'model.numdlb').is_file(), f'Missing fixture: {MODEL}'

MODULE = 'sub_drag_drop_test'
spec = importlib.util.spec_from_file_location(MODULE, ROOT / '__init__.py',
                                             submodule_search_locations=[str(ROOT)])
addon = importlib.util.module_from_spec(spec)
sys.modules[MODULE] = addon
spec.loader.exec_module(addon)
addon.__time__ = (ROOT / '__init__.py').stat().st_mtime
importlib.import_module(MODULE + '.source.updater.version_check').check_for_newer_version = lambda: None
labels = importlib.import_module(MODULE + '.source.param_labels')
labels.ensure_param_labels = lambda: ROOT / 'ParamLabels.csv'
labels.load_param_labels = lambda: ROOT / 'ParamLabels.csv'
importlib.import_module(MODULE + '.expy_kit.preset_handler').install_presets = lambda: None

errors = []
enabled = addon_utils.enable(MODULE, default_set=False,
                             handle_error=lambda _e: errors.append(__import__('traceback').format_exc()))
assert enabled is addon and not errors, '\n'.join(errors)

handler = bpy.types.FileHandler.bl_rna_get_subclass_py('SUB_FH_smash_files')
assert handler is not None and handler.bl_import_operator == 'sub.drop_import'
assert '.nuanmb' in handler.bl_file_extensions.split(';')

for obj in list(bpy.data.objects):
    bpy.data.objects.remove(obj)
scene = bpy.context.scene
scene.sub_scene_properties.auto_import_default_eyelid = False


def drop(folder, names):
    return bpy.ops.sub.drop_import('EXEC_DEFAULT', directory=str(folder),
                                   files=[{'name': name} for name in names])


def refused(folder, names, reason):
    # An ERROR report surfaces as RuntimeError when an operator is scripted.
    try:
        drop(folder, names)
    except RuntimeError as error:
        assert reason in str(error), error
        return True
    return False


# Nothing Smash-shaped: cancelled, scene untouched.
assert refused(MODEL, ['update.prc', 'shyguy.marker'], 'No Smash files')
assert not bpy.data.objects

# Animations with no armature anywhere are refused rather than guessed.
assert refused(ANIMS, ['a00wait1.nuanmb'], 'Select an armature')

# Every file of one model folder imports that model exactly once.
model_files = [name for name in os.listdir(MODEL) if name.endswith(('.numdlb', '.numshb', '.nusktb', '.numatb', '.nuhlpb'))]
assert drop(MODEL, model_files) == {'FINISHED'}
armatures = [obj for obj in bpy.data.objects if obj.type == 'ARMATURE']
assert len(armatures) == 1, [obj.name for obj in armatures]
armature = armatures[0]
assert any(obj.type == 'MESH' and obj.find_armature() == armature for obj in bpy.data.objects)

# With a mesh active, dropped motions go to the mesh's armature; the one whose
# name merely contains "light" is a fighter motion, not stage lighting.
mesh = next(obj for obj in bpy.data.objects if obj.type == 'MESH' and obj.find_armature() == armature)
bpy.ops.object.select_all(action='DESELECT')
bpy.context.view_layer.objects.active = mesh
actions_before = set(bpy.data.actions)
assert drop(ANIMS, ['a00wait2.nuanmb', 'a05landinglight.nuanmb']) == {'FINISHED'}
new_actions = {action.name for action in set(bpy.data.actions) - actions_before}
assert any('a00wait2' in name for name in new_actions), new_actions
assert any('a05landinglight' in name for name in new_actions), new_actions
assert bpy.context.view_layer.objects.active == armature
assert not any(obj.get('sub_stage_light_node') for obj in bpy.data.objects)

# The Animation browser now lists the folder the motions came from.
ssp = scene.sub_scene_properties
assert os.path.normcase(ssp.animation_import_folder_path) == os.path.normcase(str(ANIMS)), ssp.animation_import_folder_path
assert any(item.name == 'a00wait1' for item in ssp.animation_import_files)

print('drag and drop test passed')
