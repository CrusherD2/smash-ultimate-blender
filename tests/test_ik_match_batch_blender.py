"""Modern generated rigs batch; user dependencies must retain serial solving."""
from pathlib import Path
import importlib
import os
import tempfile

fixture = Path(__file__).with_name('test_addon_registration_blender.py')
exec(compile(fixture.read_text().split('addon_utils.disable(MODULE')[0], str(fixture), 'exec'))
ik = importlib.import_module(MODULE + '.source.extras.ik_channels')
baseline = Path(os.environ.get('SUB_BASELINE_BLEND', ROOT / '.tests/benchmarks/ik_apply/out/baseline.blend'))
if not baseline.exists():
    print(f'SKIP IK match batching: missing real-rig fixture {baseline}')
    raise SystemExit(0)
bpy.ops.wm.open_mainfile(filepath=str(baseline))
obj = next(o for o in bpy.context.scene.objects if o.type == 'ARMATURE')
bpy.context.view_layer.objects.active = obj
obj.select_set(True)
ik.create_controls(bpy.context, obj, 'BOTH')


def can_batch(limbs='BOTH'):
    states = [(c, c.mute) for _, c, _ in
              (*ik.outputs(obj, limbs), *ik.toe_outputs(obj, limbs))]
    try:
        for con, _ in states:
            con.mute = True
        return ik._can_batch_match(obj, list(ik.chains(obj, limbs)))
    finally:
        for con, mute in states:
            con.mute = mute


for limbs in ('ARMS', 'LEGS', 'BOTH'):
    assert can_batch(limbs), limbs

# Read-only property inputs for stretch/pull are safe, pose-transform inputs aren't.
fc = next(fc for fc in obj.animation_data.drivers if 'SUB IK Arm Pull' in fc.data_path)
variable = fc.driver.variables[0]
prop = variable.targets[0].data_path
variable.type = 'TRANSFORMS'
variable.targets[0].id = obj
variable.targets[0].bone_target = 'HandIKR'
assert not can_batch()
variable.type = 'SINGLE_PROP'
variable.targets[0].id_type = 'ARMATURE'
variable.targets[0].id = obj.data
variable.targets[0].data_path = prop
assert can_batch()

bone = obj.pose.bones[ik.PREFIX + 'ArmL']
con = bone.constraints.new('COPY_ROTATION')
con.target, con.subtarget = obj, 'HandIKR'
assert not can_batch()
con.mute = True
assert not can_batch(), 'a custom constraint may be animated back on'
bone.constraints.remove(con)

con = bone.constraints.new('COPY_LOCATION')
empty = bpy.data.objects.new('External dependency', None)
bpy.context.scene.collection.objects.link(empty)
con.target = empty
assert not can_batch()
bone.constraints.remove(con)

# Even a currently muted constraint with animated settings must fall back.
con = bone.constraints.new('COPY_ROTATION')
con.target, con.subtarget = obj, 'HandIKL'
con.keyframe_insert('mute', frame=1)
assert not can_batch()
con.keyframe_delete('mute', frame=1)
path = con.path_from_id()
compat = importlib.import_module(MODULE + '.source.anim.fcurve_compat')
for fc in list(compat.get_all_action_fcurves(obj.animation_data.action, id_type='OBJECT')):
    if fc.data_path.startswith(path):
        compat.remove_fcurve(obj.animation_data.action, fc)
bone.constraints.remove(con)
assert can_batch()

# A solver may never reach above the verified chain.
solver = bone.constraints['SUB IK Solve']
count = solver.chain_count
solver.chain_count = 0
assert not can_batch()
solver.chain_count = count + 1
assert not can_batch()
solver.chain_count = count
assert can_batch()
solver.name = 'Legacy solver'
assert not can_batch(), 'incomplete independent solver generation must fall back'
solver.name = 'SUB IK Solve'
assert can_batch()
print('Modern IK batch guard and dependency fallbacks OK')

# Serial and batched matching start from the very same rig/action state.
def capture():
    action = obj.animation_data.action
    keys = {(fc.data_path, fc.array_index): [tuple(k.co) for k in fc.keyframe_points]
            for fc in compat.get_all_action_fcurves(action, id_type='OBJECT')}
    poses = []
    for frame in range(bpy.context.scene.frame_start, bpy.context.scene.frame_end + 1):
        bpy.context.scene.frame_set(frame)
        poses.extend(float(v) for b in obj.pose.bones if b.bone.use_deform
                     for row in b.matrix for v in row)
    return keys, poses


with tempfile.TemporaryDirectory(prefix='sub_match_batch_') as folder:
    path = str(Path(folder) / 'rig.blend')
    bpy.ops.wm.save_as_mainfile(filepath=path)
    for limbs in ('BOTH', 'ARMS', 'LEGS'):
        snapshots = []
        for batch in (False, True):
            bpy.ops.wm.open_mainfile(filepath=path)
            obj = bpy.context.object
            ik.match(bpy.context, obj, limbs, _batch=batch)
            snapshots.append(capture())
        (keys_a, poses_a), (keys_b, poses_b) = snapshots
        assert keys_a == keys_b, limbs + ' changed keys'
        error = max(abs(a-b) for a,b in zip(poses_a, poses_b))
        assert error < 1e-4, (limbs, error)
        print('BATCH_EQUIVALENCE', limbs, error)
