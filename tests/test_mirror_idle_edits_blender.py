from pathlib import Path
fixture=Path(__file__).with_name('test_export_scope_custom_mirror_blender.py')
exec(compile(fixture.read_text(encoding='utf-8').split("for frame in (1,5,9):")[0],str(fixture),'exec'))
import json
idle=importlib.import_module(MODULE+'.source.extras.idle_pose_library')
bpy.ops.object.mode_set(mode='EDIT')
for name in ('LegCL','LegCR','ClavicleCL','ClavicleCR','LegC','ClavicleC'):
    b=obj.data.edit_bones.new(name)
    b.head=(0,0,1)
    b.tail=(0,0,2)
bpy.ops.object.mode_set(mode='POSE')
scene=bpy.context.scene
scene.frame_set(1)
pose={n:{'translation':[.3,.7,.2],'rotation':[0,0,0,1],'scale':[1,1,1]} for n in obj.pose.bones.keys()}
# LegC / ClavicleC are skipped unconditionally: the engine rejects keys there.
assert all(idle.is_engine_fixed_bone(n) for n in ('LegC', 'ClavicleC', 'LegCL', 'ClavicleCR'))
assert not idle.is_engine_fixed_bone('LegL')
result,message=idle.apply_pose_with_options(bpy.context,json.dumps(pose))
assert result=={'FINISHED'},message
curves=importlib.import_module(MODULE+'.source.anim.fcurve_compat')
action=obj.animation_data.action
assert not any('LegC' in fc.data_path or 'ClavicleC' in fc.data_path for fc in curves.get_all_action_fcurves(action))
# A deliberately stale imported cache must never replace a changed idle pose.
flip.store_smash_pose_cache(action, {'1': {'Trans': {'translation':[99,99,99], 'rotation':[0,0,0,1], 'scale':[1,1,1]}}})
live=flip.smash_pose_data_from_armature(obj)
expected=flip.mirror_smash_pose_data(live)
flip.apply_smash_node_to_bone(obj.pose.bones['Trans'],expected['Trans'])
bpy.context.view_layer.update()
wanted=obj.pose.bones['Trans'].matrix.copy()
scene.frame_set(2)
scene.frame_set(1)
mirror.mirror_action_smash_y(action,context=bpy.context,only_active_frame=True,include_fingers=True)
bpy.context.view_layer.update()
actual=obj.pose.bones['Trans'].matrix
assert max(abs(actual[i][j]-wanted[i][j]) for i in range(4) for j in range(4))<1e-5
# There is no opt-out any more: re-applying still leaves the fixed bones alone.
assert not hasattr(ssp,'idle_pose_exclude_fixed_bones')
result,message=idle.apply_pose_with_options(bpy.context,json.dumps(pose))
assert result=={'FINISHED'},message
assert not any('LegC' in fc.data_path or 'ClavicleC' in fc.data_path
               for fc in curves.get_all_action_fcurves(action))
print('LIVE EDIT MIRROR AND IDLE FIXED-BONE EXCLUSION PASSED')
