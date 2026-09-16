from pathlib import Path
fixture=Path(__file__).with_name('test_face_components_blender.py')
exec(compile(fixture.read_text(encoding='utf-8-sig').split("component('MOUTH'")[0],str(fixture),'exec'))
matching=importlib.import_module(MODULE+'.source.extras.component_matching')
from mathutils import Matrix
c=editor.components[0]
obj['sub_custom_components']=json.dumps([cc.serialize(c)])
data=json.loads(c.face_data)
main=obj.pose.bones[cc.control_name(obj,c)]
constraints=[con for p in obj.pose.bones for con in p.constraints if con.name.startswith('SUB Component ')]
for con in constraints: con.mute=True
wanted=[('Left Closed',1,1),('Right Closed',1,2),('Right Closed',.5,2),(None,0,0)]
for f,(label,strength,index) in enumerate(wanted,1):
    bpy.context.scene.frame_set(f)
    for n in ('LidUpper','LidLower'):
        value=list(data['neutral'][n])
        if label:
            target=data['poses'][label].get(n,value)
            value[:3]=[a+(b-a)*strength for a,b in zip(value[:3],target[:3])]
        face.restore(obj.pose.bones[n],value)
        obj.pose.bones[n].keyframe_insert('location',frame=f)
for con in constraints: con.mute=False
matching.match_animation(bpy.context,obj,1,4,match_ik=False)
for f,(label,strength,index) in enumerate(wanted,1):
    bpy.context.scene.frame_set(f)
    bpy.context.view_layer.update()
    assert face.expression_get(main)==index,(f,face.expression_get(main),index)
    assert abs(main.location.y-strength)<1e-5,(f,main.location.y,strength)
print('BEST EXPRESSION AND STRENGTH ARE MATCHED AND KEYED PASSED')
