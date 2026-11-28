from pathlib import Path
fixture = Path(__file__).with_name('test_addon_registration_blender.py')
exec(compile(fixture.read_text(encoding='utf-8').split('floor = importlib.import_module')[0], str(fixture), 'exec'))
visibility = importlib.import_module(MODULE + '.source.blender_compat')
scene = bpy.context.scene
bpy.ops.object.armature_add()
source = bpy.context.object
source.name = 'AdjustmentSource'
bpy.ops.object.mode_set(mode='EDIT')
for name in ('foot_RET', 'hand_RET', 'hidden'):
    bone = source.data.edit_bones.new(name)
    bone.head, bone.tail = (0, 0, 0), (0, 0, 1)
bpy.ops.object.mode_set(mode='OBJECT')
collection = source.data.collections.new('Retarget Bones')
for name in ('foot_RET', 'hand_RET'):
    collection.assign(source.data.bones[name])
collection.is_visible = False
visibility.set_pose_bone_hidden(source.pose.bones['hidden'], True)
bpy.ops.object.armature_add()
target = bpy.context.object
scene.expykit_bind_to = source
scene.sub_retarget_apply_to = target
assert bpy.ops.sub.retarget_adjustments() == {'FINISHED'}
assert bpy.context.object == source and source.mode == 'POSE'
assert visibility.is_pose_bone_hidden(source.pose.bones['Bone'])
assert not visibility.is_pose_bone_hidden(source.pose.bones['foot_RET']) and collection.is_visible
assert all(visibility.is_pose_bone_hidden(b) == (not b.name.endswith('_RET')) for b in source.pose.bones)
source.pose.bones['foot_RET'].location.x = 0.5
assert bpy.ops.sub.retarget_adjustments() == {'FINISHED'}
assert bpy.context.object == target
assert visibility.is_pose_bone_hidden(source.pose.bones['foot_RET'])
assert not visibility.is_pose_bone_hidden(source.pose.bones['Bone'])
assert visibility.is_pose_bone_hidden(source.pose.bones['hidden'])
assert not collection.is_visible
compat = importlib.import_module(MODULE + '.source.anim.fcurve_compat')
curves = compat.get_all_action_fcurves(source.animation_data.action)
assert curves and all('foot_RET' in curve.data_path for curve in curves)
assert not scene.get('sub_retarget_adjustments')
print('RETARGET_ADJUSTMENTS_OK')

scene.expykit_bound_source = target
scene.expykit_bound_target = source
scene.expykit_bind_is_active = True
mesh = bpy.data.objects.new('SourceModel', bpy.data.meshes.new('SourceModel'))
scene.collection.objects.link(mesh)
mesh.parent = source
assert bpy.ops.sub.retarget_toggle_bind_preview() == {'FINISHED'}
assert bpy.context.object == source and source.mode == 'POSE'
assert source.select_get() and not target.select_get() and target.hide_get()
assert bpy.ops.sub.retarget_source_meshes() == {'FINISHED'}
assert bpy.context.object == target and target.mode == 'POSE'
assert target.select_get() and not source.select_get() and not target.hide_get()
assert mesh.hide_get()
print('RETARGET_FOCUS_POSE_OK')
