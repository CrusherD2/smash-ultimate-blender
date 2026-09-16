"""Record the 'blender' variant's per-run numbers across the whole corpus.

This is the reference table Tasks 3 and 5 compare their candidate variants
against, so it captures more than a pass/fail: source, scenario, limbs, frame
count, bone count, total residual, and the pole-search evaluation count
(diag's 'search' counter, which the blender-side solver increments the same
way the native one does), plus timing for context.

Not itself a pass/fail test -- there is nothing to compare the baseline against
yet. It is a data-collection driver over ik_match_corpus.available() and
ik_match_gate.run_variant/compare's sibling primitives.
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
        run = gate.run_variant('blender', source['blend'], scenario, limbs)
        total_residual = sum(run['residuals'].values())
        runs.append(dict(
            source=source['name'],
            blend=str(source['blend'].relative_to(ROOT)),
            scenario=scenario,
            limbs=limbs,
            frame_count=len(run['residuals']),
            bone_count=len(run['names']),
            total_residual=total_residual,
            candidates=run['counts'].get('search'),
            seconds=run['seconds'],
        ))
        print(f"RECORDED {source['name']}/{scenario}/{limbs} "
              f"frames={runs[-1]['frame_count']} bones={runs[-1]['bone_count']} "
              f"total_residual={total_residual:.6g} "
              f"candidates={runs[-1]['candidates']} seconds={run['seconds']:.3f}")

table = dict(
    generated='2026-09-13',
    tolerance=gate.TOLERANCE,
    variant='blender',
    sources=[s['name'] for s in sources],
    run_count=len(runs),
    total_seconds=time.perf_counter() - started,
    runs=runs,
)

out = ROOT / 'docs' / 'benchmarks' / 'ik-corpus-baseline-2026-09-13.json'
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(json.dumps(table, indent=2))
print(f'IK_CORPUS_BASELINE_OK sources={len(sources)} runs={len(runs)} -> {out}')
