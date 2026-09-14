"""Automatically fit existing animation-rig controls after a transform import."""
import bpy
from . import create_animation_rig as rig


def import_with_matching(importer, context, filepath, transforms, materials, visibility, first, obj=None):
    obj = obj or context.object
    match = bool(transforms and obj and obj.type == 'ARMATURE' and rig.armature_has_animation_rig(obj))
    states = [(con,con.mute) for pb in obj.pose.bones for con in pb.constraints] if match else []
    paused = rig._IK_FK_MUTE_SYNC_PAUSED
    if match:
        rig.pause_ik_fk_mute_sync(True)
    try:
        # The importer must recover original local transforms, unaffected by
        # controls left at the last pose of the previously imported action.
        for con,_ in states:
            con.mute=True
        result=importer(context,filepath,transforms,materials,visibility,first,obj)
    finally:
        for con,state in states:
            con.mute=state
        if match:
            rig.pause_ik_fk_mute_sync(paused)
    if match:
        match_imported_animation(context,obj)
    return result


def match_imported_animation(context,obj):
    from . import ik_channels, finger_sliders, component_matching, component_workflow
    if not rig.armature_has_animation_rig(obj):
        return
    action=obj.animation_data.action if obj.animation_data else None
    if action is None:
        return
    # Material-only imports must not key unrelated rig controls.
    from ..anim.fcurve_compat import get_all_action_fcurves
    if not any(fc.data_path.startswith('pose.bones[') for fc in get_all_action_fcurves(action,id_type='OBJECT')):
        return
    has_components=component_workflow.has_components(obj)
    has_fingers=finger_sliders.has_finger_sliders(obj)
    mode=obj.mode
    try:
        rig._activate_armature(context,obj)
        if rig.armature_has_ik(obj):
            # Old custom poses must not leak into the IK source sample.
            muted=[(con,con.mute) for pb in obj.pose.bones for con in pb.constraints
                   if con.name.startswith('SUB Component ') or con.name.startswith(finger_sliders.FINGER_CON_PREFIX)]
            try:
                for con,_ in muted:
                    con.mute=True
                ik_channels.match(context,obj,entire=True,key=True)
            finally:
                for con,state in muted:
                    con.mute=state
        if has_components or has_fingers:
            component_matching.match_animation(context,obj,context.scene.frame_start,
                context.scene.frame_end,include_fingers=has_fingers,match_ik=False)
        action['sub_rig_import_matched']=True
    finally:
        if obj.mode!=mode and mode in {'OBJECT','POSE'}:
            bpy.ops.object.mode_set(mode=mode)
