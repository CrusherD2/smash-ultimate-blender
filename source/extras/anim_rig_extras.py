"""Add / remove Animation Rig extras (IK, eyes, fingers) after Create.

Also re-match IK to a newly loaded animation.
"""

from __future__ import annotations

import bpy
from bpy.types import Operator

from .create_animation_rig import (
    ProgressCursor,
    _activate_armature,
    _ensure_extra_arm_ik,
    _ensure_ik_influence_drivers,
    _ik_fk_props,
    apply_eye_look_shape,
    apply_eye_option_shapes,
    armature_has_ik,
    find_target_armature,
)
from . import anim_layers_compat
from . import apply_ik_animation
from . import eye_rig
from . import finger_sliders
from . import fk_to_ik

_IK_MATCHED_FLAG = "sub_ik_matched_limbs"
_IK_MATCHED_DONE = "sub_ik_matched"


def _current_anim_action(armature_obj):
    """Active action for match tracking (Animation Layers aware)."""
    if armature_obj is None:
        return None
    anim = getattr(armature_obj, "animation_data", None)
    if anim is None:
        return None

    # Prefer the active Animation Layers strip when AL is on
    try:
        als = getattr(armature_obj, "als", None)
        if als is not None and getattr(als, "turn_on", False):
            index = int(getattr(als, "layer_index", 0) or 0)
            tracks = getattr(anim, "nla_tracks", None)
            if tracks and 0 <= index < len(tracks) and tracks[index].strips:
                strip_action = tracks[index].strips[0].action
                if strip_action is not None:
                    return strip_action
    except Exception:
        pass

    action = getattr(anim, "action", None)
    if action is not None:
        return action
    return None


def _actions_for_ik_match_mark(armature_obj):
    """Actions that should receive the matched flag (active + AL strip)."""
    actions = []
    seen = set()

    def _add(action):
        if action is None:
            return
        key = action.as_pointer()
        if key in seen:
            return
        seen.add(key)
        actions.append(action)

    _add(_current_anim_action(armature_obj))
    anim = getattr(armature_obj, "animation_data", None)
    if anim is not None:
        _add(getattr(anim, "action", None))
        try:
            als = getattr(armature_obj, "als", None)
            if als is not None and getattr(als, "turn_on", False):
                index = int(getattr(als, "layer_index", 0) or 0)
                tracks = getattr(anim, "nla_tracks", None)
                if tracks and 0 <= index < len(tracks) and tracks[index].strips:
                    _add(tracks[index].strips[0].action)
        except Exception:
            pass
    return actions


def _ik_matched_limbs(action):
    if action is None:
        return set()
    raw = str(action.get(_IK_MATCHED_FLAG, "") or "")
    return {part for part in raw.split("|") if part in {"ARMS", "LEGS"}}


def mark_ik_matched(armature_obj, limbs="BOTH"):
    """Record that Match IK finished for this action.

    Sets a whole-action done flag so the Match button hides after a Legs-only
    (or Arms-only) match — typical when both IK types exist on the rig.
    """
    actions = _actions_for_ik_match_mark(armature_obj)
    if not actions:
        return
    for action in actions:
        state = _ik_matched_limbs(action)
        if limbs == "BOTH":
            state.update({"ARMS", "LEGS"})
        elif limbs in {"ARMS", "LEGS"}:
            state.add(limbs)
        action[_IK_MATCHED_FLAG] = "|".join(sorted(state))
        action[_IK_MATCHED_DONE] = True


def animation_needs_ik_match(armature_obj):
    """True when this action still needs Match IK."""
    if armature_obj is None or not armature_has_ik(armature_obj):
        return False
    action = _current_anim_action(armature_obj)
    # No action yet — still offer Match so the user can run it after loading anim
    if action is None:
        return True
    if bool(action.get(_IK_MATCHED_DONE, False)):
        return False
    matched = _ik_matched_limbs(action)
    # Legacy limb flags: hide once every present IK limb type was matched
    if armature_has_ik(armature_obj, "ARMS") and "ARMS" not in matched:
        return True
    if armature_has_ik(armature_obj, "LEGS") and "LEGS" not in matched:
        return True
    return False


def has_eye_look(armature_obj):
    if armature_obj is None or armature_obj.type != "ARMATURE":
        return False
    return armature_obj.pose.bones.get(eye_rig.EYE_CTRL_BONE) is not None


