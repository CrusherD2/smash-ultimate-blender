"""Run the adaptive stopping rule against the fixed search over the whole corpus.

One row per (source, scenario, limbs): both candidate counts, the full gate
verdict, and both wall times. Not a pass/fail driver -- whether the adaptive
rule is safe is the question being measured, so a failing row is recorded, not
raised. Task 4 acts on the table.
"""
from pathlib import Path
import importlib, json, sys, time

fixture = Path(__file__).with_name('test_addon_registration_blender.py')
exec(compile(fixture.read_text().split('addon_utils.disable(MODULE')[0], str(fixture), 'exec'))
sys.path.insert(0, str(Path(__file__).parent))
gate = importlib.import_module('ik_match_gate')
gate.bind(MODULE)
corpus = importlib.import_module('ik_match_corpus')

sources = corpus.available()
assert sources, 'corpus is empty; no fixtures resolved locally'

runs = []
started = time.perf_counter()
for source in sources:
    for scenario, limbs in source['configurations']:
        base = gate.run_variant('blender', source['blend'], scenario, limbs)
        adap = gate.run_variant('adaptive', source['blend'], scenario, limbs)
        verdict = gate.compare(base, adap, base['names'], gate.TOLERANCE)
        row = dict(
            source=source['name'],
            blend=str(source['blend'].relative_to(ROOT)),
            scenario=scenario,
            limbs=limbs,
            frame_count=len(base['residuals']),
            bone_count=len(base['names']),
            candidates_baseline=base['counts'].get('candidates'),
            candidates_adaptive=adap['counts'].get('candidates'),
            adaptive_early=adap['counts'].get('adaptive_early', 0),
            engaged=adap['counts'].get('adaptive_early', 0) > 0,
            seconds_baseline=base['seconds'],
            seconds_adaptive=adap['seconds'],
            verdict=verdict,
        )
        runs.append(row)
        print(f"ADAPTIVE_ROW {row['source']}/{scenario}/{limbs} "
              f"candidates={row['candidates_baseline']}->{row['candidates_adaptive']} "
              f"early={row['adaptive_early']} passed={verdict['passed']} "
              f"worse={verdict['frames_worse']} total_delta={verdict['total_delta']:.6g} "
              f"pose={verdict['max_pose_difference']:.3g} "
              f"seconds={row['seconds_baseline']:.3f}->{row['seconds_adaptive']:.3f}")

total_base = sum(r['candidates_baseline'] or 0 for r in runs)
total_adap = sum(r['candidates_adaptive'] or 0 for r in runs)
failing = [r for r in runs if not r['verdict']['passed']]

table = dict(
    generated='2026-09-13',
    tolerance=gate.TOLERANCE,
    baseline_variant='blender',
    candidate_variant='adaptive',
    adaptive_relative=importlib.import_module(
        MODULE + '.source.extras.ik_channels')._ADAPTIVE_RELATIVE,
    sources=[s['name'] for s in sources],
    run_count=len(runs),
    total_candidates_baseline=total_base,
    total_candidates_adaptive=total_adap,
    candidate_reduction=total_base - total_adap,
    candidate_reduction_percent=(100.0 * (total_base - total_adap) / total_base) if total_base else 0.0,
    failing_rows=[f"{r['source']}/{r['scenario']}/{r['limbs']}" for r in failing],
    total_seconds=time.perf_counter() - started,
    runs=runs,
)

out = ROOT / 'docs' / 'benchmarks' / 'adaptive-search-2026-09-13.json'
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(json.dumps(table, indent=2))
print(f"ADAPTIVE_CORPUS_TOTAL candidates={total_base}->{total_adap} "
      f"reduction={table['candidate_reduction']} "
      f"({table['candidate_reduction_percent']:.2f}%) "
      f"failing={len(failing)}/{len(runs)} {table['failing_rows']}")
print(f'ADAPTIVE_CORPUS_OK runs={len(runs)} -> {out}')
