# Motion List Panel Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move the motion-list controls out of the Animation Exporter into the Ultimate Animation Data panel, reduce them to per-animation values, drive the cancel frame from a timeline pose marker, resolve hash40 names to readable strings, write every motion-list format present, and delete the external `yamlist` dependency.

**Architecture:** `source/anim/motion_list.py` stays Blender-free and gains multi-file discovery plus label-aware YAML output. A new Blender-free `source/anim/hash_labels.py` resolves hash40 integers using the already-bundled `ParamLabels.csv`. `source/anim/motion_list_ui.py` is rewritten: its panel re-parents to `SUB_PT_sub_smush_anim_data_main`, per-animation values move onto `bpy.types.Action.sub_motion`, and the cancel frame comes from an `action.pose_markers` entry instead of a property.

**Tech Stack:** Python 3.11, Blender 4.4-5.2 `bpy`, vendored PyYAML at `dependencies/yaml`, `unittest`.

**Spec:** `docs/superpowers/specs/2026-09-10-motion-list-panel-design.md`

## Global Constraints

- **No git write commands.** The user has barred `git add`, `git commit`, and every other git command that writes. Each task ends with a verification checkpoint instead of a commit. Never run a git write command in this repo.
- Test-driven: write the failing test, watch it fail, implement, watch it pass.
- `source/anim/motion_list.py` and `source/anim/hash_labels.py` must not import `bpy` — the pure-Python test suite loads them without Blender.
- Cancel frames and blend frames are bytes: whole numbers 0-255. Out-of-range values raise `ValueError`; they are never clamped.
- The cancel frame is the pose marker's `frame` value used **raw**, with no `scene.frame_start` adjustment.
- Preserve the existing write guarantees per file: one-time `<name>.bak`, a conflict check against the bytes read at load, and atomic `os.replace`.
- Pure-Python tests run with: `python tests/test_motion_list.py`
- Blender tests run with: `python tests/run_blender_test.py --blender "C:/Program Files/Blender Foundation/Blender 4.5/blender.exe" tests/test_motion_list_blender.py`

---

### Task 1: Hash40 label resolution

**Files:**
- Create: `source/anim/hash_labels.py`
- Test: `tests/test_motion_list.py` (add `HashLabelTests`)

**Interfaces:**
- Consumes: nothing from earlier tasks. Reads `dependencies/pyprc/ParamLabels.csv`, whose lines are `0x<hex>,<name>`.
- Produces:
  - `labels() -> dict[int, str]` — cached hash-to-name map.
  - `label(value: int | str) -> str` — readable name, `'0x%x' % value` when unresolved, strings returned unchanged.
  - `harvest(doc: dict) -> None` — adds a decoded YAML document's string motion keys and animation names to the cache.

- [x] **Step 1: Write the failing test**

Add to `tests/test_motion_list.py`, and add `hash_labels = importlib.import_module('motion_test.source.anim.hash_labels')` next to the existing `motion = importlib.import_module(...)` line at the top of the file.

```python
class HashLabelTests(unittest.TestCase):
    def setUp(self):
        hash_labels._CACHE = None
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.addCleanup(setattr, hash_labels, '_CACHE', None)

    def test_resolves_known_motion_name(self):
        self.assertEqual('attack_air_f', hash_labels.label(motion.hash40('attack_air_f')))

    def test_passes_strings_through(self):
        self.assertEqual('attack_air_f', hash_labels.label('attack_air_f'))

    def test_unknown_hash_falls_back_to_hex(self):
        self.assertEqual('0xdeadbeef01', hash_labels.label(0xdeadbeef01))

    def test_harvest_adds_names_from_a_yaml_document(self):
        unknown = motion.hash40('sub_test_harvested_move')
        self.assertEqual(hex(unknown), hash_labels.label(unknown))
        hash_labels.harvest({'list': {'sub_test_harvested_move': {
            'animations': [{'name': 'c00subtestharvested.nuanmb'}]}}})
        self.assertEqual('sub_test_harvested_move', hash_labels.label(unknown))
        self.assertEqual('c00subtestharvested.nuanmb',
                         hash_labels.label(motion.hash40('c00subtestharvested.nuanmb')))

    def test_missing_csv_yields_an_empty_map_without_raising(self):
        hash_labels._CACHE = None
        original = hash_labels.csv_path
        hash_labels.csv_path = lambda: Path(self.folder.name) / 'absent.csv'
        try:
            self.assertEqual({}, hash_labels.labels())
            self.assertEqual('0x1', hash_labels.label(1))
        finally:
            hash_labels.csv_path = original
            hash_labels._CACHE = None
```

- [x] **Step 2: Run test to verify it fails**

Run: `python tests/test_motion_list.py HashLabelTests -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'motion_test.source.anim.hash_labels'`

- [x] **Step 3: Write minimal implementation**

Create `source/anim/hash_labels.py`:

```python
"""Resolve hash40 integers to readable names using the bundled ParamLabels.csv.

No Blender dependency, so it can be tested alongside motion_list.py.
"""
from pathlib import Path
import zlib

_CACHE = None


def csv_path():
    return Path(__file__).resolve().parents[2] / 'dependencies' / 'pyprc' / 'ParamLabels.csv'


def _hash40(text):
    data = text.encode('utf-8')
    return (len(data) << 32) | zlib.crc32(data)


def labels():
    """Hash-to-name map, parsed once. A missing file yields an empty map."""
    global _CACHE
    if _CACHE is None:
        _CACHE = {}
        try:
            text = csv_path().read_text(encoding='utf-8-sig')
        except OSError:
            return _CACHE
        for line in text.splitlines():
            key, separator, name = line.partition(',')
            if not separator or not key.startswith('0x'):
                continue
            try:
                _CACHE[int(key, 16)] = name.strip()
            except ValueError:
                continue
    return _CACHE


def label(value):
    """Readable name for a hash40 integer; strings pass through unchanged."""
    if isinstance(value, str):
        return value
    return labels().get(value, '0x%x' % value)


def harvest(doc):
    """Record names a YAML document spells out, which the CSV may not list."""
    known = labels()
    for key, motion in (doc.get('list') or {}).items():
        for name in (key, *(a.get('name') for a in motion.get('animations') or [])):
            if isinstance(name, str):
                known[_hash40(name)] = name
```

