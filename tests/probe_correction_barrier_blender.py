"""Can the correction be computed from the native search's own pose?

The correction write costs one depsgraph barrier per frame, because it reads
the solved pose back out of Blender. Solver.search already RETURNS the pose it
settled on and _match_chain_steps throws it away -- so if that pose equals
Blender's, the barrier is free to delete.

Nothing has ever checked that. Verification mode compares solve_many's
per-candidate output bit-for-bit, but the native-search gate is off in
verification mode, so search() is never exercised there; and
test_native_ik_search_blender.py compares the keyed pole ANGLES, not the pose.
Today only the angle is consumed, so the corpus evidence holds regardless.

This measures it, by substituting an instrumented _match_chain_steps -- the
same source-substitution the benchmarks use. Reports, per chain-frame:
  * whether search()'s pose is bit-identical to Blender's at the same angle
  * the worst absolute element difference if not
  * what the correction basis would become either way, since that difference
    is what would land in the keyed output
  * the endpoint bone's correction, which search() does not cover at all
    (Solver is built over solver[:-1])
"""
from pathlib import Path
import importlib
import json
import math
import os

from mathutils import Vector

fixture = Path(__file__).with_name('test_addon_registration_blender.py')
exec(compile(fixture.read_text().split('addon_utils.disable(MODULE')[0], str(fixture), 'exec'))

ik = importlib.import_module(MODULE + '.source.extras.ik_channels')

BASELINE = Path(os.environ.get('SUB_BASELINE_BLEND',
                               ROOT / '.tests/benchmarks/ik_apply/out/baseline.blend'))
if not BASELINE.exists():
    print('SKIP native pose probe, no baseline at ' + str(BASELINE))
    raise SystemExit(0)

CAPTURE_ANCHOR = """        native = _native(obj, job, solver[:-1], con, frame)
"""

CAPTURE_PROBE = """        if _CAPTURE_ROWS is not None:
            _bones = solver[:-1]
            _pose = 0.0
            for _i, _name in enumerate(path[:-1]):
                for _r in range(4):
                    for _c in range(4):
                        _pose = max(_pose, abs(_bones[_i].matrix[_r][_c] - matrices[_name][_r][_c]))
            _head = max((_b.head - _b.matrix.translation).length for _b in _bones)
            _tail = max((_b.tail - (_b.matrix @ Vector((0.0, _b.bone.length, 0.0)))).length
                        for _b in _bones)
            _parent = _bones[0].parent
            _pworld = 0.0
            if _parent is not None and entry['parent'] in matrices:
                for _r in range(4):
                    for _c in range(4):
                        _pworld = max(_pworld, abs(_parent.matrix[_r][_c] - matrices[entry['parent']][_r][_c]))
            _tgt = obj.pose.bones[con.subtarget].matrix
            _tdelta = 0.0
            for _r in range(4):
                for _c in range(4):
                    _tdelta = max(_tdelta, abs(_tgt[_r][_c] - matrices[path[-1]][_r][_c]))
            _CAPTURE_ROWS.append({'frame': frame, 'chain': target,
                                  'solver_pose_delta': _pose,
                                  'head_delta': _head, 'tail_delta': _tail,
                                  'parent_delta': _pworld, 'target_delta': _tdelta})
"""

ANCHOR = """    for name in path:
        correction = obj.pose.bones.get(CORRECTION_PREFIX + name)
        if correction is not None:
            solved = obj.pose.bones[PREFIX + name].matrix.copy()
            correction.matrix_basis = solved.inverted_safe() @ matrices[name]
            if key:
                writer.stash_pose_bone(correction, frame)
"""

PROBE = """    if _PROBE_ROWS is not None and found is not None and len(found) > 1:
        _blender = [b.matrix.copy() for b in solver[:-1]]
        _proposed = found[1]
        _worst = 0.0
        _bit = True
        for _p, _o in zip(_proposed, _blender):
            for _rp, _ro in zip(_p, _o):
                if tuple(_rp) != tuple(_ro):
                    _bit = False
                for _a, _b in zip(_rp, _ro):
                    _worst = max(_worst, abs(_a - _b))
        # What the two routes would actually key, which is the number that
        # matters: a pose difference only counts if it moves the correction.
        _corr = 0.0
        for _i, _name in enumerate(path[:-1]):
            _from_blender = _blender[_i].inverted_safe() @ matrices[_name]
            _from_native = _proposed[_i].inverted_safe() @ matrices[_name]
            for _rp, _ro in zip(_from_native, _from_blender):
                for _a, _b in zip(_rp, _ro):
                    _corr = max(_corr, abs(_a - _b))
        # The endpoint bone is outside the native model entirely.
        _end = obj.pose.bones[PREFIX + path[-1]].matrix.copy()
        _end_basis = _end.inverted_safe() @ matrices[path[-1]]
        # Is the endpoint correction a pure translation? (3x3 == identity)
        _basis33 = 0.0
        for _r in range(3):
            for _c in range(3):
                _basis33 = max(_basis33, abs(_end_basis[_r][_c] - (1.0 if _r == _c else 0.0)))
        # Is the endpoint's world position just the parent solver bone's tail,
        # which the native pose already gives us? found[1][-1] is solver[-2].
        _parent_solved = _proposed[-1]
        _plen = solver[-2].bone.length
        _tail = _parent_solved @ Vector((0.0, _plen, 0.0))
        _tail_delta = max(abs(_tail[_i] - _end[_i][3]) for _i in range(3))
        _PROBE_ROWS.append({'frame': frame, 'chain': target,
                            'bitwise': _bit, 'pose_delta': _worst,
                            'correction_delta': _corr,
                            'endpoint_translation': _end_basis.to_translation().length,
                            'endpoint_rotation': abs(_end_basis.to_quaternion().angle),
                            'endpoint_basis_33_delta': _basis33,
                            'endpoint_tail_delta': _tail_delta})
"""

