import bpy
from bpy.props import FloatProperty, FloatVectorProperty, PointerProperty
from mathutils import Euler, Matrix


def _preview(self, context):
    if self.container is None:
        return
    self.container['expykit_alignment_scale'] = self.scale
    values = self.container['expykit_offset_basis']
    base = Matrix([values[index:index + 4] for index in range(0, 16, 4)])
    self.container.matrix_basis = (base @ Matrix.Translation(self.location)
                                   @ Euler(self.rotation).to_matrix().to_4x4() @ Matrix.Scale(self.scale, 4))
    context.view_layer.update()


class OffsetSettings(bpy.types.PropertyGroup):
    source: PointerProperty(type=bpy.types.Object)
    container: PointerProperty(type=bpy.types.Object)
    scale: FloatProperty(name='Scale', default=1.0, min=1e-6, update=_preview)
    rotation: FloatVectorProperty(name='Rotation', subtype='EULER', update=_preview)
    location: FloatVectorProperty(name='Location', subtype='TRANSLATION', update=_preview)


def _begin(context):
    settings = context.scene.expykit_offset
    context.view_layer.update()
    if settings.container is not None:
        return False
    source = context.object
    settings.source = source
    settings.scale = 1.0
    settings.rotation = (0.0, 0.0, 0.0)
    settings.location = (0.0, 0.0, 0.0)
    container = bpy.data.objects.new('EMP-Transforms-Offset', None)
    context.collection.objects.link(container)
    container.empty_display_type = 'PLAIN_AXES'
    container.matrix_world = Matrix.Translation(source.matrix_world.translation)
    # Preserve local animation channels; only the parent supplies the alignment.
    objects = [source]
    for obj in sorted(bpy.data.objects, key=lambda item: item.name):
        if obj == source or obj.parent_type != 'OBJECT':
            continue
        ancestor = obj.parent
        while ancestor is not None and ancestor != source:
            ancestor = ancestor.parent
        if ancestor is None and any(
            mod.type == 'ARMATURE' and mod.object == source for mod in obj.modifiers
        ):
            objects.append(obj)
    parent = source.parent
    if parent is not None:
        world = container.matrix_world.copy()
        container.parent = parent
        container.matrix_world = world
    for obj in objects:
        parent_world = obj.parent.matrix_world if obj.parent else Matrix.Identity(4)
        inverse = obj.matrix_parent_inverse.copy() if obj.parent else Matrix.Identity(4)
        basis = obj.matrix_basis.copy()
        obj.parent = container
        obj.matrix_parent_inverse = container.matrix_world.inverted_safe() @ parent_world @ inverse
        obj.matrix_basis = basis
    container['expykit_offset_basis'] = [value for row in container.matrix_basis for value in row]
    settings.container = container
    context.view_layer.update()
    if context.area and context.area.type == 'VIEW_3D':
        context.space_data.show_region_ui = True
    return True


def alignment_scale(source):
    scale = 1.0
    parent = source.parent
    while parent is not None:
        scale *= parent.get('expykit_alignment_scale', 1.0)
        parent = parent.parent
    return scale


class ApplyOffset(bpy.types.Operator):
    bl_idname = 'object.expykit_apply_offset'
    bl_label = 'Apply'
    bl_description = 'Keep this source alignment for binding and baking'
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.scene.expykit_offset.container is not None

    def execute(self, context):
        settings = context.scene.expykit_offset
        settings.container = None
        settings.source = None
        return {'FINISHED'}


def draw_offset(layout, context):
    settings = context.scene.expykit_offset
    if settings.container is None:
        return
    box = layout.box()
    box.label(text='Source Alignment Offset')
    box.label(text='Source: ' + settings.source.name)
    box.prop(settings.container, 'name', text='Name')
    box.prop(settings, 'location')
    box.prop(settings, 'rotation')
    box.prop(settings, 'scale')
    box.operator(ApplyOffset.bl_idname, text='Apply', icon='CHECKMARK')


_CLASSES = (OffsetSettings, ApplyOffset)


def register():
    for cls in _CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.Scene.expykit_offset = PointerProperty(type=OffsetSettings)


def unregister():
    del bpy.types.Scene.expykit_offset
    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)
