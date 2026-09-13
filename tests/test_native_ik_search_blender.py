"""The native whole-search must choose the same pole angles as the Python one.

The search decides the output: its three seed candidates, tolerance check and
golden-section refinement pick the angle that gets keyed. Moving it into Rust is
only safe if it picks the identical angle, so this compares the keyed pole-angle
curves across three paths -- Blender's backend, native per-candidate, and the
native whole-search.
"""
from pathlib import Path
import importlib
import json
import os

fixture = Path(__file__).with_name('test_addon_registration_blender.py')
exec(compile(fixture.read_text().split('addon_utils.disable(MODULE')[0], str(fixture), 'exec'))

ik = importlib.import_module(MODULE + '.source.extras.ik_channels')
ik_native = importlib.import_module(MODULE + '.source.extras.ik_native')
curves = importlib.import_module(MODULE + '.source.anim.fcurve_compat')

BASELINE = Path(os.environ.get(
    'SUB_BASELINE_BLEND',
    ROOT / '.tests' / 'benchmarks' / 'ik_apply' / 'out' / 'baseline.blend'))

if not BASELINE.exists():
    print(f'SKIP native search comparison, no baseline at {BASELINE}')
    raise SystemExit(0)

searches = {'count': 0}
_search = ik_native.Solver.search


def counting_search(self, *args, **kwargs):
    found = _search(self, *args, **kwargs)
    searches['count'] += int(found is not None)
    return found


ik_native.Solver.search = counting_search


def pole_angles(obj):
    """Every keyed pole angle, which is what the search actually decides."""
    return sorted(
        (fc.data_path, [(k.co[0], k.co[1]) for k in fc.keyframe_points])
        for fc in curves.get_all_action_fcurves(obj.animation_data.action, id_type='OBJECT')
        if fc.data_path.endswith('.pole_angle'))


def run(native, search):
    os.environ['SUB_NATIVE_IK'] = native
    os.environ['SUB_NATIVE_SEARCH'] = search
    searches['count'] = 0
    bpy.ops.wm.open_mainfile(filepath=str(BASELINE))
    obj = next(o for o in bpy.context.scene.objects if o.type == 'ARMATURE')
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    ik.create_controls(bpy.context, obj, 'BOTH')
    ik.match(bpy.context, obj, _batch=True)
    return pole_angles(obj), searches['count']


results = {}
for label, native, search in (('blender', '0', '0'),
                              ('per_candidate', 'experimental', '0'),
                              ('native_search', 'experimental', '1')):
    angles, used = run(native, search)
    results[label] = angles
    print('SEARCH_PATH', label, 'native_searches', used,
          'curves', len(angles), flush=True)
    if label == 'native_search':
        # Without this the comparison would pass whether or not the native
        # search ran at all.
        assert used > 0, 'the native whole-search never ran; nothing was compared'
    else:
        assert used == 0, f'{label} unexpectedly used the native whole-search'

matches = {k: results[k] == results['blender'] for k in results}
print('SEARCH_ANGLES_MATCH ' + json.dumps(matches), flush=True)
assert results['per_candidate'] == results['blender'], 'per-candidate path already diverged'
assert results['native_search'] == results['blender'], 'native whole-search chose different angles'
print('NATIVE_SEARCH_OK', flush=True)
