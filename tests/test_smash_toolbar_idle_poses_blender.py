"""Smash Toolbar idle pose list: added from the library, click to apply, bigger searchable popup."""
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

fixture = Path(__file__).with_name('test_addon_registration_blender.py')
exec(compile(fixture.read_text().split('floor = importlib.import_module')[0], str(fixture), 'exec'))
toolbar = importlib.import_module(MODULE + '.source.extras.smash_toolbar')
prefs_mod = importlib.import_module(MODULE + '.source.addon_preferences')

bpy.types.Scene.sub_test_toolbar = bpy.props.CollectionProperty(type=prefs_mod.SUB_PG_toolbar_button)
buttons = bpy.context.scene.sub_test_toolbar
toolbar.get_addon_preferences = lambda context=None: SimpleNamespace(toolbar_buttons=buttons)
scene = bpy.context.scene
ssp = scene.sub_scene_properties
wm = bpy.context.window_manager


class Layout:
    def __init__(self):
        self.calls, self.buttons, self.lists, self.props = [], [], [], []

    def operator(self, idname, text=None, icon=None, **kwargs):
        self.calls.append('operator')
        self.buttons.append((idname, text))
        return SimpleNamespace(index=0, action='', group='', idname='', props='')

    def prop(self, data, name, **kwargs):
        self.calls.append('prop')
        self.props.append(name)

    def template_list(self, *args, **kwargs):
        self.calls.append('template_list')
        self.lists.append(args)

    def __getattr__(self, name):
        def record(*args, **kwargs):
            self.calls.append(name)
            return self if name in {'row', 'column'} else SimpleNamespace(index=0)
        return record


ssp.idle_pose_list.clear()
for name in ('a00wait1', 'a02run', 'a05squatwait'):
    ssp.idle_pose_list.add().name = name

# The library list's right-click menu offers it.
menu = Layout()
toolbar.draw_button_context(SimpleNamespace(layout=menu), SimpleNamespace(
    button_operator=None, button_prop=ssp.bl_rna.properties['idle_pose_list_index'], button_pointer=ssp,
    scene=scene))
assert menu.buttons == [('sub.toolbar_add', 'Add Idle Pose List to Smash Toolbar')], menu.buttons
assert bpy.ops.sub.toolbar_add(idname='sub.toolbar_apply_idle_pose', props='{}') == {'FINISHED'}
assert buttons[0].label == 'Idle Pose List'

# On the bar: the one-row list plus the arrow that opens the bigger list.
bar = Layout()
toolbar.draw_toolbar(bar, bpy.context)
assert any(args[3] == 'idle_pose_list' and args[5] == 'sub_toolbar_pose_index' for args in bar.lists), bar.lists
assert ('sub.toolbar_idle_pose_menu', '') in bar.buttons, bar.buttons
popup = Layout()
toolbar.SUB_PT_toolbar_poses.draw(SimpleNamespace(layout=popup), bpy.context)
assert any(args[3] == 'idle_pose_list' and args[5] == 'sub_toolbar_pose_popup_index' for args in popup.lists)
assert popup.calls.count('prop') >= 4, popup.calls  # three pose options + search
# Blender lines the popup up on the first highlighted button made: it must be the arrow,
# not a switched-on option toggle, or the popup opens off to the side.
ssp.idle_pose_include_trans = True
assert popup.props[0] == 'sub_toolbar_menu_open', popup.props

# Clicking a pose (in the strip or the popup) applies it through the library's own Apply.
rig = bpy.data.objects.new('Rig', bpy.data.armatures.new('Rig'))
scene.collection.objects.link(rig)
applied = []


def fake_apply(*args, **kwargs):
    applied.append(ssp.idle_pose_list[ssp.idle_pose_list_index].name)
    return {'FINISHED'}


real_sub = bpy.ops.sub


class FakeApply:
    def poll(self, *args):
        return True

    def __call__(self, *args, **kwargs):
        return fake_apply()


class SubProxy:
    def __getattr__(self, name):
        if name == 'apply_idle_pose_from_list':
            return FakeApply()
        return getattr(real_sub, name)


with patch.object(toolbar.bpy.ops, 'sub', SubProxy()):
    bpy.context.view_layer.objects.active = None
    assert toolbar.bpy.ops.sub.toolbar_apply_idle_pose(index=1) == {'CANCELLED'}
    bpy.context.view_layer.objects.active = rig
    assert toolbar.bpy.ops.sub.toolbar_apply_idle_pose(index=1) == {'FINISHED'}
    assert toolbar.bpy.ops.sub.toolbar_apply_idle_pose(index=7) == {'CANCELLED'}
    wm.sub_toolbar_pose_index = 2
    wm.sub_toolbar_pose_popup_index = 0
assert applied == ['a02run', 'a05squatwait', 'a00wait1'], applied
assert wm.sub_toolbar_pose_popup_index == -1 and wm.sub_toolbar_pose_index == 0
tip = toolbar.SUB_OT_toolbar_apply_idle_pose.description(bpy.context, SimpleNamespace(index=2))
assert 'a05squatwait' in tip, tip

# Search filters the popup list; right-clicking the strip offers group/remove.
wm.sub_toolbar_pose_search = 'run'
flags, _order = toolbar.SUB_UL_toolbar_poses_expanded.filter_items(
    SimpleNamespace(bitflag_filter_item=1 << 30), bpy.context, ssp, 'idle_pose_list')
assert [bool(f & (1 << 30)) for f in flags] == [False, True, False], flags
wm.sub_toolbar_pose_search = ''
menu = Layout()
toolbar.draw_button_context(SimpleNamespace(layout=menu), SimpleNamespace(
    button_operator=None, button_prop=SimpleNamespace(identifier='sub_toolbar_pose_index'), button_pointer=wm,
    scene=scene))
assert ('sub.toolbar_edit', 'Remove from Smash Toolbar') in menu.buttons and 'menu' in menu.calls, menu.buttons
buttons.clear()
bpy.data.objects.remove(rig)
print('SMASH_TOOLBAR_IDLE_POSES_OK')
