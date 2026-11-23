# Changelog

Patch notes shown by the plugin's updater. When you bump `bl_info['version']` in
`__init__.py`, add a section for that version at the top:

    ## 4.8.1 - 2026-10-01
    - One short, user-facing line per change

The updater shows every section newer than the user's installed version, and
the "What's New" popup shows them once after the update installs. Sections
that aren't headed by a version number (like "Unreleased") are never shown.

## Unreleased

### Revamp of IK, improvements to Retargetting

apologies for making so many small updates so frequently, this one should be the definitive one

- IK rebuilt as one IK constraint per arm or leg, matched 1:1 to FK: no correction bones, fade drivers or pole-rotation controls, so editing IK is predictable
- Each IK-driven bone now has exactly one constraint; Stretch, Stretch Chain, Arm Pull and Progressive Scale only add constraints while they are in use
- Nearly straight arms and legs are bent very slightly (only on the hidden IK bones) so they always fold toward their elbow or knee control
- Old IK rigs, including ones from 5.0.11, are detected and updated to the new setup with their animation kept
- Scaling HandIK, FootIK or the foot roll control scales the hand or foot again
- Animations that slide the elbow, knee, hand or foot (location keys) now put the IK controls on the visible hand/foot, and moving a control moves the limb by the same amount

- Create Scale Offset and the new Create Rotation Offset use persistent controls and a single Apply button inside Ultimate > Retargeting > Actions > Conversion, so the viewport can still be orbited
- Source offsets preserve animation keys and rest data; retarget helpers compensate alignment scale so the receiving rig does not grow
- Binding respects the aligned source object's rotation and transforms instead of temporarily stripping them
- Map by Proximity keeps Arms, Legs, Fingers, Core and other categorized mappings out of Custom Bones, reuses shared FK/IK assignments, and removes stale duplicate custom aliases when remapping
- Proximity matching accepts nearly coincident bone heads even when nearby helper bones and different bone lengths make midpoint scores ambiguous
- Binding reads saved custom mapping entries directly, and custom aliases cannot override categorized mappings
- Removing the final Custom Bone leaves the list empty instead of restoring old aliases; panel drawing is read-only and custom property defaults do not leak between armatures
- Add Active Bone changes to Add Selected Bones for multiple selected bones, adding all of them with suggested identifiers while keeping the single-bone naming dialog
- Added regression coverage for old IK upgrades, control scaling, sliding joints, offset binding/baking, proximity categories, custom-list deletion and multi-bone custom additions

## 5.0.11 - 2026-11-20
- Old IK rigs are detected when a file opens, with an Update button in the popup and in Misc.; a backup is kept and the rig is restored if the update does not match
- Updating a posed or stretched old rig now gives the same result as a rig created in T-pose
- Stretch Chain: new Follow Parent/Child slider places the elbow or knee between the shoulder/leg and the hand/foot
- ArmIK Pull now also pulls the tail of the shoulder
- Much faster IK matching on rigs made with older versions, using the native solver again
- IK/FK controls stay hidden or shown until the next switch key, with smoother playback on switch frames

## 5.0.10 - 2026-11-19
- Smash Viewport: optional Lightweight Lighting disables shadows and bloom without lowering resolution
- Smash Viewport: live textured previews while editing meshes and armatures, plus improved undo refresh and less repeated upload/readback work
- Isolated controls: keyable isolation ON/OFF switches and parent-follow behavior, including standalone component animation imports
- Faster native IK capture and bulk animation-key buffering, with compatible fallback paths

## 5.0.9 - 2026-11-19
- Faster Animation Rig creation: match IK, fingers and custom components together, with recovery if matching fails or is cancelled
- Smaller orange HandIK and FootIK boxes, sized slightly larger than their FK controls without shortening the IK bones
- Switch to IK buttons now appear on original hand and foot controls in FK mode
- Improved arm IK alignment, pole rotation controls and progressive deformation on long chains, including straightening beyond reach
- Visibility Autofill only adds valid _VIS_O_OBJShape meshes and skips duplicates

