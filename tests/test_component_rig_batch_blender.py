"""Rig creation samples and matches a preset plus fingers in one pass."""
from pathlib import Path
fixture=Path(__file__).with_name('test_finger_creation_match_blender.py')
exec(compile(fixture.read_text(encoding='utf-8-sig').split('expected=snapshot()')[0],str(fixture),'exec'))
matching=importlib.import_module(MODULE+'.source.extras.component_matching')
graph=importlib.import_module(MODULE+'.source.extras.component_graph')
expected=snapshot()
component('ISOLATED','Floating Wing',['WingL'])
editor.save_on_build=False
bpy.context.scene.sub_scene_properties.clean_keyframes_after_rig=False
original=matching.match_animation
calls=[]
def counted(*args,**kwargs):
    calls.append(kwargs)
    return original(*args,**kwargs)
matching.match_animation=counted
with tempfile.TemporaryDirectory() as folder:
    cc.preset_dir=lambda:Path(folder)
    preset=cc.save_preset(editor)
    assert bpy.ops.sub.create_animation_rig(setup_ik=False,setup_eye_look=False,
        setup_finger_sliders=True,setup_custom_components=True,
        custom_component_preset=preset.name)=={'FINISHED'}
assert len(calls)==1 and calls[0]['include_fingers'],calls
assert graph.LAST_DIAGNOSTICS['batched_components']==2,graph.LAST_DIAGNOSTICS
assert graph.LAST_DIAGNOSTICS['fallback_frames']==0,graph.LAST_DIAGNOSTICS
actual=snapshot()
for f,poses in expected.items():
    for name,wanted in poses.items():
        error=max(abs(actual[f][name][r][c]-wanted[r][c]) for r in range(4) for c in range(4))
        assert error<2e-4,(f,name,error)
print('COMBINED PRESET AND FINGER RIG CREATION PASSED',graph.LAST_DIAGNOSTICS)
