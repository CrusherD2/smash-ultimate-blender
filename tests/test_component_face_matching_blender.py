from pathlib import Path
fixture=Path(__file__).with_name('test_face_components_blender.py')
exec(compile(fixture.read_text(encoding='utf-8').split('# Removing face controllers')[0],str(fixture),'exec'))
matching=importlib.import_module(MODULE+'.source.extras.component_matching')
workflow=importlib.import_module(MODULE+'.source.extras.component_workflow')
# Store all built definitions; direct pose authoring may have rebuilt components.
obj['sub_custom_components']=json.dumps([cc.serialize(c) for c in editor.components])
scene=bpy.context.scene
scene.frame_start,scene.frame_end=1,3
originals=['LidUpper','LidLower','Jaw','EyeL','EyeR']
owned=[con for pb in obj.pose.bones for con in pb.constraints if con.name.startswith('SUB Component ')]
for con in owned: con.mute=True
for frame in range(1,4):
    scene.frame_set(frame)
    for n in originals:
        pb=obj.pose.bones[n]
        pb.rotation_mode='XYZ'
        pb.location=(0,0,0)
        pb.rotation_euler=(0,0,0)
        pb.scale=(1,1,1)
        if n=='LidUpper': pb.location.z=-.25*frame/3
        if n=='LidLower': pb.location.z=.3*frame/3
        if n=='Jaw':
            pb.location=(.1*frame/3,.2*frame/3,-.3*frame/3)
            pb.rotation_euler.z=.45*frame/3
        if n.startswith('Eye'): pb.location.x=-.2*frame/3
        pb.keyframe_insert('location',frame=frame)
        pb.keyframe_insert('rotation_euler',frame=frame)
        pb.keyframe_insert('scale',frame=frame)
source={}
for frame in range(1,4):
    scene.frame_set(frame)
    source[frame]={n:matrix(n) for n in originals+['Head']}
for con in owned: con.mute=False
count,extra=matching.match_animation(bpy.context,obj,1,3)
assert count==3
for frame,poses in source.items():
    scene.frame_set(frame)
    for name,wanted in poses.items(): close(matrix(name),wanted,name)
# Export includes all matching offsets and excludes their helper tracks.
with tempfile.TemporaryDirectory() as folder:
    path=str(Path(folder)/'matched.nuanmb')
    export.export_model_anim_fast(bpy.context,SimpleNamespace(report=lambda *args:None),obj,path,True,False,False,1,3)
    anim=addon.dependencies.ssbh_data_py.anim_data.read_anim(path)
    nodes=next(g.nodes for g in anim.groups if g.group_type.name=='Transform')
    assert not any(n.name.startswith('BL_') for n in nodes)
    for node in nodes:
        if node.name not in originals:
            continue
        parent=obj.pose.bones[node.name].parent.name
        for index,value in enumerate(node.tracks[0].values):
            wanted=export.get_smash_transform(source[index+1][parent].inverted_safe() @ source[index+1][node.name])
            actual=Matrix.LocRotScale(Vector(value.translation),Quaternion((value.rotation[3],*value.rotation[:3])),Vector(value.scale))
            close(actual,Matrix.LocRotScale(*wanted.decompose()),node.name)
# Re-running is stable and never samples its own correction constraints.
matching.match_animation(bpy.context,obj,1,3)
for frame,poses in source.items():
    scene.frame_set(frame)
    for name,wanted in poses.items(): close(matrix(name),wanted,name)
workflow.bake_remove(bpy.context,obj,True)
for frame,poses in source.items():
    scene.frame_set(frame)
    for name,wanted in poses.items(): close(matrix(name),wanted,name)
print('FACIAL COMPONENT MATCH, REMATCH, EXPORT AND BAKE PASSED')
