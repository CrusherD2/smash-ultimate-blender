"""Swing import saves its names to ParamLabels.csv in one batch, and its buttons live in the properties panel."""
from pathlib import Path

fixture = Path(__file__).with_name('test_addon_registration_blender.py')
exec(compile(fixture.read_text(encoding='utf-8').split('floor = importlib.import_module')[0], str(fixture), 'exec'))
labels = importlib.import_module(MODULE + '.source.param_labels')
ui = importlib.import_module(MODULE + '.source.swing.ui')

csv_path = Path(profile.name) / 'ParamLabels.csv'
csv_path.write_text('0x0000000000,placeholder\n', encoding='utf-8')
labels.labels_path = lambda: csv_path
labels.ensure_param_labels = lambda: csv_path
writes = []
real_append = labels._append_entries
labels._append_entries = lambda path, entries: writes.append(len(entries)) or real_append(path, entries)

with labels.deferred_hash_labels():
    for name in ('skirtc1', 'legr', 'bust', 'skirtc1'):
        assert labels.add_hash_label(name)
    with labels.deferred_hash_labels():  # nested use joins the outer batch
        labels.add_hash_label('apron1')
    assert writes == [], 'nothing is written until the batch ends'
assert len(writes) == 1, writes
rows = csv_path.read_text(encoding='utf-8')
for name in ('skirtc1', 'legr', 'bust', 'apron1'):
    assert rows.count(',' + name + '\n') == 1, (name, rows)

writes.clear()
labels.add_hash_label('outside_batch')
assert writes == [1], 'outside a batch each label is still written right away'

# An error inside the batch still saves what was queued before it.
writes.clear()
try:
    with labels.deferred_hash_labels():
        labels.add_hash_label('before_error')
        raise ValueError('boom')
except ValueError:
    pass
assert writes == [1] and ',before_error' in csv_path.read_text(encoding='utf-8')

assert not hasattr(bpy.types, 'SUB_PT_swing_io'), 'the sidebar Swing panel is gone'
drawn = []
recorder = type('R', (), {'row': lambda self, **_k: self,
                          'operator': lambda self, idname, **_k: drawn.append(idname)})()
ui.SUB_PT_swing_data_master.draw(type('P', (), {'layout': recorder})(), bpy.context)
assert drawn == ['sub.swing_import', 'sub.swing_export'], drawn
print('SWING_IMPORT_LABELS_OK')
