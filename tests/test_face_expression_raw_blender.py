from pathlib import Path
fixture=Path(__file__).with_name('test_face_components_blender.py')
exec(compile(fixture.read_text(encoding='utf-8-sig').split('# Removing face controllers')[0],str(fixture),'exec'))
raw=importlib.import_module(MODULE+'.source.anim.raw_anim')
editor.active_index=1
c=editor.components[1]
pose('NEW')
obj.pose.bones['Jaw'].location.x=.4
pose('CAPTURE','Frown')
assert set(json.loads(c.face_data)['poses'])=={'Smile','Frown'}
main=obj.pose.bones[cc.control_name(obj,c)]
for f,choice in ((1,1),(3,2)):
    main.sub_face_expression=choice
    main.location.y=1
    main.keyframe_insert('sub_face_expression',frame=f)
    main.keyframe_insert('location',frame=f)
# Key the dropdown the way the add-on keys it. component_matching writes this
# channel through PoseKeyWriter(obj, interpolation='CONSTANT') because the
# value is a discrete choice; keyframe_insert defaults to interpolating, which
# left frame 2 holding choice 1.5, matching neither pose. Both rigs then showed
# whatever their leftover unkeyed pose happened to be, so the comparison was
# measuring test setup rather than the round trip.
for fc in curves.get_all_action_fcurves(obj.animation_data.action,id_type='OBJECT'):
    if fc.data_path.endswith('.sub_face_expression'):
        for k in fc.keyframe_points:
            k.interpolation='CONSTANT'
        fc.update()
expected={}
for f in (1,2,3):
    bpy.context.scene.frame_set(f)
    expected[f]=matrix('Jaw')
with tempfile.TemporaryDirectory() as folder:
    path=str(Path(folder)/'expressions.rawanim')
    assert raw.export_raw_animation(obj,obj.animation_data.action,path,1,3)
    bpy.ops.object.mode_set(mode='OBJECT')
    data=bpy.data.armatures.new('Raw face')
    restored=bpy.data.objects.new('Raw face',data)
    bpy.context.scene.collection.objects.link(restored)
    assert raw.import_raw_animation(bpy.context,restored,path)
    for f,wanted in expected.items():
        bpy.context.scene.frame_set(f)
        bpy.context.view_layer.update()
        close(restored.pose.bones['Jaw'].matrix,wanted,'raw expression '+str(f))
print('MOUTH MULTIPLE EXPRESSIONS AND RAW DROPDOWN ROUNDTRIP PASSED')
