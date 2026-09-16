"""Blender integration: registration, help coverage, export commits and failures.

Run with tests/run_blender_test.py to isolate Blender's extension cache too.
"""
from pathlib import Path
from types import SimpleNamespace
import importlib
import tempfile
import copy

fixture = Path(__file__).with_name('test_addon_registration_blender.py')
exec(compile(fixture.read_text().split('addon_utils.disable(MODULE')[0], str(fixture), 'exec'))

motion = importlib.import_module(MODULE + '.source.anim.motion_list')
export = importlib.import_module(MODULE + '.source.anim.export_anim')
yaml = importlib.import_module(MODULE + '.dependencies.yaml')
help_ui = importlib.import_module(MODULE + '.source.ui_help')
retarget = importlib.import_module(MODULE + '.source.retargeting')

for identifier in help_ui.RETIRED_PANEL_IDS:
    assert bpy.types.Panel.bl_rna_get_subclass_py(identifier) is None, identifier
motion_panel = bpy.types.Panel.bl_rna_get_subclass_py('SUB_PT_motion_list')
assert motion_panel.bl_parent_id == 'SUB_PT_sub_smush_anim_data_main', motion_panel.bl_parent_id
assert motion_panel.bl_space_type == 'PROPERTIES' and motion_panel.bl_context == 'data'

operators = set()
panels = set()
for module_name, module in list(sys.modules.items()):
    if not module_name.startswith(MODULE + '.') or module is None or 'backup' in module_name:
        continue
    for cls in list(vars(module).values()):
        if not isinstance(cls, type) or not cls.__module__.startswith(MODULE + '.'):
            continue
        if issubclass(cls, bpy.types.Operator) and getattr(cls, 'is_registered', False):
            operators.add(cls)
        if issubclass(cls, bpy.types.Panel) and getattr(cls, 'is_registered', False):
            panels.add(cls)
missing = []
for cls in operators:
    namespace, name = cls.bl_idname.split('.')
    description = getattr(getattr(bpy.ops, namespace), name).get_rna_type().description
    if not description or description in ('Undocumented operator', 'Tooltip'):
        missing.append(cls.__name__)
assert not missing, missing

class Layout:
    """Check draws against real RNA while recording controls and help URLs."""
    def __init__(self):
        self.buttons = []
        self.sections = []
        self.searches = []
    def panel(self, identifier, **kwargs):
        self.sections.append(identifier)
        return self, self
    def row(self, **kwargs): return self
    def column(self, **kwargs): return self
    def box(self): return self
    def grid_flow(self, **kwargs): return self
    def split(self, **kwargs): return self
    def label(self, **kwargs): pass
    def separator(self): pass
    def menu(self, *args, **kwargs): pass
    def prop(self, data, name, **kwargs):
        assert hasattr(data, name), (type(data), name)
    def prop_search(self, data, name, search_data, search_name, **kwargs):
        assert hasattr(data, name), (type(data), name)
        assert hasattr(search_data, search_name)
        self.searches.append(name)
    def template_list(self, *args, **kwargs): pass
    def operator(self, name, **kwargs):
        op = SimpleNamespace(name=name)
        self.buttons.append(op)
        return op

for cls in panels:
    if '.source.' not in cls.__module__:
        continue
    assert hasattr(cls, 'draw_header_preset'), cls.__name__
    # Construct a lightweight instance that retains the actual class identity.
    proxy = object.__new__(type('HelpProxy', (), {'__module__': cls.__module__}))
    proxy.__class__.__name__ = cls.__name__
    path = help_ui.panel_doc_path(proxy)
    file, _, anchor = path.partition('#')
    assert (ROOT/file).is_file(), (cls.__name__, path)
    if anchor:
        import re
        headings = [line.lstrip('# ').strip() for line in (ROOT/file).read_text(encoding='utf-8').splitlines() if line.startswith('#')]
        anchors = [re.sub(r'[^\w\- ]', '', heading.lower()).replace(' ', '-') for heading in headings]
        assert anchor in anchors, (cls.__name__, path)

layout = Layout()
retarget.SUB_PT_retargeting_main.draw(SimpleNamespace(layout=layout), bpy.context)
assert any(button.name == 'object.ultimate_bind_armatures' for button in layout.buttons)
bpy.ops.object.armature_add()
Path(retarget_presets.get_retarget_dir()).mkdir(parents=True, exist_ok=True)
bpy.context.object.data.expykit_retarget.deform_preset = '--'
mapping_layout = Layout()
retarget.SUB_PT_retargeting_main.draw(SimpleNamespace(layout=mapping_layout), bpy.context)
assert mapping_layout.sections == ['sub_retarget_mapping_' + name for name in
    ('custom', 'core', 'arms', 'legs', 'fingers', 'root')]
