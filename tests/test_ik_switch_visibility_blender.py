"""Animated switches update only changed limbs and preserve independent IK poses."""
from pathlib import Path
import importlib
fixture=Path(__file__).with_name('test_ik_detail_acceleration_blender.py')
exec(compile(fixture.read_text().split('\naudit()\nfor repeat')[0],str(fixture),'exec'))
rig=importlib.import_module(MODULE+'.source.extras.create_animation_rig')
original=rig._set_ik_bone_visibility
calls=[]
def tracked(armature,visible,limbs='BOTH',**kwargs):
    calls.append(limbs)
    return original(armature,visible,limbs,**kwargs)
rig._set_ik_bone_visibility=tracked
rig._IK_VIS_CACHE.clear()

def switch(value):
    old=rig._IK_FK_APPLYING
    rig._IK_FK_APPLYING=True
    try:obj.data.sub_use_ik_legs=value
    finally:rig._IK_FK_APPLYING=old
    rig._sync_ik_fk_visibility(scene)

try:
    switch(0)
    assert calls==['LEGS'],calls
    assert not obj.data.bones['LegL'].hide
    assert obj.data.bones['FootIKL'].hide
    calls.clear()
    switch(0)
    assert not calls,calls
    switch(.5)
    assert calls==['LEGS'],calls
    assert not obj.data.bones['LegL'].hide
    assert not obj.data.bones['FootIKL'].hide
    calls.clear()
    switch(.7)
    assert not calls,calls
    switch(1)
    assert calls==['LEGS'],calls
    assert obj.data.bones['LegL'].hide
    assert not obj.data.bones['FootIKL'].hide
    # Explicit show-both remains authoritative across animated mode changes.
    rig.set_off_mode_bones_hidden(obj,False)
    switch(0)
    assert not obj.data.bones['LegL'].hide
    assert not obj.data.bones['FootIKL'].hide
    rig.set_off_mode_bones_hidden(obj,True)
    # Sample the same keyed switches with and without the display handler.
    for frame,value in ((1,False),(5,True),(10,False),(16,True)):
        rig._key_use_ik(obj,frame,limbs='LEGS',enabled=value)
    snapshots=[]
    handler=rig._sync_ik_fk_visibility
    for enabled in (False,True):
        if handler in bpy.app.handlers.frame_change_post:bpy.app.handlers.frame_change_post.remove(handler)
        if enabled:bpy.app.handlers.frame_change_post.append(handler)
        poses=[]
        for frame in range(1,17):
            scene.frame_set(frame)
            bpy.context.view_layer.update()
            poses.extend(float(value) for name in ('LegL','KneeL','FootL','LegR','KneeR','FootR','H_Helper')
                         for row in obj.pose.bones[name].matrix for value in row)
        snapshots.append(poses)
    error=max(abs(a-b) for a,b in zip(*snapshots))
    assert error<1e-6,error
    # The actual FK button must expose original animated bones and allow edits.
    assert bpy.ops.sub.anim_rig_toggle_ik_fk(
        limbs='LEGS', set_enabled=True, enable_ik=False) == {'FINISHED'}
    for name in ('LegL', 'KneeL', 'FootL'):
        assert not obj.data.bones[name].hide, name
        pb = obj.pose.bones[name]
        output = pb.constraints.get(ik.OUTPUT)
        assert output is None or output.influence == 0.0, name
    pb = obj.pose.bones['KneeL']
    before = pb.matrix.translation.copy()
    pb.location.x += .25
    bpy.context.view_layer.update()
    assert (pb.matrix.translation - before).length > .1
    print('IK_SWITCH_VISIBILITY_OK; POSE ERROR',error)
finally:
    rig._set_ik_bone_visibility=original
    if rig._sync_ik_fk_visibility not in bpy.app.handlers.frame_change_post:
        bpy.app.handlers.frame_change_post.append(rig._sync_ik_fk_visibility)
