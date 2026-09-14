"""Time Blender graph updates explicitly; cProfile hides some RNA calls."""
from pathlib import Path
from types import SimpleNamespace
test=Path(__file__).with_name('benchmark_shyguy_match_blender.py')
exec(compile(test.read_text().split('\nrows=[]')[0],str(test),'exec'))
evaluate=ik._evaluate_match_steps
stats={}
def measured(ctx,steps,batch):
    def update():
        t=time.perf_counter()
        try: return ctx.view_layer.update()
        finally:
            stats['seconds']+=time.perf_counter()-t
            stats['calls']+=1
    return evaluate(SimpleNamespace(view_layer=SimpleNamespace(update=update)),steps,batch)
ik._evaluate_match_steps=measured
rows=[]
for phase in ('IMPORT','MATCH'):
    stats.update(seconds=0.,calls=0)
    row=run(phase,True)
    row.update(search_graph_update_seconds=stats['seconds'],search_graph_updates=stats['calls'])
    rows.append(row)
    print('SHYGUY_GRAPH_TIME',row,flush=True)
(out/'graph_time.json').write_text(json.dumps(rows,indent=2))
