import importlib
import json
import math
import os
from pathlib import Path
import time

import bpy

INSTALL = Path(__file__).resolve().parents[1]
ROOT = Path(os.environ.get('SUB_BENCH_ROOT', str(INSTALL)))
fixture = INSTALL / 'tests/test_addon_registration_blender.py'
prefix = fixture.read_text().split("floor = importlib.import_module")[0]
prefix = prefix.replace("ROOT = Path(__file__).resolve().parents[1]", "ROOT = Path(os.environ['SUB_BENCH_ROOT'])")
exec(compile(prefix, str(fixture), 'exec'))
ik = importlib.import_module(MODULE + '.source.extras.ik_channels')
rig = importlib.import_module(MODULE + '.source.extras.create_animation_rig')


def build(frames):
    if bpy.context.object and bpy.context.object.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete(use_global=False)
    for action in list(bpy.data.actions):
        if action.users == 0:
            bpy.data.actions.remove(action)
    data = bpy.data.armatures.new('Benchmark')
    obj = bpy.data.objects.new('Benchmark', data)
    bpy.context.collection.objects.link(obj)
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    bpy.ops.object.mode_set(mode='EDIT')
    hip = data.edit_bones.new('Hip')
    hip.head, hip.tail = (0, 0, 4), (0, 0, 5)
    names = []
    for side, x in (('L', 1), ('R', -1)):
        for chain in (
            (('Leg', (x, 0, 4), (x, -.3, 2)), ('Knee', (x, -.3, 2), (x, 0, 0)),
             ('Foot', (x, 0, 0), (x, -1, 0)), ('Toe', (x, -1, 0), (x, -1.5, 0))),
            (('Shoulder', (x * 1.2, 0, 4.6), (x * 2.8, .2, 4.6)),
             ('Arm', (x * 2.8, .2, 4.6), (x * 4.4, 0, 4.6)),
             ('Hand', (x * 4.4, 0, 4.6), (x * 5, 0, 4.6))),
        ):
            parent = hip
            for name, head, tail in chain:
                bone = data.edit_bones.new(name + side)
                bone.head, bone.tail, bone.parent = head, tail, parent
                names.append(bone.name)
                parent = bone
    bpy.ops.object.mode_set(mode='POSE')
    scene = bpy.context.scene
    scene.frame_start, scene.frame_end = 1, frames
    for frame in range(1, frames + 1):
        scene.frame_set(frame)
        for index, name in enumerate(names):
            bone = obj.pose.bones[name]
            bone.rotation_mode = 'XYZ'
            phase = frame * .045 + index * .27
            bone.rotation_euler = (.12 * math.sin(phase), .08 * math.cos(phase), .18 * math.sin(phase * .7))
            bone.keyframe_insert('rotation_euler', frame=frame)
    scene.frame_set(1)
    return obj, names


def capture(obj, names):
    result = {}
    for frame in range(1, bpy.context.scene.frame_end + 1):
        bpy.context.scene.frame_set(frame)
        bpy.context.view_layer.update()
        result[frame] = {name: obj.pose.bones[name].matrix.copy() for name in names}
    return result


def error(wanted, actual):
    return max(abs(a - b) for frame in wanted for name in wanted[frame]
               for row, other in zip(wanted[frame][name], actual[frame][name])
               for a, b in zip(row, other))


rows = []
for repeat in range(int(os.environ.get('SUB_BENCH_RUNS', '3'))):
    for frames in (24, 120):
        obj, names = build(frames)
        expected = capture(obj, names)
        bpy.context.scene.frame_set(1)
        start = time.perf_counter()
        ik.create_controls(bpy.context, obj, 'BOTH')
        create_seconds = time.perf_counter() - start
        start = time.perf_counter()
        ik.match(bpy.context, obj, 'BOTH', entire=True, key=True)
        match_seconds = time.perf_counter() - start
        rig._set_ik_enabled(bpy.context, obj, True, limbs='BOTH')
        matched = capture(obj, names)
        bpy.context.scene.frame_set(1)
        start = time.perf_counter()
        result = bpy.ops.sub.apply_ik_animation('EXEC_DEFAULT')
        bake_seconds = time.perf_counter() - start
        assert result == {'FINISHED'}, result
        baked = capture(obj, names)
        row = dict(repeat=repeat, frames=frames, create_seconds=create_seconds,
                   match_seconds=match_seconds, bake_seconds=bake_seconds,
                   match_max_matrix_error=error(expected, matched),
                   bake_max_matrix_error=error(matched, baked))
        rows.append(row)
        print('IK_BENCH', json.dumps(row), flush=True)
        Path(os.environ['SUB_BENCH_OUTPUT']).write_text(json.dumps(
            dict(blender=bpy.app.version_string, root=str(ROOT), rows=rows), indent=2))
print('IK BENCHMARK COMPLETE', flush=True)
