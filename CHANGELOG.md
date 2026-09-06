# Changelog — Local Delta from CrusherD2 `animation-workflow`

This document describes only what the current local workspace adds, changes, fixes, or removes relative to CrusherD2's upstream `animation-workflow` branch. Features already present upstream are intentionally omitted.

## Comparison basis

- Upstream repository: `https://github.com/CrusherD2/smash-ultimate-blender`
- Upstream branch: `animation-workflow`
- Fetched upstream revision: `498a7948e0d89b897bfa0d2a8af7bde4d3b3bd56`
- Local branch: `animation-workflow`
- Local committed revision: `7c4aedb597dabecae03e31f93c43e8584006433b`
- Comparison recorded: 2026-09-05

The comparison target is the complete local workspace snapshot: local commit `7c4aedb` plus all current uncommitted and untracked feature work. Those two layers are treated as one local state rather than separate releases. The source comparison is `git diff upstream/animation-workflow`, supplemented by locally untracked files such as `source/extras/collection_presets.py`.

## Added

### Armature Collection Presets

- Integrated and substantially expanded j00bert's standalone Armature Collection Preset Sorter as a native **Armature Collection Presets** panel in the Ultimate sidebar.
- Added versioned, human-readable v2 JSON presets with atomic file replacement.
- Added backward-compatible loading for the original v1 `collection_presets/*.json` format, including the supplied `shy_guy.json` and `shy_guy(old).json` examples.
- Legacy whole-scene presets are narrowed to their recorded armature and meshes when fingerprint data is available, preventing unrelated scene objects from being reorganized.
- Added three library locations:
  - **Blend File** stores presets in `collection_presets` next to the saved `.blend`.
  - **Global** stores presets in Blender's user configuration.
  - **Custom** uses the directory configured in the add-on preferences.
- Unsaved blend files and unconfigured custom libraries safely fall back to the global library.
- Libraries refresh automatically after add-on startup, blend-file loading, and library changes.
- Added a searchable preset list with refresh, automatic best-match selection, save, update, duplicate, rename, delete, multi-file import, and export operations.
- Added independently selectable save/apply sections for:
  - Scene collection hierarchy, color tags, viewport visibility, render visibility, exclusion, holdout, and indirect-only state.
  - Object placement, including multiple simultaneous collection memberships.
  - Mesh material-slot assignments.
  - Nested bone collections, visibility, and bone membership.
  - Data-bone and pose-bone colors, custom shapes, custom-shape transforms, scale, translation, rotation, wire width, and bone-size behavior.
  - Armature display type, names, axes, bone colors, and in-front drawing.
- Object scope is limited to the selected armature, armature-modified meshes, direct children, and optionally recursive descendants and custom-shape objects.
- Applying a hierarchy reparents collections within the current scene while preserving links owned exclusively by other scenes. It never deletes objects or collections.
- Added exact and normalized name matching. Normalized matching is case-insensitive and understands Blender suffixes such as `.001`.
- Added optional fuzzy matching with a configurable threshold of 85% by default. Fuzzy mappings are displayed before application and require explicit acceptance.
- Added non-destructive preview and post-apply reports for exact, normalized, fuzzy, missing, and unmatched objects, bones, and bone collections.
- Unmatched objects stay in place by default. Moving them to a configurable red Unmatched collection is opt-in.
- Preset application supports Blender Undo. Update, delete, and low-confidence apply paths require confirmation.
- Fixed the original standalone sorter's omission of nested bone collections by using Blender's complete bone-collection hierarchy instead of root collections alone.
- The panel participates in the persistent Ultimate-sidebar panel ordering system.

### Batch animation import

- Added multi-file selection to the standard Blender animation file browser.
- Added Ctrl-click toggling and Shift-click range selection to the animation-folder list.
- Combined single and multiple selected imports under **Import Selected Animations**.
- Added Select All, Deselect All, selected counts, and consistent five-row checkbox lists.
- Batch imports are deduplicated and processed in stable case-insensitive filename order.
- Successful files remain imported if another selected file fails, with failures reported individually.
- Batch operations preserve Blender's object mode and auto-key setting and leave the last successful animation active.
- Duplicate action names use Blender's standard `.001`, `.002`, and later suffixes.
- `.rawanim` files are excluded from the main Animation Importer and remain in the dedicated **Raw Animations** panel.

