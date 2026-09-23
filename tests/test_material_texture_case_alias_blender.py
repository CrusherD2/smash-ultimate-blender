"""Case-only MATL texture aliases should share one imported image.

Run with Blender --background --factory-startup --python-exit-code 1 --python this_file.
"""
from pathlib import Path
from types import SimpleNamespace
import importlib


fixture = Path(__file__).with_name('test_addon_registration_blender.py')
exec(compile(fixture.read_text().split('addon_utils.disable(MODULE')[0], str(fixture), 'exec'))

materials = importlib.import_module(
    MODULE + '.source.model.material.create_blender_materials_from_matl'
)

model_dir = Path(profile.name)
(model_dir / 'eyeW_sonic_001_prm.nutexb').write_bytes(b'fixture')
conversion_calls = []
original_convert = materials._convert_nutexb_files


def fake_convert(conversions):
    conversion_calls.extend(conversions)
    for _texture_name, _nutexb_path, png_path in conversions:
        fixture_image = bpy.data.images.new('case_alias_fixture', 1, 1)
        fixture_image.filepath_raw = str(png_path)
        fixture_image.file_format = 'PNG'
        fixture_image.save()
        bpy.data.images.remove(fixture_image)
    return {}


materials._convert_nutexb_files = fake_convert
try:
    matl = SimpleNamespace(entries=[
        SimpleNamespace(textures=[
            SimpleNamespace(data='eyeW_sonic_001_prm'),
            SimpleNamespace(data='eyew_sonic_001_prm'),
        ])
    ])
    images = materials.import_material_images(SimpleNamespace(), matl, model_dir)
finally:
    materials._convert_nutexb_files = original_convert

assert len(conversion_calls) == 1, conversion_calls
assert conversion_calls[0][0] == 'eyeW_sonic_001_prm'
assert images['eyeW_sonic_001_prm'] is images['eyew_sonic_001_prm']
assert images['eyeW_sonic_001_prm'].packed_file is not None
assert not (model_dir / 'eyeW_sonic_001_prm_temp.png').exists()

addon_utils.disable(MODULE, default_set=False, handle_error=on_error)
assert not errors, errors
print('MATERIAL TEXTURE CASE ALIAS PASSED')
profile.cleanup()