- [x] **Step 4: Run test to verify it passes**

Run: `python tests/test_motion_list.py HashLabelTests -v`
Expected: PASS, 5 tests.

- [x] **Step 5: Verification checkpoint**

Run the whole pure-Python suite and confirm nothing regressed:

```bash
python tests/test_motion_list.py -v
```

Expected: the pre-existing tests still pass. Do **not** run any git command. Report the test output.

---

### Task 2: Discover every motion-list format, newest first

**Files:**
- Modify: `source/anim/motion_list.py` (`discover`, around line 106)
- Test: `tests/test_motion_list.py` (replace `test_nearest_detection_stops_at_motion`)

**Interfaces:**
- Consumes: nothing.
- Produces: `discover(animation_path) -> list[Path]` — every `motion_list.bin` / `.yml` / `.yaml` in the nearest directory that holds any, ordered by modification time newest first, `[]` when none is found. **Breaking change:** it previously returned a single `Path` or `None` and raised on multiple formats. Task 3 and Task 7 are its only callers.

- [x] **Step 1: Write the failing test**

Replace `test_nearest_detection_stops_at_motion` in `tests/test_motion_list.py` with:

```python
    def test_discovery_returns_nearest_directory_newest_first(self):
        folder = self.root/'fighter/pacman/motion/body/c00'
        folder.mkdir(parents=True)
        far = folder.parents[1]/'motion_list.yml'
        far.touch()
        self.assertEqual([far], motion.discover(folder/'test.nuanmb'))
        binary = folder/'motion_list.bin'
        binary.touch()
        self.assertEqual([binary], motion.discover(folder/'test.nuanmb'))
        near_yaml = folder/'motion_list.yml'
        near_yaml.touch()
        os.utime(binary, (1_600_000_000, 1_600_000_000))
        os.utime(near_yaml, (1_700_000_000, 1_700_000_000))
        self.assertEqual([near_yaml, binary], motion.discover(folder/'test.nuanmb'))
        os.utime(binary, (1_800_000_000, 1_800_000_000))
        self.assertEqual([binary, near_yaml], motion.discover(folder/'test.nuanmb'))

    def test_discovery_stops_at_motion_and_returns_empty(self):
        folder = self.root/'fighter/pacman/motion/body/c00'
        folder.mkdir(parents=True)
        (self.root/'fighter/pacman/motion_list.bin').touch()
        self.assertEqual([], motion.discover(folder/'test.nuanmb'))
```

`os` is already imported at the top of `tests/test_motion_list.py`.

- [x] **Step 2: Run test to verify it fails**

Run: `python tests/test_motion_list.py MotionListTests.test_discovery_returns_nearest_directory_newest_first -v`
Expected: FAIL — the assertion compares a list against a bare `Path`.

- [x] **Step 3: Write minimal implementation**

Replace `discover` in `source/anim/motion_list.py`:

```python
def discover(animation_path):
    """Every list in the nearest directory up to /motion, newest first."""
    folder = Path(animation_path).resolve().parent
    for directory in (folder, *folder.parents):
        found = [directory / ('motion_list' + suffix) for suffix in ('.bin', '.yml', '.yaml')]
        found = [path for path in found if path.is_file()]
        if found:
            return sorted(found, key=lambda path: path.stat().st_mtime, reverse=True)
        if directory.name.lower() == 'motion':
            break
    return []
```

- [x] **Step 4: Run test to verify it passes**

Run: `python tests/test_motion_list.py MotionListTests -v`
Expected: both discovery tests PASS. Other tests in the class still pass.

- [x] **Step 5: Verification checkpoint**

Run: `python tests/test_motion_list.py -v`
Expected: all pure-Python tests pass except `test_yamlist_compatibility`, which may skip. No git commands. Report the output.

---

### Task 3: Drop yamlist, write every discovered file

**Files:**
- Modify: `source/anim/motion_list.py` (`load`, `save`, `_convert`, imports)
- Test: `tests/test_motion_list.py` (remove `test_yamlist_compatibility`, add `test_save_all_writes_every_format`)

**Interfaces:**
- Consumes: `discover()` from Task 2.
- Produces:
  - `load(path) -> dict` — the `converter` parameter is gone.
  - `save(path, doc, *, expected=None) -> None` — the `converter` parameter is gone; otherwise unchanged.
  - `load_all(paths) -> tuple[dict, Path, dict[Path, bytes]]` — decodes the first path in the list, returning the document, the path it came from, and every path's bytes as read.
  - `save_all(originals, doc) -> None` — writes every path in the `{Path: bytes}` mapping from one document, aborting the whole write if any file's current bytes differ from the recorded ones.

- [x] **Step 1: Write the failing test**

Delete `test_yamlist_compatibility` entirely, and the now-unused `import shutil` at the top of `tests/test_motion_list.py`. Add:

```python
    def test_save_all_writes_every_format_from_one_edit(self):
        binary = self.root/'motion_list.bin'
        text = self.root/'motion_list.yml'
        binary.write_bytes(motion.encode_binary(fixture()))
        text.write_bytes(yaml.safe_dump(fixture()).encode())
        doc, source, originals = motion.load_all([binary, text])
        self.assertEqual(binary, source)
        self.assertEqual({binary, text}, set(originals))
        edited = motion.update(doc, 'c05attackairf.nuanmb', cancel=45, blend=3)
        motion.save_all(originals, edited)
        for path in (binary, text):
            entry = motion.load(path)['list'][
                motion.hash40('attack_air_f') if path.suffix == '.bin' else 'attack_air_f']
            self.assertEqual(45, entry['extra']['cancel_frame'])
            self.assertEqual(3, entry['blend_frames'])
            self.assertTrue(path.with_name(path.name + '.bak').is_file())

    def test_save_all_aborts_when_any_sibling_changed(self):
        binary = self.root/'motion_list.bin'
        text = self.root/'motion_list.yml'
        binary.write_bytes(motion.encode_binary(fixture()))
        text.write_bytes(yaml.safe_dump(fixture()).encode())
        doc, _, originals = motion.load_all([binary, text])
        edited = motion.update(doc, 'c05attackairf.nuanmb', cancel=45)
        before = binary.read_bytes()
        text.write_bytes(yaml.safe_dump(fixture()).encode() + b'\n# touched\n')
        touched = text.read_bytes()
        with self.assertRaisesRegex(ValueError, 'changed on disk'):
            motion.save_all(originals, edited)
        self.assertEqual(before, binary.read_bytes())
        self.assertEqual(touched, text.read_bytes())
        self.assertFalse(binary.with_name(binary.name + '.bak').is_file())

    def test_load_rejects_a_converter_argument(self):
        path = self.root/'motion_list.bin'
        path.write_bytes(motion.encode_binary(fixture()))
        with self.assertRaises(TypeError):
            motion.load(path, 'yamlist.exe')
```

