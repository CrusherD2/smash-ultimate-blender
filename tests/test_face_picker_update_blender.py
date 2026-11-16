from pathlib import Path
from unittest.mock import patch
import importlib

fixture = Path(__file__).with_name('test_addon_registration_blender.py')
exec(compile(fixture.read_text().split('addon_utils.disable(MODULE')[0], str(fixture), 'exec'))
face = importlib.import_module(MODULE + '.source.extras.face_picker')
data = bpy.data.armatures.new('UpdateTest')
arma = bpy.data.objects.new('UpdateTest', data)
bpy.context.collection.objects.link(arma)
bpy.context.view_layer.objects.active = arma
arma.select_set(True)
picker = face.get_picker(arma)
sap = face.get_sap(arma)
for name in ('FaceA', 'FaceB'):
    sap.vis_track_entries.add().name = name
expr = picker.expressions.add()
expr.expression_id, expr.name = 'original', 'Original'
face.set_expression_vis_data(expr, ['FaceA'])
image = bpy.data.images.new('Original thumbnail', width=8, height=8)
expr.image, expr.image_path = image, 'original.png'
other = picker.expressions.add()
other.expression_id, other.name = 'other', 'Other'
face.set_expression_vis_data(other, ['FaceB'])
picker.active_expression_index = 0
assert bpy.ops.sub.face_picker_load_selected() == {'FINISHED'}
assert picker.updating_expression_id == 'original'
assert picker.new_expression_name == 'Original'
assert face.selected_track_names(picker) == ['FaceA']
# Selecting another saved expression must not retarget the pending update.
picker.active_expression_index = 1
for item in picker.track_choices:
    item.selected = item.name == 'FaceB'
picker.new_expression_name = 'Updated'
with patch.object(face, 'capture_expression_thumbnail', side_effect=AssertionError('Unexpected capture')):
    assert bpy.ops.sub.face_picker_add() == {'FINISHED'}
assert len(picker.expressions) == 2
assert expr.expression_id == 'original' and expr.name == 'Updated'
assert [track.name for track in expr.tracks] == ['FaceB']
assert expr.image == image and expr.image_path == 'original.png'
assert other.name == 'Other'
assert picker.updating_expression_id == ''
assert picker.active_expression_index == 0
# Optional thumbnail replacement happens only on finishing.
assert bpy.ops.sub.face_picker_load_selected() == {'FINISHED'}
picker.update_thumbnail = True
replacement = bpy.data.images.new('Replacement', width=8, height=8)
with patch.object(face, 'capture_expression_thumbnail', return_value=replacement) as capture:
    assert bpy.ops.sub.face_picker_add() == {'FINISHED'}
    capture.assert_called_once()
assert expr.image == replacement and expr.image_path == ''
assert picker.updating_expression_id == '' and len(picker.expressions) == 2
# Failed validation leaves the mode and original data intact.
assert bpy.ops.sub.face_picker_load_selected() == {'FINISHED'}
for item in picker.track_choices:
    item.selected = False
try:
    result = bpy.ops.sub.face_picker_add()
except RuntimeError:
    result = {'CANCELLED'}
assert result == {'CANCELLED'}
assert picker.updating_expression_id == 'original'
assert [track.name for track in expr.tracks] == ['FaceB']
assert expr.image == replacement
print('FACE PICKER UPDATE MODE TEST PASSED')
