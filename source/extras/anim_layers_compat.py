"""Compatibility helpers for Animation Layers during Smash Ultimate IK ops.

Animation Layers runs depsgraph handlers that sync NLA while armatures are
rebuilt (Edit Mode bones, IK constraints). That combination crashes Blender
(BKE_object_eval_eval_base_flags). Pause AL handlers around those ops.
"""

from __future__ import annotations

import sys
from contextlib import contextmanager, nullcontext


def _find_anim_layers_subscriptions():
    # Prefer already-loaded module
    for name, mod in list(sys.modules.items()):
        if not mod:
            continue
        if name == 'Animation_Layers.subscriptions' or name.endswith('.subscriptions'):
            if hasattr(mod, 'pause_subscriptions') and hasattr(mod, 'resume_subscriptions'):
                if 'Animation_Layers' in name or 'anim_layers' in name.lower() or name == 'Animation_Layers.subscriptions':
                    return mod
    # Import if the addon is enabled but not yet referenced
    try:
        import Animation_Layers.subscriptions as als  # type: ignore
        if hasattr(als, 'pause_subscriptions'):
            return als
    except Exception:
        pass
    for name, mod in list(sys.modules.items()):
        if mod and hasattr(mod, 'pause_subscriptions') and hasattr(mod, 'resume_subscriptions'):
            if 'Animation' in name and 'Layer' in name:
                return mod
    return None


def _find_anim_layers_module():
    for name, mod in list(sys.modules.items()):
        if not mod:
            continue
        if hasattr(mod, 'draw_embedded_ui') or hasattr(mod, 'convert_pose_to_additive_offsets'):
            if 'Animation_Layers' in name or name.endswith('anim_layers'):
                return mod
    try:
        import Animation_Layers.anim_layers as al  # type: ignore
        if hasattr(al, 'draw_embedded_ui') or hasattr(al, 'convert_pose_to_additive_offsets'):
            return al
    except Exception:
        pass
    return None


def anim_layers_enabled(obj):
    """True when Animation Layers is on for this object with at least one layer."""
    if obj is None:
        return False
    als = getattr(obj, 'als', None)
    layers = getattr(obj, 'Anim_Layers', None)
    if als is None or layers is None:
        return False
    try:
        if not bool(getattr(als, 'turn_on', False)):
            return False
        return len(layers) > 0
    except Exception:
        return False


def is_non_base_anim_layer(obj):
    """True when Anim Layers is on and the active layer is not the base (index 0)."""
    if not anim_layers_enabled(obj):
        return False
    try:
        return int(getattr(obj.als, 'layer_index', 0) or 0) > 0
    except Exception:
        return False


def make_pose_additive_on_active_layer(context, obj, bones):
    """
    Convert absolute pose/keys on bones into ADD-layer offsets and set Blend to Add.
    Returns (keyed_count, error_message).
    """
    al = _find_anim_layers_module()
    if al is None:
        return 0, "Animation Layers additive convert is unavailable"
    if obj is None or not bones:
        return 0, "No bones to convert"
    try:
        keyed = int(al.convert_pose_to_additive_offsets(context, obj, list(bones)) or 0)
    except Exception as exc:
        return 0, str(exc)

    _set_active_layer_blend(obj, 'ADD')
    return keyed, None


def _set_active_layer_blend(obj, blend_type):
    """Set the active Anim Layers strip (and tweak-mode) blend type."""
    try:
        anim_data = getattr(obj, 'animation_data', None)
        if anim_data is None or not getattr(anim_data, 'nla_tracks', None):
            return
        index = int(getattr(obj.als, 'layer_index', 0) or 0)
        tracks = anim_data.nla_tracks
        if 0 <= index < len(tracks) and tracks[index].strips:
            strip = tracks[index].strips[0]
            strip.blend_type = blend_type
            if getattr(anim_data, 'use_tweak_mode', False):
                anim_data.action_blend_type = blend_type
        if hasattr(obj.als, 'blend_type'):
            try:
                obj.als['blend_type'] = blend_type
            except Exception:
                pass
    except Exception:
        pass


def prepare_absolute_keys_on_layer(obj):
    """Force REPLACE while inserting absolute keys so ADD layers do not store deltas."""
    _set_active_layer_blend(obj, 'REPLACE')


