"""Pure Python motion-list tests for the codec, discovery, labels, and writes."""
import copy
import importlib
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest

ROOT = Path(__file__).resolve().parents[1]
# Load just the codec and vendored YAML, without importing bpy or the add-on.
for name, path in [('motion_test', ROOT), ('motion_test.source', ROOT/'source'),
                   ('motion_test.source.anim', ROOT/'source/anim')]:
    package = types.ModuleType(name)
    package.__path__ = [str(path)]
    sys.modules[name] = package
motion = importlib.import_module('motion_test.source.anim.motion_list')
hash_labels = importlib.import_module('motion_test.source.anim.hash_labels')
yaml = importlib.import_module('motion_test.dependencies.yaml')


def fixture():
    entry = dict(game_script='game_attackairf',
        flags={name: name in ('move', 'unk_80') for name in motion.FLAGS}, blend_frames=6,
        animations=[dict(name='c05attackairf.nuanmb', unk=0)],
        scripts=['expression_attackairf', 'sound_attackairf', 'effect_attackairf'],
        extra=dict(xlu_start=1, xlu_end=2, cancel_frame=30, no_stop_intp=True))
    second = copy.deepcopy(entry)
    second['animations'][0]['name'] = 'a00wait1.nuanmb'
    return dict(motion_path='fighter/pacman/motion/body/c00',
                list={'attack_air_f': entry, 'wait': second})


class MotionListTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.root = Path(self.folder.name)
        self.addCleanup(self.folder.cleanup)

    def test_binary_roundtrip_and_reserved_bits(self):
        doc = fixture()
        doc['list']['wait']['_reserved_flags'] = 0xc000
        raw = motion.encode_binary(doc)
        self.assertEqual(raw, motion.encode_binary(motion.decode_binary(raw)))
        self.assertEqual(['attack_air_f'], motion.matching_keys(doc, 'c05attackairf.nuanmb'))
        binary = motion.decode_binary(raw)
        self.assertEqual([motion.hash40('attack_air_f')], motion.matching_keys(binary, 'c05attackairf.nuanmb'))

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
            written = motion.load(path)
            entry = written['list'][motion.matching_keys(written, 'c05attackairf.nuanmb')[0]]
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

    def test_unknown_hashes_stay_hexadecimal_and_roundtrip(self):
        doc = motion.decode_binary(motion.encode_binary(fixture()))
        unknown = motion.hash40('sub_test_unlabelled_move_xyz')
        doc['list'][unknown] = doc['list'].pop(motion.hash40('wait'))
        path = self.root/'motion_list.yml'
        path.write_bytes(b'motion_path: placeholder\nlist: {}\n')
        motion.save(path, doc)
        self.assertIn('0x%x' % unknown, path.read_text(encoding='utf-8'))
        self.assertEqual(motion.encode_binary(motion.load(path)), motion.encode_binary(doc))

    def test_motion_path_is_never_written_as_a_bare_integer(self):
        binary_doc = motion.decode_binary(motion.encode_binary(fixture()))
        self.assertIsInstance(binary_doc['motion_path'], int)
        path = self.root/'motion_list.yml'
        path.write_bytes(b'motion_path: placeholder\nlist: {}\n')
        motion.save(path, binary_doc)
        self.assertIsInstance(motion.load(path)['motion_path'], str)
        self.assertEqual(motion.encode_binary(motion.load(path)),
                         motion.encode_binary(binary_doc))

    def test_edit_preserves_other_fields(self):
        doc = fixture()
        edited = motion.update(doc, 'c05attackairf.nuanmb', cancel=39, blend=4, flags={'loop': True})
        self.assertEqual(doc['list']['wait'], edited['list']['wait'])
        entry = edited['list']['attack_air_f']
        self.assertEqual(doc['list']['attack_air_f']['scripts'], entry['scripts'])
        self.assertTrue(entry['flags']['unk_80'])
        self.assertTrue(entry['flags']['loop'])
        self.assertEqual(30, doc['list']['attack_air_f']['extra']['cancel_frame'])

    def test_yaml_extensions_backup_and_conflict(self):
        for suffix in ('.yml', '.yaml'):
            path = self.root/('motion_list' + suffix)
            original = yaml.safe_dump(fixture()).encode()
            path.write_bytes(original)
            doc = motion.load(path)
            doc['notes'] = 'Unrelated top-level metadata'
            edited = motion.update(doc, 'c05attackairf.nuanmb', cancel=255)
            motion.save(path, edited, expected=original)
            self.assertEqual(edited, motion.load(path))
            self.assertEqual(original, path.with_name(path.name+'.bak').read_bytes())
            with self.assertRaisesRegex(ValueError, 'changed on disk'):
                motion.save(path, doc, expected=original)
            motion.save(path, doc)
            self.assertEqual(original, path.with_name(path.name+'.bak').read_bytes())

    def test_creation_requires_template_and_unique_key(self):
        doc = fixture()
        with self.assertRaises(ValueError):
            motion.update(doc, 'new.nuanmb', cancel=20)
        with self.assertRaises(ValueError):
            motion.update(doc, 'new.nuanmb', key='wait', template='wait')
        result = motion.update(doc, 'new.nuanmb', key='new_move', template='wait', cancel=20)
        self.assertEqual(['new_move'], motion.matching_keys(result, 'new.nuanmb'))
        self.assertEqual(doc['list']['wait']['scripts'], result['list']['new_move']['scripts'])

    def test_ambiguity_and_shared_animation(self):
        doc = fixture()
        doc['list']['wait']['animations'][0]['name'] = 'c05attackairf.nuanmb'
        with self.assertRaisesRegex(ValueError, 'shared'):
            motion.update(doc, 'c05attackairf.nuanmb', cancel=1)
        edited = motion.update(doc, 'c05attackairf.nuanmb', key='attack_air_f', cancel=1)
        self.assertEqual(doc['list']['wait'], edited['list']['wait'])

    def test_ranges_and_nonfighter(self):
        for value in (-1, 256, 1.5):
            with self.assertRaises(ValueError):
                motion.update(fixture(), 'c05attackairf.nuanmb', cancel=value)
        doc = fixture()
        doc['list']['attack_air_f']['extra'] = None
        self.assertEqual(doc, motion.update(doc, 'c05attackairf.nuanmb'))
        with self.assertRaisesRegex(ValueError, 'no fighter extra'):
            motion.update(doc, 'c05attackairf.nuanmb', cancel=5)

    def test_discovery_returns_one_file_from_the_nearest_directory(self):
        folder = self.root/'fighter/pacman/motion/body/c00'
        folder.mkdir(parents=True)
        far = folder.parents[1]/'motion_list.yml'
        far.touch()
        self.assertEqual([far], motion.discover(folder/'test.nuanmb'))
        binary = folder/'motion_list.bin'
        binary.touch()
        self.assertEqual([binary], motion.discover(folder/'test.nuanmb'))
        # YAML wins over the binary regardless of which was written last.
        near_yaml = folder/'motion_list.yml'
        near_yaml.touch()
        os.utime(binary, (1_800_000_000, 1_800_000_000))
        os.utime(near_yaml, (1_600_000_000, 1_600_000_000))
        self.assertEqual([near_yaml], motion.discover(folder/'test.nuanmb'))
        near_yaml.unlink()
        (folder/'motion_list.yaml').touch()
        self.assertEqual([folder/'motion_list.yaml'], motion.discover(folder/'test.nuanmb'))

    def test_discovery_stops_at_motion_and_returns_empty(self):
        folder = self.root/'fighter/pacman/motion/body/c00'
        folder.mkdir(parents=True)
        (self.root/'fighter/pacman/motion_list.bin').touch()
        self.assertEqual([], motion.discover(folder/'test.nuanmb'))

    def test_invalid_binary_and_yaml(self):
        raw = motion.encode_binary(fixture())
        for bad in (b'', b'bad header', raw[:-1], raw+b'junk'):
            with self.assertRaises(ValueError):
                motion.decode_binary(bad)
        path = self.root/'motion_list.yml'
        path.write_text('!!python/object/apply:os.system [echo unsafe]')
        with self.assertRaises(yaml.YAMLError):
            motion.load(path)


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
        original = hash_labels.csv_path
        hash_labels.csv_path = lambda: Path(self.folder.name) / 'absent.csv'
        try:
            self.assertEqual({}, hash_labels.labels())
            self.assertEqual('0x1', hash_labels.label(1))
        finally:
            hash_labels.csv_path = original


if __name__ == '__main__':
    unittest.main()
