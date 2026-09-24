import textwrap

from bpy.types import Panel

# Characters per label line; Blender labels do not wrap on their own.
NOTE_WRAP_WIDTH = 72


def draw_notes(layout, notes, max_lines=None, wrap_width=NOTE_WRAP_WIDTH):
    """Draw [(heading, [note, ...]), ...] as bulleted, word-wrapped labels.

    Stops after `max_lines` label lines and says how many notes were left out.
    """
    if not notes:
        layout.label(text="No patch notes were published for this update.")
        return

    box = layout.box()
    col = box.column(align=True)
    used = 0
    hidden = 0
    for heading, lines in notes:
        if max_lines is not None and used >= max_lines:
            hidden += len(lines)
            continue
        col.label(text=heading, icon='DOT')
        used += 1
        for note in lines:
            wrapped = textwrap.wrap(note, wrap_width - 4) or [""]
            if max_lines is not None and used + len(wrapped) > max_lines:
                hidden += 1
                continue
            col.label(text="  • " + wrapped[0])
            for continuation in wrapped[1:]:
                col.label(text="     " + continuation)
            used += len(wrapped)
        col.separator()
    if hidden:
        col.label(text=f"...and {hidden} more. See the full changelog.", icon='THREE_DOTS')


class SUB_PT_update_plugin(Panel):
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'Ultimate'
    bl_label = 'Update Available!'

    @classmethod
    def poll(cls, context):
        # LOCAL_VERSION_AHEAD is a cached flag from the last check, so this stays
        # cheap enough for a poll and keeps the panel hidden on newer local builds.
        from .version_check import UPDATE_AVAILABLE, LOCAL_VERSION_AHEAD
        return bool(UPDATE_AVAILABLE) and not LOCAL_VERSION_AHEAD

    def draw(self, context):
        from . import version_check as vc
        from .changelog import format_version
        from ..blender_compat import draw_progress

        layout = self.layout
        layout.use_property_decorate = False
        layout.use_property_split = False

        col = layout.column(align=True)
        col.label(text=f"Installed: v{format_version(vc.LOCAL_ADDON_VERSION)}")
        col.label(text=f"Available: v{format_version(vc.REMOTE_ADDON_VERSION)}", icon='IMPORT')
        if vc.LATEST_COMMIT_DATE:
            col.label(text=f"Published: {vc.LATEST_COMMIT_DATE[:10]}")

        if not vc.UPDATE_BLENDER_COMPATIBLE:
            box = layout.box()
            box.alert = True
            box.label(text=f"Requires Blender {format_version(vc.REMOTE_BLENDER_REQUIREMENT)}+", icon='ERROR')
            box.label(text="Update Blender to install this version.")

        layout.label(text="What's New:")
        draw_notes(layout, vc.pending_update_notes(), max_lines=6, wrap_width=40)
        layout.operator("sub.view_update_changelog", text="View Full Changelog", icon='TEXT')

        layout.separator()
        if vc.UPDATE_STATUS == "idle":
            row = layout.row()
            row.scale_y = 1.4
            row.enabled = vc.UPDATE_BLENDER_COMPATIBLE
            row.operator("sub.download_update", text="Download & Install Update", icon='IMPORT')
        elif vc.UPDATE_STATUS == "checking":
            layout.label(text="Checking for updates...", icon='INFO')
        elif vc.UPDATE_STATUS == "downloading":
            layout.label(text="Downloading update...", icon='IMPORT')
            draw_progress(layout, vc.UPDATE_DOWNLOAD_PROGRESS, text=f"Progress: {vc.UPDATE_DOWNLOAD_PROGRESS:.1%}")
        elif vc.UPDATE_STATUS == "installing":
            layout.label(text="Installing update...", icon='FILE_REFRESH')
            layout.label(text="Please wait, Blender will restart automatically!")
            layout.label(text="Do not close Blender manually!", icon='ERROR')

    def draw_header_preset(self, context):
        from ..ui_help import draw_panel_help
        draw_panel_help(self.layout, self)


class SUB_PT_updater_settings(Panel):
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'Ultimate'
    bl_label = 'Plugin Updater'
    bl_parent_id = "SUB_PT_update_plugin"
    bl_options = {'DEFAULT_CLOSED'}

    @classmethod
    def poll(cls, context):
        # LOCAL_VERSION_AHEAD is a cached flag from the last check, so this stays
        # cheap enough for a poll and keeps the panel hidden on newer local builds.
        from .version_check import UPDATE_AVAILABLE, LOCAL_VERSION_AHEAD
        return bool(UPDATE_AVAILABLE) and not LOCAL_VERSION_AHEAD

    def draw(self, context):
        from . import version_check as vc
        from ..addon_preferences import get_addon_preferences

        layout = self.layout
        layout.use_property_decorate = False
        layout.use_property_split = False

        prefs = get_addon_preferences(context)
        if prefs is not None:
            layout.prop(prefs, "show_update_popup")
        layout.operator("sub.check_for_updates", text="Check for Updates", icon='FILE_REFRESH')
        if vc.UPDATE_STATUS not in {"downloading", "installing"}:
            row = layout.row()
            row.enabled = vc.UPDATE_BLENDER_COMPATIBLE
            row.operator("sub.download_update", text="Force Download & Install", icon='IMPORT')

        layout.separator()
        col = layout.column(align=True)
        col.label(text=f"Repository: {vc.REPO}")
        col.label(text=f"Branch: {vc.BRANCH}")
        col.label(text=f"Installed commit: {(vc.CURRENT_COMMIT_SHA or 'unknown')[:8]}")
        col.label(text=f"Latest commit: {(vc.LATEST_COMMIT_SHA or 'unknown')[:8]}")

    def draw_header_preset(self, context):
        from ..ui_help import draw_panel_help
        draw_panel_help(self.layout, self)
