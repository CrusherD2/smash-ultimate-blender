from pathlib import Path
import importlib

fixture = Path(__file__).with_name('test_addon_registration_blender.py')
exec(compile(fixture.read_text().split('addon_utils.disable(MODULE')[0], str(fixture), 'exec'))
face = importlib.import_module(MODULE + '.source.extras.face_picker')
bpy.ops.object.armature_add()
arma = bpy.context.object
picker = face.get_picker(arma)
picker.insert_keyframes = False
sap = face.get_sap(arma)
for name in ('baseform_FaceN', 'baseform_Raging', 'baseform_Angry', 'baseform_Blink'):
    sap.vis_track_entries.add().name = name
    expr = picker.expressions.add()
    expr.expression_id, expr.name = name, name
    face.set_expression_vis_data(expr, [name])
for expr in (picker.expressions[1], picker.expressions[2], picker.expressions[3], picker.expressions[0]):
    face.apply_vis_expression(bpy.context, arma, expr)
    assert [entry.name for entry in sap.vis_track_entries if entry.value] == [expr.name]
# A full setup containing an eye mesh must not become a partial eye expression.
for name in ('Angry', 'AngryEye'):
    sap.vis_track_entries.add().name = name
mixed = picker.expressions.add()
mixed.expression_id = 'mixed'
face.set_expression_vis_data(mixed, ['Angry', 'AngryEye'])
face.apply_vis_expression(bpy.context, arma, mixed)
assert {entry.name for entry in sap.vis_track_entries if entry.value} == {'Angry', 'AngryEye'}
# Truly isolated mouth/eye expressions still combine without clearing each other.
for name in ('HappyMouth', 'SadMouth', 'OpenEye', 'ClosedEye'):
    sap.vis_track_entries.add().name = name
    expr = picker.expressions.add()
    expr.expression_id, expr.name = name, name
    face.set_expression_vis_data(expr, [name])
face.apply_vis_expression(bpy.context, arma, picker.expressions[-4])
face.apply_vis_expression(bpy.context, arma, picker.expressions[-2])
face.apply_vis_expression(bpy.context, arma, picker.expressions[-3])
assert face.vis_entry_by_name(sap, 'SadMouth').value
assert face.vis_entry_by_name(sap, 'OpenEye').value
assert not face.vis_entry_by_name(sap, 'HappyMouth').value
print('FULL ANGRY/BLINK EXCLUSIVITY AND PARTIAL EXPRESSION TEST PASSED')
