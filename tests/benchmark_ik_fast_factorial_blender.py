"""Final production components separately/together, with/without experimental Rust."""
from pathlib import Path
import os
import json
import hashlib
import importlib

root=Path(__file__).resolve().parents[1]
bench=root/'tests/benchmark_position_ik_blender.py'
exec(compile(bench.read_text().split("\nfor repeat in range(int(os.environ.get('SUB_MATCH_RUNS'")[0],str(bench),'exec'))
fast=importlib.import_module(MODULE+'.source.extras.ik_match_fast')
fast._benchmark_sample=fast.sample_fk
fast._benchmark_isolate=fast.can_isolate
current=(root/'source/extras/ik_channels.py').read_text()
start=current.index('def match(')
end=current.index('def _arithmetic_bake_ok(',start)
reference=current[:start]+(root/'tests/ik_match_reference.py').read_text()+current[end:]
variants=['baseline','sample','isolate','combined','baseline_rust','sample_rust','isolate_rust','combined_rust']
sources={}
for variant in variants:
    mode=variant.split('_')[0]
    native='experimental' if variant.endswith('_rust') else '0'
    prefix=f'''import os
from . import ik_match_fast as _fastmod
os.environ['SUB_NATIVE_IK']={native!r}
_fastmod.sample_fk = {'(lambda *args: None)' if mode=='isolate' else '_fastmod._benchmark_sample'}
_fastmod.can_isolate = {'(lambda *args: False)' if mode=='sample' else '_fastmod._benchmark_isolate'}
'''
    sources[variant]=prefix+(reference if mode=='baseline' else current)
source_hashes={name:hashlib.sha256(text.encode()).hexdigest() for name,text in sources.items()}
for repeat in range(int(os.environ.get('SUB_MATCH_RUNS','3'))):
    for phase in os.environ.get('SUB_MATCH_PHASES','BOTH,IMPORT').split(','):
        for variant in variants if repeat%2==0 else reversed(variants):
            measure(phase,repeat,variant)
for row in rows:
    ref=next(r for r in rows if r['variant']=='baseline' and r['phase']==row['phase'] and r['repeat']==row['repeat'])
    row.update(exact_keys=row['keys']==ref['keys'],exact_poses=row['poses']==ref['poses'])
out=root/'.tests/benchmarks'/f'position_{label}.json'
report=json.loads(out.read_text())
report['rows']=rows
report['implementation_sha256']={str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest()
    for p in [root/'source/extras/ik_channels.py',root/'source/extras/ik_match_fast.py',
              root/'source/extras/ik_native.py',root/'native/bin/sub_ik_match_native.dll']}
out.write_text(json.dumps(report,indent=2))
assert all(r['exact_keys'] and r['exact_poses'] for r in rows),rows
print('FACTORIAL_EXACT_FIXTURE',len(rows),flush=True)
