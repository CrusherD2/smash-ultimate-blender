from pathlib import Path
fixture=Path(__file__).with_name('test_rig_import_matching_blender.py')
exec(compile(fixture.read_text(encoding='utf-8-sig').split('with tempfile.TemporaryDirectory()')[0],str(fixture),'exec'))
expected=snapshot()
bpy.context.scene.sub_scene_properties.clean_keyframes_after_rig=False
assert bpy.ops.sub.create_animation_rig(setup_ik=False,setup_eye_look=False,setup_finger_sliders=True,setup_custom_components=False)=={'FINISHED'}
def check():
    actual=snapshot()
    for f,poses in expected.items():
        for n,wanted in poses.items():
            assert max(abs(actual[f][n][i][j]-wanted[i][j]) for i in range(4) for j in range(4))<3e-4,(f,n)
    tracks=curves.get_all_action_fcurves(obj.animation_data.action)
    assert any(fingers.is_finger_control_bone(fc.data_path.split('"')[1]) and any(abs(k.co.y)>.0001 for k in fc.keyframe_points) for fc in tracks if 'pose.bones["' in fc.data_path and fc.data_path.endswith('location'))
check()
# Rematch a fresh original action through the new visible operator.
fingers.remove_finger_sliders(bpy.context,obj)
for f in range(1,4):
    scene.frame_set(f)
    for i,name in enumerate(names):
        pb=obj.pose.bones[name]
        pb.rotation_mode='XYZ'
        pb.rotation_euler=(f*.04*(i+1),0,f*.01)
        pb.location=(f*.08,0,0) if name in {'Trans','WingL'} else (0,0,0)
        pb.keyframe_insert('rotation_euler',frame=f)
        pb.keyframe_insert('location',frame=f)
assert bpy.ops.sub.anim_rig_add_fingers()=={'FINISHED'}
check()
assert bpy.ops.sub.anim_rig_match_fingers.poll()
print('RIG CREATION AND EXPLICIT FINGER MATCH PASSED')

