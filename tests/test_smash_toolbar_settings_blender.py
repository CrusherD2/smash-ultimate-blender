"""Smash Toolbar settings: toggles, sliders and dropdowns from panels, live on the bar."""
from pathlib import Path
from types import SimpleNamespace

fixture = Path(__file__).with_name('test_addon_registration_blender.py')
exec(compile(fixture.read_text().split('floor = importlib.import_module')[0], str(fixture), 'exec'))
toolbar = importlib.import_module(MODULE + '.source.extras.smash_toolbar')
prefs_mod = importlib.import_module(MODULE + '.source.addon_preferences')

bpy.types.Scene.sub_test_toolbar = bpy.props.CollectionProperty(type=prefs_mod.SUB_PG_toolbar_button)
buttons = bpy.context.scene.sub_test_toolbar
toolbar.get_addon_preferences = lambda context=None: SimpleNamespace(toolbar_buttons=buttons)
scene = bpy.context.scene
ssp = scene.sub_scene_properties


class Layout:
    def __init__(self):
        self.calls, self.props, self.buttons = [], [], []
        self.enabled = True

    def prop(self, data, name, **kwargs):
        self.calls.append('prop')
        self.props.append((data, name, kwargs))

    def operator(self, idname, text=None, icon=None, **kwargs):
        self.calls.append('operator')
        self.buttons.append((idname, text))
        return SimpleNamespace(index=0, action='', group='', owner='', base='', name='')

    def __getattr__(self, name):
        def record(*args, **kwargs):
            self.calls.append(name)
            return self if name == 'row' else SimpleNamespace(index=0)
        return record


def rna(data, name):
    return data.bl_rna.properties[name]


# Scene settings (Eye Look's Invert X) are found again from the scene.
source = toolbar.setting_source(bpy.context, ssp, rna(ssp, 'eye_look_invert_x'))
assert source == ('SCENE', 'sub_scene_properties', 'eye_look_invert_x'), source
assert toolbar.setting_source(bpy.context, scene.render, rna(scene.render, 'fps')) == ('SCENE', 'render', 'fps')

# Object and armature-data settings follow the selected object.
arm = bpy.data.objects.new('Rig', bpy.data.armatures.new('Rig'))
scene.collection.objects.link(arm)
bpy.context.view_layer.objects.active = arm
assert toolbar.setting_source(bpy.context, arm, rna(arm, 'show_in_front')) == ('OBJECT', '', 'show_in_front')
assert toolbar.setting_source(bpy.context, arm.data, rna(arm.data, 'show_axes')) == ('OBJECT_DATA', '', 'show_axes')
other = bpy.data.objects.new('Other', None)
assert toolbar.setting_source(bpy.context, other, rna(other, 'hide_select')) is None  # not selected: unreachable
assert toolbar.setting_source(bpy.context, ssp, rna(scene, 'camera')) is None  # pointers aren't settings

# Right-click menu offers it for panel settings, and not twice.
menu = Layout()
toolbar.draw_button_context(SimpleNamespace(layout=menu), SimpleNamespace(
    button_operator=None, button_prop=rna(ssp, 'eye_look_invert_x'), button_pointer=ssp, scene=scene,
    window_manager=bpy.context.window_manager, active_object=arm, space_data=None))
assert menu.buttons == [('sub.toolbar_add_setting', None)], menu.buttons
for owner, base, name in (source, ('SCENE', 'render', 'fps'), ('OBJECT_DATA', '', 'show_axes')):
    assert bpy.ops.sub.toolbar_add_setting(owner=owner, base=base, name=name) == {'FINISHED'}
assert bpy.ops.sub.toolbar_add_setting(owner=source[0], base=source[1], name=source[2]) == {'CANCELLED'}
assert bpy.ops.sub.toolbar_add_setting(owner='SCENE', base='nope', name='x') == {'CANCELLED'}
assert [b.label for b in buttons] == ['Invert X', 'FPS', 'Display Axes'], [b.label for b in buttons]
menu = Layout()
toolbar.draw_button_context(SimpleNamespace(layout=menu), SimpleNamespace(
    button_operator=None, button_prop=rna(ssp, 'eye_look_invert_x'), button_pointer=ssp, scene=scene,
    window_manager=bpy.context.window_manager, active_object=arm, space_data=None))
assert menu.buttons == [], menu.buttons

# On the bar they are the live settings: a toggle button, a number field and an armature toggle.
bar = Layout()
toolbar.draw_toolbar(bar, bpy.context)
shown = [(data, name, kwargs.get('text'), kwargs.get('toggle')) for data, name, kwargs in bar.props]
assert shown == [(ssp, 'eye_look_invert_x', 'Invert X', True), (scene.render, 'fps', 'FPS', -1),
                 (arm.data, 'show_axes', 'Display Axes', True)], shown
ssp.eye_look_invert_x = True
assert toolbar.resolve_setting(bpy.context, buttons[0]) == (ssp, 'eye_look_invert_x')

# Icon mode shows just the icon; it still edits the same setting.
assert bpy.ops.sub.toolbar_icon(index=0, icon='ARROW_LEFTRIGHT') == {'FINISHED'}
bar = Layout()
toolbar.draw_toolbar(bar, bpy.context)
data, name, kwargs = bar.props[0]
assert (data, name, kwargs['text'], kwargs['icon'], kwargs['icon_only']) == (ssp, 'eye_look_invert_x', '', 'ARROW_LEFTRIGHT', True)

# With no armature selected the armature setting is greyed out instead of failing.
bpy.context.view_layer.objects.active = None
bar = Layout()
toolbar.draw_toolbar(bar, bpy.context)
assert [name for _data, name, _kw in bar.props] == ['eye_look_invert_x', 'fps'], bar.props
assert toolbar.resolve_setting(bpy.context, buttons[2]) is None

# Right-clicking a setting on the toolbar shows the toolbar options, including groups.
bpy.context.view_layer.objects.active = arm
menu = Layout()
toolbar.draw_button_context(SimpleNamespace(layout=menu), SimpleNamespace(
    button_operator=None, button_prop=rna(scene.render, 'fps'), button_pointer=scene.render, scene=scene,
    window_manager=bpy.context.window_manager, active_object=arm,
    space_data=SimpleNamespace(tree_type=toolbar.TREE_ID)))
assert ('sub.toolbar_edit', 'Remove from Smash Toolbar') in menu.buttons and 'menu' in menu.calls, menu.buttons
assert bpy.ops.sub.toolbar_group_new(index=1, name='Eye Look') == {'FINISHED'}
assert buttons[2].group == 'group1' and buttons[2].prop_name == 'fps'
buttons.clear()
bpy.data.objects.remove(arm)
print('SMASH_TOOLBAR_SETTINGS_OK')
