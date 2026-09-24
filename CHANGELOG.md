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
- Much faster animation rig creation and finger matching with a native solver on Windows (e.g. a 55-frame Machamp animation: finger matching went from about 1 minute to about 1 second)
- New Add > Image > From Clipboard in the 3D Viewport: paste a copied image (or a copied image path) as a reference image
- Model export has a "Convert Non-Smash Materials" option (on by default), and the Export Doctor has a matching default in its settings
- The Export Doctor now checks only the animations you are exporting, not every action in the file
- Fixes for applying IK animation, bulk IK and material conversion

## 4.7.0 - 2026-09-16
- Custom Components moved into the Animation Tools sidebar, with a new Match Animation button
- Custom Components gained face poses, a bake/remove workflow, appearance presets, and Make Custom Components (work in progress)
- Importing onto an Animation Rig now matches IK, finger sliders and custom components
- Keyframable Expression dropdown for mouth and eyelid poses, with a Strength control
- Match Finger Controls to Animation, a "Both" finger display mode, and faster finger and component matching
- The native IK accelerator is on by default and makes whole-animation IK matching much faster, with an off switch in Preferences
- IK viewport buttons sit on the widget face (they can be turned off), and connected chain tips extend correctly
- Hide Off-Mode Bones hides FK bones on limbs posed in IK, and IK controls on limbs posed in FK
- Raw anims store the animation rig and match isolated foot roll/toe handles
- Mirror Animation handles custom bones in rest space
- Raw animation export runs the Export Doctor checks first
- Preference to hide the "?" help buttons on Ultimate panels

## 4.6.0 - 2026-09-11
- IK Floor Contact places foot IK controls on the floor and locks their contact
- New FootRollIK, improved reverse foot IK, and a "Stretch Chain" option for stretch IK
- Custom IK: build IK on any bone chain and save or load it as a preset
- Ultimate Motion List integration: load blend frames and flags from the motion list onto an action, and place cancel markers
- Copy Materials From Armature copies materials from another armature onto meshes with the same names
- Panels reorganized, and every Ultimate panel has a "?" button that opens its documentation
- Faster IK matching, baking and import-with-IK, and faster visual bakes using parallel Blender workers
- Finger sliders fixed on Blender 4.x, and their bake is faster
- Bulk channel edits keep the interpolation of keyframes they don't touch
- Removed the "Bake and Exit" checkbox from the bake dialogs
- Fixed animation export

## 4.5.0 - 2026-09-08
- New Export Doctor: checks models and animations before export, fixes safe issues in one click, and can block invalid exports
- Stage Tools: import a Battlefield stage, scaled to your fighter's in-game size, as a size reference
- Optimize Textures previews and halves texture sizes for the active material
- Faster model export, and faster model and animation loading
- Animation Folders: keep several animation folders and switch between them
- Per-model export folders (in Preferences) match each imported model folder to its export destination
- Armature Collection Presets can be linked to a model folder so they apply automatically on import
- Toggle and Key IK Stretch
- Move panels and reset the panel order from Panel Presets
- IK fixes

## 4.4.0 - 2026-09-05
- Panel Presets: built-in All / Animate / Modeling layouts that control which Ultimate panels are shown and in what order
- Armature Collection Presets: save, apply, import and export bone collection setups, with a match report before applying
- Timeline FPS shortcut buttons, plus Play Animation Sequence and next/previous action buttons
- Import a whole animation folder or only selected animations, and purge unused visibility tracks
- Refresh Bone Drawing, and extra ParamLabels files that receive newly generated hashes
- Add or remove IK, Eye Look and Finger Sliders in one click, optionally baking them first
- IK/FK switches ease smoothly, and bakes key into the Animation Layers strip
- Raw Animations have their own panel and can import a single .rawanim file
- Retargeting Guided Mode walks through presets, animations, binding and baking step by step
- Relink Smash Model Folder and Reload Smash Model for Smash Viewport
- Smash Viewport fixes: no black ghost mesh, hair material animations follow the right animation, and Rendered shading no longer restarts sampling endlessly
- Trans exports round-trip correctly, animation saves retry when Windows locks the file, and raw anims import into Blender 5 action slots
