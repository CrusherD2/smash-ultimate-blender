"""Startup update popup, "Skip This Version", and post-update "What's New".

State that must survive add-on updates (the add-on folder is replaced on
install) lives in a small JSON file in Blender's user config folder rather
than in add-on preferences, which only persist when preferences are saved.
"""
import json
import os

import bpy
from bpy.types import Operator

from . import version_check
from .changelog import format_version, parse_version, sections_between

_STATE_FILE = "updater_state.json"
_prompted_this_session = False


# --- Persistent state -------------------------------------------------------

def _state_path():
    folder = bpy.utils.user_resource('CONFIG', path="smash_ultimate_blender", create=True)
    return os.path.join(folder, _STATE_FILE)


def load_state():
    try:
        with open(_state_path(), encoding="utf-8") as f:
            state = json.load(f)
        return state if isinstance(state, dict) else {}
    except (OSError, ValueError):
        return {}


def save_state(state):
    try:
        with open(_state_path(), "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)
    except OSError as e:
        print(f"Smash_ultimate_blender: Could not save updater state: {e}")


def skipped_version():
    return parse_version(load_state().get("skipped_version", ""))


def set_skipped_version(version):
    state = load_state()
    if version:
        state["skipped_version"] = format_version(version)
    else:
        state.pop("skipped_version", None)
    save_state(state)


def popup_enabled(context=None):
    from ..addon_preferences import get_addon_preferences
    prefs = get_addon_preferences(context)
    return True if prefs is None else prefs.show_update_popup


# --- Decisions --------------------------------------------------------------

def should_prompt_for_update():
    """Whether the startup popup should offer the update found by the last check."""
    if _prompted_this_session:
        return False
    if not version_check.UPDATE_AVAILABLE or version_check.LOCAL_VERSION_AHEAD:
        return False
    if not version_check.UPDATE_BLENDER_COMPATIBLE:
        return False
    if not popup_enabled():
        return False
    remote = version_check.REMOTE_ADDON_VERSION
    return remote is None or skipped_version() != remote


def whats_new_sections():
    """Local CHANGELOG sections the user has not seen since their last version.

    Records the installed version as seen, so this returns notes only once.
    The very first run records the version without showing anything.
    """
    installed = version_check.get_local_addon_version()
    if installed is None:
        return []
    state = load_state()
    last_seen = parse_version(state.get("last_seen_version", ""))
    if last_seen != installed:
        state["last_seen_version"] = format_version(installed)
        save_state(state)
    if last_seen is None or last_seen >= installed:
        return []
    return sections_between(version_check.get_local_changelog_sections(), last_seen, installed)


# --- Showing popups from timers --------------------------------------------

def _invoke_in_window(operator):
    """Invoke an operator's popup in the first window; False if none exists yet."""
    wm = bpy.context.window_manager
    if wm is None or not wm.windows:
        return False
    window = wm.windows[0]
    with bpy.context.temp_override(window=window, screen=window.screen):
        operator('INVOKE_DEFAULT')
    return True


def _on_check_finished():
    global _prompted_this_session
    if not bpy.app.background and should_prompt_for_update():
        _prompted_this_session = True
        _invoke_in_window(bpy.ops.sub.update_prompt)


_startup_attempts = 0


def _startup_timer():
    global _startup_attempts
    # Windows do not exist while Blender is still starting; retry briefly.
    if bpy.context.window_manager is None or not bpy.context.window_manager.windows:
        _startup_attempts += 1
        return 1.0 if _startup_attempts < 30 else None
    sections = whats_new_sections()
    if sections:
        SUB_OP_whats_new.startup_sections = sections
        _invoke_in_window(bpy.ops.sub.update_whats_new)
    version_check.start_background_check(on_done=_on_check_finished)
    return None


def schedule_startup():
    """Show What's New if the version changed, then check for updates in the background."""
    if bpy.app.background:
        return
    if not bpy.app.timers.is_registered(_startup_timer):
        bpy.app.timers.register(_startup_timer, first_interval=1.0, persistent=True)


def cancel_startup():
    if bpy.app.timers.is_registered(_startup_timer):
        bpy.app.timers.unregister(_startup_timer)


# --- Operators --------------------------------------------------------------

class SUB_OP_update_prompt(Operator):
    """Offer the available plugin update with its patch notes"""
    bl_idname = "sub.update_prompt"
    bl_label = "Plugin Update Available"
    bl_description = "Show the available plugin update and its patch notes"

    def execute(self, context):
        return {'FINISHED'}

    def invoke(self, context, event):
        # A dialog, not invoke_popup: popups vanish as soon as the mouse moves
        # away, which is easy to do by accident when one opens at startup.
        local = format_version(version_check.LOCAL_ADDON_VERSION)
        remote = format_version(version_check.REMOTE_ADDON_VERSION)
        return context.window_manager.invoke_props_dialog(
            self, width=520, title=f"Smash Ultimate Blender Tools update: v{local}  →  v{remote}")

    def draw(self, context):
        from .ui import draw_notes
        from ..addon_preferences import get_addon_preferences
        layout = self.layout
        draw_notes(layout, version_check.pending_update_notes(), max_lines=18)

        skipped = skipped_version() == version_check.REMOTE_ADDON_VERSION
        row = layout.row()
        row.scale_y = 1.3
        # template_popup_confirm buttons close the dialog (and replace its OK/Cancel).
        row.template_popup_confirm(
            "sub.update_now", text="Update Now", icon='IMPORT',
            cancel_text="Close" if skipped else "Remind Me Later")
        # Blender always pairs a confirm button with a cancel one, so Skip cannot
        # also close the dialog; it confirms in place instead.
        if skipped:
            row.label(text="Skipped", icon='CHECKMARK')
        else:
            row.operator("sub.update_skip_version", text="Skip This Version", icon='CANCEL')

        prefs = get_addon_preferences(context)
        if prefs is not None:
            layout.prop(prefs, "show_update_popup", text="Show this popup when an update is available")


class SUB_OP_update_now(Operator):
    """Download and install the update from the popup"""
    bl_idname = "sub.update_now"
    bl_label = "Update Now"
    bl_description = "Download and install the latest version of the plugin, then restart Blender"

    def execute(self, context):
        # INVOKE so the installer can ask to save unsaved changes first.
        return bpy.ops.sub.download_update('INVOKE_DEFAULT')


class SUB_OP_update_skip_version(Operator):
    """Stop the popup for this version; it returns when a newer one is published"""
    bl_idname = "sub.update_skip_version"
    bl_label = "Skip This Version"
    bl_description = ("Don't show the update popup for this version again. The update stays "
                      "available in the sidebar, and newer versions will prompt again")

    def execute(self, context):
        version = version_check.REMOTE_ADDON_VERSION
        if version is None:
            return {'CANCELLED'}
        set_skipped_version(version)
        self.report({'INFO'}, f"Skipped v{format_version(version)}")
        version_check.redraw_all_areas()
        return {'FINISHED'}


class SUB_OP_update_clear_skipped(Operator):
    """Prompt again for the version that was skipped"""
    bl_idname = "sub.update_clear_skipped"
    bl_label = "Clear Skipped Version"
    bl_description = "Show the update popup again for the skipped version"

    def execute(self, context):
        set_skipped_version(None)
        return {'FINISHED'}


class SUB_OP_whats_new(Operator):
    """Show the patch notes for the installed version"""
    bl_idname = "sub.update_whats_new"
    bl_label = "What's New"
    bl_description = "Show the patch notes for the installed version of the plugin"

    # Set by the startup check after an update: every version since the last one seen.
    startup_sections = []
    _shown = []

    def execute(self, context):
        return {'FINISHED'}

    def invoke(self, context, event):
        cls = SUB_OP_whats_new
        if cls.startup_sections:
            cls._shown, cls.startup_sections = cls.startup_sections, []
        else:
            installed = version_check.get_local_addon_version()
            cls._shown = [
                section for section in version_check.get_local_changelog_sections()
                if section.version == installed
            ]
        installed = format_version(version_check.get_local_addon_version())
        return context.window_manager.invoke_props_dialog(
            self, width=520, title=f"What's new in Smash Ultimate Blender Tools v{installed}")

    def draw(self, context):
        from .ui import draw_notes
        layout = self.layout
        notes = [
            (f"v{format_version(section.version)}" + (f"  ({section.date})" if section.date else ""),
             section.notes or ["No notes for this version."])
            for section in SUB_OP_whats_new._shown
        ]
        draw_notes(layout, notes, max_lines=24)
        row = layout.row()
        row.operator("wm.url_open", text="Full Changelog Online", icon='URL').url = version_check.CHANGELOG_URL
        row.template_popup_confirm("", cancel_text="Close")


CLASSES = (
    SUB_OP_update_prompt,
    SUB_OP_update_now,
    SUB_OP_update_skip_version,
    SUB_OP_update_clear_skipped,
    SUB_OP_whats_new,
)
