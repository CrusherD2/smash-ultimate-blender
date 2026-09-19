"""Short sliders away from the origin must use evaluated LOCAL-space math."""
from pathlib import Path
fixture=Path(__file__).with_name('test_finger_full_hand_speed_blender.py')
source=fixture.read_text(encoding='utf-8-sig')
source=source.replace('expected={}', '''
from mathutils import Vector
bpy.ops.object.mode_set(mode='EDIT')
for bone in obj.data.edit_bones:
    bone.head=bone.head*.1+Vector((8,3,6))
    bone.tail=bone.tail*.1+Vector((8,3,6))
    bone.roll=.37
bpy.ops.object.mode_set(mode='POSE')
expected={}
''',1)
exec(compile(source,str(fixture),'exec'))
graph=importlib.import_module(MODULE+'.source.extras.component_graph')
assert graph.LAST_DIAGNOSTICS['native_frames']==8,graph.LAST_DIAGNOSTICS
assert graph.LAST_DIAGNOSTICS['fallback_frames']==0,graph.LAST_DIAGNOSTICS
assert graph.LAST_DIAGNOSTICS['native_evaluations']<=24,graph.LAST_DIAGNOSTICS
print('TRANSLATED FINGER GRAPH ACCURACY AND EVALUATION BOUND PASSED')
