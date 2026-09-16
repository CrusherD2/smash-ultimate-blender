from pathlib import Path
fixture=Path(__file__).with_name('test_custom_components_blender.py')
exec(compile(fixture.read_text(encoding='utf-8').split('components = [')[0],str(fixture),'exec'))
rig=importlib.import_module(MODULE+'.source.extras.create_animation_rig')
fingers=importlib.import_module(MODULE+'.source.extras.finger_sliders')
importer=importlib.import_module(MODULE+'.source.anim.import_anim')
bpy.ops.object.mode_set(mode='EDIT')
bone('HandL',(0,0,2),'Trans')
for i in range(4): bone('FingerL1'+str(i),(0,i*.25,2),'HandL' if i==0 else 'FingerL1'+str(i-1))
bone('LegL',(0,0,1),'Trans')
bone('KneeL',(0,.2,0),'LegL')
bone('FootL',(0,0,-1),'KneeL')
bpy.ops.object.mode_set(mode='POSE')
scene=bpy.context.scene
scene.frame_start,scene.frame_end=1,3
names=['Trans','WingL','HandL','FingerL10','FingerL11','FingerL12','FingerL13','LegL','KneeL','FootL']
for f in range(1,4):
    scene.frame_set(f)
    for i,name in enumerate(names):
        pb=obj.pose.bones[name]
        pb.rotation_mode='XYZ'
        pb.rotation_euler=(f*.04*(i+1),0,f*.01)
        pb.location=(f*.08,0,0) if name in {'Trans','WingL'} else (0,0,0)
        pb.keyframe_insert('rotation_euler',frame=f)
        pb.keyframe_insert('location',frame=f)
def snapshot():
    result={}
    for f in range(1,4):
        scene.frame_set(f)
        bpy.context.view_layer.update()
        ev=obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
        result[f]={n:ev.pose.bones[n].matrix.copy() for n in names}
    return result
with tempfile.TemporaryDirectory() as folder:
    path=str(Path(folder)/'input.nuanmb')
    export.export_model_anim_fast(bpy.context,SimpleNamespace(report=lambda *args:None),obj,path,True,False,False,1,3)
    importer.import_model_anim(bpy.context,path,True,False,False,1,obj)
    assert not obj.animation_data.action.get('sub_rig_import_matched')
    expected=snapshot()
    obj.data[rig.ARMATURE_FLAG]=True
    ik.create_controls(bpy.context,obj,'LEGS')
    fingers.build_finger_sliders(bpy.context,obj)
    editor.save_on_build=False
    component('ISOLATED','Floating Wing',['WingL'])
    assert bpy.ops.sub.component_build()=={'FINISHED'}
    for iteration in range(2):
        for pb in obj.pose.bones:
            if pb.name.startswith('BL_') or pb.name.startswith('FootIK'):
                pb.location=(.4,.2,.1)
        importer.import_model_anim(bpy.context,path,True,False,False,1,obj)
        assert obj.animation_data.action.get('sub_rig_import_matched')
        actual=snapshot()
        for f,poses in expected.items():
            for n,wanted in poses.items():
                error=max(abs(actual[f][n][i][j]-wanted[i][j]) for i in range(4) for j in range(4))
                assert error<3e-4,(iteration,f,n,error)
    curves_now=curves.get_all_action_fcurves(obj.animation_data.action)
    assert any('FootIK' in fc.data_path for fc in curves_now)
    assert any('BL_CC_' in fc.data_path for fc in curves_now)
    assert any(fingers.is_finger_control_bone(fc.data_path.split('"')[1]) for fc in curves_now if 'pose.bones["' in fc.data_path)
    raw=importlib.import_module(MODULE+'.source.anim.raw_anim')
    expected=snapshot()
    before=curves.get_all_action_fcurves(obj.animation_data.action)
    for fc in before:
        for k in fc.keyframe_points:
            k.interpolation='BEZIER'
            k.handle_left_type='FREE'
            k.handle_right_type='VECTOR'
    rawpath=str(Path(folder)/'roundtrip.rawanim')
    assert raw.export_raw_animation(obj,obj.animation_data.action,rawpath,1,3)
    import json
    before_payload=json.loads(Path(rawpath).read_text())
    scene.sub_scene_properties.anim_include_raw_animation=True
    scene.sub_doctor.run_before_export=False
    operator=SimpleNamespace(filepath=str(Path(folder)/'roundtrip.nuanmb'),
        include_transform_track=True,include_material_track=False,include_visibility_track=False,
        first_blender_frame=1,last_blender_frame=3,transform_compensate_scale=False,
        transform_override_translation=False,transform_override_rotation=False,
        transform_override_scale=False,transform_override_compensate_scale=False,
        report=lambda *args:None)
    # Exercise the actual Export Current Animation + Raw orchestration.
    original_export=export.export_model_anim_fast_steps
    def verify_raw_first(*args,**kwargs):
        assert json.loads(Path(rawpath).read_text())==before_payload
        yield from original_export(*args,**kwargs)
    export.export_model_anim_fast_steps=verify_raw_first
    Path(rawpath).unlink()
    try:
        list(export.SUB_OP_anim_export.export_steps(operator,bpy.context))
    finally:
        export.export_model_anim_fast_steps=original_export
    assert Path(operator.filepath).is_file()
    after_payload=json.loads(Path(rawpath).read_text())
    def differences(a,b,path=''):
        if isinstance(a,dict) and isinstance(b,dict):
            return [r for k in a.keys()|b.keys() for r in differences(a.get(k),b.get(k),path+'/'+str(k))]
        if isinstance(a,list) and isinstance(b,list) and len(a)==len(b):
            return [r for i,(x,y) in enumerate(zip(a,b)) for r in differences(x,y,path+'/'+str(i))]
        if a!=b: return [(path,a,b)]
        return []
    assert before_payload==after_payload,differences(before_payload,after_payload)[:15]
    print('PAIRED RAW IDENTICAL TO STANDALONE RAW PASSED')

    import json
    payload=json.loads(Path(rawpath).read_text())
    original=obj
    bpy.ops.object.mode_set(mode='OBJECT')
    data=bpy.data.armatures.new('Clean')
    obj=bpy.data.objects.new('Clean',data)
    scene.collection.objects.link(obj)
    assert raw.import_raw_animation(bpy.context,obj,rawpath)
    actual=snapshot()
    for f,poses in expected.items():
        for n,wanted in poses.items():
            error=max(abs(actual[f][n][i][j]-wanted[i][j]) for i in range(4) for j in range(4))
            assert error<3e-4,('RAW',f,n,error)
    for mode in (True,False):
        fingers.set_finger_slider_mode(obj,mode,bpy.context)
        actual=snapshot()
        for f,poses in expected.items():
            for n,wanted in poses.items():
                assert max(abs(actual[f][n][i][j]-wanted[i][j]) for i in range(4) for j in range(4))<3e-4,(mode,f,n)
    assert any(p.bone.get('sub_isolated_role')=='HEEL' for p in obj.pose.bones)
    assert any(p.bone.get('sub_isolated_role')=='TOE' for p in obj.pose.bones)
    after=curves.get_all_action_fcurves(obj.animation_data.action)
    assert len(after)==len(before)
    for fc in after:
        assert len(fc.keyframe_points)==3
        for k in fc.keyframe_points:
            assert k.handle_left_type=='FREE' and k.handle_right_type=='VECTOR'
    print('RAW COMPLETE RIG AND HANDLES ROUNDTRIP PASSED')