## 5.0.8 - 2026-11-18
- IK creation can hide original hands, feet and toes in Pose/Object modes while keeping shoulders, arms, legs and knees visible
- Switching to FK hides IK controls and reveals original endpoints; switching back restores IK visibility
- Knee IK controls sit directly in front of their own knees, and lifted feet bend the knees toward their pole controls
- Longer HandIK, FootIK and ToeIK controls, with improved knee-control rotation and legacy visibility repair

## 5.0.7 - 2026-11-18
- Smash Viewport: restore model visibility and animated deformation after hiding and unhiding a model hierarchy in the Outliner

## 5.0.6 - 2026-11-18
- Mirror Animation: include fingers by default and remember the Include Fingers setting for single and batch mirrors
- Idle Pose Library: mirrored imports now swap and flip finger poses too

## 5.0.5 - 2026-11-17
- Solid preview: prepare hidden expression textures upfront and reuse them at visibility keys to avoid playback stalls
- Smash Viewport: correctly reload the remaining model after deleting the primary armature hierarchy

## 5.0.4 - 2026-11-16
- New Smash Toolbar editor: pick "Smash Toolbar" in any area's editor menu and fill it with your favorite buttons (right-click a button > Add to Smash Toolbar)
- Toolbar buttons can show as text or icons, be reordered or removed, and be put in color-coded groups that open to the right
- Settings (toggles, checkboxes, sliders, dropdowns) can be added to the toolbar too
- Animation Importer and Idle Pose Library lists can go on the toolbar: scroll and click to import or apply, or open a bigger searchable list with the arrow
- Animation Importer: clicking an animation now selects the one under the mouse on the first click, even right after scrolling
- Smash Viewport: deleting an armature and its children now removes its model right away

## 5.0.3 - 2026-11-16
- New hand and foot IK controls point the same way as the hand/foot they control and are a bit longer, instead of pointing straight up

## 5.0.2 - 2026-11-16
- Smash Viewport: changing a bone's parent no longer twists the rendered model until you undo or move a bone

## 5.0.1 - 2026-11-16
- Smash Viewport: two copies of the same model both render, and each keeps its own bone edits no matter which one is selected
- Smash Viewport matches Blender in Edit Mode and after editing armature bones
- Smash Viewport updates right away when panning a zoomed camera view
- Exporting a model no longer leaves hidden facial expressions visible afterwards
- Facial picker thumbnails use the Smash Viewport render when it's active, without overlays or gizmos
- Visibility layers have their own folder browser, separate from the Animation Importer
- Model export file and setting options are back in the export file browser
- Mesh Data properties (vertex groups, shape keys) show while Smash Viewport is the render engine

## 5.0.0 - 2026-11-16
- Smash Viewport works on Blender's Vulkan backend: correct colors and soft edges, and it runs about as fast as OpenGL
- Smash Viewport plays animations much faster: far less work per frame for visibility, bones and moved meshes
- Smash Viewport: locked side/front views stay lined up with the bones and outlines while playing and zooming
- Smash Viewport: meshes you move or drag now deform with the armature, like in Blender
- Smash Viewport: meshes you delete in Blender disappear from the render instead of staying behind
- Smash Viewport: material animations only affect their own material (e.g. a hair color layer no longer changes the clothes)
- Faster Solid view playback: the material texture preview no longer rebuilds every material when visibility changes, and skips unchanged frames
- Visibility layers: load an animation's visibility and material tracks as a layer on top of the current animation (e.g. a transformation's hair color)
- Solid view shows Smash material textures, including eye and facial expressions
- Facial picker: better layout and sorting, stays on top while you work, and full expressions replace each other while face-part expressions combine
- GIF and photo capture has framerate options
- Eye look exports correctly when the animation is in NLA tweak mode
- Applying a collection preset keeps the imported model's own materials
- Mirror Selected Bones keeps only the mirrored bones selected
- Faster IK matching on rigs with helper bones, and faster swing.prc export
- New Profile Playback and Find Slow Animation Parts tools (F3 search) to see what slows playback down

## 4.9.10 - 2026-11-14
- Link a thrown character to an attacker from the Animation Importer, with an armature picker and support for Rot/Throw bone names.
- Automatically pair forward, back, up and down throw/thrown animations in both directions using the attacker's animation folder.

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
