"""Generate a near-straight limb fixture: the pole search's worst case."""
from pathlib import Path
import math
fixture = Path(__file__).with_name('test_addon_registration_blender.py')
exec(compile(fixture.read_text().split('addon_utils.disable(MODULE')[0], str(fixture), 'exec'))
import importlib
ik = importlib.import_module(MODULE + '.source.extras.ik_channels')

BASELINE = ROOT / '.tests/benchmarks/ik_apply/out/baseline.blend'
OUT = ROOT / '.tests/benchmarks/ik_corpus/near_straight.blend'
assert BASELINE.exists(), BASELINE
bpy.ops.wm.open_mainfile(filepath=str(BASELINE))
obj = next(o for o in bpy.context.scene.objects if o.type == 'ARMATURE')
bpy.context.view_layer.objects.active = obj
obj.select_set(True)
if bpy.context.object.mode != 'POSE':
    bpy.ops.object.mode_set(mode='POSE')
scene = bpy.context.scene
scene.frame_end = scene.frame_start + 39
# ik.chains() enumerates by looking up the FootIK/HandIK control bones by name
# (see fk_to_ik.iter_leg_fk_chains/iter_arm_fk_chains); baseline.blend does not
# ship with those bones until create_controls() has run, so without this call
# the loop below silently iterates zero chains and no keyframes are written.
ik.create_controls(bpy.context, obj, 'BOTH')
for _kind, chain, _t, _p in ik.chains(obj, 'BOTH'):
    path = ik.limb_path(obj, chain)
    middle = obj.pose.bones[ik.bend_name(obj, chain)]
    middle.rotation_mode = 'XYZ'
    for index, frame in enumerate(range(scene.frame_start, scene.frame_end + 1)):
        t = index / (scene.frame_end - scene.frame_start)
        # 0.9 rad of bend down to 0.002 rad: straight enough that the bend plane
        # is nearly undefined, without being exactly singular.
        middle.rotation_euler.x = 0.9 * (1.0 - t) + 0.002 * t
        middle.keyframe_insert('rotation_euler', index=0, frame=frame)
OUT.parent.mkdir(parents=True, exist_ok=True)
bpy.ops.wm.save_as_mainfile(filepath=str(OUT))
print(f'NEAR_STRAIGHT_FIXTURE_OK {OUT} frames={scene.frame_end - scene.frame_start + 1}')
