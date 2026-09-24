"""Mirror a real moveset animation and report how far each bone class lands
from the correct mirror.

Not part of the suite: it reads a mod folder outside the repo.

SUB_MIRROR_MODEL=<fighter>/model/body/cXX  SUB_MIRROR_ANIM=<...>.nuanmb \
    python tests/run_blender_test.py --blender <blender> tests/check_moveset_mirror_blender.py

The model folder is copied first, so the mod itself is never touched. Swing
bones the animation leaves unkeyed get synthetic keys so they are exercised.
Smash bones must follow anim_flip (Y @ opposite @ local Z flip); extra and
swing bones must mirror the mesh deformation.
"""
from pathlib import Path
import os
import shutil
import tempfile

fixture = Path(__file__).with_name('test_addon_registration_blender.py')
exec(compile(fixture.read_text(encoding='utf-8').split('addon_utils.disable(MODULE')[0], str(fixture), 'exec'))
from mathutils import Matrix, Quaternion

model = importlib.import_module(MODULE + '.source.model.import_model')
anim = importlib.import_module(MODULE + '.source.anim.import_anim')
mirror = importlib.import_module(MODULE + '.source.extras.mirror_animation')
flip = importlib.import_module(MODULE + '.source.extras.anim_flip')

source = Path(os.environ['SUB_MIRROR_MODEL'])
animation = Path(os.environ['SUB_MIRROR_ANIM'])
smash_y = os.environ.get('SUB_MIRROR_SMASH_Y', '1') == '1'


class Reporter:
    def report(self, levels, message):
        print(levels, message, flush=True)


work = Path(tempfile.mkdtemp(prefix='sub_mirror_model_'))
shutil.copytree(source, work / 'model')
for obj in list(bpy.data.objects):
    bpy.data.objects.remove(obj, do_unlink=True)
props = bpy.context.scene.sub_scene_properties
props.model_import_folder_path = str(work / 'model')
model._assign_model_file_names(props, [p.name for p in (work / 'model').iterdir()])
assert model.import_model(Reporter(), bpy.context) == {'FINISHED'}
obj = next(o for o in bpy.context.scene.objects if o.type == 'ARMATURE')
bpy.context.view_layer.objects.active = obj
obj.select_set(True)
anim.import_animation_file(bpy.context, Reporter(), obj, str(animation), True, True, True, 1)
bpy.ops.object.mode_set(mode='POSE')
action = obj.animation_data.action
start, end = (int(round(v)) for v in action.frame_range)
frames = sorted({start, (start + end) // 3, 2 * (start + end) // 3, end})

animated = mirror._action_bone_names(action)
swing = [b for b in obj.pose.bones if b.name.startswith('S_')]
keyed_swing = [b.name for b in swing if b.name in animated]
for index, bone in enumerate(b for b in swing if b.name not in animated):
    bone.rotation_mode = 'QUATERNION'
    for k, frame in enumerate(frames):
        bone.rotation_quaternion = Quaternion((1, .05 * (index % 5) - .1, .04 * k + .02, .03 * (index % 3))).normalized()
        flip.keyframe_pose_bones([bone], frame)
animated = mirror._action_bone_names(action)

custom = set(flip.find_custom_mirror_bones(obj))
excluded = flip.collect_excluded_bone_names(obj, include_fingers=True)
custom_mirror = importlib.import_module(MODULE + '.source.extras.mirror_custom_bones')
mirror_map = custom_mirror.control_mirror_map(obj)
pairs = [(n, t) for n, t in mirror_map.items()
         if (n in animated or t in animated) and n not in excluded - custom]
unpaired = sorted(n for n in custom if mirror_map.get(n, n) == n and n[-1:] in 'LR' and n in animated)

before = {}
for frame in frames:
    bpy.context.scene.frame_set(frame)
    before[frame] = {p.name: p.matrix.copy() for p in obj.pose.bones}
ok, _ = mirror.apply_mirror_to_action(
    bpy.context, obj, action, 'Y', smash_y_anim_flip=smash_y, include_fingers=True)
assert ok

Y = Matrix.Diagonal((1, -1, 1, 1))
X = Matrix.Diagonal((-1, 1, 1, 1))
D = Matrix.Diagonal((1, 1, -1, 1))
worst, bad = {}, []
for frame in frames:
    bpy.context.scene.frame_set(frame)
    for src, dst in pairs:
        if src in custom:
            kind = 'swing' if src.startswith('S_') else 'extra'
            expected = (Y @ before[frame][src] @ obj.data.bones[src].matrix_local.inverted()
                        @ X @ obj.data.bones[dst].matrix_local)
        else:
            kind = 'body'
            expected = Y @ before[frame][src] @ D
        got = obj.pose.bones[dst].matrix
        error = max((got.translation - expected.translation).length,
                    max(abs(got[r][c] - expected[r][c]) for r in range(3) for c in range(3)))
        worst[kind] = max(worst.get(kind, (0, None)), (error, (frame, src, dst)))
        if error > 1e-3:
            bad.append((round(error, 4), frame, src, dst))
print('MODEL', source)
print('ANIM', animation.name, 'frames', frames, 'smash_y', smash_y)
print('SWING', len(swing), 'keyed by the animation', len(keyed_swing))
print('EXTRA', sorted(n for n in custom if not n.startswith('S_'))[:60])
print('UNPAIRED L/R-looking extras', unpaired)
print('PAIRED BY POSITION', sorted((n, t) for n, t in mirror_map.items()
                                  if n < t and flip.create_mirror_map(obj.pose.bones.keys()).get(n, n) == n))
print('WORST', worst)
for row in sorted(bad, reverse=True)[:25]:
    print('BAD', row)
print('MOVESET MIRROR CHECK DONE')