def has_finger_controls(armature_obj):
    return finger_sliders.has_finger_sliders(armature_obj)


def _draw_ik_fk_switch_rows(layout, arm):
    """Shared Arms/Legs/Both IK↔FK switches (Animation Rig + IK Tools)."""
    if arm is None or not armature_has_ik(arm):
        return
    from .create_animation_rig import armature_ik_is_enabled

    has_arms = armature_has_ik(arm, "ARMS")
    has_legs = armature_has_ik(arm, "LEGS")
    if has_arms:
        row = layout.row(align=True)
        row.label(text="Arms")
        if armature_ik_is_enabled(arm, "ARMS"):
            op = row.operator("sub.anim_rig_toggle_ik_fk", text="Switch to FK", icon="BONE_DATA")
        else:
            op = row.operator("sub.anim_rig_toggle_ik_fk", text="Switch to IK", icon="CON_KINEMATIC")
        op.limbs = "ARMS"
    if has_legs:
        row = layout.row(align=True)
        row.label(text="Legs")
        if armature_ik_is_enabled(arm, "LEGS"):
            op = row.operator("sub.anim_rig_toggle_ik_fk", text="Switch to FK", icon="BONE_DATA")
        else:
            op = row.operator("sub.anim_rig_toggle_ik_fk", text="Switch to IK", icon="CON_KINEMATIC")
        op.limbs = "LEGS"
    if has_arms and has_legs:
        row = layout.row(align=True)
        row.label(text="Both")
        op = row.operator("sub.anim_rig_toggle_ik_fk", text="IK", icon="CON_KINEMATIC")
        op.limbs = "BOTH"
        op.set_enabled = True
        op.enable_ik = True
        op = row.operator("sub.anim_rig_toggle_ik_fk", text="FK", icon="BONE_DATA")
        op.limbs = "BOTH"
        op.set_enabled = True
        op.enable_ik = False
    if animation_needs_ik_match(arm):
        row = layout.row(align=True)
        row.operator(
            "sub.match_ik_to_animation",
            text="Match IK to Current Animation",
            icon="CON_ARMATURE",
        )


def draw_anim_rig_extras(layout, context, arm):
    """UI under Create Animation Rig: detect missing/present extras."""
    from .create_animation_rig import armature_has_animation_rig

    if arm is None or not armature_has_animation_rig(arm):
        return

    has_ik = armature_has_ik(arm)
    has_eyes = has_eye_look(arm)
    has_fingers = has_finger_controls(arm)

    box = layout.box()
    box.label(text="Rig Extras", icon="MODIFIER")

    # IK
    row = box.row(align=True)
    row.label(text="IK")
    if has_ik:
        row.label(text="Added", icon="CHECKMARK")
        row.operator("sub.anim_rig_remove_ik", text="Bake & Remove", icon="ACTION").bake = True
        row.operator("sub.anim_rig_remove_ik", text="", icon="X").bake = False
    else:
        row.label(text="Missing")
        row.operator("sub.anim_rig_add_ik", text="Add IK", icon="CON_KINEMATIC")

    # Eyes
    row = box.row(align=True)
    row.label(text="Eyes")
    if has_eyes:
        row.label(text="Added", icon="CHECKMARK")
        row.operator("sub.anim_rig_remove_eyes", text="Bake & Remove", icon="ACTION").bake = True
        row.operator("sub.anim_rig_remove_eyes", text="", icon="X").bake = False
    else:
        row.label(text="Missing")
        row.operator("sub.anim_rig_add_eyes", text="Add Eyes", icon="HIDE_OFF")

    # Fingers
    row = box.row(align=True)
    row.label(text="Fingers")
    if has_fingers:
        row.label(text="Added", icon="CHECKMARK")
        row.operator("sub.anim_rig_remove_fingers", text="Bake & Remove", icon="ACTION").bake = True
        row.operator("sub.anim_rig_remove_fingers", text="", icon="X").bake = False
    else:
        row.label(text="Missing")
        row.operator("sub.anim_rig_add_fingers", text="Add Fingers", icon="DRIVER")


