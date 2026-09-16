from pathlib import Path
fixture=Path(__file__).with_name('test_face_components_blender.py')
exec(compile(fixture.read_text(encoding='utf-8-sig').split('# Removing face controllers')[0],str(fixture),'exec'))
selection=importlib.import_module(MODULE+'.source.extras.component_selection')
editor.is_open=True
editor.armature=obj
mouth=obj.pose.bones[cc.control_name(obj,editor.components[1])]
lids=obj.pose.bones[cc.control_name(obj,editor.components[0])]
editor.active_index=0
obj.data.bones.active=mouth.bone
assert selection.sync(bpy.context)
assert editor.active_index==1
obj.data.bones.active=lids.bone
assert selection.sync(bpy.context)
assert editor.active_index==0
# Manual list navigation remains possible until viewport selection changes.
editor.active_index=1
assert not selection.sync(bpy.context)
assert editor.active_index==1
obj.data.bones.active=obj.data.bones['Head']
assert not selection.sync(bpy.context)
assert editor.active_index==1
print('COMPONENT PANEL FOLLOWS SELECTED SLIDER PASSED')