assert {'hips', 'arm', 'leg', 'a', 'root'} <= set(mapping_layout.searches)
model_layout = Layout()
model_ui = importlib.import_module(MODULE + '.source.extras.misc_panel')
model_ui.SUB_PT_model_tools.draw(SimpleNamespace(layout=model_layout), bpy.context)
assert 'sub_model_exo_skel' in model_layout.sections
assert any(button.name == 'sub.add_single_exo_constraint' for button in model_layout.buttons)
# Reordering cannot detach controls that are not registered Panel classes.
order.apply_order(list(reversed(order.default_order())))
for identifier in help_ui.RETIRED_PANEL_IDS:
    assert bpy.types.Panel.bl_rna_get_subclass_py(identifier) is None, identifier
# Saved presets that showed only a retired panel keep its parent accessible.
saved_presets = presets.serialize_presets(bpy.context.scene)
presets.apply_presets_payload(bpy.context.scene, {'presets': [{'name': 'Legacy', 'panels': [
    {'panel_id': 'SUB_PT_ultimate_exo_skel', 'enabled': True},
    {'panel_id': 'SUB_PT_model_tools', 'enabled': False},
    {'panel_id': 'ULTIMATE_PT_retarget_fingers', 'enabled': True},
]}]})
assert presets.panel_allowed(bpy.context, 'SUB_PT_model_tools')
assert presets.panel_allowed(bpy.context, 'SUB_PT_retargeting_main')
presets.apply_presets_payload(bpy.context.scene, saved_presets)
settings = bpy.context.scene.sub_motion_list
for removed in ('converter', 'key', 'template', 'cancel_mode', 'cancel',
                'override_blend', 'blend', 'override_flags', 'flag_turn'):
    assert not hasattr(settings, removed), removed
for kept in ('enabled', 'filepath', 'override_path', 'status'):
    assert hasattr(settings, kept), kept

probe_action = bpy.data.actions.new('sub_motion_probe')
probe_action.use_fake_user = True  # Survive the .blend round trip below.
probe_action.sub_motion.blend_frames = 7
probe_action.sub_motion.flag_loop = True
assert probe_action.sub_motion.synced, 'editing a value must mark it synced'
assert not bpy.data.actions.new('sub_motion_untouched').sub_motion.synced

# The cancel frame lives on a pose marker, driven by its own operators.
ui = importlib.import_module(MODULE + '.source.anim.motion_list_ui')
marker_obj = bpy.context.object
assert marker_obj.type == 'ARMATURE', marker_obj.type
marker_action = bpy.data.actions.new('cancel_marker_probe')
if marker_obj.animation_data is None:
    marker_obj.animation_data_create()
marker_obj.animation_data.action = marker_action
assert ui.cancel_frame(marker_action) is None
bpy.context.scene.frame_set(12)
assert bpy.ops.sub.set_cancel_frame_marker() == {'FINISHED'}
assert ui.cancel_frame(marker_action) == 12
assert len(marker_action.pose_markers) == 1
bpy.context.scene.frame_set(20)
assert bpy.ops.sub.set_cancel_frame_marker() == {'FINISHED'}
assert ui.cancel_frame(marker_action) == 20 and len(marker_action.pose_markers) == 1
assert bpy.ops.sub.clear_cancel_frame_marker() == {'FINISHED'}
assert ui.cancel_frame(marker_action) is None and len(marker_action.pose_markers) == 0
ui.SUB_PT_motion_list.draw(SimpleNamespace(layout=Layout()), bpy.context)

doctor = importlib.import_module(MODULE + '.source.doctor')
doctor.preflight = lambda *args: True
bpy.ops.object.camera_add()
obj = bpy.context.object
for frame in (1, 40):
    obj.location.x = frame / 10
    obj.keyframe_insert('location', frame=frame)
entry = dict(game_script='game_test', flags={name: False for name in motion.FLAGS},
    blend_frames=6, animations=[dict(name='test.nuanmb', unk=0)],
    scripts=['expression_test', 'sound_test', 'effect_test'],
    extra=dict(xlu_start=0, xlu_end=0, cancel_frame=0, no_stop_intp=False))
