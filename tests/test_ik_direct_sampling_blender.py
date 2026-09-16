"""Measure direct FK sampling separately, exposing the first exactness failure."""
from pathlib import Path
import sys
import os
import time
import json
import importlib
from mathutils import Matrix

fixture = Path(__file__).with_name('test_addon_registration_blender.py')
exec(compile(fixture.read_text().split('addon_utils.disable(MODULE')[0],str(fixture),'exec'))
sys.path.insert(0,str(Path(__file__).parent))
from ik_strategy_prototypes import direct_samples
ik = importlib.import_module(MODULE+'.source.extras.ik_channels')
curves = importlib.import_module(MODULE+'.source.anim.fcurve_compat')
baseline = Path(os.environ.get('SUB_BASELINE_BLEND',ROOT/'.tests/benchmarks/ik_apply/out/4.5/baseline.blend'))
bpy.ops.wm.open_mainfile(filepath=str(baseline))
obj = next(o for o in bpy.context.scene.objects if o.type=='ARMATURE')
bpy.context.view_layer.objects.active = obj
obj.select_set(True)
ik.create_controls(bpy.context,obj,'BOTH')
for _,con,_ in (*ik.outputs(obj),*ik.toe_outputs(obj)):
    con.mute = True
jobs = list(ik.chains(obj))
names = ik._sample_names(obj,jobs,ik._chain_cache(obj,jobs))
frames = range(bpy.context.scene.frame_start,bpy.context.scene.frame_end+1)
reference = {}
t = time.perf_counter()
for frame in frames:
    bpy.context.scene.frame_set(frame)
    bpy.context.view_layer.update()
    reference[frame] = {n:obj.pose.bones[n].matrix.copy() for n in names}
reference_seconds = time.perf_counter()-t
fcurves = list(curves.get_all_action_fcurves(obj.animation_data.action,id_type='OBJECT'))
t = time.perf_counter()
actual = direct_samples(obj,frames,names,fcurves)
direct_seconds = time.perf_counter()-t
diffs = [dict(frame=f,bone=n,row=r,column=c,reference=a,direct=b,error=abs(a-b))
         for f in frames for n in names
         for r,(ra,rb) in enumerate(zip(reference[f][n],actual[f][n]))
         for c,(a,b) in enumerate(zip(ra,rb)) if a!=b]
report = dict(blender=bpy.app.version_string,reference_seconds=reference_seconds,
              direct_seconds=direct_seconds,unequal_elements=len(diffs),
              first=diffs[:12],worst=max(diffs,key=lambda d:d['error']) if diffs else None)
# A second probe uses Blender's RNA channel-to-basis implementation, detached
# from any scene, instead of mathutils' TRS composition. No depsgraph is needed.
clone = obj.copy()
clone.animation_data_clear()
needed = set(names)
for n in names:
    needed.update(b.name for b in obj.pose.bones[n].parent_recursive)
bones = sorted((clone.pose.bones[n] for n in needed),key=lambda b:len(b.parent_recursive))
channels = {}
for pb in bones:
    for p in ('location','rotation_quaternion','rotation_euler','rotation_axis_angle','scale'):
        channels[pb.path_from_id()+'.'+p] = (pb,p)
relevant = [(fc,*channels[fc.data_path]) for fc in fcurves if fc.data_path in channels and not fc.mute]
rna_diffs = []
offset_diffs = []
offsets = {}
for pb in bones:
    offset = pb.bone.matrix.to_4x4()
    offset.translation = pb.bone.head
    if pb.parent:
        offset[1][3] += pb.parent.bone.length
    offsets[pb.name] = offset
t = time.perf_counter()
try:
    for f in frames:
        for fc,pb,p in relevant:
            getattr(pb,p)[fc.array_index] = fc.evaluate(f)
        worlds = {}
        for pb in bones:
            kwargs = dict(parent_matrix=worlds[pb.parent.name],parent_matrix_local=pb.parent.bone.matrix_local) if pb.parent else {}
            worlds[pb.name] = pb.bone.convert_local_to_pose(pb.matrix_basis,pb.bone.matrix_local,**kwargs)
        for n in names:
            for r,(ra,rb) in enumerate(zip(reference[f][n],worlds[n])):
                for c,(a,b) in enumerate(zip(ra,rb)):
                    if a!=b:
                        rna_diffs.append(dict(frame=f,bone=n,row=r,column=c,reference=a,direct=b,error=abs(a-b)))
        worlds = {}
        for pb in bones:
            kwargs = dict(parent_matrix=worlds[pb.parent.name],parent_matrix_local=Matrix.Identity(4)) if pb.parent else {}
            worlds[pb.name] = pb.bone.convert_local_to_pose(pb.matrix_basis,offsets[pb.name],**kwargs)
        for n in names:
            for r,(ra,rb) in enumerate(zip(reference[f][n],worlds[n])):
                for c,(a,b) in enumerate(zip(ra,rb)):
                    if a!=b:
                        offset_diffs.append(dict(frame=f,bone=n,row=r,column=c,reference=a,direct=b,error=abs(a-b)))
finally:
    bpy.data.objects.remove(clone)
report['rna_seconds'] = time.perf_counter()-t
report['rna_unequal_elements'] = len(rna_diffs)
report['rna_first'] = rna_diffs[:12]
report['rna_worst'] = max(rna_diffs,key=lambda d:d['error']) if rna_diffs else None
report['offset_unequal_elements'] = len(offset_diffs)
report['offset_first'] = offset_diffs[:12]
report['offset_worst'] = max(offset_diffs,key=lambda d:d['error']) if offset_diffs else None
report['active_constraints'] = {n:[(c.name,c.type) for c in obj.pose.bones[n].constraints if not c.mute]
                                for n in needed if any(not c.mute for c in obj.pose.bones[n].constraints)}
out = ROOT/'.tests/benchmarks'/f'direct_sampling_{bpy.app.version[0]}.{bpy.app.version[1]}.json'
out.write_text(json.dumps(report,indent=2))
print('DIRECT_SAMPLING',report)
