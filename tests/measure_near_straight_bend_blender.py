"""Measure the near-straight fixture's actual geometric bend angle.

Reviewer finding: the min/max bend-angle table in the Task 2 report was
produced by an ad hoc scratch script that was never committed, so nobody could
re-run or audit it. This is that script, committed, so the claim that
near_straight.blend reaches genuinely near-collinear geometry is evidence, not
an assertion.

Trusting the generator's local-rotation constants (0.9 rad down to 0.002 rad,
see build_near_straight_fixture_blender.py) would not prove the *limb* actually
approaches straight: that value is a local Euler rotation on the middle joint,
not the geometric angle a solver would see between the two limb segments in
world space. This script computes the latter directly, per chain, per frame,
and prints the observed min/max -- the number that matters is the minimum
(how close to genuinely straight the clip gets), not the maximum.
"""
from pathlib import Path
import importlib, sys
fixture = Path(__file__).with_name('test_addon_registration_blender.py')
exec(compile(fixture.read_text().split('addon_utils.disable(MODULE')[0], str(fixture), 'exec'))
ik = importlib.import_module(MODULE + '.source.extras.ik_channels')

sys.path.insert(0, str(Path(__file__).parent))
corpus = importlib.import_module('ik_match_corpus')

assert corpus.NEAR_STRAIGHT.exists(), f'fixture missing at {corpus.NEAR_STRAIGHT}; ' \
    'run build_near_straight_fixture_blender.py first'
bpy.ops.wm.open_mainfile(filepath=str(corpus.NEAR_STRAIGHT))
obj = next(o for o in bpy.context.scene.objects if o.type == 'ARMATURE')
bpy.context.view_layer.objects.active = obj
obj.select_set(True)
if bpy.context.object.mode != 'POSE':
    bpy.ops.object.mode_set(mode='POSE')
scene = bpy.context.scene
ik.create_controls(bpy.context, obj, 'BOTH')  # chains() needs the control bones to exist

overall = []
for _kind, chain, _t, _p in ik.chains(obj, 'BOTH'):
    path = ik.limb_path(obj, chain)
    root_name, mid_name, end_name = path[0], ik.bend_name(obj, chain), path[-1]
    per_chain = []
    for frame in range(scene.frame_start, scene.frame_end + 1):
        scene.frame_set(frame)
        bpy.context.view_layer.update()
        root = obj.pose.bones[root_name].head
        mid = obj.pose.bones[mid_name].head
        end = obj.pose.bones[end_name].head
        v1, v2 = mid - root, end - mid
        if v1.length < 1e-9 or v2.length < 1e-9:
            continue
        per_chain.append(v1.angle(v2))
    print(f'BEND_ANGLE chain={chain} min={min(per_chain):.6f} max={max(per_chain):.6f} rad')
    overall.extend(per_chain)

print(f'BEND_ANGLE_OVERALL min={min(overall):.6f} max={max(overall):.6f} rad')
print('NEAR_STRAIGHT_BEND_MEASURE_OK')
