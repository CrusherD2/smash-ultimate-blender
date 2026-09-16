"""Paired exact comparison and default-backend profile on fresh Shy Guy feet."""
from pathlib import Path
import os, importlib, json, time, hashlib, cProfile, pstats, io
fixture=Path(__file__).with_name('test_addon_registration_blender.py')
exec(compile(fixture.read_text().split('addon_utils.disable(MODULE')[0],str(fixture),'exec'))
# Defaults to Blender's backend so the historical figures in
# docs/benchmarks/shyguy-fresh-foot-ik-2026-09-13.md stay reproducible, but an
# explicit SUB_NATIVE_IK wins: pass 'experimental' to measure and fingerprint the
# shipped default instead. Both rows of the comparison in
# docs/benchmarks/native-default-2026-09-13.md are produced this way.
os.environ.setdefault('SUB_NATIVE_IK','0')
ik=importlib.import_module(MODULE+'.source.extras.ik_channels')
anim=importlib.import_module(MODULE+'.source.anim.import_anim')
curves=importlib.import_module(MODULE+'.source.anim.fcurve_compat')
rig=importlib.import_module(MODULE+'.source.extras.create_animation_rig')
out=ROOT/'.tests/benchmarks/shyguy_ik_repro'
source=Path('C:/Users/notja/Documents/Coding/SSBU Modding/Movesets/Shy-Guy-Moveset/romfs/fighter/pacman/motion/body/c40/a00wait1.nuanmb')
real_match=ik.match
class Reporter:
    def report(self,levels,message): print(levels,message,flush=True)
def fingerprint(obj):
    keys=sorted((f.data_path,f.array_index,[(tuple(k.co),k.interpolation) for k in f.keyframe_points]) for f in curves.get_all_action_fcurves(obj.animation_data.action,id_type='OBJECT'))
    digest=hashlib.sha256()
    for f in range(bpy.context.scene.frame_start,bpy.context.scene.frame_end+1):
        bpy.context.scene.frame_set(f)
        digest.update(json.dumps([[tuple(r) for r in b.matrix] for b in obj.pose.bones]).encode())
    return dict(keys=hashlib.sha256(json.dumps(keys).encode()).hexdigest(),poses=digest.hexdigest())
def run(phase,fast,profile=False):
    bpy.ops.wm.open_mainfile(filepath=str(out/('fresh_foot_ik.blend' if phase=='IMPORT' else 'matched_wait.blend')))
    obj=next(o for o in bpy.context.scene.objects if o.type=='ARMATURE')
    bpy.context.view_layer.objects.active=obj; obj.select_set(True)
    def match(*args,**kwargs):
        kwargs['_fast']=fast
        return real_match(*args,**kwargs)
    ik.match=match
    prof=cProfile.Profile()
    if profile: prof.enable()
    t=time.perf_counter()
    if phase=='IMPORT':
        assert anim.import_animation_file(bpy.context,Reporter(),obj,str(source),True,True,True,1)
    else:
        assert bpy.ops.sub.fk_to_ik_transfer('EXEC_DEFAULT',cleanup_mode='LEGS',entire_animation=True)=={'FINISHED'}
    elapsed=time.perf_counter()-t
    if profile:
        prof.disable()
        stream=io.StringIO(); pstats.Stats(prof,stream=stream).sort_stats('cumulative').print_stats(65)
        (out/(phase.lower()+'_profile.txt')).write_text(stream.getvalue())
        prof.dump_stats(str(out/(phase.lower()+'.prof')))
    return dict(phase=phase,fast=fast,seconds=elapsed,**fingerprint(obj))
rows=[]
for repeat in range(3):
    for phase in ('IMPORT','MATCH'):
        pair=[]
        for enabled in ((False,True) if repeat%2==0 else (True,False)):
            r=run(phase,enabled); r['repeat']=repeat; rows.append(r); pair.append(r)
            print('SHYGUY_PAIR',r,flush=True)
        assert pair[0]['keys']==pair[1]['keys'] and pair[0]['poses']==pair[1]['poses'],pair
        (out/'paired.json').write_text(json.dumps(rows,indent=2))
for phase in ('IMPORT','MATCH'): run(phase,True,profile=True)
print('SHYGUY_EXACT_PAIRS',len(rows)//2,flush=True)
