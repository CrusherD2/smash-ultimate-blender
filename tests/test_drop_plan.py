"""Pure Python tests for how dropped files are routed to importers.

python -m pytest tests/test_drop_plan.py
"""
import importlib.util
import os
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('drop_plan', ROOT / 'source' / 'drop_plan.py')
drop_plan = importlib.util.module_from_spec(spec)
spec.loader.exec_module(drop_plan)

BODY = os.path.join('mario', 'model', 'body', 'c00')
MOTION = os.path.join('mario', 'motion', 'body', 'c00')


class DropPlanTest(unittest.TestCase):
    def test_every_file_of_a_model_imports_the_folder_once(self):
        names = ['model.numdlb', 'model.numshb', 'model.nusktb', 'model.numatb', 'model.nuhlpb']
        plan = drop_plan.plan_drop([os.path.join(BODY, name) for name in names])
        self.assertEqual(plan.model_folders, [BODY])
        self.assertFalse(plan.needs_armature)

    def test_two_color_slots_are_two_models(self):
        c01 = BODY[:-1] + '1'
        plan = drop_plan.plan_drop([os.path.join(BODY, 'model.numdlb'), os.path.join(c01, 'model.numdlb')])
        self.assertEqual(plan.model_folders, [BODY, c01])

    def test_animations_keep_drop_order_and_need_an_armature(self):
        paths = [os.path.join(MOTION, 'a00wait1.nuanmb'), os.path.join(MOTION, 'a00wait1.NUANMB'),
                 os.path.join('raw', 'clip.rawanim')]
        plan = drop_plan.plan_drop(paths)
        self.assertEqual(plan.animations, [paths[0], paths[2]])
        self.assertTrue(plan.needs_armature)

    def test_stage_lighting_is_not_a_fighter_motion(self):
        light = os.path.join('stage', 'battlefield', 'normal', 'light', 'light00.nuanmb')
        loose = os.path.join('downloads', 'light.nuanmb')
        in_light_folder = os.path.join('stage', 'light', 'anything.nuanmb')
        motion = os.path.join(MOTION, 'a05landinglight.nuanmb')
        plan = drop_plan.plan_drop([light, loose, in_light_folder, motion])
        self.assertEqual(plan.stage_lights, [light, loose, in_light_folder])
        self.assertEqual(plan.animations, [motion])

    def test_only_swing_prc_is_claimed(self):
        swing = os.path.join('mario', 'motion', 'swing.prc')
        plan = drop_plan.plan_drop([swing, os.path.join('mario', 'model', 'update.prc')])
        self.assertEqual(plan.swing_files, [swing])
        self.assertEqual(plan.skipped, [os.path.join('mario', 'model', 'update.prc')])
        self.assertTrue(plan.needs_armature)

    def test_shpc_and_unknown_files(self):
        plan = drop_plan.plan_drop(['chara.shpcanim', 'grid.shpc', 'readme.txt', ''])
        self.assertEqual(plan.shpc_files, ['chara.shpcanim', 'grid.shpc'])
        self.assertEqual(plan.skipped, ['readme.txt'])

    def test_nothing_importable(self):
        self.assertTrue(drop_plan.plan_drop(['readme.txt', 'update.prc']).is_empty())

    def test_every_routed_suffix_is_claimed_by_the_handler(self):
        for suffix in drop_plan.MODEL_SUFFIXES + drop_plan.SHPC_SUFFIXES + ('.nuanmb', '.rawanim', '.prc'):
            self.assertIn(suffix, drop_plan.DROP_EXTENSIONS)


if __name__ == '__main__':
    unittest.main()
