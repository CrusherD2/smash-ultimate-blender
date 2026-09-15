from pathlib import Path
fixture=Path(__file__).with_name('test_face_components_blender.py')
exec(compile(fixture.read_text(encoding='utf-8-sig').split("component('MOUTH'")[0],str(fixture),'exec'))
c=editor.components[0]
before=json.loads(c.face_data)
existing={p.name for p in face.owned(obj,c) if not p.bone.get('sub_face_helper')}
neutral_jaw=face.sample(obj.pose.bones['Jaw'])
c.bones.add().bone='Jaw'
face.build_face(bpy.context,obj,c)
after=json.loads(c.face_data)
assert after['poses']==before['poses']
for name,value in before['neutral'].items(): assert after['neutral'][name]==value
assert after['neutral']['Jaw']==neutral_jaw
assert {p.name for p in face.owned(obj,c) if not p.bone.get('sub_face_helper')}==existing
for p in face.owned(obj,c):
    if p.get('expression')=='Left Closed': p.location.y=1
close(matrix('LidUpper'),left,'existing pose preserved')
assert face.sample(obj.pose.bones['Jaw'])==neutral_jaw
# Removing and re-adding the assignment keeps its neutral snapshot.
c.bones.remove(len(c.bones)-1)
face.build_face(bpy.context,obj,c)
c.bones.add().bone='Jaw'
face.build_face(bpy.context,obj,c)
assert json.loads(c.face_data)['neutral']['Jaw']==neutral_jaw
print('FACE ADD REMOVE READD PRESERVES SAVED POSES PASSED')