with tempfile.TemporaryDirectory() as folder:
    path = Path(folder)/'motion_list.yml'
    original = yaml.safe_dump(dict(motion_path='fighter/test/motion/body/c00', list={'test': entry})).encode()
    path.write_bytes(original)
    settings.override_path = False
    settings.filepath = ''
    bpy.context.scene.sub_scene_properties.last_anim_export_dir = folder
    settings.override_path = True
    assert Path(settings.filepath) == path.resolve(), settings.filepath
    settings.enabled = True
    export_action = obj.animation_data.action
    marker = export_action.pose_markers.new(ui.CANCEL_FRAME_MARKER)
    marker.frame = 39
    export_action.sub_motion.blend_frames = 3
    export_action.sub_motion.flag_loop = True
    output = str(Path(folder)/'test.nuanmb')
    result = bpy.ops.sub.anim_export(filepath=output, first_blender_frame=1, last_blender_frame=40)
    assert result == {'FINISHED'}
    read = motion.load(path)['list']['test']
    assert read['extra']['cancel_frame'] == 39
    assert read['blend_frames'] == 3 and read['flags']['loop']
    assert path.with_name(path.name+'.bak').read_bytes() == original
    assert Path(output).is_file()

    # Batch exports resolve each animation independently and retain earlier edits.
    doc = motion.load(path)
    doc['list']['second'] = copy.deepcopy(entry)
    doc['list']['second']['animations'][0]['name'] = 'second.nuanmb'
    motion.save(path, doc)
    first_action = obj.animation_data.action
    first_action.name = 'test.nuanmb'
    second_action = first_action.copy()
    second_action.name = 'second.nuanmb'
    # A copied action inherits both the cancel marker and the per-action values,
    # so the duplicate is retimed rather than given a second marker.
    second_marker = ui.cancel_marker(second_action)
    assert second_marker is not None and second_marker.frame == 39
    assert second_action.sub_motion.blend_frames == 3 and second_action.sub_motion.synced
    second_marker.frame = 24
    second_action.sub_motion.blend_frames = 9
    second_action.sub_motion.flag_move = True
    for curve in export.get_fcurves(second_action):
        curve.keyframe_points[-1].co.x = 25
        curve.update()
    items = bpy.context.scene.sub_scene_properties.action_export_list
    items.clear()
    for action in (first_action, second_action):
        item = items.add()
        item.name = action.name
        item.action = action
        item.export = True
    result = bpy.ops.sub.batch_export_anim(directory=folder, first_blender_frame=1, use_auto_range=True)
    assert result == {'FINISHED'}
    doc = motion.load(path)
    assert doc['list']['test']['extra']['cancel_frame'] == 39
    assert doc['list']['test']['blend_frames'] == 3
    assert doc['list']['second']['extra']['cancel_frame'] == 24
    assert doc['list']['second']['blend_frames'] == 9
    assert doc['list']['second']['flags']['move']
    assert path.with_name(path.name+'.bak').read_bytes() == original

    # Invalid metadata is rejected before overwriting the animation.
    before = Path(output).read_bytes()
    marker.frame = 300
    try:
        export.save_ssbh_anim_data(SimpleNamespace(final_frame_index=20), output,
                                   action=export_action)
    except ValueError:
        pass
    else:
        raise AssertionError('Out-of-range cancel frame accepted')
    assert Path(output).read_bytes() == before
    marker.frame = 39

    # An action nobody synced or edited keeps the entry's blend frames and flags.
    untouched = bpy.data.actions.new('untouched.nuanmb')
    doc = motion.load(path)
    doc['list']['untouched'] = copy.deepcopy(entry)
    doc['list']['untouched']['animations'][0]['name'] = 'untouched.nuanmb'
    doc['list']['untouched']['blend_frames'] = 11
    motion.save(path, doc)
    untouched_output = str(Path(folder)/'untouched.nuanmb')
    real_writer = export._save_ssbh_anim_data
    export._save_ssbh_anim_data = lambda data, target, op=None: target
    try:
        export.save_ssbh_anim_data(SimpleNamespace(final_frame_index=20),
                                   untouched_output, action=untouched)
    finally:
        export._save_ssbh_anim_data = real_writer
    assert motion.load(path)['list']['untouched']['blend_frames'] == 11

    # No metadata commit after an animation write failure or renamed output.
    original_writer = export._save_ssbh_anim_data
    before = path.read_bytes()
    def fail(*args): raise OSError('test disk error')
    export._save_ssbh_anim_data = fail
    try:
        export.save_ssbh_anim_data(SimpleNamespace(final_frame_index=20), output, action=export_action)
    except OSError:
        pass
    else:
        raise AssertionError('Expected animation write failure')
    assert path.read_bytes() == before
    export._save_ssbh_anim_data = lambda *args: str(Path(folder)/'test_1.nuanmb')
    export.save_ssbh_anim_data(SimpleNamespace(final_frame_index=20), output, action=export_action)
    assert path.read_bytes() == before
    export._save_ssbh_anim_data = original_writer

# Per-action values must survive a .blend round trip. This resets the scene, so it
# runs last, after every block above has finished with the current file.
with tempfile.TemporaryDirectory() as probe_folder:
    blend_file = str(Path(probe_folder)/'probe.blend')
    bpy.ops.wm.save_as_mainfile(filepath=blend_file)
    bpy.ops.wm.open_mainfile(filepath=blend_file)
    reloaded = bpy.data.actions['sub_motion_probe'].sub_motion
    assert reloaded.blend_frames == 7, reloaded.blend_frames
    assert reloaded.flag_loop and reloaded.synced

addon_utils.disable(MODULE, default_set=False)
print(f'MOTION LIST INTEGRATION PASSED: {len(operators)} operators, {len(panels)} panels')
profile.cleanup()