- [x] **Step 2: Run test to verify it fails**

Run: `python tests/test_motion_list.py MotionListTests.test_save_all_writes_every_format_from_one_edit -v`
Expected: FAIL — `AttributeError: module ... has no attribute 'load_all'`

- [x] **Step 3: Write minimal implementation**

In `source/anim/motion_list.py`:

Delete the `import subprocess` line and the entire `_convert` function.

Replace `load` with:

```python
def load(path):
    path = Path(path)
    if path.suffix.lower() == '.bin':
        return decode_binary(path.read_bytes())
    if path.suffix.lower() not in ('.yml', '.yaml'):
        raise ValueError('Choose a .bin, .yml, or .yaml motion list')
    from ...dependencies import yaml
    class UniqueKeyLoader(yaml.SafeLoader):
        def construct_mapping(self, node, deep=False):
            self.flatten_mapping(node)
            mapping = {}
            for key_node, value_node in node.value:
                key = self.construct_object(key_node, deep=deep)
                if key in mapping:
                    raise ValueError(f'Duplicate YAML key: {key}')
                mapping[key] = self.construct_object(value_node, deep=deep)
            return mapping

    doc = yaml.load(path.read_text(encoding='utf-8-sig'), Loader=UniqueKeyLoader)
    if not isinstance(doc, dict) or not isinstance(doc.get('list'), dict) or 'motion_path' not in doc:
        raise ValueError('Expected a motion_path and list mapping')
    # Validate the complete schema and byte ranges before offering edits.
    encode_binary(doc)
    from . import hash_labels
    hash_labels.harvest(doc)
    return doc
```

Replace the body of `save` so it no longer takes or uses `converter`:

```python
def save(path, doc, *, expected=None):
    """Atomic replacement with a one-time original backup and conflict check."""
    path = Path(path)
    encode_binary(doc)
    if path.suffix.lower() == '.bin':
        data = encode_binary(doc)
    else:
        from ...dependencies import yaml
        data = yaml.safe_dump(doc, sort_keys=False, allow_unicode=True).encode('utf-8')
    original = path.read_bytes()
    if expected is not None and original != expected:
        raise ValueError('Motion list changed on disk; load it again before exporting')
    backup = path.with_name(path.name + '.bak')
    try:
        with backup.open('xb') as stream:
            stream.write(original)
    except FileExistsError:
        pass
    fd, temporary = tempfile.mkstemp(prefix='.motion_list_', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
```

Append the two multi-file helpers:

```python
def load_all(paths):
    """Decode the first path; remember every path's bytes for conflict checks."""
    paths = [Path(path) for path in paths]
    if not paths:
        raise ValueError('No motion_list.bin/.yml/.yaml found beside the animation or up to /motion')
    originals = {path: path.read_bytes() for path in paths}
    return load(paths[0]), paths[0], originals


def save_all(originals, doc):
    """Write every file from one document, or none of them."""
    for path, expected in originals.items():
        if Path(path).read_bytes() != expected:
            raise ValueError(f'{Path(path).name} changed on disk; load it again before exporting')
    for path, expected in originals.items():
        save(path, doc, expected=expected)
```

- [x] **Step 4: Run test to verify it passes**

Run: `python tests/test_motion_list.py -v`
Expected: all tests PASS, including the three new ones.

- [x] **Step 5: Verification checkpoint**

Confirm no yamlist references survive in the codec:

```bash
grep -rn "yamlist\|subprocess\|disasm\|asm" source/anim/motion_list.py
```

Expected: no output. No git commands. Report both results.

---

### Task 4: Write readable names into YAML output

**Files:**
- Modify: `source/anim/motion_list.py` (`save`)
- Test: `tests/test_motion_list.py`

**Interfaces:**
- Consumes: `hash_labels.label()` from Task 1.
- Produces: `labeled(doc) -> dict` — a copy whose integer `motion_path`, motion keys, animation names, `game_script` values and `scripts` entries become readable strings, or `'0x…'` strings when the name is unknown. Never a bare integer, so the YAML always round-trips through `hash40()`. `save()` applies it to YAML output only; binary output is byte-identical to before.

- [x] **Step 1: Write the failing test**

```python
    def test_yaml_output_uses_readable_names(self):
        binary_doc = motion.decode_binary(motion.encode_binary(fixture()))
        self.assertIn(motion.hash40('attack_air_f'), binary_doc['list'])
        path = self.root/'motion_list.yml'
        path.write_bytes(b'motion_path: placeholder\nlist: {}\n')
        motion.save(path, binary_doc)
        text = path.read_text(encoding='utf-8')
        self.assertIn('attack_air_f:', text)
        self.assertIn('c05attackairf.nuanmb', text)
        self.assertIn('wait:', text)
        # Names absent from ParamLabels.csv stay hexadecimal rather than vanishing.
        self.assertIn('0x%x' % motion.hash40('game_attackairf'), text)
        self.assertEqual(motion.encode_binary(motion.load(path)),
                         motion.encode_binary(binary_doc))

    def test_motion_path_is_never_written_as_a_bare_integer(self):
        binary_doc = motion.decode_binary(motion.encode_binary(fixture()))
        self.assertIsInstance(binary_doc['motion_path'], int)
        path = self.root/'motion_list.yml'
        path.write_bytes(b'motion_path: placeholder\nlist: {}\n')
        motion.save(path, binary_doc)
        self.assertIsInstance(motion.load(path)['motion_path'], str)
        self.assertEqual(motion.encode_binary(motion.load(path)),
                         motion.encode_binary(binary_doc))

    def test_unknown_hashes_stay_hexadecimal_and_roundtrip(self):
        doc = motion.decode_binary(motion.encode_binary(fixture()))
        unknown = motion.hash40('sub_test_unlabelled_move_xyz')
        doc['list'][unknown] = doc['list'].pop(motion.hash40('wait'))
        path = self.root/'motion_list.yml'
        path.write_bytes(b'motion_path: placeholder\nlist: {}\n')
        motion.save(path, doc)
        self.assertIn('0x%x' % unknown, path.read_text(encoding='utf-8'))
        self.assertEqual(motion.encode_binary(motion.load(path)), motion.encode_binary(doc))
```

