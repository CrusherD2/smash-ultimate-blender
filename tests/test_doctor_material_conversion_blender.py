"""A model whose materials are plain Blender ones must still export.

Run with Blender --background --factory-startup --python-exit-code 1 --python this_file.
"""
from pathlib import Path
import importlib

fixture = Path(__file__).with_name('test_addon_registration_blender.py')
exec(compile(fixture.read_text().split('addon_utils.disable(MODULE')[0], str(fixture), 'exec'))

core = importlib.import_module(MODULE + '.source.doctor.core')
doctor_ui = importlib.import_module(MODULE + '.source.doctor.ui')


class Reporter:
    """Stands in for the export operator preflight reports through."""

    def __init__(self):
        self.lines = []

    def report(self, level, message):
        self.lines.append((sorted(level)[0], message))


def build_model(material_name):
    bpy.ops.object.armature_add()
    armature = bpy.context.object
    bpy.ops.mesh.primitive_cube_add()
    mesh = bpy.context.object
    mesh.parent = armature
    mesh.location = (1, 2, 3)          # an unapplied transform, fixed as well
    material = bpy.data.materials.new(material_name)
    material.use_nodes = True
    mesh.data.materials.append(material)
    mesh.vertex_groups.new(name='Bone')
    mesh.modifiers.new('Armature', 'ARMATURE').object = armature
    bpy.context.scene.sub_scene_properties.model_export_arma = armature
    bpy.context.view_layer.objects.active = armature
    bpy.context.view_layer.update()    # matrix_local is stale until this runs
    return armature, mesh, material


def shader_label(material):
    return getattr(getattr(material, 'sub_matl_data', None), 'shader_label', '')


def blockers(results):
    return [result.message for result in core.blocking_results(results)]


armature, mesh, material = build_model('PlainBlenderMat')

results = core.run_checks(bpy.context, (core.SCOPE_MODEL,))
missing = [r for r in results if r.check_id == 'missing_materials']
assert len(missing) == 1 and missing[0].blocking, missing
assert missing[0].fix_id == 'convert_blender_material' and missing[0].fixable
assert missing[0].fix_is_safe, 'the shader blocker has to be part of Fix Safe Issues'
assert blockers(results), 'the plain material should block before anything is fixed'

# "Fix Safe Issues" has to leave nothing blocking behind: converting the
# material also renames the mesh attributes the exporter rejects.
state = bpy.context.scene.sub_doctor
doctor_ui.store_results(state, results, 'MODEL')
assert bpy.ops.sub.doctor_fix_safe() == {'FINISHED'}
assert shader_label(material), 'the material kept no Smash shader label'
assert [layer.name for layer in mesh.data.uv_layers] == ['map1']
assert tuple(mesh.location) == (0.0, 0.0, 0.0), 'the safe transform fix ran too'
assert not blockers(core.run_checks(bpy.context, (core.SCOPE_MODEL,)))

# A model export must convert rather than stop, and say that it did.
second = bpy.data.materials.new('SecondPlainMat')
second.use_nodes = True
mesh.data.materials.append(second)
assert blockers(core.run_checks(bpy.context, (core.SCOPE_MODEL,)))

reporter = Reporter()
assert state.auto_convert_materials, 'converting on export is the default'
assert doctor_ui.preflight(bpy.context, reporter, 'MODEL') is True
assert shader_label(second), 'the export left a material unconverted'
assert any('converted 1 material' in message for _level, message in reporter.lines), reporter.lines

# With the setting off, the same model stops the export as before.
third = bpy.data.materials.new('ThirdPlainMat')
third.use_nodes = True
mesh.data.materials.append(third)
state.auto_convert_materials = False
reporter = Reporter()
assert doctor_ui.preflight(bpy.context, reporter, 'MODEL') is False
assert not shader_label(third)
state.auto_convert_materials = True

# Converting a material that already has a Smash shader is a no-op, not an error.
result = next(r for r in core.run_checks(bpy.context, (core.SCOPE_MODEL,))
              if r.check_id == 'missing_materials')
ok, message = core.run_fix(bpy.context, result)
assert ok and shader_label(third), message
ok, message = core.run_fix(bpy.context, result)
assert ok and 'already' in message, message

addon_utils.disable(MODULE, default_set=False, handle_error=on_error)
assert not errors, errors
print('DOCTOR MATERIAL CONVERSION PASSED')
profile.cleanup()
