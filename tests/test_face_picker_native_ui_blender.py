from pathlib import Path
from types import SimpleNamespace
import importlib

fixture = Path(__file__).with_name('test_face_picker_selection_blender.py')
exec(compile(fixture.read_text(), str(fixture), 'exec'))


class Layout:
    def __init__(self):
        self.props = []
    def row(self, **kwargs):
        return self
    def prop(self, data, name, **kwargs):
        self.props.append((name, kwargs))
    def separator(self):
        pass
    def label(self, **kwargs):
        pass


original_grid = face.draw_expression_grid
calls = []
face.draw_expression_grid = lambda *args, **kwargs: calls.append(kwargs)
try:
    picker.active_mode = 'BONE'
    layout = Layout()
    face.draw_popup_picker_layout(layout, bpy.context)
    assert [name for name, _ in layout.props] == [
        'active_mode', 'insert_keyframes', 'select_affected_bones', 'columns', 'organize_by']
    assert not dict(layout.props)['select_affected_bones'].get('toggle', False)
    assert calls and calls[0]['scale'] > 0
    picker.active_mode = 'VIS'
    layout = Layout()
    face.draw_popup_picker_layout(layout, bpy.context)
    assert 'select_affected_bones' not in dict(layout.props)
finally:
    face.draw_expression_grid = original_grid
area = bpy.context.area or bpy.context.screen.areas[0]
old_type = area.type
try:
    face._configure_picker_area(area)
    assert area.type == 'IMAGE_EDITOR'
    assert area.spaces.active.image is None
    assert not area.spaces.active.show_region_header
    assert not area.spaces.active.show_region_ui
    assert not area.spaces.active.show_region_toolbar
finally:
    area.type = old_type
print('Native face picker layout tests passed')


# The dedicated canvas has no dependency on Properties panel polling.
assert not hasattr(face, '_picker_panel_polls')
assert face._picker_window_region(bpy.context.screen.areas[0]) is not None
print('Dedicated canvas editor tests passed')

# Exercise the whole canvas, including the theme colors passed to GPU uniforms.
from unittest.mock import patch


class Shader:
    def bind(self):
        pass
    def uniform_float(self, name, value):
        assert name == 'color' and len(value) == 4, value


class Batch:
    def draw(self, shader):
        pass


def rectangle(x, y, width, height, color):
    assert len(color) == 4, color


scissors = []
scissor_enabled = []
state = SimpleNamespace(
    scissor_get=lambda: (0, 0, 540, 820),
    scissor_set=lambda *bounds: scissors.append(bounds),
    scissor_test_set=lambda enabled: scissor_enabled.append(enabled),
)
labels = []
with patch.object(face.gpu, 'state', state),      patch.object(face, '_draw_rect', rectangle), \
     patch.object(face, '_draw_label', lambda text, *args: labels.append(text)), \
     patch.object(face, '_ui_shader', lambda: Shader()), \
     patch.object(face, 'batch_for_shader', lambda *args, **kwargs: Batch()):
    picker.active_mode = 'BONE'
    for keyframes in (True, False):
        picker.insert_keyframes = keyframes
        labels.clear()
        face._draw_picker_canvas(bpy.context, SimpleNamespace(width=540, height=820), picker)
        assert 'Keyframes' in labels
        assert 'Select Affected Bones' in labels
        kinds = {hit['kind'] for hit in face._picker_hits}
        assert {'keyframes', 'select_affected_bones', 'expression'} <= kinds, kinds
        assert expr.name in labels
    for index in range(18):
        extra = picker.expressions.add()
        extra.expression_id = f'scroll-{index}'
        extra.mode = face.EXPRESSION_MODE_BONE
    face._picker_scroll = 150
    scissors.clear()
    face._draw_picker_canvas(bpy.context, SimpleNamespace(width=540, height=820), picker)
    x, bottom, width, height = scissors[0]
    top = bottom + height
    assert top < 820 and height > 0
    for hit in face._picker_hits:
        if hit['kind'] == 'expression':
            assert hit['y'] >= bottom
            assert hit['y'] + hit['h'] <= top + 1
        elif hit['kind'] == 'keyframes':
            assert hit['y'] > top
    assert scissors[-1] == (0, 0, 540, 820)
    assert scissor_enabled[-1] is False
print('Full canvas draw and theme color regression tests passed')

items = [SimpleNamespace(name=name, mode=face.EXPRESSION_MODE_BONE)
         for name in ['ReachR', 'OpenL', 'FistR', 'OpenR', 'FistL', 'ReachL']]
fake = SimpleNamespace(expressions=items, organize_by='MOVE')
assert [e.name for e in face.expressions_for_mode(fake, 'BONE')] == [
    'FistL', 'FistR', 'OpenL', 'OpenR', 'ReachL', 'ReachR']
fake.organize_by = 'SIDE'
assert [e.name for e in face.expressions_for_mode(fake, 'BONE')] == [
    'FistL', 'OpenL', 'ReachL', 'FistR', 'OpenR', 'ReachR']
fake.organize_by = 'ALPHABETICAL'
assert [e.name for e in face.expressions_for_mode(fake, 'BONE')] == sorted([e.name for e in items], key=str.casefold)
assert items[0].name == 'ReachR'
print('Expression organization tests passed')
