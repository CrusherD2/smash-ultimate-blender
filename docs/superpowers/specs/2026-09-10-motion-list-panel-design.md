# Motion list panel redesign

## Problem

The motion-list feature lives in a sub-panel of the Animation Exporter and is
duplicated inside both export file browsers. It exposes fourteen flags, a
cancel-frame mode enum, a motion key, a new-entry template, and a path to an
external `yamlist` executable. The controls that matter for ordinary animation
work are buried among ones that almost never change, and the cancel frame --
which is a position in time -- is typed as a number instead of being placed on
the timeline.

Three defects follow from the current structure:

- All settings are scene-level, so batch export writes one set of blend frames
  and flags to every entry it touches.
- `yamlist` must be located by the user, yet the bundled Python codec is
  strictly more capable: `load()` refuses `yamlist` outright when an entry has
  reserved flag bits set.
- Motion keys and animation names are shown as raw `0x...` hashes.

## Goals

Move the feature into **Ultimate Animation Data**, reduce it to the controls
that are edited per animation, move the cancel frame onto the timeline, store
per-animation values on the action, resolve hashes to readable names, update
every motion-list format present, and remove the `yamlist` dependency.

## Non-goals

Creating motion entries from scratch, disambiguating animations shared by
several motions, editing the eleven undocumented flags, and editing game /
effect / sound scripts. Existing values for all of these are preserved on
write; they are simply no longer editable from the panel.

## Design

### 1. Panel relocation

`SUB_PT_motion_list` is re-declared in `source/anim/motion_list_ui.py` as:

- `bl_label = 'Ultimate Motion List'`
- `bl_space_type = 'PROPERTIES'`, `bl_region_type = 'WINDOW'`, `bl_context = 'data'`
- `bl_parent_id = SUB_PT_sub_smush_anim_data_main.bl_idname`
- `poll` returns true only for armature objects, matching its sibling panels

It becomes a sibling of `SUB_PT_sub_smush_anim_data_vis_tracks` and
`SUB_PT_sub_smush_anim_data_mat_tracks` in `source/anim/anim_data.py`.

`source/ui_help.py` is **not** touched. `unregister_retired_panels()`
unregisters every panel whose `bl_idname` appears in `RETIRED_PANEL_IDS`, and
the relocated panel keeps the identifier `SUB_PT_motion_list`; listing it there
would unregister the new panel at startup. Re-parenting an existing identifier
needs no retirement entry, because the addon unregisters and re-registers the
class on reload. `panel_doc_path()` already routes any `motion_list` module to
`docs/motion-list.md` and needs no change either.

`draw_settings()` and both of its call sites in the export file browsers
(`source/anim/export_anim.py`, in the `draw()` methods of the single and batch
export operators) are removed. The file dialogs show no motion-list controls.

Panel layout, in order:

1. `Update Motion List on Export` toggle.
2. Resolved-path line: an `INFO` label naming each discovered file and marking
   which one is being read. When discovery fails, the editable `Motion List`
   field is shown instead, with the discovery error as the label. An
   `Override path` toggle reveals the field even when discovery succeeds.
3. Cancel frame readout plus `Set Cancel Marker` / `Clear Cancel Marker`.
4. `Blend Frames`.
5. `Turn`, `Loop`, `Move`.
6. `Sync From Motion List` operator and the last-read status line.

Items 3-5 are drawn only when the armature object has an active action
(`object.animation_data.action`), since they are stored on it. That is the same
action the single-animation exporter writes, so the panel always describes what
a single export would do. Items 3-5 are greyed when `Update Motion List on Export` is off, matching
the current panel's behavior. The sync operator stays enabled so values can be
reviewed without arming export.

### 2. Per-action storage

A new `SUB_PG_action_motion` property group:

| Property | Type | Range | Notes |
|---|---|---|---|
| `blend_frames` | Int | 0-255 | Frames used to blend into this motion |
| `flag_turn` | Bool | | Motion turn flag |
| `flag_loop` | Bool | | Motion loop flag |
| `flag_move` | Bool | | Motion movement flag |
| `synced` | Bool | | True once values are trustworthy |

Registered as `bpy.types.Action.sub_motion` in the `register()` of
`source/anim/motion_list_ui.py`, beside the `Scene.sub_motion_list` it already
owns. It cannot go in `source/blender_property_extensions.py`: that module
registers before `motion_list_ui`, so `SUB_PG_action_motion` has no `bl_rna`
yet and `PointerProperty` fails. Keeping the property with its owning module
removes the ordering dependency.

`SUB_PG_motion_list` on the scene is reduced to `enabled`, `filepath`,
`override_path`, and `status`. The removed properties are `converter`, `key`,
`template`, `cancel_mode`, `cancel`, `override_blend`, `blend`,
`override_flags`, and the fourteen `flag_*` properties.

**The `synced` contract.** `blend_frames` and the three flags are written on
export only when `synced` is true for that action. `synced` is set by the
`Sync From Motion List` operator and by an `update` callback on each of the
four editable properties. An action that has never been synced or edited
exports with its entry's existing blend frames and flags preserved -- the same
"no opinion means no change" rule the cancel marker follows. This prevents a
freshly added action, whose properties default to zero and false, from zeroing
a real entry.

Because values live on the action, batch export writes each exported action's
own blend frames and flags.

### 3. Cancel frame as a pose marker

A module constant `CANCEL_FRAME_MARKER = 'Cancel Frame'` names a pose marker in
`action.pose_markers`.

- `sub.set_cancel_frame_marker` creates the marker at `scene.frame_current`, or
  moves the existing one there. Only one such marker exists per action.
