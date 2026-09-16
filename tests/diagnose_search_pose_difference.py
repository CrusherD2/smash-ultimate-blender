"""Which bones differ between the per-candidate and whole-search native paths?

The benchmark reports identical key fingerprints but different whole-rig pose
fingerprints. The residual matrix only compares limb-chain bones, so this walks
every pose bone at every frame to locate the difference.
"""
from pathlib import Path
import importlib
import json
import os

fixture = Path(__file__).with_name('test_addon_registration_blender.py')
exec(compile(fixture.read_text().split('addon_utils.disable(MODULE')[0], str(fixture), 'exec'))

ik = importlib.import_module(MODULE + '.source.extras.ik_channels')
curves = importlib.import_module(MODULE + '.source.anim.fcurve_compat')

BASELINE = Path(os.environ.get(
    'SUB_BASELINE_BLEND',
    ROOT / '.tests' / 'benchmarks' / 'ik_apply' / 'out' / 'baseline.blend'))


def run(search):
    os.environ['SUB_NATIVE_IK'] = 'experimental'
    os.environ['SUB_NATIVE_SEARCH'] = search
    bpy.ops.wm.open_mainfile(filepath=str(BASELINE))
    obj = next(o for o in bpy.context.scene.objects if o.type == 'ARMATURE')
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    ik.create_controls(bpy.context, obj, 'BOTH')
    ik.match(bpy.context, obj, _batch=True)
    scene = bpy.context.scene
    poses = {}
    for frame in range(scene.frame_start, scene.frame_end + 1):
        scene.frame_set(frame)
        poses[frame] = {b.name: [list(r) for r in b.matrix] for b in obj.pose.bones}
    keys = sorted((fc.data_path, fc.array_index, [tuple(k.co) for k in fc.keyframe_points])
                  for fc in curves.get_all_action_fcurves(obj.animation_data.action, id_type='OBJECT'))
    return poses, keys


off_poses, off_keys = run('0')
on_poses, on_keys = run('1')

print('KEYS_IDENTICAL', off_keys == on_keys, flush=True)

worst = {}
for frame in off_poses:
    for name, a in off_poses[frame].items():
        b = on_poses[frame][name]
        delta = max(abs(a[r][c] - b[r][c]) for r in range(4) for c in range(4))
        if delta > 0.0 and delta > worst.get(name, (0.0, 0))[0]:
            worst[name] = (delta, frame)

print('BONES_DIFFERING', len(worst), 'of', len(off_poses[min(off_poses)]), flush=True)
for name, (delta, frame) in sorted(worst.items(), key=lambda kv: -kv[1][0])[:12]:
    print(f'  {name:28s} max_delta={delta:.6e} @frame {frame}', flush=True)

path = ROOT / '.tests/benchmarks/native_ik' / f'search_pose_diff_{bpy.app.version[0]}.{bpy.app.version[1]}.json'
path.parent.mkdir(parents=True, exist_ok=True)
path.write_text(json.dumps({
    'keys_identical': off_keys == on_keys,
    'bones_differing': {k: {'delta': v[0], 'frame': v[1]} for k, v in worst.items()},
}, indent=2))
print('DIAGNOSE_DONE', flush=True)
