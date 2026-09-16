"""Adaptive pole-search stopping rule: rejected by the corpus, removed.

Task 3 implemented a convergence-based early stop behind SUB_IK_ADAPTIVE and
measured it against the acceptance corpus: 2.53% fewer candidate evaluations,
no wall-time win, and 13 of 14 corpus runs failed the pose gate (the one pass
is vacuous -- the rule never fired there). Task 4's finding, recorded in
docs/benchmarks/adaptive-search-2026-09-13.md, is that the gate's per-element
pose tolerance makes it an output-identity test on Blender's warm-started
solver: *any* stopping rule that changes the search path fails it, regardless
of whether the result is better or worse. The 2.53% saving does not justify
the risk or the maintenance cost, so the rule was removed rather than kept
behind a flag.

This test used to exercise that rule and assert it passed the gate -- it
could not, by construction, once the gate's behaviour was understood, so it
was committed red. With the rule gone there is nothing left to exercise.
What is worth pinning is that the machinery does not quietly come back: a
future re-introduction of adaptive early-stopping must be a deliberate,
visible change, not a silent regression of this decision.
"""
from pathlib import Path
import importlib, sys

fixture = Path(__file__).with_name('test_addon_registration_blender.py')
exec(compile(fixture.read_text().split('addon_utils.disable(MODULE')[0], str(fixture), 'exec'))
sys.path.insert(0, str(Path(__file__).parent))

ik = importlib.import_module(MODULE + '.source.extras.ik_channels')

# Pin the removal so a later change cannot bring the machinery back silently.
assert not hasattr(ik, '_adaptive_enabled'), (
    'adaptive stopping rule reintroduced: _adaptive_enabled exists again -- '
    'see docs/benchmarks/adaptive-search-2026-09-13.md before re-adding it')
assert not hasattr(ik, '_ADAPTIVE_RELATIVE'), (
    'adaptive stopping rule reintroduced: _ADAPTIVE_RELATIVE exists again -- '
    'see docs/benchmarks/adaptive-search-2026-09-13.md before re-adding it')

print('IK_ADAPTIVE_SEARCH_REMOVED_OK')
