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
# The whole point of widening: more than one animation, not one in ten costumes.
assert len(sources) >= 2, names
assert corpus.NEAR_STRAIGHT.exists(), f'near-straight fixture missing at {corpus.NEAR_STRAIGHT}'
assert any(s['blend'] == corpus.NEAR_STRAIGHT for s in sources), names
total = sum(len(s['configurations']) for s in sources)
print(f'IK_MATCH_CORPUS_OK sources={len(sources)} runs={total}')
