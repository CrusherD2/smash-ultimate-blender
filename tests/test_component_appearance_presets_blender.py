"""Portable appearance edits, autosave and progressive editor regression."""

from pathlib import Path

fixture = Path(__file__).with_name('test_custom_components_blender.py')
exec(
    compile(
        fixture.read_text(encoding='utf-8').split('components = [')[0],
        str(fixture),
        'exec',
    )
)
workflow = importlib.import_module(MODULE + '.source.extras.component_workflow')
appearance = importlib.import_module(
    MODULE + '.source.extras.component_appearance_presets'
)
compat = importlib.import_module(MODULE + '.source.blender_compat')
component('ISOLATED', 'Feet', ['LidUpper', 'LidLower'])
assert bpy.ops.sub.component_build() == {'FINISHED'}
names = [p.name for p in obj.pose.bones if p.bone.get('sub_component_control')]
name = next(n for n in names if n != cc.control_name(obj, editor.components[0]))
for p in obj.pose.bones:
    compat.set_pose_bone_select(p, p.name == name)
obj.data.bones.active = obj.data.bones[name]
pb = obj.pose.bones[name]
bpy.context.scene.sub_control_shape = 'diamond'
bpy.context.scene.sub_control_size = 2.25
assert bpy.ops.sub.control_shape(action='APPLY') == {'FINISHED'}
path = cc.preset_dir() / (bpy.path.clean_name(editor.preset_name) + '.json')
payload = json.loads(path.read_text(encoding='utf-8'))
assert payload['appearances'][name]['scale'] == [2.25] * 3
# UI-style direct RNA changes are captured by the debounced notification path.
pb.custom_shape_translation = (0.3, 0.2, 0.1)
pb.custom_shape_rotation_euler = (0.4, 0.1, -0.2)
for w in bpy.context.window_manager.windows:
    w.screen['sub_components_window'] = True
appearance._changed()
appearance._flush()
payload = json.loads(path.read_text(encoding='utf-8'))
assert abs(payload['appearances'][name]['offset'][0] - 0.3) < 1e-6
assert abs(payload['appearances'][name]['rotation'][0] - 0.4) < 1e-6
# Functional changes and actual edited mesh vertices must also be portable.
assert bpy.ops.sub.control_shape(action='FUNCTIONAL') == {'FINISHED'}
expected_matrix = pb.bone.matrix_local.copy()
assert bpy.ops.sub.control_shape(action='EDIT') == {'FINISHED'}
widget = bpy.context.scene.sub_shape_edit_object
widget_name = widget.name
import bmesh

bm = bmesh.from_edit_mesh(widget.data)
bm.verts.ensure_lookup_table()
bm.verts[0].co.x += 0.371
bmesh.update_edit_mesh(widget.data)
assert bpy.ops.sub.control_shape(action='FINISH') == {'FINISHED'}
expected_vertices = [list(v.co) for v in pb.custom_shape.data.vertices]
payload = json.loads(path.read_text(encoding='utf-8'))
assert payload['appearances'][name]['vertices'] == expected_vertices
assert payload['appearances'][name]['adjustment'] is not None
# Remove the built controls and the edited widget object to force reconstruction.
cc.remove_component(bpy.context, obj, editor.components[0])
bpy.data.objects.remove(bpy.data.objects[widget_name], do_unlink=True)
obj['sub_custom_components'] = '[]'
workflow.build_preset(bpy.context, obj, path.name)
pb = obj.pose.bones[name]
assert [list(v.co) for v in pb.custom_shape.data.vertices] == expected_vertices
assert tuple(pb.custom_shape_scale_xyz) == (2.25,) * 3
assert (
    max(
        abs(pb.bone.matrix_local[i][j] - expected_matrix[i][j])
        for i in range(4)
        for j in range(4)
    )
    < 1e-5
)
cc.build_component(bpy.context, obj, editor.components[0])
assert (
    max(
        abs(pb.bone.matrix_local[i][j] - expected_matrix[i][j])
        for i in range(4)
        for j in range(4)
    )
    < 1e-5
)
# Explicit Save works even when auto-save is disabled.
editor.auto_save_appearance = False
for p in obj.pose.bones:
    compat.set_pose_bone_select(p, p.name == name)
obj.data.bones.active = obj.data.bones[name]
pb.custom_shape_scale_xyz = (1.75,) * 3
assert bpy.ops.sub.control_shape(action='SAVE') == {'FINISHED'}
assert (
    json.loads(path.read_text(encoding='utf-8'))['appearances'][name]['scale']
    == [1.75] * 3
)
editor.auto_save_appearance = True
# Older presets without appearance snapshots remain valid.
legacy = json.loads(json.dumps(payload))
legacy.pop('appearances')
cc.validate_preset(legacy)
# Each page is independently drawable; destructive rig buttons are absent.
from types import SimpleNamespace


class Layout:
    def __init__(self):
        self.operations = []

    def panel(self, *a, **kw):
        return self, self

    def __getattr__(self, n):
        if n in {'prop', 'prop_search'}:
            return lambda owner, field, *a, **kw: getattr(owner, field)
        if n == 'operator':

            def op(name, *a, **kw):
                self.operations.append(name)
                return SimpleNamespace()

            return op
        return lambda *a, **kw: self


editor.show_placement = editor.show_appearance = editor.show_pose_manage = True
for page in ('BONES', 'CONTROLS', 'ANIMATE'):
    editor.page = page
    layout = Layout()
    cc.draw_editor(layout, bpy.context)
    assert 'sub.components_bake_remove' not in layout.operations
    assert 'sub.component_remove' not in layout.operations
# Building only the active component does not require unfinished entries.
component('JAW', 'Not assigned yet', [])
editor.active_index = 0
assert bpy.ops.sub.component_build(active_only=True, advance=True) == {'FINISHED'}
assert editor.page == 'ANIMATE'
print('PORTABLE APPEARANCE AUTOSAVE AND PROGRESSIVE UI PASSED')
