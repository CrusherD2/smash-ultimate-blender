"""Paired production before/after timings and exact fingerprints, Rust off."""
from pathlib import Path
import os
import json
import hashlib

root=Path(__file__).resolve().parents[1]
os.environ['SUB_NATIVE_IK']='0'
bench=root/'tests/benchmark_position_ik_blender.py'
exec(compile(bench.read_text().split("\nfor repeat in range(int(os.environ.get('SUB_MATCH_RUNS'")[0],str(bench),'exec'))
current=(root/'source/extras/ik_channels.py').read_text()
start=current.index('def match(')
end=current.index('def _arithmetic_bake_ok(',start)
sources={'before':current[:start]+(root/'tests/ik_match_reference.py').read_text()+current[end:],
         'after':current}
source_hashes={name:hashlib.sha256(text.encode()).hexdigest() for name,text in sources.items()}
for repeat in range(int(os.environ.get('SUB_MATCH_RUNS','3'))):
    for phase in os.environ.get('SUB_MATCH_PHASES','BOTH,IMPORT').split(','):
        for variant in sorted(sources,reverse=not repeat%2):
            measure(phase,repeat,variant)
for row in rows:
    ref=next(r for r in rows if r['variant']=='before' and r['phase']==row['phase'] and r['repeat']==row['repeat'])
    row.update(exact_keys=row['keys']==ref['keys'],exact_poses=row['poses']==ref['poses'])
out=root/'.tests/benchmarks'/f'position_{label}.json'
report=json.loads(out.read_text())
report['rows']=rows
report['fast_module_sha256']=hashlib.sha256((root/'source/extras/ik_match_fast.py').read_bytes()).hexdigest()
out.write_text(json.dumps(report,indent=2))
assert all(r['exact_keys'] and r['exact_poses'] for r in rows),rows
print('PRODUCTION_FAST_EXACT',len(rows)//2,flush=True)
