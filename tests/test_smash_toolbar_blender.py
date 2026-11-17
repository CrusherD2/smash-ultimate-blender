"""Smash Toolbar: add, run, reorder and remove favorite buttons; header hook is reversible."""
import json
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
buttons.clear()

assert bpy.types.NodeTree.bl_rna_get_subclass_py(toolbar.TREE_ID) is not None
for op_name in dir(bpy.ops.sub):
    rna = getattr(bpy.ops.sub, op_name).get_rna_type()
    assert toolbar.operator_idname(rna.identifier) == f'sub.{op_name}', rna.identifier
assert toolbar.operator_idname('sub.set_fps_preset') == 'sub.set_fps_preset'

# Settings the button set are kept and replayed.
bpy.ops.sub.set_fps_preset(fps=24)
last = bpy.context.window_manager.operator_properties_last('sub.set_fps_preset')
# Panel buttons assign their settings, which marks them as set (like row.operator(...).fps = 24).
assert toolbar.serialize_properties(last) == '{}'
last.fps = 24
props = toolbar.serialize_properties(last)
assert json.loads(props) == {'fps': 24}, props
assert bpy.ops.sub.toolbar_add(idname='sub.set_fps_preset', props=props) == {'FINISHED'}
assert bpy.ops.sub.toolbar_add(idname='sub.set_fps_preset', props=props) == {'CANCELLED'}
assert bpy.ops.sub.toolbar_add(idname='sub.set_fps_preset', props='{"fps": 12}') == {'FINISHED'}
assert bpy.ops.sub.toolbar_add(idname='sub.not_a_real_tool') == {'CANCELLED'}
assert [b.label for b in buttons] == ['Set Timeline FPS'] * 2
buttons[1].label = 'Slow'

class Layout:
    def __init__(self):
        self.calls, self.labels, self.buttons = [], [], []

    def operator(self, *args, text=None, icon=None, **kwargs):
        self.calls.append('operator')
        self.labels.append(text)
        self.buttons.append((text, icon))
        return SimpleNamespace(index=0, action='')

    def __getattr__(self, name):
        def record(*args, **kwargs):
            self.calls.append(name)
            return self if name == 'row' else SimpleNamespace(index=0)
        return record


scene = bpy.context.scene
scene.render.fps = 60
assert bpy.ops.sub.toolbar_run(index=0) == {'FINISHED'}
assert scene.render.fps == 24
assert bpy.ops.sub.toolbar_run(index=1) == {'FINISHED'}
assert scene.render.fps == 12
assert bpy.ops.sub.toolbar_run(index=5) == {'CANCELLED'}

assert bpy.ops.sub.toolbar_edit(index=1, action='UP') == {'FINISHED'}
assert [b.label for b in buttons] == ['Slow', 'Set Timeline FPS']
assert bpy.ops.sub.toolbar_edit(index=0, action='UP') == {'CANCELLED'}
assert bpy.ops.sub.toolbar_edit(index=0, action='REMOVE') == {'FINISHED'}
assert [b.label for b in buttons] == ['Set Timeline FPS']

# Buttons are added as text; the right-click option switches one to an icon and back.
entry = buttons[0]
assert not entry.show_icon and entry.icon == ''
assert bpy.ops.sub.toolbar_icon(index=0, icon='ARMATURE_DATA') == {'FINISHED'}
assert entry.show_icon and entry.icon == 'ARMATURE_DATA'
tip = toolbar.SUB_OT_toolbar_run.description(bpy.context, SimpleNamespace(index=0))
assert tip.startswith('Set Timeline FPS' + chr(10)), tip
assert bpy.ops.sub.toolbar_run(index=0) == {'FINISHED'}
assert bpy.ops.sub.toolbar_icon(index=3, icon='ARMATURE_DATA') == {'CANCELLED'}
for layout_index, expect in ((0, ['Display as Text', 'Change Icon...']), ):
    menu = Layout()
    toolbar.draw_toolbar_button_context(menu, bpy.context, layout_index)
    assert menu.labels[:2] == expect, menu.labels
