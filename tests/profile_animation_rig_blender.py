"""Read-only on-disk rig profiling; never saves the opened blend.

SUB_RIG_PROFILE_BLEND is required. SUB_RIG_PROFILE_RUN=1 enables creation.
Run in a background factory-startup process. Output includes stage timings.
"""
from pathlib import Path
import os,time,cProfile,pstats
fixture=Path(__file__).with_name('test_addon_registration_blender.py')
exec(compile(fixture.read_text(encoding='utf-8-sig').split('addon_utils.disable(MODULE')[0],str(fixture),'exec'))
path=os.environ['SUB_RIG_PROFILE_BLEND']
bpy.ops.wm.open_mainfile(filepath=path,load_ui=False,use_scripts=False)
rig=importlib.import_module(MODULE+'.source.extras.create_animation_rig')
for obj in bpy.context.scene.objects:
    if obj.type=='ARMATURE':
        print('RIG_PROFILE_OBJECT',obj.name,'bones',len(obj.data.bones),'action',obj.animation_data.action.name if obj.animation_data and obj.animation_data.action else None,
              'rig',obj.data.get(rig.ARMATURE_FLAG,False),'custom',len(obj.get('sub_custom_components','')),
              'range',(bpy.context.scene.frame_start,bpy.context.scene.frame_end),flush=True)
if os.environ.get('SUB_RIG_PROFILE_RUN')=='1':
    arms=[obj for obj in bpy.context.scene.objects if obj.type=='ARMATURE' and rig._looks_like_smash_armature(obj)]
    assert arms,'No Smash armature'
    obj=max(arms,key=lambda obj:len(obj.data.bones))
    if bpy.context.object and bpy.context.object.mode!='OBJECT': bpy.ops.object.mode_set(mode='OBJECT')
    for other in bpy.context.view_layer.objects: other.select_set(False)
    obj.hide_set(False);obj.hide_viewport=False;obj.select_set(True);bpy.context.view_layer.objects.active=obj
    stages={}
    if os.environ.get('SUB_RIG_PROFILE_GRAPH')=='1':
        graph_module=importlib.import_module(MODULE+'.source.extras.component_graph')
        original_evaluate=graph_module.Graph.evaluate
        probe_count=[0]
        def probe(graph):
            result=original_evaluate(graph)
            if probe_count[0]<20:
                probe_count[0]+=1
                bpy.context.view_layer.update()
                errors={n:max(abs(result.pose.bones[n].matrix[r][c]-obj.pose.bones[n].matrix[r][c]) for r in range(4) for c in range(4)) for n in graph.names}
                external={n:errors[n] for n in graph.external if n in errors}
                print('RIG_PROFILE_GRAPH',bpy.context.scene.frame_current,sorted(errors.items(),key=lambda v:-v[1])[:3],
                      'external',sorted(external.items(),key=lambda v:-v[1])[:3],flush=True)
            return result
        graph_module.Graph.evaluate=probe
    def timed(module,name):
        original=getattr(module,name)
        def call(*args,**kwargs):
            expected={}
            if name=='match_animation' and os.environ.get('SUB_RIG_PROFILE_VERIFY')=='1':
                fingers=importlib.import_module(MODULE+'.source.extras.finger_sliders')
                pairs=list(fingers._iter_finger_slider_constraints(obj))
                muted=[(con,con.mute) for pb,con in pairs]
                frame=bpy.context.scene.frame_current
                try:
                    for con,_ in muted: con.mute=True
                    for f in range(bpy.context.scene.frame_start,bpy.context.scene.frame_end+1):
                        bpy.context.scene.frame_set(f);bpy.context.view_layer.update()
                        expected[f]={pb.name:pb.matrix.copy() for pb,con in pairs}
                finally:
                    for con,state in muted: con.mute=state
                    bpy.context.scene.frame_set(frame)
            start=time.perf_counter()
            try:
                result=original(*args,**kwargs)
                if expected:
                    worst=0.0
                    for f,poses in expected.items():
                        bpy.context.scene.frame_set(f);bpy.context.view_layer.update()
                        for n,wanted in poses.items():
                            error=max(abs(obj.pose.bones[n].matrix[r][c]-wanted[r][c]) for r in range(4) for c in range(4))
                            worst=max(worst,error)
                            assert error<2e-4,(f,n,error)
                    bpy.context.scene.frame_set(frame)
                    print('RIG_PROFILE_SAVED_KEYS_VERIFIED',len(expected),'frames; worst',worst,flush=True)
                return result
            finally:
                elapsed=time.perf_counter()-start;stages[name]=stages.get(name,0)+elapsed
                print('RIG_PROFILE_STAGE',name,round(elapsed,4),flush=True)
        setattr(module,name,call)
    for module_name,names in (
        ('create_animation_rig',('_apply_shapes','clean_redundant_keys_on_id')),
        ('finger_sliders',('build_finger_sliders',)),
        ('component_matching',('match_animation',)),
        ('eye_rig',('add_eye_look_control_bone',)),
    ):
        module=importlib.import_module(MODULE+'.source.extras.'+module_name)
        for name in names: timed(module,name)
    profile=cProfile.Profile();profile.enable();start=time.perf_counter()
    result=bpy.ops.sub.create_animation_rig(setup_ik=True,setup_eye_look=True,setup_finger_sliders=True,setup_custom_components=False)
    elapsed=time.perf_counter()-start;profile.disable()
    print('RIG_PROFILE_RESULT',result,'seconds',elapsed,'stages',stages,flush=True)
    pstats.Stats(profile).strip_dirs().sort_stats('cumtime').print_stats(35)
    graph=importlib.import_module(MODULE+'.source.extras.component_graph')
    print('RIG_PROFILE_NATIVE',graph.LAST_DIAGNOSTICS,flush=True)
print('RIG_PROFILE_DONE_NO_SAVE',flush=True)
