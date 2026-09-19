from pathlib import Path
import sys, os
graph_fixture_name=os.environ.get('SUB_GRAPH_FIXTURE','test_finger_full_hand_speed_blender.py')
fixture=Path(__file__).with_name(graph_fixture_name)
exec(compile(fixture.read_text(encoding='utf-8-sig'),str(fixture),'exec'))
graph=sys.modules[MODULE+'.source.extras.component_graph']
print('DETACHED GRAPH',graph.LAST_DIAGNOSTICS)
assert graph.LAST_DIAGNOSTICS.get('native_frames',0)>0,graph.LAST_DIAGNOSTICS
assert graph.LAST_DIAGNOSTICS.get('fallback_frames',0)==0,graph.LAST_DIAGNOSTICS
print('DETACHED GRAPH INTEGRATION PASSED',graph_fixture_name)
