from pathlib import Path
import time,sys
fixture=Path(__file__).with_name('test_finger_neutral_blender.py')
exec(compile(fixture.read_text(encoding='utf-8-sig').split('expected=')[0],str(fixture),'exec'))
matching=importlib.import_module(MODULE+'.source.extras.component_matching')
scene=bpy.context.scene
scene.frame_start,scene.frame_end=1,8
names=[p.name for p in obj.pose.bones if fingers.is_finger_circle_bone(p.name)]
expected={}
for f in range(1,9):
    scene.frame_set(f)
    for i,name in enumerate(names):
        p=obj.pose.bones[name]
        p.rotation_mode='XYZ'
        p.rotation_euler=(f*.025*(i%3+1),f*.009*(i%2),f*.014)
        p.keyframe_insert('rotation_euler',frame=f)
    bpy.context.view_layer.update()
    expected[f]={n:obj.pose.bones[n].matrix.copy() for n in names}
fingers.build_finger_sliders(bpy.context,obj)
calls=[0]
update=matching._update
def counted(*args):
    calls[0]+=1
    return update(*args)
matching._update=counted
started=time.perf_counter()
matching.match_animation(bpy.context,obj,1,8,include_fingers=True,fingers_only=True,match_ik=False)
elapsed=time.perf_counter()-started
for f,poses in expected.items():
    scene.frame_set(f)
    bpy.context.view_layer.update()
    for n,wanted in poses.items():
        actual=obj.pose.bones[n].matrix
        assert max(abs(actual[i][j]-wanted[i][j]) for i in range(4) for j in range(4))<2e-4,(f,n)
print('FULL HAND ACCURACY PASSED; BENCHMARK',calls[0],round(elapsed,3))
