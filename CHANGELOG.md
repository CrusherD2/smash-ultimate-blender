# Changelog

Patch notes shown by the plugin's updater. When you bump `bl_info['version']` in
`__init__.py`, add a section for that version at the top:

    ## 4.7.2 - 2026-09-30
    - One short, user-facing line per change

The updater shows every section newer than the user's installed version, and
the "What's New" popup shows them once after the update installs. Sections
that aren't headed by a version number (like "Unreleased") are never shown.

## Unreleased
- Update popup with patch notes, "Remind Me Later" and "Skip This Version" (can be turned off in Preferences)
- Updates that need a newer Blender are shown but can't be installed until Blender is updated
- "What's New" popup after the plugin updates
- The update check no longer slows down Blender startup
- Fixed animation mirroring, including IK bones

## 4.7.1 - 2026-09-22
- Much faster animation rig creation and finger matching (native solver on Windows)
- Bug fixes

## 4.7.0 - 2026-09-16
- Custom Components moved into the Animation Tools sidebar, with a new Match Animation button
- Importing onto an Animation Rig now matches IK, finger sliders and custom components
- Keyframable Expression dropdown for mouth and eyelid poses
- Faster finger and component matching, plus a "Both" finger display mode
- Native IK accelerator is on by default, with an off switch in Preferences
- IK viewport buttons sit on the widget face, and connected chain tips extend correctly
- Raw anims store the animation rig and match isolated foot roll/toe handles
