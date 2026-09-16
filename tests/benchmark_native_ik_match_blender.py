"""Paired full-operation native benchmarks with exact output fingerprints."""
from pathlib import Path
import os
import hashlib
import json

root = Path(__file__).resolve().parents[1]
out = root / '.tests/benchmarks/native_ik'
out.mkdir(parents=True, exist_ok=True)
current = root / 'source/extras/ik_channels.py'
before = Path(os.environ.get('SUB_MATCH_COMPARE_SOURCE',out/'match_pre_native.py'))
before_text = before.read_text() if before.exists() else current.read_text()
after_text = current.read_text()
assert 'from __future__' not in before_text+after_text
(out/'match_before.py').write_text("import os\nos.environ['SUB_NATIVE_IK']='0'\n"+before_text)
native_mode = os.environ.get('SUB_NATIVE_BENCH_MODE', 'experimental')
assert native_mode in {'1', 'experimental', '0'}
(out/'match_after.py').write_text(f"import os\nos.environ['SUB_NATIVE_IK']={native_mode!r}\n"+after_text)
os.environ['SUB_MATCH_SOURCE'] = str(out/'match_after.py')
os.environ['SUB_MATCH_COMPARE_SOURCE'] = str(out/'match_before.py')
os.environ.setdefault('SUB_MATCH_LABEL', 'rust_full_match')
os.environ.setdefault('SUB_MATCH_PHASES', 'BOTH,IMPORT')
os.environ.setdefault('SUB_MATCH_RUNS','1')
benchmark = root/'tests/benchmark_position_ik_blender.py'
exec(compile(benchmark.read_text(),str(benchmark),'exec'))
for phase in {r['phase'] for r in rows}:
    for repeat in {r['repeat'] for r in rows}:
        pair = [r for r in rows if r['phase'] == phase and r['repeat'] == repeat]
        assert len(pair) == 2
        assert pair[0]['keys'] == pair[1]['keys'], (phase,repeat,'keys differ')
        assert pair[0]['poses'] == pair[1]['poses'], (phase,repeat,'poses differ')
report_path = root/'.tests/benchmarks'/f'position_{os.environ["SUB_MATCH_LABEL"]}.json'
report = json.loads(report_path.read_text())
files = [current, root/'source/extras/ik_native.py', root/'native/ik_match/Cargo.lock',
         root/'native/bin/sub_ik_match_native.dll', *sorted((root/'native/ik_match/src').glob('*.rs'))]
report['native_sha256'] = {str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
report['native_threads'] = int(os.environ.get('SUB_NATIVE_THREADS','1'))
report['native_mode'] = native_mode
report['exact_pairs'] = len(rows)//2
report_path.write_text(json.dumps(report,indent=2))