`hash40` already accepts `'0x...'` strings, so a hex-string key re-encodes to the same integer.

- [x] **Step 2: Run test to verify it fails**

Run: `python tests/test_motion_list.py MotionListTests.test_yaml_output_uses_readable_names -v`
Expected: FAIL — the YAML holds integer keys, so `'attack_air_f'` is absent.

- [x] **Step 3: Write minimal implementation**

Add to `source/anim/motion_list.py`:

```python
def labeled(doc):
    """Copy with resolvable hashes replaced by names; re-encodes identically."""
    from . import hash_labels
    result = dict(doc)
    result['motion_path'] = hash_labels.label(doc['motion_path'])
    result['list'] = {}
    for key, motion in doc['list'].items():
        entry = copy.deepcopy(motion)
        entry['game_script'] = hash_labels.label(entry['game_script'])
        entry['scripts'] = [hash_labels.label(script) for script in entry['scripts']]
        entry['animations'] = [dict(animation, name=hash_labels.label(animation['name']))
                               for animation in entry['animations']]
        result['list'][hash_labels.label(key)] = entry
    if encode_binary(result) != encode_binary(doc):
        raise ValueError('Label substitution changed the motion list; refusing to write')
    return result
```

In `save`, replace the YAML branch's dump line:

```python
        from ...dependencies import yaml
        data = yaml.safe_dump(labeled(doc), sort_keys=False, allow_unicode=True).encode('utf-8')
```

- [x] **Step 4: Run test to verify it passes**

Run: `python tests/test_motion_list.py -v`
Expected: every test PASSES.

- [x] **Step 5: Verification checkpoint**

Run the full pure-Python suite once more and report the count. No git commands.

---

### Task 5: Per-action motion properties

**Files:**
- Modify: `source/anim/motion_list_ui.py` (property groups)
- Test: `tests/test_motion_list_blender.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces:
  - `SUB_PG_action_motion` with `blend_frames: IntProperty(min=0, max=255)`, `flag_turn`, `flag_loop`, `flag_move` (all `BoolProperty`), and `synced: BoolProperty`.
  - `bpy.types.Action.sub_motion` pointing at it, registered in `motion_list_ui.register()`.
  - `SUB_PG_motion_list` on the scene reduced to `enabled`, `filepath`, `override_path`, `status`.

- [x] **Step 1: Write the failing test**

In `tests/test_motion_list_blender.py`, replace these three lines:

```python
settings = bpy.context.scene.sub_motion_list
settings.override_flags = True
settings.override_blend = True
```

with:

```python
settings = bpy.context.scene.sub_motion_list
for removed in ('converter', 'key', 'template', 'cancel_mode', 'cancel',
                'override_blend', 'blend', 'override_flags', 'flag_turn'):
    assert not hasattr(settings, removed), removed
for kept in ('enabled', 'filepath', 'override_path', 'status'):
    assert hasattr(settings, kept), kept

probe_action = bpy.data.actions.new('sub_motion_probe')
probe_action.sub_motion.blend_frames = 7
probe_action.sub_motion.flag_loop = True
assert probe_action.sub_motion.synced, 'editing a value must mark it synced'
assert not bpy.data.actions.new('sub_motion_untouched').sub_motion.synced
with tempfile.TemporaryDirectory() as probe_folder:
    blend_file = str(Path(probe_folder)/'probe.blend')
    bpy.ops.wm.save_as_mainfile(filepath=blend_file)
    bpy.ops.wm.open_mainfile(filepath=blend_file)
    reloaded = bpy.data.actions['sub_motion_probe'].sub_motion
    assert reloaded.blend_frames == 7 and reloaded.flag_loop and reloaded.synced
```

**Placement matters.** `wm.open_mainfile` resets the scene and would invalidate everything the later export block builds. Split the test: keep the property-existence assertions (the first two `for` loops) where the old three lines were, and move the `probe_action` save/reload block to the very end of the file, on the line immediately before `addon_utils.disable(MODULE, default_set=False)`.

- [x] **Step 2: Run test to verify it fails**

Run: `python tests/run_blender_test.py --blender "C:/Program Files/Blender Foundation/Blender 4.5/blender.exe" tests/test_motion_list_blender.py`
Expected: FAIL — `AssertionError: converter` (the property still exists).

- [x] **Step 3: Write minimal implementation**

In `source/anim/motion_list_ui.py`, delete `default_converter()` and the `import shutil` line, and replace the whole `SUB_PG_motion_list` class plus the `for _flag in motion_list.FLAGS:` loop beneath it with:

```python
def _mark_synced(self, context):
    self.synced = True


class SUB_PG_action_motion(bpy.types.PropertyGroup):
    """Per-animation motion values, stored on the action like its pose markers."""
    blend_frames: IntProperty(name='Blend Frames', min=0, max=255, update=_mark_synced,
        description='Number of frames used to blend into this motion')
    flag_turn: BoolProperty(name='Turn', update=_mark_synced,
        description='Enable the motion turn flag')
    flag_loop: BoolProperty(name='Loop', update=_mark_synced,
        description='Enable looping for this motion')
    flag_move: BoolProperty(name='Move', update=_mark_synced,
        description='Enable the motion movement flag')
    synced: BoolProperty(name='Synced',
        description='These values came from the motion list or were edited, so export may write them')


class SUB_PG_motion_list(bpy.types.PropertyGroup):
    enabled: BoolProperty(name='Update Motion List on Export', default=False,
        description='Update the matching motion only after its animation is saved successfully')
    filepath: StringProperty(name='Motion List', subtype='FILE_PATH',
        description='Choose motion_list.bin, .yml, or .yaml; leave empty to search beside the animation and up to /motion')
    override_path: BoolProperty(name='Override Path',
        description='Choose the motion list by hand instead of detecting it beside the animation')
    status: StringProperty(name='Loaded Entry',
        description='Most recently loaded motion-list entry and frame values')
