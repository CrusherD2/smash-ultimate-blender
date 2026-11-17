"""A click on an Animation Importer row selects that animation; list refreshes don't."""
from pathlib import Path
from types import SimpleNamespace

fixture = Path(__file__).with_name('test_addon_registration_blender.py')
exec(compile(fixture.read_text().split('floor = importlib.import_module')[0], str(fixture), 'exec'))
anim = importlib.import_module(MODULE + '.source.anim.import_anim')
ssp = bpy.context.scene.sub_scene_properties

for state in (ssp, ssp.visibility_animation_browser):
    state.animation_import_files.clear()
    for name in ('a00', 'a01', 'a02', 'a03'):
        item = state.animation_import_files.add()
        item.name, item.path = name, name
    anim.set_animation_list_index(state, 0)
    state.animation_import_files[3].selected = True
    # Row click (Blender sets the index through the list row).
    state.animation_import_files_index = 2
    assert [i.selected for i in state.animation_import_files] == [False, False, True, False]
    assert state.animation_import_selection_anchor == 'a02'
    # Code that only moves the active row leaves the checkmarks alone.
    anim.set_animation_list_index(state, 1)
    assert state.animation_import_files_index == 1
    assert [i.selected for i in state.animation_import_files] == [False, False, True, False]

# The selection operator still works and doesn't trigger the row-click reset.
state = ssp
bpy.ops.sub.toggle_animation_import_selection(index=0, toggle=True)
assert [i.selected for i in state.animation_import_files] == [True, False, True, False]
assert state.animation_import_files_index == 0

# Refreshing the folder resets to the first row without selecting it.
folder = Path(bpy.app.tempdir or '.') / 'sub_row_click_anims'
folder.mkdir(exist_ok=True)
for name in ('b00', 'b01'):
    (folder / f'{name}.nuanmb').write_bytes(b'')
assert anim.fill_animation_import_list(ssp, str(folder)) == 2
assert ssp.animation_import_files_index == 0
assert not any(i.selected for i in ssp.animation_import_files)

# Names are plain text, so clicks reach the list row.
class Layout:
    def __init__(self):
        self.calls = []

    def __getattr__(self, name):
        def record(*args, **kwargs):
            self.calls.append(name)
        return record


row = Layout()
anim.SUB_UL_animation_import_list.draw_item(SimpleNamespace(
    layout_type='DEFAULT', list_id='', filter_name='', bitflag_filter_item=1 << 30, use_filter_invert=False,
    use_filter_sort_alpha=False, use_filter_sort_reverse=False), bpy.context, row, ssp,
                                            ssp.animation_import_files[0], 0, ssp, '', 0)
assert row.calls == ['prop', 'label'], row.calls
# The checkbox switches to its twin property only for the redraw after a scroll.
ui_list = SimpleNamespace(list_id='', filter_name='', bitflag_filter_item=1 << 30,
                          use_filter_invert=False, use_filter_sort_alpha=False, use_filter_sort_reverse=False)
anim._list_draw_passes.clear()
for _ in range(10):
    item = ssp.animation_import_files.add()
    item.name = item.path = f'z{_:02}'
pick = lambda first: [anim._checkbox_property(ui_list, ssp, i) for i in range(first, first + 5)]
first = pick(0)
assert first == ['selected'] * 5, first
assert pick(0) == first
scrolled = pick(2)
assert scrolled == ['selected_twin'] * 5, scrolled
assert pick(2) == scrolled
item = ssp.animation_import_files[0]
item.selected_twin = True
assert item.selected and item.selected_twin
item.selected = False
assert not item.selected_twin
print('ANIMATION_LIST_ROW_CLICK_OK')
