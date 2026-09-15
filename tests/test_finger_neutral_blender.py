from pathlib import Path
fixture=Path(__file__).with_name('test_rig_import_matching_blender.py')
exec(compile(fixture.read_text(encoding='utf-8-sig').split('scene=bpy.context.scene')[0],str(fixture),'exec'))
from mathutils import Matrix
# Include both bend-axis signs and all cascade positions.
bpy.ops.object.mode_set(mode='EDIT')
bone('HandR',(1,0,2),'Trans')
for side in ('L','R'):
    for digit in range(1,6):
        for segment in range(4):
            name=f'Finger{side}{digit}{segment}'
            if name not in obj.data.edit_bones:
                bone(name,((1 if side=='R' else 0)+digit*.1,segment*.25,2),'Hand'+side if segment==0 else f'Finger{side}{digit}{segment-1}')
bpy.ops.object.mode_set(mode='POSE')
expected={p.name:p.matrix.copy() for p in obj.pose.bones}
fingers.build_finger_sliders(bpy.context,obj)
bpy.context.view_layer.update()
for name,wanted in expected.items():
    actual=obj.evaluated_get(bpy.context.evaluated_depsgraph_get()).pose.bones[name].matrix
    assert max(abs(actual[i][j]-wanted[i][j]) for i in range(4) for j in range(4))<1e-5,name
# Both sweep directions curl, with zero neutral for positive/negative weights.
for pb,con in fingers._iter_finger_slider_constraints(obj):
    if 'Cascade' not in con.name: continue
    slider=obj.pose.bones[con.subtarget]
    half=obj.data['sub_finger_slider_travel']
    slider.location.x=0
    assert abs(fingers._constraint_amount(slider,con,half))<1e-6
    slider.location.x=-half if 'Cascade-' in con.name else half
    assert abs(fingers._constraint_amount(slider,con,half)-1)<1e-6
    slider.location.x=0
print('FINGER REST POSE AND BOTH CASCADE DIRECTIONS PASSED')

fingers.set_finger_slider_mode(obj,True,bpy.context,show_both=True)
assert obj.data.collections[fingers.SLIDER_COLLECTION].is_visible
assert obj.data.collections[fingers.CIRCLE_COLLECTION].is_visible
for b in obj.data.bones:
    if fingers.is_finger_control_bone(b.name) or fingers.is_finger_circle_bone(b.name):
        assert not b.hide,b.name
        if not fingers.is_finger_pad_bone(b.name): assert not b.hide_select,b.name
fingers.set_finger_slider_mode(obj,False,bpy.context)
assert not obj.data.collections[fingers.SLIDER_COLLECTION].is_visible
assert obj.data.collections[fingers.CIRCLE_COLLECTION].is_visible
print('BOTH FINGER DISPLAY MODE PASSED')
