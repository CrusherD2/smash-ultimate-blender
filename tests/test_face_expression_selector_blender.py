from pathlib import Path
fixture=Path(__file__).with_name('test_face_components_blender.py')
exec(compile(fixture.read_text(encoding='utf-8-sig').split("component('MOUTH'")[0],str(fixture),'exec'))
c=editor.components[0]
main=obj.pose.bones[cc.control_name(obj,c)]
main.location.y=1
main.sub_face_expression='POSE_1'
close(matrix('LidUpper'),left,'selected left')
close(matrix('LidLower'),neutral['LidLower'],'right neutral')
main.sub_face_expression='POSE_2'
close(matrix('LidLower'),right,'selected right')
close(matrix('LidUpper'),neutral['LidUpper'],'left neutral')
for frame,choice in ((1,'POSE_1'),(4,'POSE_2')):
    main.sub_face_expression=choice
    main.keyframe_insert('sub_face_expression',frame=frame)
    main.keyframe_insert('location',index=1,frame=frame)
bpy.context.scene.frame_set(1)
close(matrix('LidUpper'),left,'keyed left')
bpy.context.scene.frame_set(2)
close(matrix('LidUpper'),left,'dropdown holds expression between keys')
bpy.context.scene.frame_set(4)
close(matrix('LidLower'),right,'keyed right')
assert all(p.bone.hide for p in face.owned(obj,c) if p.name!=main.name)
# New expression names never accidentally replace previous saved poses.
old=set(json.loads(c.face_data)['poses'])
pose('NEW')
assert c.pose_name not in old
pose('CAPTURE')
assert len(json.loads(c.face_data)['poses'])==len(old)+1
assert old<=set(json.loads(c.face_data)['poses'])
print('MULTIPLE EXPRESSIONS AND KEYFRAMED DROPDOWN PASSED')