```

`IntProperty` is already imported at the top of the module.

Add `SUB_PG_action_motion` to the `classes` tuple at the bottom, before `SUB_PG_motion_list`.

Register the property in `motion_list_ui.register()`, beside the `Scene.sub_motion_list` it already owns:

```python
    bpy.types.Scene.sub_motion_list = PointerProperty(type=SUB_PG_motion_list)
    # Per-animation values live on the action, beside its cancel-frame pose marker.
    bpy.types.Action.sub_motion = PointerProperty(type=SUB_PG_action_motion)
```

and delete it in `unregister()`:

```python
    del bpy.types.Action.sub_motion
    del bpy.types.Scene.sub_motion_list
```

It must **not** go in `source/blender_property_extensions.py`: that module's `register()` runs before `motion_list_ui.register()`, so `SUB_PG_action_motion` has no `bl_rna` yet and `PointerProperty` raises `TypeError: expected an RNA type`.

- [x] **Step 4: Run test to verify it passes**

Run: `python tests/run_blender_test.py --blender "C:/Program Files/Blender Foundation/Blender 4.5/blender.exe" tests/test_motion_list_blender.py`
Expected: the property assertions pass. The run will still FAIL later, at `settings.cancel_mode = 'LENGTH'` in the export section — that is Task 7's work. Confirm the failure has moved past the new assertions.

- [x] **Step 5: Verification checkpoint**

Report which assertion the run now stops at. It must be the export block, not the property block. No git commands.

---

### Task 6: Panel relocation, cancel marker, new layout

**Files:**
- Modify: `source/anim/motion_list_ui.py` (panel class, operators, `draw_settings`)
- Modify: `source/ui_help.py` (`RETIRED_PANEL_IDS`)
- Test: `tests/test_motion_list_blender.py`

**Interfaces:**
- Consumes: `SUB_PG_action_motion` (Task 5), `discover`/`load_all` (Tasks 2-3), `hash_labels.label` (Task 1).
- Produces:
  - `CANCEL_FRAME_MARKER = 'Cancel Frame'`
  - `cancel_marker(action)` → the marker or `None`.
  - `cancel_frame(action)` → `marker.frame` as an `int`, or `None` when absent.
  - Operators `sub.set_cancel_frame_marker`, `sub.clear_cancel_frame_marker`, `sub.load_motion_list`.
  - `SUB_PT_motion_list` parented to `SUB_PT_sub_smush_anim_data_main`.

- [x] **Step 1: Write the failing test**

In `tests/test_motion_list_blender.py`, replace the line

```python
assert bpy.types.Panel.bl_rna_get_subclass_py('SUB_PT_motion_list').bl_parent_id == 'SUB_PT_export_anim'
```

with:

```python
motion_panel = bpy.types.Panel.bl_rna_get_subclass_py('SUB_PT_motion_list')
assert motion_panel.bl_parent_id == 'SUB_PT_sub_smush_anim_data_main', motion_panel.bl_parent_id
assert motion_panel.bl_space_type == 'PROPERTIES' and motion_panel.bl_context == 'data'
```

And replace the `draw_settings(Layout(), bpy.context)` line with a marker exercise plus a draw:

```python
ui = importlib.import_module(MODULE + '.source.anim.motion_list_ui')
marker_obj = bpy.data.objects.get('Armature') or bpy.context.object
marker_action = bpy.data.actions.new('cancel_marker_probe')
if marker_obj.animation_data is None:
    marker_obj.animation_data_create()
marker_obj.animation_data.action = marker_action
assert ui.cancel_frame(marker_action) is None
bpy.context.scene.frame_set(12)
assert bpy.ops.sub.set_cancel_frame_marker() == {'FINISHED'}
assert ui.cancel_frame(marker_action) == 12
assert len(marker_action.pose_markers) == 1
bpy.context.scene.frame_set(20)
assert bpy.ops.sub.set_cancel_frame_marker() == {'FINISHED'}
assert ui.cancel_frame(marker_action) == 20 and len(marker_action.pose_markers) == 1
assert bpy.ops.sub.clear_cancel_frame_marker() == {'FINISHED'}
assert ui.cancel_frame(marker_action) is None and len(marker_action.pose_markers) == 0
ui.SUB_PT_motion_list.draw(SimpleNamespace(layout=Layout()), bpy.context)
```

- [x] **Step 2: Run test to verify it fails**

Run: `python tests/run_blender_test.py --blender "C:/Program Files/Blender Foundation/Blender 4.5/blender.exe" tests/test_motion_list_blender.py`
Expected: FAIL — `AssertionError: SUB_PT_export_anim`

- [x] **Step 3: Write minimal implementation**

In `source/anim/motion_list_ui.py`, replace `resolve_path`, `SUB_OP_load_motion_list`, `draw_settings` and `SUB_PT_motion_list` with:

```python
CANCEL_FRAME_MARKER = 'Cancel Frame'


def cancel_marker(action):
    if action is None:
        return None
    return action.pose_markers.get(CANCEL_FRAME_MARKER)


def cancel_frame(action):
    marker = cancel_marker(action)
    return None if marker is None else int(marker.frame)


def active_action(context):
    obj = context.active_object
    if obj is None or obj.animation_data is None:
        return None
    return obj.animation_data.action


def resolve_paths(settings, animation_path):
    """Explicit override targets one file; detection returns every format."""
    if settings.filepath:
        path = Path(bpy.path.abspath(settings.filepath))
        if not path.is_file():
            raise ValueError(f'Motion list does not exist: {path}')
        return [path]
    paths = motion_list.discover(animation_path)
    if not paths:
        raise ValueError('No motion_list.bin/.yml/.yaml found beside the animation or up to /motion')
    return paths


class SUB_OP_set_cancel_frame_marker(bpy.types.Operator):
    bl_idname = 'sub.set_cancel_frame_marker'
    bl_label = 'Set Cancel Marker'
    bl_description = 'Place the cancel frame marker on the active action at the current frame'

    @classmethod
    def poll(cls, context):
        return active_action(context) is not None

    def execute(self, context):
        action = active_action(context)
        marker = cancel_marker(action)
        if marker is None:
            marker = action.pose_markers.new(CANCEL_FRAME_MARKER)
        marker.frame = context.scene.frame_current
        self.report({'INFO'}, f'Cancel frame marker at {marker.frame}')
        return {'FINISHED'}


