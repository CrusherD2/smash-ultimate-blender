from pathlib import Path

fixture = Path(__file__).with_name('test_rig_import_matching_blender.py')
exec(compile(fixture.read_text(encoding='utf-8-sig').split('with tempfile.TemporaryDirectory() as folder:')[0], str(fixture), 'exec'))
assert not rig.armature_has_animation_rig(obj)
with tempfile.TemporaryDirectory() as folder:
    path = str(Path(folder) / 'isolated.nuanmb')
    export.export_model_anim_fast(bpy.context, SimpleNamespace(report=lambda *args: None), obj, path, True, False, False, 1, 3)
    importer.import_model_anim(bpy.context, path, True, False, False, 1, obj)
    expected = snapshot()
    editor.save_on_build = False
    component('ISOLATED', 'Standalone Wing', ['WingL'])
    assert bpy.ops.sub.component_build() == {'FINISHED'}
    control = obj.pose.bones[cc.control_name(obj, editor.components[-1])]
    for mode, follow in (('OBJECT', 0.0), ('POSE', 0.6), ('OBJECT', 1.0)):
        control['follows_parent_bone'] = follow
        control.location = (5.0, -3.0, 2.0)
        bpy.ops.object.mode_set(mode=mode)
        importer.import_model_anim(bpy.context, path, True, False, False, 1, obj)
        assert obj.mode == mode
        assert obj.animation_data.action.get('sub_rig_import_matched')
        actual = snapshot()
        for frame, poses in expected.items():
            wanted = poses['WingL']
            error = max(abs(actual[frame]['WingL'][r][k] - wanted[r][k]) for r in range(4) for k in range(4))
            assert error < 3e-4, (mode, follow, frame, error)
        follow_path = control.path_from_id() + '["follows_parent_bone"]'
        fc = next(fc for fc in curves.get_all_action_fcurves(obj.animation_data.action) if fc.data_path == follow_path)
        assert len(fc.keyframe_points) == 3
        assert all(abs(key.co.y) < 1e-7 for key in fc.keyframe_points)
print('STANDALONE ISOLATED IMPORT: OBJECT/POSE AND ALL FOLLOW STATES PASSED')
