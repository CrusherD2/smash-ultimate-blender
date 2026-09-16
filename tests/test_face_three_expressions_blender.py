from pathlib import Path
fixture=Path(__file__).with_name('test_face_components_blender.py')
exec(compile(fixture.read_text(encoding='utf-8-sig').split("component('MOUTH'")[0],str(fixture),'exec'))
c=editor.components[0]
pose('NEW')
obj.pose.bones['LidUpper'].location.z=-.1
obj.pose.bones['LidLower'].location.z=.1
pose('CAPTURE','Both Soft')
main=obj.pose.bones[cc.control_name(obj,c)]
assert set(json.loads(c.face_data)['poses'])=={'Left Closed','Right Closed','Both Soft'}
rna=main.bl_rna.properties['sub_face_strength']
assert rna.hard_min==0 and rna.hard_max==1
main.sub_face_strength=1.5
assert main.sub_face_strength==1
for choice,upper,lower in ((1,left,neutral['LidLower']),(2,neutral['LidUpper'],right)):
    main.sub_face_expression=choice
    main.sub_face_strength=1
    close(matrix('LidUpper'),upper,'pose '+str(choice)+' upper')
    close(matrix('LidLower'),lower,'pose '+str(choice)+' lower')
main.sub_face_expression=3
main.sub_face_strength=1
assert matrix('LidUpper').translation.z<neutral['LidUpper'].translation.z
assert matrix('LidLower').translation.z>neutral['LidLower'].translation.z
main.sub_face_strength=0
close(matrix('LidUpper'),neutral['LidUpper'],'third pose zero strength')
close(matrix('LidLower'),neutral['LidLower'],'third pose zero strength lower')
print('THREE EXPRESSIONS AND 0-1 STRENGTH PASSED')
