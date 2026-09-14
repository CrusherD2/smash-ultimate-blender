"""Check actual panel help destinations without importing Blender."""
import ast
import importlib.util
from pathlib import Path
import re
import unittest
from unittest.mock import Mock


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('ui_help', ROOT / 'source/ui_help.py')
help_ui = importlib.util.module_from_spec(spec)
spec.loader.exec_module(help_ui)


class PanelHelpTests(unittest.TestCase):
    def test_all_help_panels_are_in_ultimate_and_have_real_targets(self):
        count = 0
        for path in (ROOT / 'source').rglob('*.py'):
            tree = ast.parse(path.read_text(encoding='utf-8-sig'))
            for cls in ast.walk(tree):
                if not isinstance(cls, ast.ClassDef):
                    continue
                if not any(isinstance(n, ast.Name) and n.id == 'draw_panel_help'
                           for n in ast.walk(cls)):
                    continue
                with self.subTest(panel=cls.name):
                    attrs = {
                        s.targets[0].id: s.value.value for s in cls.body
                        if isinstance(s, ast.Assign)
                        and isinstance(s.targets[0], ast.Name)
                        and isinstance(s.value, ast.Constant)
                    }
                    self.assertEqual(attrs.get('bl_space_type'), 'VIEW_3D')
                    self.assertEqual(attrs.get('bl_region_type'), 'UI')
                    self.assertEqual(attrs.get('bl_category'), 'Ultimate')
                    attrs['__module__'] = '.'.join(path.relative_to(ROOT).with_suffix('').parts)
                    panel = type(cls.name, (), attrs)()
                    target, _, anchor = help_ui.panel_doc_path(panel).partition('#')
                    doc = ROOT / target
                    self.assertTrue(doc.is_file(), target)
                    if anchor:
                        headings = re.findall(r'^#+ (.+)$', doc.read_text(encoding='utf-8'), re.M)
                        slugs = [re.sub(r'[^\w\- ]', '', h.lower()).replace(' ', '-')
                                 for h in headings]
                        self.assertIn(anchor, slugs, target)
                    layout = Mock()
                    help_ui.draw_panel_help(layout, panel)
                    self.assertEqual(layout.row.return_value.operator.return_value.url,
                                     help_ui.DOCS_ROOT + help_ui.panel_doc_path(panel))
                    count += 1
        self.assertGreater(count, 0)

    def test_other_editors_tabs_and_regions_do_not_draw_help(self):
        for space, region, category in [('PROPERTIES', 'WINDOW', 'Ultimate'),
                                        ('VIEW_3D', 'UI', 'IK Bones'),
                                        ('VIEW_3D', 'HEADER', 'Ultimate')]:
            panel = type('MovedPanel', (), dict(bl_space_type=space,
                         bl_region_type=region, bl_category=category))()
            layout = Mock()
            help_ui.draw_panel_help(layout, panel)
            layout.row.assert_not_called()


if __name__ == '__main__':
    unittest.main()
