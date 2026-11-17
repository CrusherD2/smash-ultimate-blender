"""Smash Toolbar groups: create, fill, open to the right, reorder, recolor and ungroup."""
from pathlib import Path
from types import SimpleNamespace

fixture = Path(__file__).with_name('test_addon_registration_blender.py')
exec(compile(fixture.read_text().split('floor = importlib.import_module')[0], str(fixture), 'exec'))
toolbar = importlib.import_module(MODULE + '.source.extras.smash_toolbar')
prefs_mod = importlib.import_module(MODULE + '.source.addon_preferences')

# This loader doesn't create add-on preferences; use the same collection type on the scene.
bpy.types.Scene.sub_test_toolbar = bpy.props.CollectionProperty(type=prefs_mod.SUB_PG_toolbar_button)
buttons = bpy.context.scene.sub_test_toolbar
toolbar.get_addon_preferences = lambda context=None: SimpleNamespace(toolbar_buttons=buttons)


class Layout:
    def __init__(self):
        self.calls, self.buttons = [], []

    def operator(self, idname, text=None, icon=None, **kwargs):
        self.calls.append('operator')
        self.buttons.append((idname, text, icon))
        return SimpleNamespace(index=0, action='', group='')

    def __getattr__(self, name):
        def record(*args, **kwargs):
            self.calls.append(name)
            return self if name == 'row' else SimpleNamespace(index=0)
        return record


def labels():
    return [entry.label for entry in buttons]


def bar():
    layout = Layout()
    toolbar.draw_toolbar(layout, bpy.context)
    return [(idname.split('.')[-1], text) for idname, text, _icon in layout.buttons]


for fps in (12, 24, 30, 60):
    assert bpy.ops.sub.toolbar_add(idname='sub.set_fps_preset', props=f'{{"fps": {fps}}}') == {'FINISHED'}
for entry, fps in zip(buttons, (12, 24, 30, 60)):
    entry.label = f'{fps} FPS'

# A new group takes the button's spot on the bar and starts open.
assert bpy.ops.sub.toolbar_group_new(index=1, name='Eye Look') == {'FINISHED'}
assert labels() == ['12 FPS', 'Eye Look', '24 FPS', '30 FPS', '60 FPS'], labels()
group = buttons[1]
assert group.is_group and group.uid == 'group1' and group.expanded
assert buttons[2].group == 'group1'
assert bpy.ops.sub.toolbar_group_new(index=1) == {'CANCELLED'}  # groups don't nest
assert bpy.ops.sub.toolbar_group_assign(index=4, group='group1') == {'FINISHED'}
assert bpy.ops.sub.toolbar_group_assign(index=3, group='missing') == {'CANCELLED'}

# Open: the group's buttons follow it, joined; closed: only the group shows.
assert bar() == [('toolbar_run', '12 FPS'), ('toolbar_group_toggle', 'Eye Look'),
                 ('toolbar_run', '24 FPS'), ('toolbar_run', '60 FPS'), ('toolbar_run', '30 FPS')], bar()
# The group button is colored by an overlay drawn where the layout put it.
tints = next(iter(toolbar._gate_state['tints'].values())) if toolbar._gate_state.get('tints') else None
layout = Layout()
toolbar.draw_toolbar(layout, SimpleNamespace(**{k: getattr(bpy.context, k) for k in ('preferences', 'scene', 'window_manager')},
                                             area=SimpleNamespace(as_pointer=lambda: 7)))
tint = toolbar._gate_state['tints'][7][0]
ctx = bpy.context
w12 = toolbar._button_width(ctx, '12 FPS', False)
sep = int(6.0 * toolbar._metrics(ctx)[0] * 0.6)
assert tint['x'] == toolbar._bar_start(ctx) + w12 + sep, tint
assert tint['width'] == toolbar._button_width(ctx, 'Eye Look', True)
assert tint['label'] == 'Eye Look' and tint['open'] and tint['joined'] and not tint['icon_mode']
assert tuple(round(c, 2) for c in tint['color']) == (0.27, 0.52, 0.92), tint
tip = toolbar.SUB_OT_toolbar_group_toggle.description(bpy.context, SimpleNamespace(index=1))
assert tip == 'Eye Look' + chr(10) + 'Hide its 2 buttons', tip
assert bpy.ops.sub.toolbar_group_toggle(index=1) == {'FINISHED'}
assert not group.expanded
assert bar() == [('toolbar_run', '12 FPS'), ('toolbar_group_toggle', 'Eye Look'), ('toolbar_run', '30 FPS')], bar()
assert bpy.ops.sub.toolbar_group_toggle(index=0) == {'CANCELLED'}
group.expanded = True