class SUB_OP_clear_cancel_frame_marker(bpy.types.Operator):
    bl_idname = 'sub.clear_cancel_frame_marker'
    bl_label = 'Clear Cancel Marker'
    bl_description = 'Remove the cancel frame marker so export keeps the existing cancel frame'

    @classmethod
    def poll(cls, context):
        return cancel_marker(active_action(context)) is not None

    def execute(self, context):
        action = active_action(context)
        action.pose_markers.remove(cancel_marker(action))
        return {'FINISHED'}


class SUB_OP_load_motion_list(bpy.types.Operator):
    bl_idname = 'sub.load_motion_list'
    bl_label = 'Sync From Motion List'
    bl_description = 'Load the matching entry blend frames and flags onto the active action'

    def execute(self, context):
        settings = context.scene.sub_motion_list
        settings.status = ''
        try:
            action = active_action(context)
            if action is None:
                raise ValueError('Select an object with an active animation')
            from .export_anim import ensure_nuanmb_filename, sanitize_filename
            name = ensure_nuanmb_filename(sanitize_filename(action.name))
            ssp = context.scene.sub_scene_properties
            folder = ssp.animation_import_folder_path or ssp.last_anim_export_dir or ssp.last_anim_import_dir
            paths = resolve_paths(settings, Path(bpy.path.abspath(folder)) / name)
            doc, source, _ = motion_list.load_all(paths)
            keys = motion_list.matching_keys(doc, name)
            if len(keys) != 1:
                raise ValueError(f'Expected one motion referencing {name}; found {len(keys)}')
            entry = doc['list'][keys[0]]
            values = action.sub_motion
            values.blend_frames = entry['blend_frames']
            values.flag_turn = entry['flags'].get('turn', False)
            values.flag_loop = entry['flags'].get('loop', False)
            values.flag_move = entry['flags'].get('move', False)
            values.synced = True
            cancel = (entry.get('extra') or {}).get('cancel_frame')
            settings.status = (f'{hash_labels.label(keys[0])} in {source.name}: '
                               f'cancel {cancel if entry.get("extra") else "not available"}, '
                               f'blend {values.blend_frames}')
            self.report({'INFO'}, settings.status)
        except Exception as error:
            self.report({'ERROR'}, str(error))
            return {'CANCELLED'}
        return {'FINISHED'}


class SUB_PT_motion_list(bpy.types.Panel):
    bl_label = 'Ultimate Motion List'
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = 'data'
    bl_options = {'DEFAULT_CLOSED'}
    bl_parent_id = 'SUB_PT_sub_smush_anim_data_main'

    @classmethod
    def poll(cls, context):
        return context.object is not None and context.object.type == 'ARMATURE'

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False
        settings = context.scene.sub_motion_list
        layout.prop(settings, 'enabled')

        path_box = layout.box()
        path_box.prop(settings, 'override_path')
        if settings.override_path:
            path_box.prop(settings, 'filepath')
            path_box.label(text='Only this file is written; siblings are untouched.', icon='INFO')
        else:
            try:
                paths = resolve_paths(settings, self._probe_path(context))
                path_box.label(text='Reads ' + paths[0].name, icon='FILE_TICK')
                for extra in paths[1:]:
                    path_box.label(text='Also writes ' + extra.name, icon='BLANK1')
            except Exception as error:
                path_box.label(text=str(error), icon='ERROR')
                path_box.prop(settings, 'filepath')

        action = active_action(context)
        if action is None:
            layout.label(text='No active action on this armature.', icon='INFO')
        else:
            column = layout.column()
            column.enabled = settings.enabled
            frame = cancel_frame(action)
            if frame is None:
                column.label(text='No cancel marker - entry value kept', icon='MARKER')
            elif 0 <= frame <= 255:
                column.label(text=f'Cancel frame: {frame} (marker)', icon='MARKER_HLT')
            else:
                column.label(text=f'Cancel frame {frame} is outside 0-255', icon='ERROR')
            row = column.row(align=True)
            row.operator('sub.set_cancel_frame_marker', icon='MARKER_HLT')
            row.operator('sub.clear_cancel_frame_marker', icon='X')
            values = action.sub_motion
            column.prop(values, 'blend_frames')
            flags = column.row(align=True)
            flags.prop(values, 'flag_turn', toggle=True)
            flags.prop(values, 'flag_loop', toggle=True)
            flags.prop(values, 'flag_move', toggle=True)
            if not values.synced:
                column.label(text='Not synced; export keeps the entry values.', icon='INFO')

        layout.operator('sub.load_motion_list', icon='FILE_REFRESH')
        if settings.status:
            layout.label(text='Last read: ' + settings.status, icon='INFO')

    def _probe_path(self, context):
        ssp = context.scene.sub_scene_properties
        folder = ssp.animation_import_folder_path or ssp.last_anim_export_dir or ssp.last_anim_import_dir
        return Path(bpy.path.abspath(folder or '//')) / 'probe.nuanmb'

    def draw_header_preset(self, context):
        from ..ui_help import draw_panel_help
        draw_panel_help(self.layout, self)
```

Add `from . import hash_labels` to the module imports. Update `classes` to:

```python
classes = (SUB_PG_action_motion, SUB_PG_motion_list, SUB_OP_set_cancel_frame_marker,
           SUB_OP_clear_cancel_frame_marker, SUB_OP_load_motion_list, SUB_PT_motion_list)