### Animation navigation and sequence playback

- Added Ctrl+Down Arrow and Ctrl+Up Arrow shortcuts to select and play the next or previous compatible armature action.
- Shortcut navigation wraps in both directions.
- Action filtering excludes SAP data, `_old` actions, and actions incompatible with the selected armature.
- Action changes update the scene frame range, start at the animation's first frame, and reset unanimated bones to rest while leaving `_RET` bones alone.
- Added **Start Sequence** next to **Start Animation Scroll** in the Action Editor and Dope Sheet header.
- Sequence playback starts at the active action, plays every compatible action once, wraps the ordered list around the starting action, adjusts each frame range, and stops after the final clip.
- Added explicit sequence stopping, Escape cancellation, playback-stop detection, and handler/timer cleanup.

### Visibility-track cleanup and normalization

- Added **Purge Current** and **Purge All Anims** to Armature Data → **Ultimate Visibility Track Entries** and its specials menu.
- Purging removes tracks whose names have no corresponding model mesh, even when those orphaned tracks contain valid keyframes.
- Current-animation cleanup removes orphaned curves from the active SAP action while retaining shared entries still referenced by other animations.
- All-animation cleanup processes every SAP action associated with the armature.
- Cleanup rebuilds the shared visibility-entry list and remaps every affected F-Curve index so deleting or sorting entries cannot retarget another animation accidentally.
- Existing Remove, Shift, Organize Alphabetically, and Organize by Move operations now remap visibility indices across all associated SAP actions.
- Easy Facial Animation references are updated when visibility entries are renamed, merged, or removed.
- Visibility names are matched case-insensitively across `.nuanmb` import/export, `.rawanim` import/export, drivers, Autofill, and Easy Facial Animation.
- Case-only duplicate tracks are merged with per-frame logical OR so visibility is retained when either duplicate is enabled.
- Matching model mesh names provide authoritative capitalization.
- Purge operations refresh drivers, support Undo, and require confirmation for all-animation cleanup.

### Configurable add-on preferences

- Added a dedicated add-on preferences class.
- Added independent imported-action extension controls:
  - `.nuanmb` is hidden by default.
  - `.rawanim` is shown by default.
- Extension settings apply to imported armature and camera actions.
- Added four configurable Timeline FPS presets, defaulting to 5, 15, 30, and 60 FPS.
- Added a preference to show or hide Timeline FPS controls; duplicate configured values are collapsed while retaining order.
- Added a configurable custom directory for Armature Collection Presets.
- Added a persistent **Ultimate Sidebar Panel Order** list with move-up, move-down, and reset controls.
- Panel ordering uses stable identifiers, restores after all panels register, appends new panels, and removes stale entries.
- Added support for any number of additional ParamLabels CSV destinations.

### ParamLabels workflow

- Added **Append New Hashes** to Misc utilities.
- Collects lowercase armature bone names, corresponding `bonecol` collision labels, child mesh names, and base names derived from `_VIS_O_OBJShape` meshes.
- Hashes and appends labels in batches rather than rewriting files per label.
- Deduplicates existing CSV rows while preserving order and prevents duplicate hashes at each destination.
- Processes files on a worker thread while keeping Blender API access on the main thread.
- Reports source-label counts, additions, skips, destination counts, and errors.
- Swing label insertion can forward the configured additional ParamLabels destinations.

### Timeline and model workflow tools

- Added configurable FPS buttons to the Timeline header.
- Added a manual **Refresh Bone Drawing** action to Armature Data → Viewport Display, with a fallback panel for Blender layouts where injection is unavailable.
- Refresh Bone Drawing toggles and restores edit-bone Connected state to recover invisible imported bones without retaining rig edits.
- Refresh Bone Drawing never triggers automatically.

### Retargeting preset

