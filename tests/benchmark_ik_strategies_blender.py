"""Factorial, exact-output IK strategy experiments. Run in isolated Blender.

SUB_STRATEGIES: baseline,update,direct,isolate,isolate_update,isolate_direct,
and any of those names suffixed with _rust. Rust is explicitly experimental.
SUB_MATCH_RUNS/PHASES/BASELINE_BLEND have the standard benchmark meanings.
"""
from pathlib import Path
import sys
import os
import time
import json
import hashlib

root = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root/'tests'))
import ik_strategy_prototypes as prototypes
bench = root/'tests/benchmark_position_ik_blender.py'
setup = bench.read_text().split("for repeat in range(int(os.environ.get('SUB_MATCH_RUNS'")[0]
exec(compile(setup,str(bench),'exec'))
original_text = (root/'source/extras/ik_channels.py').read_text()
start = original_text.index('def match(')
end = original_text.index('def _arithmetic_bake_ok(',start)
original_text = original_text[:start]+(root/'tests/ik_match_reference.py').read_text()+original_text[end:]
variants = os.environ.get('SUB_STRATEGIES',
    'baseline,update,direct,isolate,isolate_update,isolate_direct').split(',')
sources = {}
for variant in variants:
    text = original_text
    if 'update' in variant or 'direct' in variant:
        text = text.replace('                    context.view_layer.update()\n                    samples[frame]',
                            '                    samples[frame]')
    if 'direct' in variant:
        start = text.index('                for frame in frames:',text.index('def match('))
        end = text.index('                for frame, matrices in samples.items():',start)
        text = text[:start]+'''                samples = prototypes.direct_samples(obj, frames, sampled,
                    get_all_action_fcurves(obj.animation_data.action, id_type='OBJECT'))
'''+text[end:]
        if 'exact' in variant:
            text = text.replace('prototypes.direct_samples(', 'direct_exact.sample(')
    if 'isolate' in variant:
        start = text.index('                for frame, matrices in samples.items():',text.index('def match('))
        end = text.index('            if writer is not None:',start)
        block = text[start:end].replace('scene.frame_set(frame)','solve_scene.frame_set(frame)')
        block = block.replace('_match_chain_steps(obj, job','_match_chain_steps(solve_obj, job')
        block = block.replace('_evaluate_match_steps(context,','_evaluate_match_steps(solve_context,')
        text = text[:start]+'''                with prototypes.isolated(context, obj, sys.modules[__name__], jobs, sampled) as (solve_context, solve_obj, solve_scene):
'''+''.join('    '+line+'\n' for line in block.splitlines())+text[end:]
        if 'minimal' in variant:
            text = text.replace('jobs, sampled) as (solve_context',
                                'jobs, sampled, minimal=True) as (solve_context')
            text = text.replace("    con = solve_bone(obj, names).constraints['SUB IK Solve']\n    endpoints",
                                "    con = solver[-2].constraints['SUB IK Solve']\n    endpoints")
    native = 'experimental' if variant.endswith('_rust') else '0'
    sources[variant] = f"import os, sys\nimport ik_strategy_prototypes as prototypes\nimport ik_direct_exact_prototype as direct_exact\nos.environ['SUB_NATIVE_IK']={native!r}\n"+text
source_hashes = {name:hashlib.sha256(text.encode()).hexdigest() for name,text in sources.items()}
label = os.environ.get('SUB_MATCH_LABEL','strategies')
for repeat in range(int(os.environ.get('SUB_MATCH_RUNS','3'))):
    for phase in os.environ.get('SUB_MATCH_PHASES','BOTH,IMPORT').split(','):
        for variant in variants if repeat % 2 == 0 else reversed(variants):
            measure(phase,repeat,variant)
for row in rows:
    baseline_row = next(r for r in rows if r['phase']==row['phase'] and
                        r['repeat']==row['repeat'] and r['variant']=='baseline')
    row['exact_keys'] = row['keys']==baseline_row['keys']
    row['exact_poses'] = row['poses']==baseline_row['poses']
out = root/'.tests/benchmarks'/f'position_{label}.json'
report = json.loads(out.read_text())
report['rows'] = rows
report['prototype_sha256'] = hashlib.sha256(Path(prototypes.__file__).read_bytes()).hexdigest()
out.write_text(json.dumps(report,indent=2))
print('STRATEGY_RESULTS',json.dumps(rows),flush=True)
