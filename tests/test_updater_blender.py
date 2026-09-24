"""Updater: version-based detection, Blender requirement gate, popup decisions, What's New.

python tests/run_blender_test.py --blender "C:/Program Files/Blender Foundation/Blender 4.5/blender.exe" tests/test_updater_blender.py
"""
import importlib
import importlib.util
import os
from pathlib import Path
import sys
import tempfile

import addon_utils
import bpy

profile = tempfile.TemporaryDirectory(prefix='sub_updater_test_')
for variable, leaf in (('BLENDER_USER_SCRIPTS', 'scripts'), ('BLENDER_USER_CONFIG', 'config')):
    path = Path(profile.name) / leaf
    path.mkdir()
    os.environ[variable] = str(path)
assert Path(bpy.utils.user_resource('CONFIG')).is_relative_to(profile.name)

ROOT = Path(__file__).resolve().parents[1]
MODULE = 'sub_updater_test'
spec = importlib.util.spec_from_file_location(MODULE, ROOT / '__init__.py',
                                             submodule_search_locations=[str(ROOT)])
addon = importlib.util.module_from_spec(spec)
sys.modules[MODULE] = addon
spec.loader.exec_module(addon)
addon.__time__ = (ROOT / '__init__.py').stat().st_mtime

vc = importlib.import_module(MODULE + '.source.updater.version_check')
prompt = importlib.import_module(MODULE + '.source.updater.prompt')
ui = importlib.import_module(MODULE + '.source.updater.ui')
labels = importlib.import_module(MODULE + '.source.param_labels')
labels.ensure_param_labels = lambda: ROOT / 'ParamLabels.csv'
labels.load_param_labels = lambda: ROOT / 'ParamLabels.csv'
importlib.import_module(MODULE + '.expy_kit.preset_handler').install_presets = lambda: None

# Never touch the network, the repository's .current_commit, or old binaries.
REMOTE = {}
stored_sha = ['installedsha']
vc.load_current_commit_sha = lambda: stored_sha[0]
vc.save_current_commit_sha = lambda sha: stored_sha.__setitem__(0, sha)
vc.cleanup_old_binaries = lambda: None


class FakeResponse:
    def __init__(self, payload=None, text=''):
        self.payload, self.text = payload, text

    def raise_for_status(self):
        if self.payload is None and self.text is None:
            raise RuntimeError('404')

    def json(self):
        return self.payload


class FakeRequests:
    @staticmethod
    def get(url, **_kwargs):
        if url.endswith('/commits/animation-workflow'):
            return FakeResponse({'sha': 'latestsha', 'commit': {
                'message': 'Release', 'author': {'date': '2026-10-01T00:00:00Z'}}})
        if '/commits/' in url:
            return FakeResponse({'sha': 'installedsha', 'commit': {'message': 'Old', 'author': {}}})
        if '/compare/' in url:
            return FakeResponse({'commits': [{'sha': 'latestsha', 'commit': {
                'message': 'Commit subject\n\nCommit body line', 'author': {}}}]})
        for name, text in REMOTE.items():
            if url.endswith('/' + name):
                return FakeResponse(text=text)
        return FakeResponse(text=None)


vc.requests = FakeRequests

errors = []
enabled = addon_utils.enable(MODULE, default_set=True,
                             handle_error=lambda _e: errors.append(__import__('traceback').format_exc()))
assert enabled is addon and not errors, '\n'.join(errors)

for idname in ('update_prompt', 'update_now', 'update_skip_version',
               'update_clear_skipped', 'update_whats_new', 'view_update_changelog'):
    getattr(bpy.ops.sub, idname).get_rna_type()  # KeyError when not registered
assert not bpy.app.timers.is_registered(prompt._startup_timer), 'startup popups must not run headless'

LOCAL = vc.get_local_addon_version()
NEWER = (LOCAL[0], LOCAL[1] + 1, 0)
newer_text = '.'.join(map(str, NEWER))


def remote(version, blender=(4, 4, 0), changelog=None):
    REMOTE.clear()
    REMOTE['__init__.py'] = (f"bl_info = {{'version': {tuple(version)}, 'blender': {tuple(blender)}}}")
    if changelog is not None:
        REMOTE['CHANGELOG.md'] = changelog


