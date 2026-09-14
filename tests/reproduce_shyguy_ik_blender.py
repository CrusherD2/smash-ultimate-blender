"""Fresh Shy Guy import, remove imported IK, new foot IK, wait animation."""
from pathlib import Path
import os, sys, importlib, json, time, inspect, shutil
from contextlib import contextmanager

fixture=Path(__file__).with_name('test_addon_registration_blender.py')
exec(compile(fixture.read_text().split('addon_utils.disable(MODULE')[0],str(fixture),'exec'))
os.environ['SUB_NATIVE_IK']='0'
model=importlib.import_module(MODULE+'.source.model.import_model')
anim=importlib.import_module(MODULE+'.source.anim.import_anim')
ik=importlib.import_module(MODULE+'.source.extras.ik_channels')
fast=importlib.import_module(MODULE+'.source.extras.ik_match_fast')
rig=importlib.import_module(MODULE+'.source.extras.create_animation_rig')
source=Path('C:/Users/notja/Documents/Coding/SSBU Modding/Movesets/Shy-Guy-Moveset/romfs/fighter/pacman')
out=ROOT/'.tests/benchmarks/shyguy_ik_repro'
out.mkdir(parents=True,exist_ok=True)
copied=out/'input_model'
shutil.copytree(source/'model/body/c40',copied,dirs_exist_ok=True)
animation=source/'motion/body/c40/a00wait1.nuanmb'
report=dict(blender=bpy.app.version_string,model=str(source/'model/body/c40'),animation=str(animation),stages=[],guards=[])
def save():
    (out/'diagnostic.json').write_text(json.dumps(report,indent=2))
class Reporter:
    def report(self,levels,message): print(levels,message,flush=True)
def timed(name,fn):
    t=time.perf_counter(); result=fn()
    row=dict(stage=name,seconds=time.perf_counter()-t)
    report['stages'].append(row); save(); print('SHYGUY_STAGE',row,flush=True)
    return result
for obj in list(bpy.data.objects): bpy.data.objects.remove(obj,do_unlink=True)
props=bpy.context.scene.sub_scene_properties
props.model_import_folder_path=str(copied)
model._assign_model_file_names(props,[p.name for p in copied.iterdir()])
assert timed('fresh_model_import',lambda:model.import_model(Reporter(),bpy.context))=={'FINISHED'}
obj=next(o for o in bpy.context.scene.objects if o.type=='ARMATURE')
bpy.context.view_layer.objects.active=obj; obj.select_set(True)
report['imported_ik_bones']=[b.name for b in obj.data.bones if 'IK' in b.name]
assert timed('remove_existing_ik',lambda:bpy.ops.sub.anim_rig_remove_ik('EXEC_DEFAULT',limbs='BOTH'))=={'FINISHED'}
assert timed('create_new_foot_ik',lambda:bpy.ops.sub.create_foot_ik('EXEC_DEFAULT',match_position=False))=={'FINISHED'}
rig._set_ik_enabled(bpy.context,obj,True,limbs='LEGS')
bpy.context.view_layer.update()
report.update(bones=len(obj.data.bones),meshes=sum(o.type=='MESH' for o in bpy.context.scene.objects),
              legs_enabled=rig.armature_ik_is_enabled(obj,'LEGS'),
              constraints=[dict(bone=b.name,name=c.name,type=c.type) for b in obj.pose.bones for c in b.constraints])
bpy.ops.wm.save_as_mainfile(filepath=str(out/'fresh_foot_ik.blend'))
real_batch,real_sample,real_isolate=ik._can_batch_match,fast.sample_fk,fast.isolated
def batch(*args):
    reason={}
    def trace(frame,event,arg):
        if frame.f_code==real_batch.__code__:
            if event=='return': reason.update(line=frame.f_lineno,result=bool(arg))
            return trace
    old=sys.gettrace(); sys.settrace(trace)
    try: result=real_batch(*args)
    finally: sys.settrace(old)
    reason.update(kind='batch',jobs=len(args[1]),source=Path(real_batch.__code__.co_filename).read_text().splitlines()[reason['line']-1].strip())
    report['guards'].append(reason); print('SHYGUY_GUARD',reason,flush=True)
    return result
def sample(*args):
    r=real_sample(*args); report['guards'].append(dict(kind='sample',result=r is not None)); return r
@contextmanager
def isolate(ctx,arm,*args):
    with real_isolate(ctx,arm,*args) as r:
        report['guards'].append(dict(kind='isolate',result=r[1]!=arm,bones=len(r[1].data.bones)))
        yield r
ik._can_batch_match,fast.sample_fk,fast.isolated=batch,sample,isolate
assert timed('import_wait_with_ik',lambda:anim.import_animation_file(bpy.context,Reporter(),obj,str(animation),True,True,True,1))
report['frames']=bpy.context.scene.frame_end-bpy.context.scene.frame_start+1
assert timed('position_ik_controls',lambda:bpy.ops.sub.fk_to_ik_transfer('EXEC_DEFAULT',cleanup_mode='LEGS',entire_animation=True))=={'FINISHED'}
save()
bpy.ops.wm.save_as_mainfile(filepath=str(out/'matched_wait.blend'))
print('SHYGUY_REPRO_DONE',json.dumps(report),flush=True)
