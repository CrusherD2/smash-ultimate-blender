"""Playback cost of a wired IK rig, before and after a change to ik_channels.

Mirrors the upstream reference profile without needing a private .blend: the
rig comes from the shared baseline fixture and IK is created in-process.

SUB_PLAYBACK_COMPARE_SOURCE names a saved earlier ik_channels.py to pair
against the working tree. SUB_PLAYBACK_RUNS defaults to three.
SUB_BASELINE_BLEND selects a version-compatible animation fixture.
"""
from pathlib import Path
import importlib
import json
import os
import time

fixture = Path(__file__).with_name('test_addon_registration_blender.py')
exec(compile(fixture.read_text().split('addon_utils.disable(MODULE')[0], str(fixture), 'exec'))
ik = importlib.import_module(MODULE + '.source.extras.ik_channels')
baseline = Path(os.environ.get('SUB_BASELINE_BLEND',
                               ROOT / '.tests/benchmarks/ik_apply/out/baseline.blend'))
sources = {'after': (ROOT / 'source/extras/ik_channels.py').read_text()}
if os.environ.get('SUB_PLAYBACK_COMPARE_SOURCE'):
    sources['before'] = Path(os.environ['SUB_PLAYBACK_COMPARE_SOURCE']).read_text()
FRAMES = 30
rows = []


def measure(repeat, variant):
    exec(compile(sources[variant], variant, 'exec'), ik.__dict__)
    bpy.ops.wm.open_mainfile(filepath=str(baseline))
    obj = next(o for o in bpy.context.scene.objects if o.type == 'ARMATURE')
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    ik.create_controls(bpy.context, obj, 'BOTH')
    scene = bpy.context.scene
    constraints = sum(len(pb.constraints) for pb in obj.pose.bones)
    drivers = len(obj.animation_data.drivers) if obj.animation_data else 0
    # Warm the depsgraph so the timed loop measures steady-state playback.
    for frame in range(1, 4):
        scene.frame_set(frame)
    start = time.perf_counter()
    for frame in range(1, FRAMES + 1):
        scene.frame_set(frame)
    elapsed = time.perf_counter() - start
    row = dict(repeat=repeat, variant=variant, seconds=elapsed, frames=FRAMES,
               bones=len(obj.pose.bones), constraints=constraints, drivers=drivers)
    rows.append(row)
    print('PLAYBACK_BENCH', row, flush=True)
    out = ROOT / '.tests/benchmarks/ik_playback.json'
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(dict(blender=bpy.app.version_string,
                                   baseline=str(baseline), rows=rows), indent=2))


for repeat in range(int(os.environ.get('SUB_PLAYBACK_RUNS', '3'))):
    # Alternate order to reduce the effect of machine load and thermal drift.
    for variant in sorted(sources, reverse=not repeat % 2):
        measure(repeat, variant)
