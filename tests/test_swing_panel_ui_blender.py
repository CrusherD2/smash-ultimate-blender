"""The swing chain panel shows each tab's settings and handles empty rigs."""
from pathlib import Path
from types import SimpleNamespace

fixture = Path(__file__).with_name('test_addon_registration_blender.py')
exec(compile(fixture.read_text(encoding='utf-8').split('floor = importlib.import_module')[0], str(fixture), 'exec'))
ui = importlib.import_module(MODULE + '.source.swing.ui')
panel = ui.SUB_PT_swing_bone_chains


class Recorder:
    def __init__(self, log):
        self.log = log

    def _child(self, *_args, **_kwargs):
        return Recorder(self.log)

    row = column = split = box = grid_flow = _child

    def prop(self, _owner, name, **_kwargs):
        self.log.append(('prop', name))

    def operator(self, idname, **_kwargs):
        self.log.append(('operator', idname))
        log = self.log

        class Props:
            def __setattr__(self, key, value):
                log.append(('set', key, value))
        return Props()

    def menu(self, name, **_kwargs):
        self.log.append(('menu', name))

    def label(self, text='', **_kwargs):
        self.log.append(('label', text))

    def template_list(self, list_type, _id, _owner, collection, *_args, **_kwargs):
        self.log.append(('list', collection))

    def separator(self, **_kwargs):
        pass


def draw(arma_obj):
    log = []
    proxy = SimpleNamespace(layout=Recorder(log), **{
        name: getattr(panel, name)
        for name in ('draw_bone_tab', 'draw_chain_tab', 'draw_collisions_tab', 'draw_presets_tab')})
    panel.draw(proxy, SimpleNamespace(object=arma_obj, scene=bpy.context.scene))
    return log


arma = bpy.data.armatures.new('SwingPanelTest')
obj = bpy.data.objects.new('SwingPanelTest', arma)
ssd = arma.sub_swing_data

log = draw(obj)
assert ('prop', 'active_tab') not in log, log
assert ('operator', 'sub.swing_bone_chain_auto_detect') in log
assert any(entry[0] == 'label' and 'Auto-Detect' in entry[1] for entry in log), log

chain = ssd.swing_bone_chains.add()
log = draw(obj)
assert ('prop', 'active_tab') in log
assert ('prop', 'air_resistance') not in log, 'a chain without bones has no bone settings'

for _ in range(2):
    chain.swing_bones.add()
bone_props = {name for name, _ in ui.BONE_SCALAR_PROPS + ui.BONE_RANGE_PROPS} | {'ground_hit'}
copied = {'air_resistance', 'water_resistance', 'angle_z', 'angle_y', 'collision_size', 'friction_rate',
          'goal_strength', 'inertial_mass', 'local_gravity', 'fall_speed_scale', 'ground_hit', 'wind_affect'}
assert bone_props == copied, bone_props ^ copied

ssd.active_tab = 'BONE'
props = [entry[1] for entry in draw(obj) if entry[0] == 'prop']
assert set(props) >= bone_props, props
for name, _ in ui.BONE_RANGE_PROPS:
    assert props.count(name) == 2, 'min and max share one row'
log = draw(obj)
assert ('operator', 'wm.call_menu') in log and ('set', 'name', 'SUB_MT_swing_bone_apply_values') in log, log
assert hasattr(bpy.types, 'SUB_MT_swing_bone_apply_values')

ssd.active_tab = 'CHAIN'
log = draw(obj)
assert {('prop', name) for name in ui.CHAIN_PROPS} <= set(log), log
assert ('prop', 'air_resistance') not in log

ssd.active_tab = 'COLLISIONS'
assert ('list', 'collisions') in draw(obj)

ssd.active_tab = 'PRESETS'
log = draw(obj)
assert ('prop', 'sub_swing_preset') in log and ('prop', 'sub_swing_chain_preset') in log, log

print('SWING_PANEL_UI_OK')