- Added `SmashBrawl.py`, an Expy Kit mapping for Smash Brawl-style skeleton names, fingers, Throw, and an extended set of custom tail, hair, ear, skirt, and wing bones.

## Changed

- Bumped the add-on version from 4.2.2 to 4.3.0.
- Added j00bert to the add-on author metadata.
- Renamed the animation file-browser action to **Import Animation(s)** and the folder action to **Import Anim Folder**.
- Changed imported action naming from unconditional `.nuanmb` stripping to per-format preferences.
- Raw animation import now always creates a distinct action instead of deleting or clearing an existing same-named action.
- Standardized the Animation Importer and Animation Exporter around matching checkbox-list behavior, selection hints, selection controls, selected counts, and emphasized batch actions.
- Centralized compatible-action assignment, frame-range updates, rest-pose handling, and playback startup for scrolling, shortcuts, and sequence playback.
- Corrected **Gif or Photo** to **GIF or Photo** in labels.
- Feature modules now remove their panels, handlers, timers, and keymaps before the legacy central class list unregisters.
- Registration and unregistration tolerate both `ValueError` and `RuntimeError` for stale Blender class state.
- Expanded README documentation for the local animation workflow, collection presets, visibility cleanup, configurable shortcuts, ParamLabels, and related tools.

## Fixed

### Blender file-browser stability

- Worked around Blender 4.4's `file_execute_get_description` null-description crash by adding non-empty descriptions to every locally affected file-selector operator.
- Coverage includes animation import/folder/raw import/export, model import/export and reference files, material re-import, swing import/export, Stage Tools, Smash Viewport relinking/lighting, idle-pose storage, ParamLabels destinations, Expy Kit FBX action renaming, and collection-preset import/export.
- Fixed the all-animation visibility purge confirmation dialog using unsupported `TRASH` as an `invoke_confirm` icon; it now uses Blender 4.4's supported `WARNING` enum. Regular UI buttons may still use the valid `TRASH` button icon.

### Animation import and export

- Fixed folder selection and folder refresh initializing animation lists differently.
- Fixed folder-loaded entries lacking initialized multi-selection state.
- Fixed uppercase or mixed-case `.nuanmb` extensions being rejected.
- Fixed the standard file-browser importer accepting only one selected animation.
- Fixed raw imports replacing same-named `.nuanmb` actions when both extension-display settings are disabled.
- Fixed visibility case duplicates and index changes corrupting behavior across SAP actions.

### Blender 5 compatibility and display

- Added fallback imports for Blender 5's private `_rna_xml` module in both Expy Kit preset execution paths.
- Fixed washed-out GPU textures in Blender 5 draw handlers for Smash Viewport and Easy Facial Animation while retaining the Blender 4 call path.
- Preserves and restores Blender 5's image `media_type` during viewport and face-thumbnail capture.
- Fixed Smash `CustomVector47` specular conversion using the obsolete Principled input name. Blender 4/5 now writes **Specular IOR Level** with the expected normalized value.

### Registration cleanup

- Removed duplicate central registration of the animation-scroll modal operator.
- Added explicit cleanup for sequence handlers/timers and Ctrl+Arrow keymaps.
- Corrected registration order so add-on preferences are available to ParamLabels and Timeline tools.

## Removed

- Removed `expy_kit/rig_mapping/presets/Smash.py` intentionally. It duplicated the Ultimate mapping; `SmashUltimate.py` remains the Ultimate-specific preset.

## Verification

- Python compilation passes for `__init__.py` and `source`.
- `git diff --check` passes; Git only reports expected LF-to-CRLF working-copy notices.
- Visibility purge/remapping was exercised with synthetic SAP actions in Blender 4.4.3 and Blender 5.1.2.
- Armature Collection Presets were exercised in Blender 4.4.3 and Blender 5.1.2 with nested scene collections, multiple object memberships, nested bone collections, materials, `.001` normalization, hierarchy restoration, and legacy preset loading.
- Full add-on registration/unregistration, collection-preset file-selector descriptions, load handlers, and timer cleanup pass in Blender 4.4.3 and Blender 5.1.2.
