"""Export real Blender IK problems, run the Rust probe, report strict equality.

This is an experimental compatibility gate, not an addon backend. Run with
tests/run_blender_test.py. SUB_NATIVE_STRICT=0 allows diagnostic-only runs.
"""
from pathlib import Path
import importlib
import json
import os
import struct
import subprocess
import time
import sys
from mathutils import Matrix, Vector
sys.path.insert(0, str(Path(__file__).parent))

fixture = Path(__file__).with_name('test_addon_registration_blender.py')
exec(compile(fixture.read_text().split('addon_utils.disable(MODULE')[0], str(fixture), 'exec'))
ik = importlib.import_module(MODULE + '.source.extras.ik_channels')
rig = importlib.import_module(MODULE + '.source.extras.create_animation_rig')
baseline = Path(os.environ.get('SUB_BASELINE_BLEND', ROOT / '.tests/benchmarks/ik_apply/out/4.5/baseline.blend'))
output = ROOT / '.tests/benchmarks/native_ik'
output.mkdir(parents=True, exist_ok=True)
bpy.ops.wm.open_mainfile(filepath=str(baseline))
obj = next(o for o in bpy.context.scene.objects if o.type == 'ARMATURE')
bpy.context.view_layer.objects.active = obj
obj.select_set(True)
ik.create_controls(bpy.context, obj, 'BOTH')
jobs = list(ik.chains(obj, 'BOTH'))
cache = ik._chain_cache(obj, jobs)
names = ik._sample_names(obj, jobs, cache)
cases = []
blender_seconds = 0.0
f32 = lambda n: struct.unpack('f', struct.pack('f', n))[0]
matrix_list = lambda m: [list(row) for row in m]


from native_ik_capture import capture_input, length_f32, multiply

paused = rig._IK_FK_MUTE_SYNC_PAUSED
rig.pause_ik_fk_mute_sync(True)
try:
    for _, con, _ in (*ik.outputs(obj, 'BOTH'), *ik.toe_outputs(obj, 'BOTH')):
        con.mute = True
    samples = {}
    for frame in range(bpy.context.scene.frame_start, bpy.context.scene.frame_end + 1):
        bpy.context.scene.frame_set(frame)
        samples[frame] = {name: obj.pose.bones[name].matrix.copy() for name in names}
    previous = {}
    for frame, matrices in samples.items():
        bpy.context.scene.frame_set(frame)
        for job in jobs:
            step = ik._match_chain_steps(obj, job, matrices, frame, False, None, cache[job[2]], previous)
            next(step)
            state = step.gi_frame.f_locals
            assert 'reference_columns' in state, 'fixture needs unsupported placement fallback'
            con = state['con']
            solver = state['solver'][:-1]
            assert con.chain_count == len(solver) and not con.use_rotation
            assert not any(any(getattr(b, name) for name in
                ('lock_ik_x','lock_ik_y','lock_ik_z','use_ik_limit_x','use_ik_limit_y','use_ik_limit_z',
                 'ik_stiffness_x','ik_stiffness_y','ik_stiffness_z')) for b in solver)
            assert not con.use_stretch
            con.mute = True
            bpy.context.view_layer.update()
            problem = capture_input(obj, job, solver, con, frame)
            con.mute = False
            full_search = os.environ.get('SUB_NATIVE_FULL_SEARCH') == '1'
            angles = (0.0,) if full_search else (0.0, 0.35, -0.75)
            def record(angle):
                return dict(problem, id=problem['id']+f'/{angle}', angle=con.pole_angle,
                            expected=[matrix_list(b.matrix) for b in solver])
            for angle in angles:
                con.pole_angle = angle
                start = time.perf_counter()
                bpy.context.view_layer.update()
                blender_seconds += time.perf_counter() - start
                cases.append(record(angle))
            if full_search:
                for _ in step:
                    start = time.perf_counter()
                    bpy.context.view_layer.update()
                    blender_seconds += time.perf_counter() - start
                    cases.append(record(con.pole_angle))
            step.close()
finally:
    rig.pause_ik_fk_mute_sync(paused)

input_path = output / 'input.json'
input_path.write_text(json.dumps(dict(blender=bpy.app.version_string, jobs=cases)))
binary = ROOT / 'native/ik_match/target/release/sub_ik_match_probe.exe'
native_reports = {}
for threads in (1, 4):
    result_path = output / f'output_{threads}.json'
    subprocess.run([str(binary), str(input_path), str(result_path), str(threads), '7'], check=True,
                   creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    native_reports[threads] = json.loads(result_path.read_text())
assert native_reports[1]['results'] == native_reports[4]['results'], 'thread count changed results'


def apply_changes(case, changes):
    parent = Matrix(case['parent'])
    result = []
    for delta, change in zip(case['deltas'], changes):
        matrix = multiply(parent, Matrix(delta))
        scale = [length_f32(matrix.col[i]) for i in range(3)]
        for i in (0, 2):
            length = length_f32(matrix.col[i])
            matrix.col[i] = matrix.col[i] * f32(scale[1] / length) if length else matrix.col[i]
        rotation = Matrix(change)
        matrix = multiply(matrix, rotation.to_4x4())
        for i in (0, 2):
            goal_length = f32(scale[i] * length_f32(rotation.col[i]))
            length = length_f32(matrix.col[i])
            matrix.col[i] = matrix.col[i] * f32(goal_length / length) if length else matrix.col[i]
        result.append(matrix_list(matrix))
        parent = matrix
    return result


errors = []
for case, answer in zip(cases, native_reports[1]['results']):
    actual = apply_changes(case, answer['changes'])
    assert actual == [matrix_list(Matrix(m)) for m in answer['matrices']], 'Rust pose application differs from the diagnostic reference'
    error = max(abs(a-b) for mat_a, mat_b in zip(actual,case['expected'])
                for row_a,row_b in zip(mat_a,mat_b) for a,b in zip(row_a,row_b))
    errors.append((error, case['id']))
errors.sort(reverse=True)
(output/'errors.json').write_text(json.dumps(errors, indent=2))
summary = dict(blender=bpy.app.version_string, cases=len(cases),
               exactly_equal=sum(error == 0 for error,_ in errors), worst=errors[0],
               median=sorted(error for error,_ in errors)[len(errors)//2],
               blender_evaluation_seconds=blender_seconds,
               native_seconds={threads:r['median_seconds'] for threads,r in native_reports.items()},
               top_errors=errors[:10], production_enabled=False)
(output/'summary.json').write_text(json.dumps(summary, indent=2))
print('NATIVE_IK_COMPATIBILITY', json.dumps(summary))
if os.environ.get('SUB_NATIVE_STRICT', '1') != '0':
    assert summary['exactly_equal'] == len(cases), 'Native solver has not passed the exactness gate'
