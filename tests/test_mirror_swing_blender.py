"""Mirroring must move swing bones on a vanilla Smash rig.

Requires the Shy Guy import (.tests/benchmarks/shyguy-export/imported.blend);
skips when it is absent. Swing chains (S_Cap, S_Skirt*_L/R) are keyed on top
of a real animation, then mirrored with the Smash Y flip. The check is that
the mesh deformation is mirrored: a vertex skinned to the source maps to its
mirror image skinned to the target. Shy Guy's skirt bones are placed slightly
asymmetrically, so this is stricter than mirroring each bone about its own rest.
"""
from pathlib import Path
import os

fixture = Path(__file__).with_name('test_addon_registration_blender.py')
exec(compile(fixture.read_text(encoding='utf-8').split('addon_utils.disable(MODULE')[0], str(fixture), 'exec'))
from mathutils import Matrix, Quaternion

mirror = importlib.import_module(MODULE + '.source.extras.mirror_animation')
flip = importlib.import_module(MODULE + '.source.extras.anim_flip')

BLEND = Path(os.environ.get(
    'SUB_SHYGUY_BLEND', ROOT / '.tests' / 'benchmarks' / 'shyguy-export' / 'imported.blend'))
if not BLEND.exists():
    print(f'SKIP mirror swing, no Shy Guy import at {BLEND}')
    raise SystemExit(0)

try:
    bpy.ops.wm.open_mainfile(filepath=str(BLEND))
except RuntimeError as error:
    # The fixture is saved by a newer Blender than the oldest supported one.
    print(f'SKIP mirror swing, cannot open {BLEND}: {error}')
    raise SystemExit(0)
obj = next(o for o in bpy.context.scene.objects if o.type == 'ARMATURE')
bpy.context.view_layer.objects.active = obj
for other in bpy.context.scene.objects:
    other.select_set(other is obj)
bpy.ops.object.mode_set(mode='POSE')
action = obj.animation_data.action
start, end = (int(round(v)) for v in action.frame_range)
frames = sorted({start, (start + end) // 2, end})

swing = [b for b in obj.pose.bones if b.name.startswith('S_')]
assert len(swing) > 20, [b.name for b in swing]
for index, bone in enumerate(swing):
    bone.rotation_mode = 'QUATERNION'
    for k, frame in enumerate(frames):
        bone.rotation_quaternion = Quaternion((1, .05 * (index % 5) - .1, .04 * k + .02, .03 * (index % 3))).normalized()
        bone.location = (.01 * k, -.02 * (index % 4), .015 * k)
        flip.keyframe_pose_bones([bone], frame)

mirror_map = flip.create_mirror_map(obj.pose.bones.keys())
animated = mirror._action_bone_names(action)
custom = set(flip.find_custom_mirror_bones(obj))
excluded = flip.collect_excluded_bone_names(obj, include_fingers=True)
# Unkeyed bones (Shy Guy's item rig) are left alone and simply follow Trans.
PAIRS = [(name, target) for name, target in mirror_map.items()
         if (name in animated or target in animated) and name not in excluded - custom]
assert mirror_map['S_Skirt1_L1'] == 'S_Skirt1_R1'
assert mirror_map['S_Skirt1_L3_null'] == 'S_Skirt1_R3_null'

before = {}
for frame in frames:
    bpy.context.scene.frame_set(frame)
    before[frame] = {p.name: p.matrix.copy() for p in obj.pose.bones}

ok, used_smash = mirror.apply_mirror_to_action(
    bpy.context, obj, action, 'Y', smash_y_anim_flip=True, include_fingers=True)
assert ok and used_smash

Y = Matrix.Diagonal((1, -1, 1, 1))
X = Matrix.Diagonal((-1, 1, 1, 1))
D = Matrix.Diagonal((1, 1, -1, 1))
worst = {}
for frame in frames:
    bpy.context.scene.frame_set(frame)
    for src, dst in PAIRS:
        if src in custom:
            # Extra and swing bones: the mesh deformation is mirrored.
            expected = (Y @ before[frame][src] @ obj.data.bones[src].matrix_local.inverted()
                        @ X @ obj.data.bones[dst].matrix_local)
        else:
            # Smash bones follow anim_flip exactly.
            expected = Y @ before[frame][src] @ D
        got = obj.pose.bones[dst].matrix
        error = max((got.translation - expected.translation).length,
                    max(abs(got[r][c] - expected[r][c]) for r in range(3) for c in range(3)))
        kind = 'swing' if src.startswith('S_') else 'body'
        worst[kind] = max(worst.get(kind, (0, None)), (error, (frame, src, dst)))
print('worst error', worst)
assert worst['swing'][0] < 1e-3 and worst['body'][0] < 1e-3, worst
print('MIRROR SWING TEST PASSED')
