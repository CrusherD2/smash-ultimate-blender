"""The corpus must contain more than one animation and reach the hard case."""
from pathlib import Path
import importlib, sys

fixture = Path(__file__).with_name('test_addon_registration_blender.py')
exec(compile(fixture.read_text().split('addon_utils.disable(MODULE')[0], str(fixture), 'exec'))
sys.path.insert(0, str(Path(__file__).parent))
corpus = importlib.import_module('ik_match_corpus')

sources = corpus.available()
assert sources, 'corpus is empty; no fixtures resolved'
names = [s['name'] for s in sources]
assert len(set(names)) == len(names), names
# ik_match_corpus' own rule is that a fixture absent locally is skipped rather
# than failed -- the .blend files live under .tests/ and are not distributed.
# This test asserted their presence anyway, so a checkout that had never run
# tests/build_near_straight_fixture_blender.py was simply red, with the message
# 'AssertionError: ['baseline']' and no hint that a builder exists. Skip
# instead, and name the builder.
if not corpus.NEAR_STRAIGHT.exists():
    print(f'SKIP ik match corpus, near-straight fixture missing at {corpus.NEAR_STRAIGHT}')
    print('  build it: python tests/run_blender_test.py --blender <blender> '
          'tests/build_near_straight_fixture_blender.py')
    raise SystemExit(0)
# The whole point of widening: more than one animation, not one in ten costumes.
assert len(sources) >= 2, names
assert any(s['blend'] == corpus.NEAR_STRAIGHT for s in sources), names
total = sum(len(s['configurations']) for s in sources)
print(f'IK_MATCH_CORPUS_OK sources={len(sources)} runs={total}')
