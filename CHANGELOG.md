# Changelog

Patch notes shown by the plugin's updater. When you bump `bl_info['version']` in
`__init__.py`, add a section for that version at the top:

    ## 4.8.1 - 2026-10-01
    - One short, user-facing line per change

The updater shows every section newer than the user's installed version, and
the "What's New" popup shows them once after the update installs. Sections
that aren't headed by a version number (like "Unreleased") are never shown.

## 4.8.0 - 2026-09-23
- Drag and drop Smash files onto the 3D Viewport or Outliner to import them: model files, animations (.nuanmb/.rawanim), swing.prc, stage lighting and .shpcanim. A single drop can mix types, and animations and swing.prc go onto the model that was just imported. Also under File > Import > Smash Ultimate
- Mirror Animation: IK controls now move to the other side with the body, and keyed IK pole angles are swapped and flipped
- Mirror Animation: custom bones (including ones with unusual rest orientations) mirror correctly and follow their parents' mirrored pose, so meshes line up even on rigs with slightly uneven left/right bones
- Mirror Animation: swing bones now move to the other side with the body instead of staying put
- Mirror Animation: the whole face rig is left alone (including Teeth and names like Downlip), and unrelated bones that just contain face-like letters (e.g. "flip") are no longer skipped
- Mirror Animation: expression sliders and eye pads mirror correctly
- New update popup with patch notes and Update Now / Remind Me Later / Skip This Version. You can turn it off in Preferences > Add-ons > Plugin Updates
- Updates that need a newer Blender are shown in the sidebar but can't be installed until you update Blender
- A "What's New" popup appears once after the plugin updates, and you can reopen it from Preferences
- The update check runs in the background, so it no longer slows down Blender startup
- Update Now offers to save unsaved changes before Blender restarts

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