```

Do **not** touch `source/ui_help.py`. `unregister_retired_panels()` unregisters every panel whose `bl_idname` is listed in `RETIRED_PANEL_IDS`, and this panel keeps the identifier `SUB_PT_motion_list`, so listing it would unregister the new panel at startup. Re-parenting an existing identifier needs no retirement entry.

- [x] **Step 4: Run test to verify it passes**

Run: `python tests/run_blender_test.py --blender "C:/Program Files/Blender Foundation/Blender 4.5/blender.exe" tests/test_motion_list_blender.py`
Expected: the panel and marker assertions pass; the run still fails in the export block (Task 7).

- [x] **Step 5: Verification checkpoint**

Confirm the failure is now inside the export section only. No git commands.

---

### Task 7: Export integration

**Files:**
- Modify: `source/anim/motion_list_ui.py` (`prepare`, `commit`)
- Modify: `source/anim/export_anim.py` (`save_ssbh_anim_data` at line 1241, its two call sites at lines 1761 and 1822, and the `draw()` methods at lines 587-589 and 1020-1022)
- Test: `tests/test_motion_list_blender.py`

**Interfaces:**
- Consumes: `cancel_frame` (Task 6), `load_all`/`save_all` (Task 3), `SUB_PG_action_motion` (Task 5).
- Produces:
  - `prepare(settings, animation_path, action) -> tuple | None` — replaces the `final_frame` parameter with the exported `action`.
  - `commit(prepared, operator) -> None` — unchanged signature.
  - `save_ssbh_anim_data(ssbh_anim_data, filepath, operator=None, action=None)`.

- [x] **Step 1: Write the failing test**

In `tests/test_motion_list_blender.py`, replace the export block's setup lines

```python
    settings.cancel_mode = 'LENGTH'
    settings.blend = 3
    settings.flag_loop = True
```

with:

```python
    export_action = obj.animation_data.action
    marker = export_action.pose_markers.new(ui.CANCEL_FRAME_MARKER)
    marker.frame = 39
    export_action.sub_motion.blend_frames = 3
    export_action.sub_motion.flag_loop = True
```

Replace the batch-export expectations. The second action gets its own marker, so change the block that builds `second_action` to add, right after `second_action.name = 'second.nuanmb'`:

```python
    second_marker = second_action.pose_markers.new(ui.CANCEL_FRAME_MARKER)
    second_marker.frame = 24
    second_action.sub_motion.blend_frames = 9
    second_action.sub_motion.flag_move = True
```

and change the post-batch assertions to also check per-action values:

```python
    doc = motion.load(path)
    assert doc['list']['test']['extra']['cancel_frame'] == 39
    assert doc['list']['test']['blend_frames'] == 3
    assert doc['list']['second']['extra']['cancel_frame'] == 24
    assert doc['list']['second']['blend_frames'] == 9
    assert doc['list']['second']['flags']['move']
    assert path.with_name(path.name+'.bak').read_bytes() == original
```

Replace the out-of-range block with a marker-driven one:

```python
    # Invalid metadata is rejected before overwriting the animation.
    before = Path(output).read_bytes()
    marker.frame = 300
    try:
        export.save_ssbh_anim_data(SimpleNamespace(final_frame_index=20), output,
                                   action=export_action)
    except ValueError:
        pass
    else:
        raise AssertionError('Out-of-range cancel frame accepted')
    assert Path(output).read_bytes() == before
    marker.frame = 39
```

Add an unsynced-preservation check right after it:

```python
    # An action nobody synced or edited keeps the entry's blend frames and flags.
    untouched = bpy.data.actions.new('untouched.nuanmb')
    doc = motion.load(path)
    doc['list']['untouched'] = copy.deepcopy(entry)
    doc['list']['untouched']['animations'][0]['name'] = 'untouched.nuanmb'
    doc['list']['untouched']['blend_frames'] = 11
    motion.save(path, doc)
    export.save_ssbh_anim_data(SimpleNamespace(final_frame_index=20),
                               str(Path(folder)/'untouched.nuanmb'), action=untouched)
    assert motion.load(path)['list']['untouched']['blend_frames'] == 11
```

Finally, update the two `export.save_ssbh_anim_data(SimpleNamespace(final_frame_index=20), output)` calls in the failure-path block to pass `action=export_action`.

- [x] **Step 2: Run test to verify it fails**

Run: `python tests/run_blender_test.py --blender "C:/Program Files/Blender Foundation/Blender 4.5/blender.exe" tests/test_motion_list_blender.py`
Expected: FAIL — `TypeError: save_ssbh_anim_data() got an unexpected keyword argument 'action'`

- [x] **Step 3: Write minimal implementation**

In `source/anim/motion_list_ui.py`, replace `prepare` and `commit`:

```python
def prepare(settings, animation_path, action):
    """Validate the edit before the animation is written; commit only after."""
    if not settings or not settings.enabled:
        return None
    paths = resolve_paths(settings, animation_path)
    doc, source, originals = motion_list.load_all(paths)
    cancel = cancel_frame(action)
    values = getattr(action, 'sub_motion', None) if action is not None else None
    blend = values.blend_frames if values is not None and values.synced else None
    flags = None
    if values is not None and values.synced:
        flags = {'turn': values.flag_turn, 'loop': values.flag_loop, 'move': values.flag_move}
    doc = motion_list.update(doc, Path(animation_path).name,
                             cancel=cancel, blend=blend, flags=flags)
    return originals, doc, source


def commit(prepared, operator):
    if prepared is None:
        return
    originals, doc, source = prepared
    motion_list.save_all(originals, doc)
    if operator is not None:
        names = ', '.join(sorted(path.name for path in originals))
        operator.report({'INFO'}, f'Updated {names} from {source.name}; originals backed up as .bak')
```

In `source/anim/export_anim.py`, replace `save_ssbh_anim_data` (line 1241):

```python
def save_ssbh_anim_data(ssbh_anim_data, filepath, operator=None, action=None):
    """Validate optional motion edits before export, then commit after saving."""
    from .motion_list_ui import prepare, commit
    settings = getattr(bpy.context.scene, 'sub_motion_list', None)
    prepared = prepare(settings, filepath, action) if settings else None
    saved_path = _save_ssbh_anim_data(ssbh_anim_data, filepath, operator)
    if os.path.abspath(saved_path) == os.path.abspath(filepath):
        commit(prepared, operator)
    elif prepared is not None and operator is not None:
        operator.report({'WARNING'}, 'Motion list unchanged because animation was saved under an alternate filename')
    return saved_path
```

At both call sites inside `export_model_anim_fast_steps` (lines 1761 and 1822), pass the exported action:

```python
    save_ssbh_anim_data(ssbh_anim_data, filepath, operator,
                        action=arma.animation_data.action if arma.animation_data else None)