def viewport_driving_action(obj):
    """Action (and slot) that actually drives the viewport pose.

    After Animation Layers Merge/Bake, ``animation_data.action`` is often None and
    only an NLA strip plays. Baking with keyframe_insert then creates an orphan
    action while the strip (what you see) never updates.
    """
    if obj is None:
        return None, None
    anim = getattr(obj, "animation_data", None)
    if anim is None:
        return None, None

    # Prefer the active Anim Layers strip
    if anim_layers_enabled(obj):
        try:
            index = int(getattr(obj.als, "layer_index", 0) or 0)
            tracks = anim.nla_tracks
            if 0 <= index < len(tracks) and tracks[index].strips:
                strip = tracks[index].strips[0]
                if strip.action is not None:
                    return strip.action, getattr(strip, "action_slot", None)
        except Exception:
            pass

    if anim.action is not None:
        return anim.action, getattr(anim, "action_slot", None)

    # AL merge leaves action=None — use the first unmuted strip
    for track in getattr(anim, "nla_tracks", []) or []:
        if track.mute or not track.strips:
            continue
        strip = track.strips[0]
        if strip.action is not None:
            return strip.action, getattr(strip, "action_slot", None)
    return None, None


@contextmanager
def bind_driving_action_for_bake(obj, context=None):
    """Point ``animation_data.action`` at the viewport-driving action for keying.

    Temporarily turns Animation Layers off so:
    - NLA-only evaluation (action=None after Merge/Bake) becomes an editable action
    - keyframe_insert writes into the strip action instead of an orphan action
    """
    from ..blender_compat import assign_action

    if obj is None:
        yield None
        return

    anim = getattr(obj, "animation_data", None)
    if anim is None:
        yield None
        return

    al_was_on = anim_layers_enabled(obj)
    prev_action = anim.action
    prev_slot = getattr(anim, "action_slot", None)
    prev_use_nla = bool(getattr(anim, "use_nla", True))
    target_action, target_slot = viewport_driving_action(obj)

    try:
        if al_was_on:
            # Property update assigns a strip action and disables NLA stacking.
            try:
                obj.als.turn_on = False
            except Exception:
                al_was_on = False

        if anim.action is None and target_action is not None:
            assign_action(anim, target_action)
            if target_slot is not None and hasattr(anim, "action_slot"):
                try:
                    anim.action_slot = target_slot
                except (AttributeError, TypeError, RuntimeError):
                    pass
        elif target_action is not None and anim.action != target_action:
            # Prefer the strip that was driving the viewport
            assign_action(anim, target_action)
            if target_slot is not None and hasattr(anim, "action_slot"):
                try:
                    anim.action_slot = target_slot
                except (AttributeError, TypeError, RuntimeError):
                    pass

        # Keep NLA from stacking on top of the bound action while we key
        try:
            anim.use_nla = False
        except Exception:
            pass

        yield anim.action
    finally:
        try:
            anim.use_nla = prev_use_nla
        except Exception:
            pass
        if al_was_on:
            try:
                obj.als.turn_on = True
            except Exception:
                # Fall back to restoring prior action binding
                assign_action(anim, prev_action)
                if prev_slot is not None and hasattr(anim, "action_slot"):
                    try:
                        anim.action_slot = prev_slot
                    except (AttributeError, TypeError, RuntimeError):
                        pass
        elif prev_action is not anim.action:
            # Non-AL: leave the bound action (keys live there). Only restore if
            # we had an action before and somehow lost it.
            if prev_action is not None and anim.action is None:
                assign_action(anim, prev_action)


@contextmanager
def anim_layers_paused():
    """Suspend Animation Layers handlers for the duration of the with-block."""
    als = _find_anim_layers_subscriptions()
    if als is None:
        yield
        return
    # Prefer the context manager if present
    paused_cm = getattr(als, 'paused_subscriptions', None)
    if callable(paused_cm):
        with paused_cm():
            yield
        return
    als.pause_subscriptions()
    try:
        yield
    finally:
        als.resume_subscriptions()


def maybe_paused():
    """Return a context manager; nullcontext if Animation Layers is absent."""
    als = _find_anim_layers_subscriptions()
    if als is None:
        return nullcontext()
    return anim_layers_paused()
