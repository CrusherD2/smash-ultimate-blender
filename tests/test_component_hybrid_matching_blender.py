"""Full match/export/rematch/bake with a reference-only mouth and native eyes/lids."""
from pathlib import Path
fixture=Path(__file__).with_name('test_component_face_matching_blender.py')
code=fixture.read_text(encoding='utf-8-sig')
injection="""
limit=obj.pose.bones['Jaw'].constraints.new('LIMIT_ROTATION')
limit.name='User rotation limit';limit.owner_space='CUSTOM';limit.space_object=obj;limit.space_subtarget='Head'
limit.use_limit_z=True;limit.min_z=-.2;limit.max_z=.3
"""
code=code.replace('source={}',injection+'\nsource={}',1)
exec(compile(code,str(fixture),'exec'))
graph=importlib.import_module(MODULE+'.source.extras.component_graph')
diagnostics=graph.LAST_DIAGNOSTICS
assert diagnostics['native_frames']==3,diagnostics
assert diagnostics['blender_evaluations']>0,diagnostics
assert {entry['mode'] for entry in diagnostics['components'].values()}=={'native','Blender'},diagnostics
assert diagnostics['fallback_frames']==0,diagnostics
print('MIXED NATIVE/REFERENCE MATCH, REMATCH, EXPORT AND BAKE PASSED',diagnostics)
