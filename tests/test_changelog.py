"""Pure Python tests for CHANGELOG.md parsing used by the updater.

python -m pytest tests/test_changelog.py
"""
import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('changelog', ROOT / 'source' / 'updater' / 'changelog.py')
changelog = importlib.util.module_from_spec(spec)
spec.loader.exec_module(changelog)

SAMPLE = """# Changelog

Intro text that is not part of any version.

## 4.8.0 - 2026-10-01
- Added the update popup
- Fixed mirroring
  continued on a second line

## [4.7.1] - 2026-09-22
* Bug fixes

## 4.7.0
Plain paragraph note.

## Unreleased
- Not a version, ignored
"""


class ParseTest(unittest.TestCase):
    def test_sections_are_parsed_with_versions_dates_and_notes(self):
        sections = changelog.parse_changelog(SAMPLE)
        self.assertEqual([s.version for s in sections], [(4, 8, 0), (4, 7, 1), (4, 7, 0)])
        self.assertEqual(sections[0].date, '2026-10-01')
        self.assertEqual(sections[0].notes, ['Added the update popup', 'Fixed mirroring continued on a second line'])
        self.assertEqual(sections[1].notes, ['Bug fixes'])
        self.assertEqual(sections[2].date, '')
        self.assertEqual(sections[2].notes, ['Plain paragraph note.'])

    def test_two_part_versions_are_padded(self):
        sections = changelog.parse_changelog('## v5.0\n- Big release\n')
        self.assertEqual(sections[0].version, (5, 0, 0))

    def test_garbage_or_empty_text_has_no_sections(self):
        self.assertEqual(changelog.parse_changelog(''), [])
        self.assertEqual(changelog.parse_changelog(None), [])
        self.assertEqual(changelog.parse_changelog('<html>404: Not Found</html>'), [])

    def test_indented_example_headings_are_not_sections(self):
        text = 'How to write one:\n\n    ## 9.9.9 - example\n    - example note\n\n## 1.0.0\n- real\n'
        self.assertEqual([s.version for s in changelog.parse_changelog(text)], [(1, 0, 0)])

    def test_repository_changelog_parses(self):
        sections = changelog.parse_changelog((ROOT / 'CHANGELOG.md').read_text(encoding='utf-8'))
        self.assertTrue(sections)
        self.assertTrue(all(section.notes for section in sections))
        # The indented how-to example in the file header is not a real section.
        self.assertNotIn((4, 8, 1), [s.version for s in sections])

    def test_sections_are_sorted_newest_first(self):
        text = '## 1.0.0\n- a\n## 1.2.0\n- b\n## 1.1.0\n- c\n'
        self.assertEqual([s.version for s in changelog.parse_changelog(text)], [(1, 2, 0), (1, 1, 0), (1, 0, 0)])


class RangeTest(unittest.TestCase):
    def test_notes_between_installed_exclusive_and_remote_inclusive(self):
        sections = changelog.sections_between(changelog.parse_changelog(SAMPLE), (4, 7, 0), (4, 8, 0))
        self.assertEqual([s.version for s in sections], [(4, 8, 0), (4, 7, 1)])

    def test_unknown_installed_version_shows_only_the_remote_version(self):
        sections = changelog.sections_between(changelog.parse_changelog(SAMPLE), None, (4, 8, 0))
        self.assertEqual([s.version for s in sections], [(4, 8, 0)])

    def test_no_upper_bound_includes_everything_newer(self):
        sections = changelog.sections_between(changelog.parse_changelog(SAMPLE), (4, 7, 1), None)
        self.assertEqual([s.version for s in sections], [(4, 8, 0)])

    def test_section_for_exact_version(self):
        sections = changelog.parse_changelog(SAMPLE)
        self.assertEqual(changelog.section_for(sections, (4, 7, 1)).notes, ['Bug fixes'])
        self.assertIsNone(changelog.section_for(sections, (9, 9, 9)))


class VersionTextTest(unittest.TestCase):
    def test_format_and_parse_round_trip(self):
        self.assertEqual(changelog.format_version((4, 7, 1)), '4.7.1')
        self.assertEqual(changelog.parse_version('4.7.1'), (4, 7, 1))
        self.assertEqual(changelog.parse_version('v4.7'), (4, 7, 0))
        self.assertIsNone(changelog.parse_version(''))
        self.assertIsNone(changelog.parse_version('banana'))


if __name__ == '__main__':
    unittest.main()
