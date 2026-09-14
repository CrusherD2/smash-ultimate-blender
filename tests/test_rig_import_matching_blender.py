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
    # Finger removal also removes the auto-matching helpers and constraints.
    fingers.bake_finger_slider_keys(bpy.context,obj)
    fingers.remove_finger_sliders(bpy.context,obj)
    assert not any(p.bone.get('sub_face_owner')=='f'*32 for p in obj.pose.bones)
    actual=snapshot()
    for f,poses in expected.items():
        for n in names:
            assert max(abs(actual[f][n][i][j]-poses[n][i][j]) for i in range(4) for j in range(4))<3e-4,(f,n)
print('AUTOMATIC IMPORT MATCH: IK, FINGERS, COMPONENTS, REIMPORT AND BAKE PASSED')