# 1. A higher remote version is an update, with CHANGELOG notes between the versions.
remote(NEWER, changelog=f'## Unreleased\n- no\n## {newer_text}\n- Shiny new thing\n'
                        f'## {".".join(map(str, LOCAL))}\n- Already installed\n')
vc.check_for_newer_version()
assert vc.UPDATE_AVAILABLE and vc.UPDATE_BLENDER_COMPATIBLE
assert [s.version for s in vc.PENDING_CHANGELOG_SECTIONS] == [NEWER]
notes = vc.pending_update_notes()
assert notes[0][0].startswith(f'v{newer_text}') and notes[0][1] == ['Shiny new thing'], notes
assert prompt.should_prompt_for_update()

# 2. Without a CHANGELOG section the commit notes are the fallback.
remote(NEWER)
vc.check_for_newer_version()
assert vc.UPDATE_AVAILABLE and not vc.PENDING_CHANGELOG_SECTIONS
assert vc.pending_update_notes() == [('Recent changes', ['Commit body line'])], vc.pending_update_notes()

# 3. An equal version is not an update even though the commit differs.
remote(LOCAL)
vc.check_for_newer_version()
assert not vc.UPDATE_AVAILABLE and not prompt.should_prompt_for_update()

# 4. An update needing a newer Blender is listed but never prompted or installed.
remote(NEWER, blender=(99, 0, 0))
vc.check_for_newer_version()
assert vc.UPDATE_AVAILABLE and not vc.UPDATE_BLENDER_COMPATIBLE
assert not prompt.should_prompt_for_update()
try:
    bpy.ops.sub.download_update()
    raise AssertionError('an incompatible update must not install')
except RuntimeError as error:
    assert 'requires Blender 99.0.0' in str(error), error
assert vc.UPDATE_STATUS == 'idle'

# 5. Skipping silences only that version; the preference turns the popup off.
remote(NEWER)
vc.check_for_newer_version()
bpy.ops.sub.update_skip_version()
assert prompt.skipped_version() == NEWER and not prompt.should_prompt_for_update()
remote((NEWER[0], NEWER[1] + 1, 0))
vc.check_for_newer_version()
assert prompt.should_prompt_for_update(), 'a newer version than the skipped one prompts again'
bpy.ops.sub.update_clear_skipped()
assert prompt.skipped_version() is None
prefs = bpy.context.preferences.addons[MODULE].preferences
assert prefs.show_update_popup is True
prefs.show_update_popup = False
assert not prompt.should_prompt_for_update()
prefs.show_update_popup = True

# 6. What's New: silent on first run, shows the gap once after an update.
assert prompt.whats_new_sections() == []
assert prompt.load_state()['last_seen_version'] == '.'.join(map(str, LOCAL))
state = prompt.load_state()
state['last_seen_version'] = '4.6.0'
prompt.save_state(state)
local_sections = vc.get_local_changelog_sections()
expected = [s.version for s in local_sections if (4, 6, 0) < s.version <= LOCAL]
assert [s.version for s in prompt.whats_new_sections()] == expected and expected
assert prompt.whats_new_sections() == [], 'What\'s New shows only once'


# 7. Notes drawing wraps long lines and caps the popup height.
class FakeLayout:
    def __init__(self):
        self.labels = []

    def box(self):
        return self

    def column(self, **_kwargs):
        return self

    def separator(self):
        pass

    def label(self, text='', icon='NONE'):
        self.labels.append(text)


layout = FakeLayout()
ui.draw_notes(layout, [('v9.0.0', ['word ' * 40] + [f'note {i}' for i in range(20)])], max_lines=8)
assert len(layout.labels) <= 9 and layout.labels[-1].startswith('...and'), layout.labels
assert all(len(text) <= ui.NOTE_WRAP_WIDTH + 2 for text in layout.labels)
layout = FakeLayout()
ui.draw_notes(layout, [])
assert layout.labels == ['No patch notes were published for this update.']

addon_utils.disable(MODULE, default_set=True)
print('UPDATER TEST PASSED')
