from pathlib import Path
fixture=Path(__file__).with_name('test_face_components_blender.py')
exec(compile(fixture.read_text(encoding='utf-8-sig').split("component('MOUTH'")[0],str(fixture),'exec'))
c=editor.components[0]
pose('NEW')
obj.pose.bones['LidUpper'].location.z=-.25
obj.pose.bones['LidLower'].location.z=.3
pose('CAPTURE','Squint')
pose('EDIT','Squint')
c.pose_strength=.5
obj.pose.bones['LidUpper'].location.z=-.25
pose('CAPTURE','Squint')
data=json.loads(c.face_data)
assert '0.5' in data['steps']['Squint']
main=obj.pose.bones[cc.control_name(obj,c)]
main.sub_face_expression=3
for strength,upper,lower in ((0,0,0),(.25,-.125,0),(.5,-.25,0),(.75,-.25,.15),(1,-.25,.3)):
    main.location.y=strength
    actual=matrix('LidUpper')
    assert abs(actual.translation.z-neutral['LidUpper'].translation.z-upper)<1e-5,(strength,actual)
    actual=matrix('LidLower')
    assert abs(actual.translation.z-neutral['LidLower'].translation.z-lower)<1e-5,(strength,actual)
# Match a frame between the checkpoint and endpoint.
matching=importlib.import_module(MODULE+'.source.extras.component_matching')
obj['sub_custom_components']=json.dumps([cc.serialize(c)])
constraints=[con for p in obj.pose.bones for con in p.constraints if con.name.startswith('SUB Component ')]
for con in constraints: con.mute=True
for n,z in (('LidUpper',-.25),('LidLower',.15)):
    pb=obj.pose.bones[n]
    pb.location.z=z
    pb.keyframe_insert('location',frame=1)
for con in constraints: con.mute=False
matching.match_animation(bpy.context,obj,1,1,match_ik=False)
bpy.context.scene.frame_set(1)
bpy.context.view_layer.update()
assert face.expression_get(main)==3,(face.expression_get(main),[(fc.data_path,[tuple(k.co) for k in fc.keyframe_points]) for fc in curves.get_all_action_fcurves(obj.animation_data.action) if 'sub_face_expression' in fc.data_path])
assert abs(main.location.y-.75)<1e-5,main.location.y
assert face.validate_data(c.face_data)['steps']==data['steps']
print('EXPRESSION CHECKPOINTS, INTERPOLATION AND MATCHING PASSED')

raw=importlib.import_module(MODULE+'.source.anim.raw_anim')
with tempfile.TemporaryDirectory() as folder:
    path=str(Path(folder)/'steps.rawanim')
    wanted={n:matrix(n) for n in ('LidUpper','LidLower')}
    assert raw.export_raw_animation(obj,obj.animation_data.action,path,1,1)
    bpy.ops.object.mode_set(mode='OBJECT')
    restored=bpy.data.objects.new('Steps restored',bpy.data.armatures.new('Steps restored'))
    bpy.context.scene.collection.objects.link(restored)
    assert raw.import_raw_animation(bpy.context,restored,path)
    bpy.context.view_layer.update()
    for n,m in wanted.items(): close(restored.pose.bones[n].matrix,m,'raw checkpoint')
print('EXPRESSION CHECKPOINT RAW ROUNDTRIP PASSED')