source = (ROOT / 'source/extras/ik_channels.py').read_text(encoding='utf-8')
assert source.count(ANCHOR) == 1, 'correction block moved; re-anchor the probe'
source = source.replace(ANCHOR, PROBE + ANCHOR)
assert source.count(CAPTURE_ANCHOR) == 1, 'capture block moved; re-anchor the probe'
source = source.replace(CAPTURE_ANCHOR, CAPTURE_PROBE + CAPTURE_ANCHOR)
rows = []
capture_rows = []
namespace = ik.__dict__
namespace['_PROBE_ROWS'] = rows
namespace['_CAPTURE_ROWS'] = capture_rows
exec(compile(source, 'instrumented_ik_channels', 'exec'), namespace)

os.environ.pop('SUB_NATIVE_IK', None)     # shipped default: native search on
os.environ['SUB_NATIVE_SEARCH'] = '1'

bpy.ops.wm.open_mainfile(filepath=str(BASELINE))
obj = next(o for o in bpy.context.scene.objects if o.type == 'ARMATURE')
bpy.context.view_layer.objects.active = obj
for other in bpy.context.scene.objects:
    other.select_set(other is obj)
if bpy.context.object.mode != 'POSE':
    bpy.ops.object.mode_set(mode='POSE')
ik.create_controls(bpy.context, obj, 'BOTH')
ik.match(bpy.context, obj, 'BOTH', entire=True, key=True, _batch=True)

assert rows, 'the native search never ran; nothing was measured'
bitwise = sum(1 for r in rows if r['bitwise'])
pose = sorted(r['pose_delta'] for r in rows)
corr = sorted(r['correction_delta'] for r in rows)
etr = sorted(r['endpoint_translation'] for r in rows)
b33 = sorted(r['endpoint_basis_33_delta'] for r in rows)
tail = sorted(r['endpoint_tail_delta'] for r in rows)
ero = sorted(r['endpoint_rotation'] for r in rows)
summary = {
    'blender': '%d.%d.%d' % bpy.app.version,
    'chain_frames': len(rows),
    'bitwise_identical': bitwise,
    'bitwise_fraction': round(bitwise / len(rows), 4),
    'pose_delta_worst': pose[-1],
    'pose_delta_median': pose[len(pose) // 2],
    'correction_delta_worst': corr[-1],
    'correction_delta_median': corr[len(corr) // 2],
    'endpoint_translation_worst': etr[-1],
    'endpoint_rotation_worst_deg': math.degrees(ero[-1]),
    'endpoint_is_identity': etr[-1] < 1e-9 and ero[-1] < 1e-9,
    'endpoint_basis_is_pure_translation': b33[-1] < 1e-12,
    'endpoint_basis_33_delta_worst': b33[-1],
    'endpoint_tail_delta_worst': tail[-1],
    'endpoint_tail_delta_median': tail[len(tail) // 2],
    'endpoint_derivable_from_native': b33[-1] < 1e-12 and tail[-1] == 0.0,
}
def worst(key):
    return max(r[key] for r in capture_rows)


capture_summary = {
    'chain_frames': len(capture_rows),
    'solver_pose_delta_worst': worst('solver_pose_delta'),
    'head_delta_worst': worst('head_delta'),
    'tail_delta_worst': worst('tail_delta'),
    'parent_delta_worst': worst('parent_delta'),
    'target_delta_worst': worst('target_delta'),
}
capture_summary['capture_derivable'] = all(
    v == 0.0 for k, v in capture_summary.items() if k.endswith('_worst'))
print('NATIVE_CAPTURE ' + json.dumps(capture_summary))
print('NATIVE_POSE ' + json.dumps(summary))
out = ROOT / '.tests/benchmarks' / ('native-search-pose-%d.%d.json' % bpy.app.version[:2])
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(json.dumps({'summary': summary, 'capture': capture_summary,
                           'rows': rows, 'capture_rows': capture_rows}, indent=2), encoding='utf-8')
print('NATIVE_POSE_WROTE ' + str(out))
