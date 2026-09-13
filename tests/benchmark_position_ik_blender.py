"""Before/after benchmark, run through tests/run_blender_test.py.

SUB_MATCH_SOURCE optionally names a saved pre-change ik_channels.py.
SUB_MATCH_LABEL labels the result; SUB_MATCH_RUNS defaults to three.
SUB_BASELINE_BLEND selects a version-compatible real animation fixture.
SUB_MATCH_COMPARE_SOURCE enables paired runs against a saved earlier source.
SUB_MATCH_PHASES and SUB_MATCH_SUBDIVISION select phases and mesh complexity.
Outputs timings and deterministic key/pose fingerprints under .tests/benchmarks.
"""
from pathlib import Path
import importlib
import os
import time
import json
import hashlib

fixture = Path(__file__).with_name('test_addon_registration_blender.py')
exec(compile(fixture.read_text().split('addon_utils.disable(MODULE')[0], str(fixture), 'exec'))
ik = importlib.import_module(MODULE + '.source.extras.ik_channels')
curves = importlib.import_module(MODULE + '.source.anim.fcurve_compat')
importer = importlib.import_module(MODULE + '.source.anim.import_anim')
source = Path(os.environ.get('SUB_MATCH_SOURCE', ROOT / 'source/extras/ik_channels.py'))
source_text = source.read_text()
exec(compile(source_text, str(source), 'exec'), ik.__dict__)
source_hash = hashlib.sha256(source_text.encode()).hexdigest()
sources = {'after': source_text}
if os.environ.get('SUB_MATCH_COMPARE_SOURCE'):
    sources['before'] = Path(os.environ['SUB_MATCH_COMPARE_SOURCE']).read_text()
source_hashes = {name: hashlib.sha256(text.encode()).hexdigest() for name, text in sources.items()}
label = os.environ.get('SUB_MATCH_LABEL', 'after')
baseline = Path(os.environ.get('SUB_BASELINE_BLEND', ROOT / '.tests/benchmarks/ik_apply/out/baseline.blend'))
rows = []


def fingerprint(obj):
    """Deterministic key and pose hashes for before/after comparison.

    `keys` is reproducible anywhere. `poses` is reproducible only WITHIN one
    Blender process: two runs of identical code in separate processes produce
    different pose hashes. Compare variants inside a single invocation, as the
    loop at the bottom of this file does, and never across invocations.
    See docs/benchmarks/native-search-2026-09-13.md.
    """
    keys = sorted((fc.data_path, fc.array_index,
                   [(tuple(k.co), k.interpolation) for k in fc.keyframe_points])
                  for fc in curves.get_all_action_fcurves(obj.animation_data.action, id_type='OBJECT'))
    poses = []
    scene = bpy.context.scene
    original = scene.frame_current
    for frame in range(scene.frame_start, scene.frame_end + 1):
        scene.frame_set(frame)
        poses.append([[float(v) for row in b.matrix for v in row] for b in obj.pose.bones])
    scene.frame_set(original)
    return {name: hashlib.sha256(json.dumps(data).encode()).hexdigest()
            for name, data in [('keys', keys), ('poses', poses)]}


class Reporter:
    def report(self, levels, message):
        print(levels, message, flush=True)


def measure(phase, repeat, variant):
    exec(compile(sources[variant], variant, 'exec'), ik.__dict__)
    bpy.ops.wm.open_mainfile(filepath=str(baseline))
    obj = next(o for o in bpy.context.scene.objects if o.type == 'ARMATURE')
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    ik.create_controls(bpy.context, obj, 'BOTH')
    subdivision = int(os.environ.get('SUB_MATCH_SUBDIVISION', '0'))
    if subdivision:
        for mesh in bpy.context.scene.objects:
            if mesh.type == 'MESH':
                modifier = mesh.modifiers.new('Benchmark geometry', 'SUBSURF')
                modifier.subdivision_type = 'SIMPLE'
                modifier.levels = subdivision
        bpy.context.view_layer.update()
    original_frame = bpy.context.scene.frame_current
    start = time.perf_counter()
    if phase == 'IMPORT':
        assert importer.import_animation_file(bpy.context, Reporter(), obj,
            bpy.context.scene['bench_second_anim'], True, True, True, 1)
    else:
        assert bpy.ops.sub.fk_to_ik_transfer('EXEC_DEFAULT',
            cleanup_mode=phase if phase in {'ARMS', 'LEGS'} else 'BOTH',
            entire_animation=phase != 'CURRENT') == {'FINISHED'}
        assert bpy.context.scene.frame_current == original_frame
    elapsed = time.perf_counter() - start
    row = dict(phase=phase, repeat=repeat, variant=variant, seconds=elapsed,
               frames=bpy.context.scene.frame_end-bpy.context.scene.frame_start+1,
               **fingerprint(obj))
    rows.append(row)
    print('POSITION_BENCH', label, row, flush=True)
    out = ROOT / '.tests/benchmarks' / f'position_{label}.json'
    out.write_text(json.dumps(dict(blender=bpy.app.version_string,
        source_sha256=source_hash,
        source_hashes=source_hashes, subdivision=subdivision,
        baseline=str(baseline), rows=rows), indent=2))


for repeat in range(int(os.environ.get('SUB_MATCH_RUNS', '3'))):
    for phase in os.environ.get('SUB_MATCH_PHASES', 'BOTH,ARMS,LEGS,CURRENT,IMPORT').split(','):
        # Alternate order to reduce the effect of machine load/thermal drift.
        for variant in sorted(sources, reverse=not repeat % 2):
            measure(phase, repeat, variant)
