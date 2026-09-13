"""Widen the native-vs-Blender residual comparison across rig configurations.

tests/test_native_ik_residual_blender.py establishes the property on one plain
rig. This runs the same two comparisons across the configurations that
test_ik_match_fast_blender.py constructs -- object and parent scale, scale
inheritance, stretch, arm pull, foot controls, animated stretch -- plus limb
subsets, so the evidence is not confined to a single well-behaved case.

Two things are checked per configuration:
  * per frame, the native residual against the FK source is never worse than
    Blender's, and
  * the solved pose matrices from the two backends, compared element by element.

A configuration where the per-frame guards decline native matching is recorded
with native_solvers == 0 and reported rather than silently counted as a pass.
"""
from pathlib import Path
import importlib
import json
import os

fixture = Path(__file__).with_name('test_addon_registration_blender.py')
exec(compile(fixture.read_text().split('addon_utils.disable(MODULE')[0], str(fixture), 'exec'))

ik = importlib.import_module(MODULE + '.source.extras.ik_channels')
ik_native = importlib.import_module(MODULE + '.source.extras.ik_native')

BASELINE = Path(os.environ.get(
    'SUB_BASELINE_BLEND',
    ROOT / '.tests' / 'benchmarks' / 'ik_apply' / 'out' / 'baseline.blend'))
NATIVE_MODE = os.environ.get('SUB_NATIVE_RESIDUAL_MODE', 'experimental')

if not BASELINE.exists():
    print(f'SKIP native residual matrix, no baseline at {BASELINE}')
    raise SystemExit(0)

solvers = {'count': 0}
_factory_call = ik_native.Factory.__call__


def counting_call(self, *args, **kwargs):
    solver = _factory_call(self, *args, **kwargs)
    solvers['count'] += int(solver is not None)
    return solver


ik_native.Factory.__call__ = counting_call


def active_armature():
    obj = next(o for o in bpy.context.scene.objects if o.type == 'ARMATURE')
    bpy.context.view_layer.objects.active = obj
    for other in bpy.context.scene.objects:
        other.select_set(other is obj)
    return obj


def limb_bone_names(obj, limbs):
    names = []
    for _kind, chain, _target, _pole in ik.chains(obj, limbs):
        names.extend(ik.limb_path(obj, chain))
    return list(dict.fromkeys(names))


def capture(obj, names):
    scene = bpy.context.scene
    poses = {}
    for frame in range(scene.frame_start, scene.frame_end + 1):
        scene.frame_set(frame)
        bpy.context.view_layer.update()
        poses[frame] = {n: obj.pose.bones[n].matrix.copy() for n in names}
    return poses


def residuals(reference, solved, names):
    out = {}
    for frame, before in reference.items():
        after = solved[frame]
        total = 0.0
        for name in names:
            a, b = before[name], after[name]
            for i in range(4):
                total += (a.col[i] - b.col[i]).length_squared
        out[frame] = total
    return out


def configure(obj, scenario):
    """Reproduce the rig configurations from test_ik_match_fast_blender.py."""
    scene = bpy.context.scene
    jobs = list(ik.chains(obj))
    if scenario == 'object_scale':
        obj.scale = (1.2, .7, 1.1)
        obj.rotation_euler = (.21, -.37, .14)
    elif scenario == 'parent_scale':
        pb = obj.pose.bones[ik.PREFIX + ik.limb_path(obj, jobs[0][1])[0]].parent
        pb.scale = (1.2, .7, 1.1)
        for f in range(scene.frame_start, scene.frame_end + 1):
            pb.keyframe_insert('scale', frame=f)
    elif scenario == 'inheritance':
        for _, names, _, _ in jobs:
            for n in ik.limb_path(obj, names):
                obj.data.bones[n].inherit_scale = 'ALIGNED'
                obj.data.bones[ik.PREFIX + n].inherit_scale = 'ALIGNED'
    elif scenario in {'stretch', 'arm_pull', 'animated_stretch'}:
        obj.data.sub_ik_stretch_arms = True
        obj.data.sub_ik_stretch_legs = True
        obj.data.sub_ik_stretch_chain_arms = True
        obj.data.sub_ik_stretch_chain_legs = True
        if scenario == 'arm_pull':
            for kind, _, _, pole in jobs:
                if kind == 'ARMS':
                    setattr(obj.data.bones[pole], ik.ARM_PULL_PROPERTY, .7)
        elif scenario == 'animated_stretch':
            for f in range(scene.frame_start, scene.frame_end + 1):
                obj.data.sub_ik_stretch_arms = bool(f % 2)
                obj.data.keyframe_insert('sub_ik_stretch_arms', frame=f)
    elif scenario == 'foot_controls':
        for _, names, _, _ in jobs:
            foot = ik.foot_controls(names, obj)
            if foot:
                obj.pose.bones[foot[0]].rotation_euler.x = .3
                obj.pose.bones[foot[1]].rotation_euler.x = -.2


