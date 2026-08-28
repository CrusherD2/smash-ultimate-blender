"""Bulk visual action baking for the Ultimate bake dialog."""

import bpy

from ..blender_compat import assign_action, set_pose_bone_select
from ...expy_kit import bone_utils
from ...expy_kit.operators import clean_baked_action, validate_actions


def _select_bones_for_bake(dest_armature, source_armature):
    """Return bone names selected for a visual bake."""
    bone_names = []

    if source_armature != dest_armature:
        for pb in bone_utils.get_constrained_controls(dest_armature, unselect=True, use_deform=True):
            if pb.name + "_RET" in source_armature.data.bones:
                set_pose_bone_select(pb, True)
                bone_names.append(pb.name)
    else:
        for pb in dest_armature.pose.bones:
            set_pose_bone_select(pb, True)
            bone_names.append(pb.name)

    return bone_names


def bake_visible_actions(
    context,
    source_armature,
    dest_armature,
    actions_to_bake,
    fake_user_new=True,
    clear_users_old=True,
):
    """Visually bake a list of actions from source_armature onto dest_armature."""
    if not actions_to_bake:
        return 0

    if dest_armature.animation_data is None:
        dest_armature.animation_data_create()
    if source_armature.animation_data is None:
        source_armature.animation_data_create()

    context.view_layer.objects.active = dest_armature
    dest_armature.select_set(True)
    if context.mode != 'POSE':
        bpy.ops.object.mode_set(mode='POSE')

    baked_count = 0
    use_retarget_clean = source_armature != dest_armature

    try:
        context.window.cursor_modal_set('WAIT')

        for action in list(actions_to_bake):
            if not validate_actions(action, source_armature.path_resolve):
                continue

            bone_names = _select_bones_for_bake(dest_armature, source_armature)
            if not bone_names:
                continue

            assign_action(source_armature.animation_data, action)
            fr_start, fr_end = action.frame_range
            bpy.ops.nla.bake(
                frame_start=int(fr_start),
                frame_end=int(fr_end),
                bake_types={'POSE'},
                only_selected=True,
                visual_keying=True,
                clear_constraints=False,
            )

            if not dest_armature.animation_data or not dest_armature.animation_data.action:
                continue

            baked_action = dest_armature.animation_data.action
            baked_action.use_fake_user = fake_user_new

            if use_retarget_clean:
                clean_baked_action(action, baked_action, dest_armature, baked_bone_names=bone_names)
            else:
                clean_baked_action(action, baked_action, dest_armature)

            original_name = action.name
            if "|" in original_name:
                clean_action_name = original_name.split("|")[-1]
            else:
                clean_action_name = original_name

            action.name = f"{original_name}_old"
            baked_action.name = clean_action_name
            assign_action(dest_armature.animation_data, baked_action)

            if clear_users_old:
                old_action = bpy.data.actions.get(f"{original_name}_old")
                if old_action and old_action.users > 0:
                    old_action.user_clear()

            baked_count += 1
    finally:
        context.window.cursor_modal_restore()

    return baked_count