class SUB_OP_match_ik_to_animation(Operator):
    """Re-run FK→IK matching for the current / entire animation (dialog)."""

    bl_idname = "sub.match_ik_to_animation"
    bl_label = "Match IK to Current Animation"
    bl_description = (
        "Match IK controllers to the FK pose for this animation "
        "(current frame or entire range — same dialog as Create IK)"
    )
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        arm = find_target_armature(context)
        return arm is not None and armature_has_ik(arm)

    def execute(self, context):
        arm = find_target_armature(context)
        if arm is None or not armature_has_ik(arm):
            self.report({"ERROR"}, "No IK bones on this armature.")
            return {"CANCELLED"}
        _activate_armature(context, arm)
        if context.mode != "POSE":
            bpy.ops.object.mode_set(mode="POSE")
        has_arms = armature_has_ik(arm, "ARMS")
        has_legs = armature_has_ik(arm, "LEGS")
        if has_arms and not has_legs:
            mode = "ARMS"
        elif has_legs and not has_arms:
            mode = "LEGS"
        else:
            # Both present — dialog defaults to Legs; user can pick Arms/Both
            mode = "LEGS"
        fk_to_ik.invoke_position_match_dialog(cleanup_mode=mode)
        return {"FINISHED"}


class SUB_OP_anim_rig_add_ik(Operator):
    bl_idname = "sub.anim_rig_add_ik"
    bl_label = "Add IK"
    bl_description = "Create arm + leg IK bones on this armature and open the match dialog"
    bl_options = {"REGISTER", "UNDO"}

    match_position: bpy.props.BoolProperty(name="Match IK to FK", default=True)

    @classmethod
    def poll(cls, context):
        arm = find_target_armature(context)
        return arm is not None and not armature_has_ik(arm)

    def execute(self, context):
        arm = find_target_armature(context)
        if arm is None:
            return {"CANCELLED"}
        _activate_armature(context, arm)
        with anim_layers_compat.anim_layers_paused():
            result = bpy.ops.sub.create_ik_bones("EXEC_DEFAULT", match_position=False)
            if result != {"FINISHED"} and not armature_has_ik(arm):
                self.report({"ERROR"}, "Could not create IK bones.")
                return {"CANCELLED"}
            if context.mode != "POSE":
                bpy.ops.object.mode_set(mode="POSE")
            _ensure_extra_arm_ik(arm)
            props = _ik_fk_props(arm)
            props.sub_use_ik = True
            props.sub_use_ik_arms = True
            props.sub_use_ik_legs = True
            _ensure_ik_influence_drivers(arm)
        if self.match_position:
            fk_to_ik.invoke_position_match_dialog(cleanup_mode="BOTH")
        self.report({"INFO"}, f"Added IK to {arm.name}.")
        return {"FINISHED"}


class SUB_OP_anim_rig_remove_ik(Operator):
    bl_idname = "sub.anim_rig_remove_ik"
    bl_label = "Remove IK"
    bl_description = "Remove IK bones (optionally bake FK visuals first)"
    bl_options = {"REGISTER", "UNDO"}

    bake: bpy.props.BoolProperty(name="Bake first", default=True, options={"SKIP_SAVE"})

    @classmethod
    def poll(cls, context):
        arm = find_target_armature(context)
        return arm is not None and armature_has_ik(arm)

    def execute(self, context):
        arm = find_target_armature(context)
        if arm is None:
            return {"CANCELLED"}
        _activate_armature(context, arm)
        with anim_layers_compat.anim_layers_paused():
            if self.bake:
                with ProgressCursor(context) as progress:
                    progress.update(0.15)
                    apply_ik_animation.bake_and_clean_current_action(
                        context, arm, remove_ik_rig=True
                    )
                    progress.update(1.0)
                msg = "Baked and removed IK"
            else:
                from .create_animation_rig import (
                    _remove_ik_influence_drivers,
                    _remove_ik_fk_switch_keys,
                    unmute_all_ik_fk_fcurves,
                )
                unmute_all_ik_fk_fcurves(arm)
                fk_names = apply_ik_animation.collect_fk_bone_names(arm)
                apply_ik_animation.remove_constraints_from_bones(arm, fk_names)
                apply_ik_animation.delete_ik_bones_from_armature(arm)
                _remove_ik_influence_drivers(arm)
                _remove_ik_fk_switch_keys(arm)
                unmute_all_ik_fk_fcurves(arm)
                if context.mode not in {"POSE", "OBJECT"}:
                    bpy.ops.object.mode_set(mode="POSE")
                msg = "Removed IK (no bake)"
        self.report({"INFO"}, f"{msg} on {arm.name}.")
        return {"FINISHED"}


