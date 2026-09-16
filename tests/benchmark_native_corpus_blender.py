"""Run the native backend against Blender's over the whole corpus.

This is the evidence docs/benchmarks/native-ik-residual-criterion-2026-09-12.md
named as the prerequisite for enabling the native backend by default: that
document measured ten configurations of a single animation, and asked for more
fixtures before anyone acted on it. This driver runs the same acceptance gate
over the widened corpus -- a second animation (the generated near-straight clip,
the case native/ik_match/README.md says is where the native solver diverges) and
a second production rig.

One row per (source, scenario, limbs): the full gate verdict, the native solve
count, and both wall times. Like the adaptive driver, a failing row is recorded
rather than raised -- whether the native backend holds on this corpus is the
question being measured, and a partial table is worse than a complete one with
failures in it. The engagement check is the exception: a run where the per-frame
guards declined everywhere compares nothing and must never read as a pass, so
require_engaged decides each row's `engaged` flag and the script exits non-zero
at the end if any row declined.

Results merge into docs/benchmarks/native-default-2026-09-13.json keyed by
Blender version, so running this under 4.5 and 5.2 accumulates both into one
file instead of each overwriting the other.
"""
from pathlib import Path
import importlib, json, os, sys, time

fixture = Path(__file__).with_name('test_addon_registration_blender.py')
exec(compile(fixture.read_text().split('addon_utils.disable(MODULE')[0], str(fixture), 'exec'))
sys.path.insert(0, str(Path(__file__).parent))
gate = importlib.import_module('ik_match_gate')
gate.bind(MODULE)
corpus = importlib.import_module('ik_match_corpus')

sources = corpus.available()
assert sources, 'corpus is empty; no fixtures resolved locally'

version = '.'.join(str(v) for v in bpy.app.version[:2])
runs = []
started = time.perf_counter()
for source in sources:
    for scenario, limbs in source['configurations']:
        base = gate.run_variant('blender', source['blend'], scenario, limbs)
        nat = gate.run_variant('native', source['blend'], scenario, limbs)
        verdict = gate.compare(base, nat, base['names'], gate.TOLERANCE)
        try:
            gate.require_engaged('native', nat)
            engaged, declined = True, None
        except AssertionError as error:
            engaged, declined = False, str(error)
        row = dict(
            source=source['name'],
            blend=str(source['blend'].relative_to(ROOT)),
            scenario=scenario,
            limbs=limbs,
            frame_count=len(base['residuals']),
            bone_count=len(base['names']),
            native_solves=nat['counts'].get('native_solves', 0),
            # Chain-frames the native collinearity guard refused outright, from
            # the dedicated counter rather than inferred from
            # candidates_native / 17. The derivation still agrees and is kept in
            # the results document as corroboration, but this is the figure to
            # cite -- and the one to ask for when someone reports that the
            # native default did not speed their rig up.
            native_declined=nat['counts'].get('native_declined', 0),
            decline_rate=(nat['counts'].get('native_declined', 0)
                          / nat['counts']['native_solves']
                          if nat['counts'].get('native_solves') else 0.0),
            engaged=engaged,
            guards_declined=not engaged,
            declined_reason=declined,
            candidates_blender=base['counts'].get('candidates'),
            candidates_native=nat['counts'].get('candidates'),
            total_residual_blender=sum(base['residuals'].values()),
            total_residual_native=sum(nat['residuals'].values()),
            seconds_blender=base['seconds'],
            seconds_native=nat['seconds'],
            verdict=verdict,
        )
        runs.append(row)
        print(f"NATIVE_ROW {version} {row['source']}/{scenario}/{limbs} "
              f"native_solves={row['native_solves']} "
              f"declined={row['native_declined']} "
              f"({100.0 * row['decline_rate']:.1f}%) engaged={engaged} "
              f"passed={verdict['passed']} worse={verdict['frames_worse']} "
              f"identical={verdict['frames_identical']} "
              f"total_delta={verdict['total_delta']:.6g} "
              f"pose={verdict['max_pose_difference']:.3g} "
              f"seconds={row['seconds_blender']:.3f}->{row['seconds_native']:.3f}")

failing = [r for r in runs if not r['verdict']['passed']]
declined = [r for r in runs if not r['engaged']]
seconds_blender = sum(r['seconds_blender'] for r in runs)
seconds_native = sum(r['seconds_native'] for r in runs)

result = dict(
    blender=bpy.app.version_string,
    run_count=len(runs),
    native_engaged=len(runs) - len(declined),
    guards_declined=[f"{r['source']}/{r['scenario']}/{r['limbs']}" for r in declined],
    failing_rows=[f"{r['source']}/{r['scenario']}/{r['limbs']}" for r in failing],
    max_pose_difference=max((r['verdict']['max_pose_difference'] for r in runs), default=0.0),
    native_solves=sum(r['native_solves'] for r in runs),
    native_declined=sum(r['native_declined'] for r in runs),
    total_seconds_blender=seconds_blender,
    total_seconds_native=seconds_native,
    speedup=(seconds_blender / seconds_native) if seconds_native else 0.0,
    elapsed=time.perf_counter() - started,
    runs=runs,
)

# native-default-2026-09-13.json is the evidence the default flip rests on: a
# full 14-row corpus per Blender version. A narrowed run (SUB_IK_CORPUS=...)
# measures something else and must never land there -- merging by version key
# would replace a complete version entry with a partial one and silently destroy
# the record. Narrowed runs get their own file, named for the selection.
selection = os.environ.get('SUB_IK_CORPUS')
if selection:
    leaf = 'native-default-2026-09-13-' + selection.replace(',', '-') + '.json'
else:
    leaf = 'native-default-2026-09-13.json'
out = ROOT / 'docs' / 'benchmarks' / leaf
out.parent.mkdir(parents=True, exist_ok=True)
# Merge rather than overwrite: this script is run once per Blender version and
# the decision rests on both.
table = json.loads(out.read_text()) if out.is_file() else {}
if selection:
    table['corpus_selection'] = selection
    table['partial'] = ('Narrowed run: SUB_IK_CORPUS was set, so this is not the '
                        'corpus the default flip rests on. See '
                        'native-default-2026-09-13.json for that.')
table.update(generated='2026-09-13', tolerance=gate.TOLERANCE,
             baseline_variant='blender', candidate_variant='native',
             sources=[s['name'] for s in sources])
table.setdefault('versions', {})[version] = result
out.write_text(json.dumps(table, indent=2))

print(f"NATIVE_CORPUS_TOTAL {version} runs={len(runs)} "
      f"native_engaged={result['native_engaged']} "
      f"guards_declined={result['guards_declined']} "
      f"failing={len(failing)}/{len(runs)} {result['failing_rows']} "
      f"max_pose_difference={result['max_pose_difference']:.3g} "
      f"seconds={seconds_blender:.3f}->{seconds_native:.3f} "
      f"({result['speedup']:.2f}x)")
if declined:
    raise SystemExit(
        f'{len(declined)} of {len(runs)} runs never engaged the native solver: '
        f"{result['guards_declined']}. A corpus the guards declined compares "
        'nothing and cannot support flipping the default.')
print(f'NATIVE_CORPUS_OK runs={len(runs)} failing={len(failing)} -> {out}')
