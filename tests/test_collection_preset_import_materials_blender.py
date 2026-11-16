from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch
import importlib
import json

fixture = Path(__file__).with_name('test_addon_registration_blender.py')
exec(compile(fixture.read_text().split('addon_utils.disable(MODULE')[0], str(fixture), 'exec'))
presets = importlib.import_module(MODULE + '.source.extras.collection_presets')
bpy.ops.object.armature_add()
arma = bpy.context.object
props = bpy.context.scene.sub_collection_presets
props.use_materials = True
props.use_armature_display = True
materials = {name: bpy.data.materials.new(name) for name in ('EyeL', 'face_base')}
meshes = []
for material in (materials['face_base'], materials['EyeL']):
    mesh = bpy.data.objects.new('goku_baseform_VIS_O_OBJShape', bpy.data.meshes.new('Mesh'))
    bpy.context.collection.objects.link(mesh)
    mesh.parent = arma
    mesh.data.materials.append(material)
    meshes.append(mesh)
# Legacy preset suffix assignments disagree with the current source mesh order.
preset = presets.build_preset('Goku', arma, bpy.context)
preset['model_folder'] = 'marth'
preset['sections'] = {
    'materials': {meshes[0].name: ['EyeL'], meshes[1].name: ['face_base']},
    'armature_display': {'show_in_front': True},
}
original = json.dumps(preset, sort_keys=True)
with TemporaryDirectory() as directory:
    path = Path(directory) / 'Goku.json'
    path.write_text(json.dumps(preset), encoding='utf-8')
    with patch.object(presets, '_library_dir', return_value=directory):
        for _ in range(2):
            arma.show_in_front = False
            presets.auto_apply_model_preset(bpy.context, arma, 'C:/fighter/marth/model/body/c80', Mock())
            assert meshes[0].data.materials[0] == materials['face_base']
            assert meshes[1].data.materials[0] == materials['EyeL']
            assert arma.show_in_front
    assert json.dumps(json.loads(path.read_text(encoding='utf-8')), sort_keys=True) == original
assert json.dumps(preset, sort_keys=True) == original
report = presets.apply_preset(preset, arma, bpy.context)
assert report['materials_applied'] == 2
assert meshes[0].data.materials[0] == materials['EyeL']
assert meshes[1].data.materials[0] == materials['face_base']
props.use_materials = False
assert presets.apply_preset(preset, arma, bpy.context)['materials_applied'] == 0
print('AUTO PRESET PRESERVES IMPORTED MATERIALS; OTHER SETTINGS, MANUAL OVERRIDES AND SAVED PRESETS UNCHANGED')
