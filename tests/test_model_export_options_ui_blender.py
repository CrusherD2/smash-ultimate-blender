from pathlib import Path
from types import SimpleNamespace

fixture = Path(__file__).with_name('test_addon_registration_blender.py')
exec(compile(fixture.read_text().split('floor = importlib.import_module')[0], str(fixture), 'exec'))
export = importlib.import_module(MODULE + '.source.model.export_model')
viewport = importlib.import_module(MODULE + '.source.extras.smash_viewport')

for material_count in (0, 2):
    drawn = []
    layout = SimpleNamespace(label=lambda **kwargs: None,
                             prop=lambda obj, name: drawn.append(name))
    layout.box = lambda: layout
    export.SUB_OP_model_exporter.draw(SimpleNamespace(layout=layout, material_count=material_count), bpy.context)
    expected = {name for name in export.SUB_OP_model_exporter.__annotations__
                if name not in {'filter_glob', 'directory', 'material_count'}}
    assert set(drawn) == expected, (set(drawn), expected)
    assert len(drawn) == len(expected)

from bl_ui import properties_data_mesh
mesh = bpy.data.meshes.new('PanelTest')
obj = bpy.data.objects.new('PanelTest', mesh)
bpy.context.scene.collection.objects.link(obj)
bpy.context.view_layer.objects.active = obj
bpy.context.scene.render.engine = viewport.ENGINE_ID
panels = [properties_data_mesh.DATA_PT_vertex_groups,
          properties_data_mesh.DATA_PT_shape_keys]
for panel in panels:
    assert viewport.ENGINE_ID in panel.COMPAT_ENGINES, panel.__name__
    assert panel.poll(bpy.context), panel.__name__
viewport._patch_output_panels(False)
for panel in panels:
    assert viewport.ENGINE_ID not in panel.COMPAT_ENGINES
viewport._patch_output_panels(True)
for panel in panels:
    assert panel.poll(bpy.context)
print('MODEL_EXPORT_OPTIONS_AND_DATA_PANELS_OK')
