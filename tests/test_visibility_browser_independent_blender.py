from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

fixture = Path(__file__).with_name('test_addon_registration_blender.py')
exec(compile(fixture.read_text().split('floor = importlib.import_module')[0], str(fixture), 'exec'))
imp = importlib.import_module(MODULE + '.source.anim.import_anim')
ssp = bpy.context.scene.sub_scene_properties
visibility = ssp.visibility_animation_browser
with TemporaryDirectory() as folder:
    root = Path(folder)
    normal = root / 'normal'
    layers = root / 'layers'
    for directory in (normal, layers):
        directory.mkdir()
        (directory / 'test.nuanmb').touch()
    imp.fill_animation_import_list(ssp, str(normal))
    ssp.animation_import_files[0].selected = True
    with patch.object(imp, 'sync_anim_importer_to_active', side_effect=AssertionError('synced importer')), \
         patch.object(imp, 'bind_anim_folder_to_armature', side_effect=AssertionError('bound importer')):
        assert bpy.ops.sub.ssbh_animation_folder_selector(directory=str(layers), visibility=True) == {'FINISHED'}
        assert bpy.ops.sub.switch_animation_folder(folder=str(layers), visibility=True) == {'FINISHED'}
    assert ssp.animation_import_folder_path == str(normal)
    assert len(ssp.animation_import_folders) == 1
    assert ssp.animation_import_files[0].selected
    assert visibility.animation_import_folder_path == str(layers)
    bpy.ops.sub.select_all_animation_imports(select=False, visibility=True)
    assert ssp.animation_import_files[0].selected
    bpy.ops.sub.toggle_animation_import_selection(index=0, visibility=True)
    assert visibility.animation_import_files[0].selected
    bpy.ops.sub.select_all_animation_imports(select=False)
    assert visibility.animation_import_files[0].selected
    assert not ssp.animation_import_files[0].selected
print('VISIBILITY_BROWSER_INDEPENDENT_OK')
