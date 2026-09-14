"""Compare any two IK match implementations under the project's acceptance gate.

Generalised from tests/test_native_ik_residual_matrix_blender.py, which compared
exactly two hard-coded backends. The residual and pose comparisons are unchanged;
what is new is that the implementation under test is selected by name, and that
the verdict carries a tolerance instead of demanding no frame ever fit worse.
"""
import importlib, json, os, statistics, time
from pathlib import Path
import bpy

MODULE = None

# Set by the importing test script, which has already resolved the add-on module.
def bind(module_name):
    global ik, ik_native, diag, MODULE
    MODULE = module_name
    ik = importlib.import_module(MODULE + '.source.extras.ik_channels')
    ik_native = importlib.import_module(MODULE + '.source.extras.ik_native')
    diag = importlib.import_module(MODULE + '.source.extras.ik_match_diag')


TOLERANCE = {'relative': 1e-5, 'pose': 1e-4}

# 'env' is applied before the run; every key absent from a variant's env is
# removed, so variants cannot leak into one another. 'engage' names the
# ik_match_diag count that proves the variant actually ran.
VARIANTS = {
    'blender':  {'env': {'SUB_NATIVE_IK': '0'},                              'engage': None},
    'native':   {'env': {'SUB_NATIVE_IK': 'experimental'},                   'engage': 'native_solves'},
    'adaptive': {'env': {'SUB_NATIVE_IK': '0', 'SUB_IK_ADAPTIVE': '1'},      'engage': 'adaptive_early'},
}
_MANAGED = ('SUB_NATIVE_IK', 'SUB_IK_ADAPTIVE')


def apply_env(variant):
    for key in _MANAGED:
        os.environ.pop(key, None)
    os.environ.update(VARIANTS[variant]['env'])
    pass  # DIAG_DISABLED_FOR_TEST


def require_engaged(variant, run):
    key = VARIANTS[variant]['engage']
    if key is None:
        return
    assert run['counts'].get(key, 0) > 0, (
        f'variant {variant!r} never engaged: {key} was {run["counts"].get(key, 0)}')


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


def run_variant(variant, source, scenario, limbs):
    apply_env(variant)
    bpy.ops.wm.open_mainfile(filepath=str(source))
    obj = active_armature()
    if bpy.context.object.mode != 'POSE':
        bpy.ops.object.mode_set(mode='POSE')
    ik.create_controls(bpy.context, obj, 'BOTH')
    names = limb_bone_names(obj, limbs)
    configure(obj, scenario)
    fk = capture(obj, names)
    start = time.perf_counter()
    ik.match(bpy.context, obj, limbs=limbs, entire=True, key=True, _batch=True)
    seconds = time.perf_counter() - start
    solved = capture(obj, names)
    return dict(residuals=residuals(fk, solved, names), poses=solved, names=names,
                counts=dict(diag.record()['counts']), seconds=seconds)


def compare(baseline, candidate, names, tolerance):
    base_r, cand_r = baseline['residuals'], candidate['residuals']
    worse = better = identical = 0
    worst_rel, worst_frame = 0.0, None
    deltas = []
    for frame, a in base_r.items():
        b = cand_r[frame]
        delta = b - a
        deltas.append(delta)
        if delta > 0:
            worse += 1
            # Relative to this frame's own baseline, so a large-residual frame
            # is not held to the same absolute bar as a near-perfect one.
            rel = delta / a if a > 0 else float('inf')
            if rel > worst_rel:
                worst_rel, worst_frame = rel, frame
        elif delta < 0:
            better += 1
        else:
            identical += 1

    pose_delta, pose_where = 0.0, None
    for frame, before in baseline['poses'].items():
        after = candidate['poses'][frame]
        for name in names:
            a, b = before[name], after[name]
            for r in range(4):
                for c in range(4):
                    d = abs(a[r][c] - b[r][c])
                    if d > pose_delta:
                        pose_delta, pose_where = d, f'{name}@{frame}[{r}][{c}]'

    median_delta = statistics.median(deltas) if deltas else 0.0
    total_delta = sum(cand_r.values()) - sum(base_r.values())
    passed = (worst_rel <= tolerance['relative']
              and median_delta <= 0.0
              and total_delta <= 0.0
              and pose_delta <= tolerance['pose'])
    return dict(frames_worse=worse, frames_better=better, frames_identical=identical,
                worst_relative_delta=worst_rel, worst_relative_frame=worst_frame,
                median_delta=median_delta, total_delta=total_delta,
                max_pose_difference=pose_delta, max_pose_difference_at=pose_where,
                passed=passed)