```

Delete the two `draw_settings` lines and their `from .motion_list_ui import draw_settings` imports from the export operators' `draw()` methods (lines 587-589 and 1020-1022). Then delete the now-unused `draw_settings` function from `source/anim/motion_list_ui.py` if it still exists after Task 6.

- [x] **Step 4: Run test to verify it passes**

Run: `python tests/run_blender_test.py --blender "C:/Program Files/Blender Foundation/Blender 4.5/blender.exe" tests/test_motion_list_blender.py`
Expected: PASS — the script prints `MOTION LIST INTEGRATION PASSED: <n> operators, <n> panels`.

- [x] **Step 5: Verification checkpoint**

Run the Blender suite on the oldest and newest supported versions and the pure-Python suite:

```bash
python tests/run_blender_test.py --blender "C:/Program Files/Blender Foundation/Blender 4.4/blender.exe" tests/test_motion_list_blender.py
```

```bash
python tests/run_blender_test.py --blender "C:/Program Files/Blender Foundation/Blender 5.2/blender.exe" tests/test_motion_list_blender.py
```

```bash
python tests/test_motion_list.py -v
```

Also run the registration suite, which enumerates every panel and operator:

```bash
python tests/run_blender_test.py --blender "C:/Program Files/Blender Foundation/Blender 4.5/blender.exe" tests/test_addon_registration_blender.py
```

Expected: all pass. No git commands. Report each result.

---

### Task 8: Documentation

**Files:**
- Modify: `docs/motion-list.md` (full rewrite)
- Modify: `README.md:50-52`

**Interfaces:**
- Consumes: the finished behavior from Tasks 1-7.
- Produces: no code.

- [x] **Step 1: Rewrite `docs/motion-list.md`**

Replace the whole file with:

```markdown
# Motion list integration

Open the armature's **Object Data Properties → Ultimate Animation Data →
Ultimate Motion List**. The panel edits the motion entry that matches the
active action, and the export file browsers no longer carry these controls.

Leave the path detection alone to find `motion_list.bin`, `motion_list.yml`, or
`motion_list.yaml` in the export folder or its parents, through the `motion`
directory. The nearest directory holding any of them wins. When that directory
holds several formats, the most recently modified one is read and **all** of
them are rewritten from that single edit, so a `.bin` and its `.yml` mirror
stay in step. The panel names the file it reads. Because the choice is made by
modification time, a file touched by another tool can become the source; check
the named file when that matters. Tick **Override Path** to pick one file by
hand, in which case only that file is written.

Enable **Update Motion List on Export** to save changes with animation exports.
Matching uses the entry's `animations[].name` Hash40, not the move key: for
example, `attack_air_f` can reference `c05attackairf.nuanmb`. An animation
referenced by several motions cannot be disambiguated from this panel and
reports an error instead.

- **Cancel frame** comes from a pose marker named `Cancel Frame` on the action.
  **Set Cancel Marker** places it at the current frame, **Clear Cancel Marker**
  removes it. The marker's frame number is written as-is, so work with a scene
  start frame of 0 if you want it to match the in-game index. The panel always
  shows the value that will be written. Values outside 0-255 are rejected, not
  clamped. With no marker, the entry keeps its existing cancel frame, and
  entries without fighter extra data must have no marker.
- **Blend Frames** and the **Turn**, **Loop**, and **Move** flags live on the
  action, so each animation carries its own and batch export writes each one
  correctly. They are written only after **Sync From Motion List** loads them
  from the entry or you edit them by hand; until then the panel says so and
  export preserves whatever the entry already had. The eleven undocumented
  flags and the game, effect, and sound scripts are always preserved.
- Creating a new motion entry is not supported from this panel. Exporting an
  animation no entry references reports an error.

Motion keys and animation names are shown as readable strings, resolved through
the bundled `ParamLabels.csv` and through any sibling YAML that spells them out.
Unresolved hashes are shown as `0x…`. Saving a YAML list writes readable names
in place of hashes; the result re-encodes to identical bytes, and the binary
format is unaffected.

Binary reading and writing use a built-in codec. No external tool is required,
and there is no `yamlist` path to configure. YAML parsing is bundled and needs
no Python package installation in Blender. The schema and binary layout follow
[motion_lib](https://github.com/ultimate-research/motion_lib).

Motion edits are validated before writing the animation and committed only
after the animation is saved at the requested filename. If a file lock forces
an alternate animation filename, the motion list is left unchanged. A disk
change to any discovered file aborts the whole update before anything is
written. A first-write `.bak` preserves each original, and updates replace each
file atomically. If motion saving fails after animation saving, the animation
remains exported; the export reports the error so you can retry.

YAML values and unrelated keys are preserved, but serialization normalizes
formatting and removes comments. No motion list is created from scratch, and no
game scripts are generated.
```

- [x] **Step 2: Update the README**

Replace lines 50-52 of `README.md` so the location matches:

```markdown
The **Ultimate Motion List** panel, under Ultimate Animation Data, reads and
updates **motion_list.bin/.yml/.yaml** alongside animation exports. See
[Motion list integration](docs/motion-list.md) for detection rules,
```

Keep whatever line 53 onward already says; only the location sentence changes.

- [x] **Step 3: Verify the docs link resolves**

The Blender suite asserts that every panel's help path exists and that any anchor matches a real heading.

Run: `python tests/run_blender_test.py --blender "C:/Program Files/Blender Foundation/Blender 4.5/blender.exe" tests/test_motion_list_blender.py`
Expected: PASS.

- [x] **Step 4: Grep for stale references**

```bash
grep -rn "yamlist\|cancel_mode\|override_flags\|override_blend\|New Entry Template\|Motion Key" --include=*.py --include=*.md . | grep -v __pycache__ | grep -v docs/superpowers
```

Expected: no output. Anything that appears is a leftover; remove it.

- [x] **Step 5: Verification checkpoint**

Run the full suite one last time:

```bash
python tests/test_motion_list.py -v
```

```bash
python tests/run_blender_test.py --blender "C:/Program Files/Blender Foundation/Blender 4.5/blender.exe" tests/test_motion_list_blender.py
```

```bash
python tests/run_blender_test.py --blender "C:/Program Files/Blender Foundation/Blender 4.5/blender.exe" tests/test_animation_workflow_blender.py
```

Expected: all pass. Report the output. **Do not commit** — the user will handle version control.
