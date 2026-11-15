from pathlib import Path
import importlib
import json

fixture = Path(__file__).with_name('test_addon_registration_blender.py')
exec(compile(fixture.read_text().split('addon_utils.disable(MODULE')[0], str(fixture), 'exec'))
face = importlib.import_module(MODULE + '.source.extras.face_picker')
flip = importlib.import_module(MODULE + '.source.extras.anim_flip')
compat = importlib.import_module(MODULE + '.source.blender_compat')
bpy.ops.object.armature_add()
obj = bpy.context.object
bpy.ops.object.mode_set(mode='EDIT')
obj.data.edit_bones[0].name = 'Jaw'
bone = obj.data.edit_bones.new('Other')
bone.head = (1, 0, 0)
bone.tail = (1, 1, 0)
bpy.ops.object.mode_set(mode='POSE')
picker = face.get_picker(obj)
expr = picker.expressions.add()
expr.expression_id = 'jaw-pose'
expr.mode = face.EXPRESSION_MODE_BONE
expr.bone_pose_json = json.dumps(flip.smash_pose_data_from_armature(obj))
pose = json.loads(expr.bone_pose_json)
expr.bone_pose_json = json.dumps({'Jaw': pose['Jaw']})
for bone in obj.pose.bones:
    compat.set_pose_bone_select(bone, bone.name == 'Other')
picker.insert_keyframes = True
assert face.apply_bone_expression(bpy.context, obj, expr, True)[0] == 1
assert compat.is_pose_bone_selected(obj.pose.bones['Other']) and not compat.is_pose_bone_selected(obj.pose.bones['Jaw'])
picker.select_affected_bones = True
assert face.apply_bone_expression(bpy.context, obj, expr, True)[0] == 1
assert {b.name for b in obj.pose.bones if compat.is_pose_bone_selected(b)} == {'Jaw'}
assert obj.data.bones.active.name == 'Jaw'
assert obj.animation_data.action is not None
# Selection also works with keyframing off, without adding animation data.
obj.animation_data_clear()
bpy.context.scene.tool_settings.use_keyframe_insert_auto = False
picker.insert_keyframes = False
face.apply_bone_expression(bpy.context, obj, expr, False)
assert obj.animation_data is None
assert {b.name for b in obj.pose.bones if compat.is_pose_bone_selected(b)} == {'Jaw'}
print('Face picker affected bone selection tests passed')
