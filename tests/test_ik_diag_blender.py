"""Fallback reason codes name the guard that actually rejected the rig."""
from pathlib import Path
import os, importlib

root = Path(__file__).resolve().parents[1]
bench = root/'tests/benchmark_position_ik_blender.py'
exec(compile(bench.read_text().split("\nfor repeat in range(int(os.environ.get('SUB_MATCH_RUNS'")[0], str(bench), 'exec'))
os.environ['SUB_NATIVE_IK'] = '0'
fast = importlib.import_module(MODULE+'.source.extras.ik_match_fast')
diag = importlib.import_module(MODULE+'.source.extras.ik_match_diag')
compat = importlib.import_module(MODULE+'.source.anim.fcurve_compat')

def reload():
    bpy.ops.wm.open_mainfile(filepath=str(baseline))
    obj = next(o for o in bpy.context.scene.objects if o.type == 'ARMATURE')
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    ik.create_controls(bpy.context, obj, 'BOTH')
    bpy.context.scene.frame_end = bpy.context.scene.frame_start + 15
    mute_outputs(obj)
    return obj

def mute_outputs(obj):
    for _, con, _ in (*ik.outputs(obj), *ik.toe_outputs(obj)):
        con.mute = True

def sample(obj):
    scene = bpy.context.scene
    jobs = list(ik.chains(obj))
    cache = ik._chain_cache(obj, jobs)
    names = ik._sample_names(obj, jobs, cache)
    action = obj.animation_data.action if obj.animation_data else None
    curves = compat.get_all_action_fcurves(action, id_type='OBJECT') if action else ()
    return fast.sample_fk(obj, range(scene.frame_start, scene.frame_end+1), names, curves)

# Accepted rig records 'ok'.
obj = reload()
diag.reset()
assert sample(obj) is not None
assert diag.record()['reasons']['sample'] == 'ok', diag.record()

# A foreign frame-change handler is the documented rejection.
def custom_handler(*args):
    pass

obj = reload()
bpy.app.handlers.frame_change_post.append(custom_handler)
try:
    diag.reset()
    assert sample(obj) is None
    assert diag.record()['reasons']['sample'] == 'foreign_handler', diag.record()
finally:
    bpy.app.handlers.frame_change_post.remove(custom_handler)

# An unmuted constraint on a sampled bone is a different, distinguishable reason.
obj = reload()
jobs = list(ik.chains(obj))
source_bone = ik.limb_path(obj, jobs[0][1])[0]
con = obj.pose.bones[source_bone].constraints.new('COPY_LOCATION')
diag.reset()
assert sample(obj) is None
assert diag.record()['reasons']['sample'] == 'constrained_source', diag.record()
obj.pose.bones[source_bone].constraints.remove(con)

# can_isolate reports its own guard under its own name.
obj = reload()
obj.pose.use_auto_ik = True
diag.reset()
assert not fast.can_isolate(obj, list(ik.chains(obj)), ik)
assert diag.record()['reasons']['isolate'] == 'auto_ik', diag.record()
obj.pose.use_auto_ik = False

# reset() clears, and reasons are recorded with diagnostics disabled.
assert os.environ.get('SUB_IK_DIAG') != '1'
diag.reset()
assert diag.record() == {'reasons': {}, 'stages': {}, 'counts': {}}

# Stage timings: opt-in, and the search is measurable.
os.environ['SUB_IK_DIAG'] = '1'
try:
    obj = reload()
    ik.match(bpy.context, obj, _batch=True)
    timed = diag.record()
finally:
    del os.environ['SUB_IK_DIAG']
assert set(timed['stages']) >= {'sample', 'place', 'search', 'write'}, timed
assert timed['counts']['search'] > 0, timed
assert timed['stages']['search'] > 0.0, timed
assert timed['stages']['sample'] >= 0.0, timed

# Off by default: no stage is recorded at all, but reasons still are.
obj = reload()
ik.match(bpy.context, obj, _batch=True)
untimed = diag.record()
assert untimed['stages'] == {} and untimed['counts'] == {}, untimed
assert untimed['reasons'].get('sample') == 'ok', untimed

print('IK_DIAG_REASONS_OK')