class SUB_OP_anim_rig_add_eyes(Operator):
    bl_idname = "sub.anim_rig_add_eyes"
    bl_label = "Add Eye Look"
    bl_description = "Add the eye look control bone and shapes"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        arm = find_target_armature(context)
        return arm is not None and not has_eye_look(arm)

    def execute(self, context):
        arm = find_target_armature(context)
        if arm is None:
            return {"CANCELLED"}
        _activate_armature(context, arm)
        if context.mode != "POSE":
            bpy.ops.object.mode_set(mode="POSE")
        ssp = getattr(context.scene, "sub_scene_properties", None)
        try:
            eye_rig.setup_eye_cv31_tracks(arm, context)
        except Exception:
            pass
        ok, message = eye_rig.add_eye_look_control_bone(
            arm, include_invert_sliders=True, material_anim="MATCH"
        )
        if not ok:
            self.report({"ERROR"}, message or "Could not add eye look.")
            return {"CANCELLED"}
        apply_eye_look_shape(context, arm)
        apply_eye_option_shapes(context, arm, ssp)
        if ssp is not None:
            ssp.eye_look_mode = "OFFSET"
            eye_rig.ensure_eye_live_preview(context.scene)
        self.report({"INFO"}, message)
        return {"FINISHED"}


class SUB_OP_anim_rig_remove_eyes(Operator):
    bl_idname = "sub.anim_rig_remove_eyes"
    bl_label = "Remove Eye Look"
    bl_description = "Remove eye look control (optionally bake CustomVector31 first)"
    bl_options = {"REGISTER", "UNDO"}

    bake: bpy.props.BoolProperty(name="Bake first", default=True, options={"SKIP_SAVE"})

    @classmethod
    def poll(cls, context):
        return has_eye_look(find_target_armature(context))

    def execute(self, context):
        arm = find_target_armature(context)
        if arm is None:
            return {"CANCELLED"}
        _activate_armature(context, arm)
        if context.mode != "POSE":
            bpy.ops.object.mode_set(mode="POSE")
        if self.bake:
            baked = eye_rig.bake_eye_look_keys(context, arm)
            eye_rig.remove_eye_look_control_bone(arm)
            self.report({"INFO"}, f"Baked {baked} eye keys and removed eye look.")
        else:
            eye_rig.remove_eye_look_control_bone(arm)
            self.report({"INFO"}, "Removed eye look (no bake).")
        return {"FINISHED"}


class SUB_OP_anim_rig_add_fingers(Operator):
    bl_idname = "sub.anim_rig_add_fingers"
    bl_label = "Add Finger Sliders"
    bl_description = "Build finger slider controls on this armature"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        arm = find_target_armature(context)
        return arm is not None and not has_finger_controls(arm)

    def execute(self, context):
        arm = find_target_armature(context)
        if arm is None:
            return {"CANCELLED"}
        _activate_armature(context, arm)
        count = finger_sliders.build_finger_sliders(context, arm)
        self.report({"INFO"}, f"Added {count} finger controls.")
        return {"FINISHED"}


class SUB_OP_anim_rig_remove_fingers(Operator):
    bl_idname = "sub.anim_rig_remove_fingers"
    bl_label = "Remove Finger Sliders"
    bl_description = "Remove finger sliders (optionally bake finger poses first)"
    bl_options = {"REGISTER", "UNDO"}

    bake: bpy.props.BoolProperty(name="Bake first", default=True, options={"SKIP_SAVE"})

    @classmethod
    def poll(cls, context):
        return has_finger_controls(find_target_armature(context))

    def execute(self, context):
        arm = find_target_armature(context)
        if arm is None:
            return {"CANCELLED"}
        _activate_armature(context, arm)
        if self.bake:
            keyed = finger_sliders.bake_finger_slider_keys(context, arm)
            finger_sliders.remove_finger_sliders(context, arm)
            self.report({"INFO"}, f"Baked {keyed} finger keys and removed sliders.")
        else:
            finger_sliders.remove_finger_sliders(context, arm)
            self.report({"INFO"}, "Removed finger sliders (no bake).")
        return {"FINISHED"}
