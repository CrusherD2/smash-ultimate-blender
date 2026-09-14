"""Additional factorial experiment: Blender-sampled channels on isolated rig."""
from pathlib import Path
import os
import hashlib
import json
import sys

root = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root/'tests'))
bench = root/'tests/benchmark_ik_strategies_blender.py'
os.environ['SUB_STRATEGIES'] = 'baseline,isolate,isolate_update,isolate_rust,isolate_update_rust'
setup = bench.read_text().split("\nfor repeat in range(int(os.environ.get('SUB_MATCH_RUNS'")[0]
exec(compile(setup,str(bench),'exec'))
for name,base_name in [('replay','isolate'),('replay_update','isolate_update'),
                       ('replay_rust','isolate_rust'),('replay_update_rust','isolate_update_rust')]:
    text = sources[base_name]
    text = text.replace('    samples = {}\n','''    samples = {}
    replay_states = {}
    replay_names = replay.needed_names(obj, sys.modules[__name__], jobs, sampled)
''',1)
    text = text.replace('                    samples[frame] =',
                        '                    replay_states[frame] = replay.capture(obj, replay_names)\n                    samples[frame] =',1)
    text = text.replace('prototypes.isolated(context, obj, sys.modules[__name__], jobs, sampled)',
                        'replay.isolated(context, obj, sys.modules[__name__], jobs, sampled, replay_states)')
    sources[name] = 'import ik_replay_prototype as replay\n'+text
variants = list(sources)
source_hashes = {name:hashlib.sha256(text.encode()).hexdigest() for name,text in sources.items()}
for repeat in range(int(os.environ.get('SUB_MATCH_RUNS','3'))):
    for phase in os.environ.get('SUB_MATCH_PHASES','BOTH,IMPORT').split(','):
        for variant in variants if repeat % 2 == 0 else reversed(variants):
            measure(phase,repeat,variant)
for row in rows:
    ref = next(r for r in rows if r['variant']=='baseline' and r['phase']==row['phase'] and r['repeat']==row['repeat'])
    row.update(exact_keys=row['keys']==ref['keys'],exact_poses=row['poses']==ref['poses'])
out = root/'.tests/benchmarks'/f'position_{label}.json'
report = json.loads(out.read_text())
report['rows'] = rows
out.write_text(json.dumps(report,indent=2))
print('REPLAY_RESULTS',json.dumps(rows),flush=True)
