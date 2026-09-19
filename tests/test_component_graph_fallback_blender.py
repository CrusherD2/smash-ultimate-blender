"""A rejected native candidate must retry without leaving bad keys or controls."""
from pathlib import Path
import importlib
fixture=Path(__file__).with_name('test_finger_full_hand_speed_blender.py')
prefix,suffix=fixture.read_text(encoding='utf-8-sig').split('started=time.perf_counter()',1)
exec(compile(prefix,str(fixture),'exec'))
graph=importlib.import_module(MODULE+'.source.extras.component_graph')
original=graph.Graph.evaluate
evaluations=[0]
victim=next(pb.name for pb,con in fingers._iter_finger_slider_constraints(obj))
def corrupt_candidate(self):
    result=original(self)
    evaluations[0]+=1
    if evaluations[0]==4:
        # Simulate an accepted native result which does not match Blender.
        # The reported detached pose stays correct, but its applied channels do not.
        self.obj.pose.bones[victim].location.x+=.25
    return result
graph.Graph.evaluate=corrupt_candidate
try:
    exec(compile('started=time.perf_counter()'+suffix,str(fixture),'exec'))
finally:
    graph.Graph.evaluate=original
assert graph.LAST_DIAGNOSTICS['fallback_frames']==1,graph.LAST_DIAGNOSTICS
assert 'verification failed' in graph.LAST_DIAGNOSTICS['fallback_reason'],graph.LAST_DIAGNOSTICS
# Unsupported user constraints must decline at capture instead of approximating.
extra=obj.pose.bones[names[0]].constraints.new('LIMIT_ROTATION')
extra.name='User custom limit'
extra.owner_space='CUSTOM'
try:
    result=graph.capture(obj,set(names),set(),set(names))
    assert result is None
    assert 'Unsupported constraint LIMIT_ROTATION' in graph.LAST_DIAGNOSTICS['declined'],graph.LAST_DIAGNOSTICS
finally:
    obj.pose.bones[names[0]].constraints.remove(extra)
print('DETACHED GRAPH VERIFICATION RETRY AND CAPTURE GUARD PASSED')
