"""Adaptive search must cost less, stay within the gate, and be off by default."""
from pathlib import Path
import importlib, os, sys, json

fixture = Path(__file__).with_name('test_addon_registration_blender.py')
exec(compile(fixture.read_text().split('addon_utils.disable(MODULE')[0], str(fixture), 'exec'))
sys.path.insert(0, str(Path(__file__).parent))
gate = importlib.import_module('ik_match_gate'); gate.bind(MODULE)
corpus = importlib.import_module('ik_match_corpus')

source = next((s for s in corpus.available() if s['name'] == 'baseline'), None)
if source is None:
    print('SKIP adaptive test, no baseline fixture')
    raise SystemExit(0)

base = gate.run_variant('blender', source['blend'], 'normal', 'BOTH')
adap = gate.run_variant('adaptive', source['blend'], 'normal', 'BOTH')
gate.require_engaged('adaptive', adap)
verdict = gate.compare(base, adap, base['names'], gate.TOLERANCE)
print('ADAPTIVE_VERDICT ' + json.dumps({**verdict,
      'candidates_baseline': base['counts'].get('candidates'),
      'candidates_adaptive': adap['counts'].get('candidates')}))

# The whole point: strictly less work. Never more than the fixed search.
assert adap['counts']['candidates'] < base['counts']['candidates'], (
    base['counts'], adap['counts'])
assert verdict['passed'], verdict

# Off by default: no flag means the fixed search and no early stops.
os.environ.pop('SUB_IK_ADAPTIVE', None)
plain = gate.run_variant('blender', source['blend'], 'normal', 'BOTH')
assert plain['counts'].get('adaptive_early', 0) == 0, plain['counts']
assert plain['counts']['candidates'] == base['counts']['candidates'], (
    plain['counts'], base['counts'])
print('IK_ADAPTIVE_SEARCH_OK')
