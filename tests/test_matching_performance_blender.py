from pathlib import Path
import time
fixture=Path(__file__).with_name('test_component_face_matching_blender.py')
source=fixture.read_text(encoding='utf-8-sig')
marker="matching=importlib.import_module(MODULE+'.source.extras.component_matching')"
assert marker in source
instrument=marker+"\n_calls=[0]\n_original_update=matching._update\ndef counted(*args):\n    _calls[0]+=1\n    return _original_update(*args)\nmatching._update=counted\n_started=time.perf_counter()"
exec(compile(source.replace(marker,instrument),str(fixture),'exec'))
print('MATCH BENCHMARK',_calls[0],round(time.perf_counter()-_started,3))
