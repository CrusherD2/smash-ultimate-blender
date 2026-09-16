"""The audit split keeps batching identical and admits single chains."""
from pathlib import Path
import os, importlib

root = Path(__file__).resolve().parents[1]
bench = root/'tests/benchmark_position_ik_blender.py'
exec(compile(bench.read_text().split("\nfor repeat in range(int(os.environ.get('SUB_MATCH_RUNS'")[0], str(bench), 'exec'))
os.environ['SUB_NATIVE_IK'] = '0'
diag = importlib.import_module(MODULE+'.source.extras.ik_match_diag')

def reload():
    bpy.ops.wm.open_mainfile(filepath=str(baseline))
    obj = next(o for o in bpy.context.scene.objects if o.type == 'ARMATURE')
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    ik.create_controls(bpy.context, obj, 'BOTH')
    bpy.context.scene.frame_end = bpy.context.scene.frame_start + 15
    return obj

# A clean rig batches and is self-contained.
obj = reload()
jobs = list(ik.chains(obj))
assert len(jobs) >= 2, jobs
assert ik._can_batch_match(obj, jobs)
assert ik._is_self_contained(obj, jobs)

# One chain cannot batch, but is still self-contained. This is the whole point.
single = jobs[:1]
diag.reset()
assert not ik._can_batch_match(obj, single)
assert diag.record()['reasons']['batch'] == 'single_chain', diag.record()
assert ik._is_self_contained(obj, single)

# An external parent fails both.
obj = reload()
jobs = list(ik.chains(obj))
empty = bpy.data.objects.new('external', None)
bpy.context.scene.collection.objects.link(empty)
obj.parent = empty
assert not ik._can_batch_match(obj, jobs)
diag.reset()
assert not ik._is_self_contained(obj, jobs)
assert diag.record()['reasons']['selfcontained'] == 'object_parent', diag.record()
obj.parent = None

# A constraint pointing outside the armature fails both.
obj = reload()
jobs = list(ik.chains(obj))
empty = bpy.data.objects.new('external', None)
bpy.context.scene.collection.objects.link(empty)
source_bone = ik.limb_path(obj, jobs[0][1])[0]
con = obj.pose.bones[source_bone].constraints.new('COPY_LOCATION')
con.target = empty
assert not ik._is_self_contained(obj, jobs)
assert not ik._can_batch_match(obj, jobs)
obj.pose.bones[source_bone].constraints.remove(con)

# One island vs. one island per chain.
obj = reload()
jobs = list(ik.chains(obj))
owners = ik._dependency_audit(obj, jobs, separate=False)
assert owners is not None and set(owners.values()) == {0}, sorted(set(owners.values()))
split = ik._dependency_audit(obj, jobs, separate=True)
assert split is not None and len(set(split.values())) == len(jobs), sorted(set(split.values()))
print('IK_DEPENDENCY_AUDIT_OK')
