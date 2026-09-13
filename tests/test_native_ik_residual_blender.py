"""Does the native backend fit the FK source as well as Blender's, per frame?

The bit-identity gate (docs/benchmarks/eigen-svd-gate-2026-09-12.md) fails only
in float32 rounding residue on matrix elements that are mathematically zero. The
criterion that matters to a user is different: the IK pose must reproduce the FK
animation at least as well as the current implementation does, on every frame.

This measures exactly the quantity the pole search minimises -- for each frame,
the sum over limb bones of the squared column differences between the solved
pose and the FK source -- once with Blender's backend and once with the native
one, and asserts the native residual is never worse.

Set SUB_NATIVE_RESIDUAL_MODE to override the native mode (default experimental,
which uses raw native results without verifying them against Blender).
"""
from pathlib import Path
import importlib
import json
import os

fixture = Path(__file__).with_name('test_addon_registration_blender.py')
exec(compile(fixture.read_text().split('addon_utils.disable(MODULE')[0], str(fixture), 'exec'))

ik_channels = importlib.import_module(MODULE + '.source.extras.ik_channels')
ik_native = importlib.import_module(MODULE + '.source.extras.ik_native')

BASELINE = Path(os.environ.get(
    'SUB_BASELINE_BLEND',
    ROOT / '.tests' / 'benchmarks' / 'ik_apply' / 'out' / 'baseline.blend'))
NATIVE_MODE = os.environ.get('SUB_NATIVE_RESIDUAL_MODE', 'experimental')

if not BASELINE.exists():
    print(f'SKIP native residual comparison, no baseline at {BASELINE}')
    raise SystemExit(0)

# Count how many chains actually reached the native solver, so a run where the
# guards silently declined cannot masquerade as a passing comparison.
solvers_created = {'count': 0}
_factory_call = ik_native.Factory.__call__


def counting_call(self, *args, **kwargs):
    solver = _factory_call(self, *args, **kwargs)
    solvers_created['count'] += int(solver is not None)
    return solver


ik_native.Factory.__call__ = counting_call


def active_armature():
    obj = next(o for o in bpy.context.scene.objects if o.type == 'ARMATURE')
    bpy.context.view_layer.objects.active = obj
    for other in bpy.context.scene.objects:
        other.select_set(other is obj)
    return obj


def limb_bone_names(obj):
    names = []
    for _kind, chain, _target, _pole in ik_channels.chains(obj, 'BOTH'):
        names.extend(ik_channels.limb_path(obj, chain))
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
    """Per frame, the quantity the pole search minimises.

    Mirrors error() in ik_channels: the sum over bones of the summed squared
    column differences. Column-wise rather than element-wise so orientation and
    translation are weighted exactly as the search weights them.
    """
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


def run(mode, names):
    """Match the whole animation under one backend and return per-frame residuals."""
    os.environ['SUB_NATIVE_IK'] = mode
    solvers_created['count'] = 0
    bpy.ops.wm.open_mainfile(filepath=str(BASELINE))
    obj = active_armature()
    if bpy.context.object.mode != 'POSE':
        bpy.ops.object.mode_set(mode='POSE')
    fk = capture(obj, names)
    ik_channels.create_controls(bpy.context, obj, 'BOTH')
    assert bpy.ops.sub.fk_to_ik_transfer(
        'EXEC_DEFAULT', cleanup_mode='BOTH', entire_animation=True,
        auto_keyframe=True, clean_animation=False) == {'FINISHED'}
    solved = capture(obj, names)
    return residuals(fk, solved, names), solvers_created['count'], solved


bpy.ops.wm.open_mainfile(filepath=str(BASELINE))
obj = active_armature()
if bpy.context.object.mode != 'POSE':
    bpy.ops.object.mode_set(mode='POSE')
ik_channels.create_controls(bpy.context, obj, 'BOTH')
names = limb_bone_names(obj)
assert names, 'no IK limb chains found on the baseline rig'

blender_residuals, blender_solvers, blender_poses = run('0', names)
native_residuals, native_solvers, native_poses = run(NATIVE_MODE, names)

assert blender_solvers == 0, f'the Blender run used {blender_solvers} native solvers'
assert native_solvers > 0, (
    'the native run created no solvers, so nothing was actually compared; '
    'check SUB_NATIVE_IK support and the per-frame guards')
assert set(blender_residuals) == set(native_residuals)

worse, better, equal = [], 0, 0
for frame in sorted(blender_residuals):
    a, b = blender_residuals[frame], native_residuals[frame]
    if b > a:
        worse.append((frame, a, b, b - a))
    elif b < a:
        better += 1
    else:
        equal += 1

worse.sort(key=lambda row: -row[3])

# Equal residual does not by itself prove equal pose: two different poses can
# fit the source equally well. Compare the solved matrices directly as well.
pose_delta = 0.0
pose_where = None
for frame in blender_poses:
    for name in names:
        a, b = blender_poses[frame][name], native_poses[frame][name]
        for r in range(4):
            for c in range(4):
                d = abs(a[r][c] - b[r][c])
                if d > pose_delta:
                    pose_delta, pose_where = d, f'{name}@{frame}[{r}][{c}]'
report = {
    'blender': bpy.app.version_string,
    'native_mode': NATIVE_MODE,
    'native_solvers': native_solvers,
    'frames': len(blender_residuals),
    'frames_worse': len(worse),
    'frames_better': better,
    'frames_equal': equal,
    'total_residual_blender': sum(blender_residuals.values()),
    'total_residual_native': sum(native_residuals.values()),
    'max_pose_difference': pose_delta,
    'max_pose_difference_at': pose_where,
    'worst_regressions': [
        {'frame': f, 'blender': a, 'native': b, 'delta': d} for f, a, b, d in worse[:8]
    ],
}
path = ROOT / '.tests/benchmarks/native_ik' / f'residual_{bpy.app.version[0]}.{bpy.app.version[1]}.json'
path.parent.mkdir(parents=True, exist_ok=True)
path.write_text(json.dumps(report, indent=2))
print('NATIVE_RESIDUAL ' + json.dumps(report))

assert not worse, (
    f'{len(worse)} frames fit worse than Blender, worst delta '
    f'{worse[0][3]:.3e} at frame {worse[0][0]}')
print('NATIVE_RESIDUAL_EQUAL_OR_BETTER_OK', flush=True)
if pose_delta == 0.0:
    print('NATIVE_POSE_BIT_IDENTICAL_OK', flush=True)
