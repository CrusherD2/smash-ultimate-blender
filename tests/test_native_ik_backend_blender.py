"""Backend selection, failure fallback and cleanup on the real generated rig."""
from pathlib import Path
import importlib
import os
from unittest.mock import patch

fixture = Path(__file__).with_name('test_addon_registration_blender.py')
exec(compile(fixture.read_text().split('addon_utils.disable(MODULE')[0],str(fixture),'exec'))
ik = importlib.import_module(MODULE+'.source.extras.ik_channels')
native = importlib.import_module(MODULE+'.source.extras.ik_native')
baseline = ROOT/'.tests/benchmarks/ik_apply/out/4.5/baseline.blend'
bpy.ops.wm.open_mainfile(filepath=str(baseline))
obj=next(o for o in bpy.context.scene.objects if o.type=='ARMATURE')
bpy.context.view_layer.objects.active=obj
obj.select_set(True)
ik.create_controls(bpy.context,obj,'BOTH')
jobs=list(ik.chains(obj,'BOTH'))
cache=ik._chain_cache(obj,jobs)
for job in jobs:
    bones=[obj.pose.bones[ik.PREFIX+n] for n in cache[job[2]]['path'][:-1]]
    con=ik.solve_bone(obj,job[1]).constraints['SUB IK Solve']
    assert native.supported(obj,bones,con)
    for prop,value in [('use_rotation',True),('use_stretch',True),('influence',.5),('chain_count',1),('target_space','POSE')]:
        old=getattr(con,prop)
        setattr(con,prop,value)
        assert not native.supported(obj,bones,con),prop
        setattr(con,prop,old)
    for prop,value in [('lock_ik_x',True),('use_ik_limit_y',True),('ik_stiffness_z',.5)]:
        old=getattr(bones[0],prop)
        setattr(bones[0],prop,value)
        assert not native.supported(obj,bones,con),prop
        setattr(bones[0],prop,old)
    extra=bones[0].constraints.new('COPY_ROTATION')
    assert not native.supported(obj,bones,con)
    bones[0].constraints.remove(extra)

with patch.dict(os.environ,{'SUB_NATIVE_IK':'0'}):
    assert native.get_factory() is None
with patch.dict(os.environ):
    os.environ.pop('SUB_NATIVE_IK',None)
    assert native.get_factory() is None
os.environ['SUB_NATIVE_IK']='1'
assert native.get_factory() is not None
with patch.object(native.Path,'is_file',return_value=False):
    assert native.get_factory() is None

loaded=native._dll
native._dll=None
try:
    with patch.object(native.ctypes,'CDLL',side_effect=OSError('missing runtime')):
        assert native.Factory()(obj,job,bones,con,1) is None
    assert native._dll is None
finally:
    native._dll=loaded
native.Solver(obj,job,bones,con,1).close()

# Inject an actual solve failure. The frame and output-constraint state must
# still be restored, and every created native handle must be released.
created=[]
original_init=native.Solver.__init__
def track(self,*args,**kwargs):
    original_init(self,*args,**kwargs)
    created.append(self)
original_frame=bpy.context.scene.frame_current
states=[(c,c.mute) for _,c,_ in (*ik.outputs(obj,'BOTH'),*ik.toe_outputs(obj,'BOTH'))]
def fail(*args,**kwargs):
    raise RuntimeError('injected native scheduler failure')
try:
    with patch.object(native.Solver,'__init__',track), patch.object(native._dll,'sub_ik_solve_many',side_effect=fail):
        ik.match(bpy.context,obj,'BOTH',entire=False,key=False,_batch=True)
except RuntimeError as error:
    assert str(error)=='injected native scheduler failure'
else:
    raise AssertionError('injected failure was not reached')
assert created and all(s.handle is None for s in created)
assert bpy.context.scene.frame_current==original_frame
assert all(c.mute==mute for c,mute in states)
created.clear()
with patch.object(native.Solver,'__init__',track), patch.object(native._dll,'sub_ik_solve_many',return_value=False):
    ik.match(bpy.context,obj,'BOTH',entire=False,key=False,_batch=True)
assert created and all(s.fallback and s.handle is None for s in created)
assert bpy.context.scene.frame_current==original_frame
assert all(c.mute==mute for c,mute in states)
print('NATIVE_BACKEND_GUARDS_AND_CLEANUP_OK')
