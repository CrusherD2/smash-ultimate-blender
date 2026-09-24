"""Mirroring an IK-driven Smash animation must mirror the visible limbs.

Requires the IK benchmark baseline (.tests/benchmarks/ik_apply/out/baseline.blend);
skips when it is absent, since there is no synthetic stand-in for a real
Smash limb chain.

After FK→IK transfer the Smash limb bones only follow the IK controls, so the
mirror has to move FootIK/KneeIK/HandIK/ArmIK, their foot-roll children, the
solver chain and the keyed pole angles to the other side. The check is the
anim_flip invariant for Smash bones: mirrored world = Y reflection @ opposite
world @ local Z flip.
"""
from pathlib import Path
import importlib
import os

fixture = Path(__file__).with_name('test_addon_registration_blender.py')
exec(compile(fixture.read_text(encoding='utf-8').split('addon_utils.disable(MODULE')[0], str(fixture), 'exec'))
from mathutils import Matrix

ik_channels = importlib.import_module(MODULE + '.source.extras.ik_channels')
mirror = importlib.import_module(MODULE + '.source.extras.mirror_animation')
flip = importlib.import_module(MODULE + '.source.extras.anim_flip')

BASELINE = Path(os.environ.get(
    'SUB_BASELINE_BLEND',
    ROOT / '.tests' / 'benchmarks' / 'ik_apply' / 'out' / 'baseline.blend'))
if not BASELINE.exists():
    print(f'SKIP mirror IK rig, no baseline at {BASELINE}')
    raise SystemExit(0)

bpy.ops.wm.open_mainfile(filepath=str(BASELINE))
obj = next(o for o in bpy.context.scene.objects if o.type == 'ARMATURE')
bpy.context.view_layer.objects.active = obj
for other in bpy.context.scene.objects:
    other.select_set(other is obj)
bpy.ops.object.mode_set(mode='POSE')
ik_channels.create_controls(bpy.context, obj, 'BOTH')
bpy.ops.sub.fk_to_ik_transfer(
    'EXEC_DEFAULT', cleanup_mode='BOTH', entire_animation=True,
    auto_keyframe=True, clean_animation=False)
assert any(flip.is_ik_control(n) for n in obj.pose.bones.keys())

action = obj.animation_data.action
start, end = (int(round(v)) for v in action.frame_range)
frames = sorted({start, (start + end) // 2, end})
LIMBS = [name for name in obj.pose.bones.keys()
         if name.endswith('L') and name[:-1] + 'R' in obj.pose.bones
         and name.startswith(('Leg', 'Knee', 'Foot', 'Toe', 'Shoulder', 'Arm', 'Hand'))
         and 'IK' not in name]
assert {'LegL', 'KneeL', 'FootL', 'ArmL', 'HandL'} <= set(LIMBS), LIMBS

before = {}
for frame in frames:
    bpy.context.scene.frame_set(frame)
    before[frame] = {p.name: p.matrix.copy() for p in obj.pose.bones}

ok, used_smash = mirror.apply_mirror_to_action(
    bpy.context, obj, action, 'Y', smash_y_anim_flip=True, include_fingers=True)
assert ok and used_smash

Y = Matrix.Diagonal((1, -1, 1, 1))
D = Matrix.Diagonal((1, 1, -1, 1))
worst = (0, None)
for frame in frames:
    bpy.context.scene.frame_set(frame)
    for left in LIMBS:
        for src, dst in ((left, left[:-1] + 'R'), (left[:-1] + 'R', left)):
            expected = Y @ before[frame][src] @ D
            got = obj.pose.bones[dst].matrix
            position = (got.translation - expected.translation).length
            rotation = max(abs(got[r][c] - expected[r][c]) for r in range(3) for c in range(3))
            worst = max(worst, (max(position, rotation), (frame, src, dst, position, rotation)))
print('worst limb error', worst)
assert worst[0] < 2e-3, worst
print('MIRROR IK RIG TEST PASSED')