assert bpy.ops.sub.toolbar_edit(index=0, action='TEXT') == {'FINISHED'}
assert not entry.show_icon and entry.icon == 'ARMATURE_DATA'
assert not toolbar.SUB_OT_toolbar_run.description(bpy.context, SimpleNamespace(index=0)).startswith('Set Timeline FPS')
menu = Layout()
toolbar.draw_toolbar_button_context(menu, bpy.context, 0)
assert menu.labels[0] == 'Display as Icon...', menu.labels

# Toolbar bar draws icon-only buttons with no text.
entry.show_icon = True
bar = Layout()
toolbar.draw_toolbar(bar, bpy.context)
assert ('', 'ARMATURE_DATA') in bar.buttons, bar.buttons
entry.show_icon = False
bar = Layout()
toolbar.draw_toolbar(bar, bpy.context)
assert ('Set Timeline FPS', None) in bar.buttons, bar.buttons

# Animation list: added from the Animation Importer list's right-click menu; clicking imports.
from unittest.mock import patch
anim_ops = importlib.import_module(MODULE + '.source.anim.import_anim')
ssp = bpy.context.scene.sub_scene_properties
for name in ('a00wait1', 'a02run', 'a04fall'):
    item = ssp.animation_import_files.add()
    item.name, item.path = name, f'C:/motion/{name}.nuanmb'
index_prop = SimpleNamespace(identifier='animation_import_files_index')
menu = Layout()
toolbar.draw_button_context(SimpleNamespace(layout=menu), SimpleNamespace(
    button_operator=None, button_prop=index_prop, button_pointer=ssp, scene=bpy.context.scene))
assert menu.labels == ['Add Animation List to Smash Toolbar'], menu.labels
menu = Layout()
toolbar.draw_button_context(SimpleNamespace(layout=menu), SimpleNamespace(
    button_operator=None, button_prop=index_prop, button_pointer=ssp.visibility_animation_browser, scene=bpy.context.scene))
assert menu.labels == [], menu.labels
assert bpy.ops.sub.toolbar_add(idname='sub.toolbar_import_animation', props='{}') == {'FINISHED'}
anim_index = len(buttons) - 1
assert buttons[anim_index].label == 'Animation List'
bar = Layout()
toolbar.draw_toolbar(bar, bpy.context)
assert 'template_list' in bar.calls and bar.calls.count('popover') == 1, bar.calls  # the gear menu
assert ('', 'DOWNARROW_HLT') in bar.buttons, bar.buttons
assert toolbar.SUB_PT_toolbar_animations.bl_ui_units_x == toolbar.ANIMATION_LIST_UNITS + 1
expanded = Layout()
toolbar.SUB_PT_toolbar_animations.draw(SimpleNamespace(layout=expanded), bpy.context)
assert 'template_list' in expanded.calls and 'menu' not in expanded.calls, expanded.calls
# With more than one animation folder loaded, the popup offers the folder switcher on top.
ssp.animation_import_folder_path = 'C:/motion/body/c00'
for path in ('C:/motion/body/c00', 'C:/motion/body/c88'):
    ssp.animation_import_folders.add().path = path
expanded = Layout()
toolbar.SUB_PT_toolbar_animations.draw(SimpleNamespace(layout=expanded), bpy.context)
assert expanded.calls.index('menu') < expanded.calls.index('template_list'), expanded.calls
ssp.animation_import_folders.clear()
ssp.animation_import_folder_path = ''
row = Layout()
toolbar.SUB_UL_toolbar_animations.draw_item(None, bpy.context, row, ssp, ssp.animation_import_files[0], 0, ssp, '', 0)
assert row.calls == ['label'], row.calls