# Icon mode shows the chosen icon after the color mark, with the name in the tooltip.
assert bpy.ops.sub.toolbar_icon(index=1, icon='HIDE_OFF') == {'FINISHED'}
layout = Layout()
toolbar.draw_toolbar(layout, bpy.context)
assert ('sub.toolbar_group_toggle', '', 'HIDE_OFF') in layout.buttons, layout.buttons
group.show_icon = False

# Reordering stays within a level: members swap inside the group, groups move on the bar.
assert bpy.ops.sub.toolbar_edit(index=4, action='UP') == {'FINISHED'}
assert labels() == ['12 FPS', 'Eye Look', '60 FPS', '24 FPS', '30 FPS'], labels()
assert bpy.ops.sub.toolbar_edit(index=2, action='UP') == {'CANCELLED'}
assert bpy.ops.sub.toolbar_edit(index=1, action='DOWN') == {'FINISHED'}
assert [b.label for b in buttons if not b.group] == ['12 FPS', '30 FPS', 'Eye Look'], labels()
assert bar()[1] == ('toolbar_run', '30 FPS'), bar()

# Right-click menus: buttons offer groups, groups offer name, color and ungroup.
member = next(i for i, b in enumerate(buttons) if b.label == '24 FPS')
menu = Layout()
toolbar.draw_toolbar_button_context(menu, bpy.context, member)
assert 'menu' in menu.calls and ('sub.toolbar_group_assign', 'Remove from Group', 'FILE_PARENT') in menu.buttons
free = next(i for i, b in enumerate(buttons) if b.label == '12 FPS')
groups_menu = Layout()
toolbar.SUB_MT_toolbar_groups.draw(SimpleNamespace(layout=groups_menu),
                                   SimpleNamespace(sub_toolbar_entry=buttons[free]))
assert [text for _id, text, _icon in groups_menu.buttons] == ['Eye Look', 'New Group...'], groups_menu.buttons
toggle_props = bpy.context.window_manager.operator_properties_last('sub.toolbar_group_toggle')
toggle_props.index = next(i for i, b in enumerate(buttons) if b.is_group)
group_menu = Layout()
toolbar.draw_button_context(SimpleNamespace(layout=group_menu),
                            SimpleNamespace(button_operator=toggle_props, button_prop=None))
assert group_menu.calls.count('prop') == 2, group_menu.calls
assert any(text == 'Ungroup (keep its buttons)' for _id, text, _icon in group_menu.buttons)

# A second group gets the next color; moving a button between groups keeps both.
assert bpy.ops.sub.toolbar_group_new(index=free, name='Speed') == {'FINISHED'}
speed = next(b for b in buttons if b.label == 'Speed')
assert speed.uid == 'group2' and tuple(round(c, 2) for c in speed.color) == (0.27, 0.52, 0.92)
icon = toolbar._swatch_icon(speed.color)
assert icon == toolbar._swatch_icon((0.27, 0.52, 0.92))
assert 'swatch_0.270_0.520_0.920' in toolbar._gate_state['previews']

# Ungrouping keeps the buttons and puts them back on the bar.
eye = next(i for i, b in enumerate(buttons) if b.label == 'Eye Look')
assert bpy.ops.sub.toolbar_edit(index=eye, action='REMOVE') == {'FINISHED'}
assert 'Eye Look' not in labels()
assert {b.label for b in buttons if not b.group and not b.is_group} >= {'24 FPS', '60 FPS', '30 FPS'}
assert all(b.group in ('', 'group2') for b in buttons)
buttons.clear()
print('SMASH_TOOLBAR_GROUPS_OK')
