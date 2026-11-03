"""Move-name search for the animation importer. No Blender required."""
import importlib.util
import unittest
from pathlib import Path
from types import SimpleNamespace


def _load():
    path = Path(__file__).resolve().parents[1] / 'source' / 'anim' / 'anim_search.py'
    spec = importlib.util.spec_from_file_location('anim_search', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


search = _load()

NAMES = [
    'attack11', 'attack12', 'attack13', 'c00attack100', 'attack_100_end', 'attack100start',
    'attacks3', 'attacks3s', 'attacks3hi', 'attacks3lw', 'attackhi3', 'attacklw3',
    'attacks4', 'attacks4hi', 'attacks4hold', 'attackhi4', 'attacklw4', 'attackdash',
    'c05attackairf', 'attackairn', 'attackairb', 'attackairhi', 'attackairlw',
    'specialn', 'specials', 'specials_start', 'specialhi', 'speciallw',
    'specialairn', 'specialairs', 'specialairhi', 'specialairlw',
    'catch', 'catchdash', 'catchturn', 'catchattack', 'cliffcatch',
    'a00wait1', 'cliffwait', 'throwf', 'throw_hi', 'throwlw', 'throwb',
    'escape', 'escapef', 'escapeb', 'escapeair',
    'guard', 'justshield', 'a02dash', 'a03run', 'runbrake',
    'landingairn', 'passive', 'passivestandf', 'downstand', 'appealhi',
]


def matched(query):
    return [name for name in NAMES if search.animation_matches(name, query)]


class AnimSearchTests(unittest.TestCase):
    def test_filename_search_still_matches_the_stem(self):
        self.assertIn('c05attackairf', matched('attackair'))
        self.assertNotIn('attackairn', matched('attack11'))
        self.assertEqual(search.animation_matches('run_a', 'run'), True)
        self.assertEqual(search.animation_matches('idle', 'run'), False)

    def test_jab_finds_the_jab_family(self):
        found = set(matched('jab'))
        self.assertTrue({'attack11', 'attack12', 'attack13', 'c00attack100',
                         'attack_100_end', 'attack100start'} <= found)
        self.assertNotIn('attacks3', found)
        self.assertNotIn('specials', found)
        self.assertEqual(set(matched('jab 1')), {'attack11'})
        self.assertIn('attack_100_end', matched('rapid jab'))
        self.assertNotIn('attack11', matched('rapid jab'))

    def test_side_special_finds_ground_and_air_versions(self):
        found = set(matched('side special'))
        self.assertTrue({'specials', 'specials_start', 'specialairs'} <= found)
        for name in ('specialn', 'specialhi', 'speciallw', 'specialairn', 'attacks3'):
            self.assertNotIn(name, found)
        self.assertEqual(set(matched('side-b')), found)
        self.assertIn('specialn', matched('neutral b'))
        self.assertIn('specialhi', matched('recovery'))
        self.assertNotIn('specials', matched('recovery'))

    def test_tilts_smashes_and_aerials(self):
        ftilt = set(matched('ftilt'))
        self.assertTrue({'attacks3', 'attacks3s', 'attacks3hi', 'attacks3lw'} <= ftilt)
        self.assertNotIn('attackhi3', ftilt)
        self.assertEqual(set(matched('up tilt')), {'attackhi3'})
        self.assertEqual(set(matched('dsmash')), {'attacklw4'})
        self.assertTrue({'attacks4', 'attacks4hi', 'attacks4hold'} <= set(matched('forward smash')))
        self.assertEqual(set(matched('fair')), {'c05attackairf'})
        self.assertNotIn('landingairn', matched('nair'))
        self.assertEqual(set(matched('nair')), {'attackairn'})
        self.assertEqual(set(matched('dash attack')), {'attackdash'})

    def test_direction_words_follow_the_move(self):
        up = set(matched('up'))
        for name in ('attackhi3', 'attackhi4', 'attackairhi', 'specialhi', 'specialairhi', 'throw_hi', 'appealhi'):
            self.assertIn(name, up)
        for name in ('attacklw3', 'speciallw', 'a00wait1', 'downstand'):
            self.assertNotIn(name, up)

    def test_grab_dodge_shield_and_movement(self):
        grab = set(matched('grab'))
        self.assertTrue({'catch', 'catchdash', 'catchturn', 'catchattack'} <= grab)
        self.assertNotIn('cliffcatch', grab)
        self.assertTrue({'escape', } <= set(matched('spot dodge')))
        self.assertNotIn('escapeair', matched('spot dodge'))
        self.assertEqual(set(matched('air dodge')), {'escapeair'})
        self.assertIn('escapef', matched('roll'))
        self.assertNotIn('escape', matched('roll'))
        self.assertIn('justshield', matched('parry'))
        self.assertIn('guard', matched('shield'))
        self.assertEqual(set(matched('idle')), {'a00wait1'})
        self.assertNotIn('cliffwait', matched('idle'))
        self.assertFalse(search.animation_matches('squatwait', 'idle'))
        self.assertTrue(search.animation_matches('attack_s3_hi', 'forward tilt'))
        self.assertTrue(search.animation_matches('SpecialAirS', 'side special'))
        self.assertTrue(search.animation_matches('c00attacks4hold', 'fsmash'))
        self.assertIn('a00wait1', matched('wait'))
        self.assertIn('a02dash', matched('initial dash'))
        self.assertNotIn('attackdash', matched('initial dash'))
        self.assertIn('a03run', matched('run'))
        self.assertIn('passive', matched('tech'))
        self.assertIn('passivestandf', matched('tech roll'))
        self.assertNotIn('passive', matched('tech roll'))

    def test_list_filter_sort_matches_visible_rows(self):
        items = [SimpleNamespace(name=name) for name in ('run_a', 'idle', 'run_b', 'run_c')]
        ui = SimpleNamespace(filter_name='run', bitflag_filter_item=1 << 30,
                             use_filter_invert=False, use_filter_sort_alpha=True,
                             use_filter_sort_reverse=True)
        _flags, _order, visible = search.list_filter(ui, items)
        self.assertEqual(visible, [3, 2, 0])
        ui.use_filter_invert = True
        ui.filter_name = 'run'
        _flags, _order, visible = search.list_filter(ui, items)
        self.assertEqual(visible, [1])


if __name__ == '__main__':
    unittest.main()