rig = bpy.data.objects.new('AnimRig', bpy.data.armatures.new('AnimRig'))
bpy.context.scene.collection.objects.link(rig)
calls = []
ssp.animation_import_files[2].selected = True
wm = bpy.context.window_manager
with patch.object(anim_ops, 'import_animation_paths', side_effect=lambda c, o, paths: calls.append(paths) or (1, 0)):
    bpy.context.view_layer.objects.active = None
    assert bpy.ops.sub.toolbar_import_animation(index=1) == {'CANCELLED'}
    bpy.context.view_layer.objects.active = rig
    assert bpy.ops.sub.toolbar_import_animation(index=1) == {'FINISHED'}
    assert bpy.ops.sub.toolbar_import_animation(index=9) == {'CANCELLED'}
    # Clicking a row in the toolbar list (it sets the list index) imports that row,
    # including the same row again, without touching the importer's checkmarks.
    wm.sub_toolbar_animation_index = 0
    wm.sub_toolbar_animation_index = 0
    # Picking in the big popup list imports through the bar list and clears the popup's highlight.
    wm.sub_toolbar_popup_index = 2
    assert wm.sub_toolbar_popup_index == -1 and wm.sub_toolbar_animation_index == 2
calls = calls[:3] + [c for c in calls[3:]]
assert calls == [['C:/motion/a02run.nuanmb'], ['C:/motion/a00wait1.nuanmb'], ['C:/motion/a00wait1.nuanmb'],
                 ['C:/motion/a04fall.nuanmb']], calls
# Search filters the popup list by name.
wm.sub_toolbar_animation_search = 'run'
flags, order = toolbar.SUB_UL_toolbar_animations_expanded.filter_items(
    SimpleNamespace(bitflag_filter_item=1 << 30), bpy.context, ssp, 'animation_import_files')
assert [bool(f & (1 << 30)) for f in flags] == [False, True, False], flags
wm.sub_toolbar_animation_search = ''
assert wm.sub_toolbar_menu_open
wm.sub_toolbar_menu_open = False
assert wm.sub_toolbar_menu_open
assert [i.selected for i in ssp.animation_import_files] == [False, False, True]
tip = toolbar.SUB_OT_toolbar_import_animation.description(bpy.context, SimpleNamespace(index=2))
assert 'a04fall' in tip, tip

menu = Layout()
row_prop = SimpleNamespace(identifier='sub_toolbar_animation_index')
toolbar.draw_button_context(SimpleNamespace(layout=menu), SimpleNamespace(button_operator=None, button_prop=row_prop, button_pointer=None, scene=bpy.context.scene))
assert menu.labels == ['Remove from Smash Toolbar'], menu.labels
assert bpy.ops.sub.toolbar_edit(index=anim_index, action='REMOVE') == {'FINISHED'}
bpy.data.objects.remove(rig)

# A tool that disappeared (e.g. its add-on was removed) reports instead of erroring.
buttons[0].idname = 'sub.not_a_real_tool'
assert bpy.ops.sub.toolbar_run(index=0) == {'CANCELLED'}
buttons.clear()


def header_funcs():
    return bpy.types.NODE_HT_header.draw._draw_funcs


def gate():
    return next(f for f in header_funcs() if f.__qualname__.endswith('gated'))


for tree_type, expect_toolbar in ((toolbar.TREE_ID, True), ('ShaderNodeTree', False)):
    layout = Layout()
    drawn = []
    original = gate().__closure__[0].cell_contents
    gate().__closure__[0].cell_contents = lambda self, context: drawn.append(True)
    try:
        gate()(SimpleNamespace(layout=layout), SimpleNamespace(
            space_data=SimpleNamespace(tree_type=tree_type), preferences=bpy.context.preferences))
    finally:
        gate().__closure__[0].cell_contents = original
    assert ('template_header' in layout.calls) == expect_toolbar
    assert bool(drawn) != expect_toolbar

menu_funcs = bpy.types.WM_MT_button_context.draw._draw_funcs
assert toolbar.draw_button_context in menu_funcs
toolbar.unregister()
assert not hasattr(bpy.types, 'WM_MT_button_context')
assert not any(f.__qualname__.endswith('gated') for f in header_funcs())
assert any(f.__qualname__ == 'NODE_HT_header.draw' for f in header_funcs())
toolbar.register()
assert toolbar.draw_button_context in bpy.types.WM_MT_button_context.draw._draw_funcs
assert sum(f.__qualname__.endswith('gated') for f in header_funcs()) == 1
print('SMASH_TOOLBAR_OK')