- `sub.clear_cancel_frame_marker` removes it. The operator is polled off when
  no marker exists.

On export, the cancel frame is the marker's `frame` value used **raw**, with no
adjustment for `scene.frame_start`. A value outside 0-255 raises a
`ValueError` that aborts the motion update before the animation is written; it
is never clamped. When the action has no such marker, `cancel=None` is passed
to `motion_list.update()` and the entry keeps its current cancel frame.

The panel renders `Cancel frame: <n> (marker)` or `No cancel marker - entry
value kept`, so the value that will be written is visible without exporting.

**Known consequence.** `import_anim` defaults its start frame to 1 and export
computes `final_frame_index` as `frame_end - frame_start`, so a raw marker
frame equals the game-side index only when `scene.frame_start` is 0. This was
chosen deliberately; the always-visible readout is the mitigation.

### 4. Path resolution and dual-format write

`discover(animation_path)` currently raises when a directory holds more than
one motion-list format. It is changed to return a list of every
`motion_list.bin`, `motion_list.yml`, and `motion_list.yaml` in the nearest
directory that contains any of them, walking up to and including `motion` as it
does today. It returns an empty list when none is found; the caller raises.

The list is ordered by modification time, newest first. The newest file is
decoded and edited; every file in the list is then written from that single
edited document. Per file, the existing guarantees hold unchanged: a first-write
`<name>.bak` preserving the original, a comparison against the bytes read at
load time, and an atomic `os.replace`.

The conflict check is collective. Every file's bytes are captured at load; if
any of them differs at commit time, the entire update aborts and no file is
written. Combined with the existing ordering in `save_ssbh_anim_data` -- where
`prepare()` runs before the animation is saved and `commit()` only after -- a
conflict leaves both the animation and every motion list untouched.

When `filepath` is set explicitly, that one file is read and written, and no
siblings are touched. The panel states this next to the field.

**Known consequence.** Newest-mtime selection depends on filesystem
timestamps, so a `.yml` touched by an unrelated tool can outrank a `.bin` the
user edited. The panel and the export report both name the file that was read.

### 5. Hash40 label resolution

New module `source/anim/hash_labels.py`, with no Blender dependency so it can be
tested alongside `motion_list.py`:

- `labels()` lazily parses `dependencies/pyprc/ParamLabels.csv` into an
  `{int: str}` map, cached at module level. Lines are `0x<hex>,<name>`; the
  file holds 89,856 entries and includes motion names such as `attack_air_f`.
  A missing or unreadable file yields an empty map rather than an error.
- `label(value)` returns the readable name for an int or passthrough for a
  string, falling back to `0x` hex form when unresolved.
- `harvest(doc)` adds the string keys and animation names of an already-decoded
  YAML document to the map, so a sibling `.yml` supplies names that
  `ParamLabels.csv` lacks.

Every hash the UI shows -- matched motion key, animation name, status line, and
error messages -- passes through `label()`.

On YAML write, `save()` converts hash integers -- `motion_path`, motion keys,
animation names, `game_script`, and `scripts` -- to their names before
`yaml.safe_dump`, falling back to a `'0x...'` string rather than a bare integer
so every value round-trips through `hash40()`. This is lossless because `encode_binary()` re-hashes strings
through `hash40()`. The save path asserts it: it compares
`encode_binary(labeled_doc)` against `encode_binary(doc)` and raises rather
than writing if they differ. Binary output is unaffected.

### 6. yamlist removal

Deleted from `source/anim/motion_list.py`: `_convert()`, the `converter`
parameter of `load()` and `save()`, the `disasm` branch in `load()` including
the reserved-flag refusal, and the `asm` branch in `save()` including its
`decode_binary` verification. Deleted from `source/anim/motion_list_ui.py`:
`default_converter()`, the `converter` property, and every `bpy.path.abspath`
call feeding it. `subprocess` and `shutil` imports are dropped where they
become unused.

The optional yamlist round-trip test in `tests/test_motion_list.py` is removed.

## Testing

Test-driven: each behavior below gets a failing test before its implementation.

`tests/test_motion_list.py` (pure Python, no `bpy`):

- `discover()` returns all formats in the nearest directory, newest first.
- `discover()` returns empty when no list exists up to `motion`.
- A dual-format directory writes both files from one edit, and re-decoding each
  yields the same document.
- A `.bak` is created once per file and not overwritten on a second save.
- A sibling modified after load aborts the whole commit, leaving every file
  byte-identical.
- `label()` resolves a known motion name, passes strings through, and falls
  back to `0x` form for an unknown hash.
- A labeled YAML write re-encodes to bytes identical to the unlabeled document.
- `update()` with `cancel=None` preserves the existing cancel frame, including
  zero.
- A cancel frame of 256 or -1 raises rather than clamping.

`tests/test_motion_list_blender.py` (in-Blender):

- The panel registers with the anim-data parent and the retired identifier is
  gone.
- `Action.sub_motion` survives a `.blend` save and reload.
- Set, move, and clear of the cancel marker; only one marker is ever present.
- Export with a marker writes the raw frame; export without one preserves the
  entry value.
- Export with `synced` false preserves entry blend frames and flags; with
  `synced` true it writes the action's values.
- Batch export of two actions with different values writes each entry
  correctly.

## Documentation

`docs/motion-list.md` is rewritten for the new location and controls: where the
panel lives, the marker workflow, the `synced` rule, dual-format detection and
the mtime caveat, the raw-frame caveat, and the removal of `yamlist`, motion
keys, templates, and the eleven undocumented flags. The `README.md` mention is
updated to match.