def run(scenario, limbs, mode):
    os.environ['SUB_NATIVE_IK'] = mode
    solvers['count'] = 0
    bpy.ops.wm.open_mainfile(filepath=str(BASELINE))
    obj = active_armature()
    if bpy.context.object.mode != 'POSE':
        bpy.ops.object.mode_set(mode='POSE')
    ik.create_controls(bpy.context, obj, 'BOTH')
    names = limb_bone_names(obj, limbs)
    configure(obj, scenario)
    fk = capture(obj, names)
    ik.match(bpy.context, obj, limbs=limbs, entire=True, key=True, _batch=True)
    solved = capture(obj, names)
    return residuals(fk, solved, names), solved, names, solvers['count']


CONFIGURATIONS = [
    ('normal', 'BOTH'),
    ('normal', 'ARMS'),
    ('normal', 'LEGS'),
    ('object_scale', 'BOTH'),
    ('parent_scale', 'BOTH'),
    ('inheritance', 'BOTH'),
    ('stretch', 'BOTH'),
    ('arm_pull', 'BOTH'),
    ('animated_stretch', 'BOTH'),
    ('foot_controls', 'BOTH'),
]

rows = []
failures = []
for scenario, limbs in CONFIGURATIONS:
    base_residuals, base_poses, names, base_solvers = run(scenario, limbs, '0')
    native_residuals, native_poses, _, native_solvers = run(scenario, limbs, NATIVE_MODE)
    assert base_solvers == 0, f'{scenario}/{limbs} used {base_solvers} native solvers on the Blender pass'

    worse = []
    for frame in base_residuals:
        a, b = base_residuals[frame], native_residuals[frame]
        if b > a:
            worse.append((frame, b - a))
    worse.sort(key=lambda row: -row[1])

    pose_delta, pose_where = 0.0, None
    for frame in base_poses:
        for name in names:
            a, b = base_poses[frame][name], native_poses[frame][name]
            for r in range(4):
                for c in range(4):
                    d = abs(a[r][c] - b[r][c])
                    if d > pose_delta:
                        pose_delta, pose_where = d, f'{name}@{frame}[{r}][{c}]'

    row = dict(scenario=scenario, limbs=limbs, native_solvers=native_solvers,
               frames=len(base_residuals), bones=len(names),
               frames_worse=len(worse), max_pose_difference=pose_delta,
               max_pose_difference_at=pose_where,
               worst_residual_delta=worse[0][1] if worse else 0.0,
               total_residual_blender=sum(base_residuals.values()),
               total_residual_native=sum(native_residuals.values()))
    rows.append(row)
    print('RESIDUAL_ROW ' + json.dumps(row), flush=True)
    if worse:
        failures.append(row)

engaged = [r for r in rows if r['native_solvers'] > 0]
declined = [r for r in rows if r['native_solvers'] == 0]
report = dict(blender=bpy.app.version_string, native_mode=NATIVE_MODE, rows=rows,
              configurations=len(rows), native_engaged=len(engaged),
              guards_declined=[f"{r['scenario']}/{r['limbs']}" for r in declined],
              bit_identical=[f"{r['scenario']}/{r['limbs']}" for r in engaged
                             if r['max_pose_difference'] == 0.0])
path = ROOT / '.tests/benchmarks/native_ik' / f'residual_matrix_{bpy.app.version[0]}.{bpy.app.version[1]}.json'
path.parent.mkdir(parents=True, exist_ok=True)
path.write_text(json.dumps(report, indent=2))
print('NATIVE_RESIDUAL_MATRIX ' + json.dumps({k: v for k, v in report.items() if k != 'rows'}))

assert engaged, 'no configuration engaged the native solver; nothing was compared'
assert not failures, failures
print('NATIVE_RESIDUAL_MATRIX_OK', flush=True)
