from pathlib import Path
import time
fixture=Path(__file__).with_name('test_rig_import_matching_blender.py')
s=fixture.read_text(encoding='utf-8-sig')
marker="scene=bpy.context.scene"
s=s.replace(marker,marker+"\nmatching=importlib.import_module(MODULE+'.source.extras.component_matching')\n_calls=[0]\nupdate=matching._update\ndef counted(*args):\n    _calls[0]+=1\n    return update(*args)\nmatching._update=counted\nstarted=time.perf_counter()")
exec(compile(s,str(fixture),'exec'))
print('FINGER BENCHMARK',_calls[0],round(time.perf_counter()-started,3))
