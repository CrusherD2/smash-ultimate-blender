"""Adversarial detached-solver comparisons, independent of the Sceptile fixture."""
from pathlib import Path
import sys
import random
import json
import os
import bpy
sys.path.insert(0,str(Path(__file__).parent))
from native_ik_runtime import Solver

bpy.ops.wm.read_factory_settings(use_empty=True)
data=bpy.data.armatures.new('Native compatibility rig')
obj=bpy.data.objects.new('Native compatibility rig',data)
bpy.context.scene.collection.objects.link(obj)
bpy.context.view_layer.objects.active=obj
obj.select_set(True)
bpy.ops.object.mode_set(mode='EDIT')
specs=[('root',(0,0,0),(0,1,0),None),('upper',(0,1,0),(.2,3,0),'root'),
       ('lower',(.2,3,0),(1,5,0),'upper'),('target',(1,4.5,.5),(1,5.5,.5),None),
       ('pole',(2,2,1),(2,3,1),None)]
for name,head,tail,parent in specs:
    b=data.edit_bones.new(name)
    b.head,b.tail=head,tail
    if parent:b.parent=data.edit_bones[parent]
bpy.ops.object.mode_set(mode='OBJECT')
con=obj.pose.bones['lower'].constraints.new('IK')
con.target=con.pole_target=obj
con.subtarget,con.pole_subtarget='target','pole'
con.chain_count=2
con.use_stretch=False
con.iterations=200
bones=[obj.pose.bones[n] for n in ('upper','lower')]
rng=random.Random(1803)
errors=[]
fallbacks=0
for sample in range(int(os.environ.get('SUB_NATIVE_CASES','1000'))):
    con.mute=True
    for name in ('root','upper','lower'):
        bone=obj.pose.bones[name]
        bone.rotation_mode='XYZ'
        bone.rotation_euler=[rng.uniform(-1,1) for _ in range(3)]
        bone.scale=[rng.uniform(.5,1.5) for _ in range(3)]
    obj.pose.bones['target'].location=[rng.uniform(-2,2) for _ in range(3)]
    obj.pose.bones['pole'].location=[rng.uniform(-2,2) for _ in range(3)]
    bpy.context.view_layer.update()
    native=Solver(obj,None,bones,con,sample)
    con.mute=False
    try:
        for angle in (0.0,.35,-.75,rng.uniform(-3.14,3.14)):
            con.pole_angle=angle
            bpy.context.view_layer.update()
            actual=native.solve(con.pole_angle)
            if actual is None:
                fallbacks += 1
                continue
            error=max(abs(a-b) for mat,bone in zip(actual,bones)
                      for row_a,row_b in zip(mat,bone.matrix) for a,b in zip(row_a,row_b))
            errors.append((error,sample,angle,native.iterations()))
    finally:
        native.close()
report=dict(cases=len(errors),exact=sum(e[0]==0 for e in errors),worst=max(errors),
            fallbacks=fallbacks,failures=[e for e in errors if e[0]],blender=bpy.app.version_string)
path=Path(__file__).resolve().parents[1]/'.tests/benchmarks/native_ik/synthetic.json'
path.write_text(json.dumps(report,indent=2))
path.with_name(f'synthetic_{bpy.app.version[0]}.{bpy.app.version[1]}.json').write_text(json.dumps(report,indent=2))
print('NATIVE_SYNTHETIC',report)
assert report['exact']==report['cases'],report
