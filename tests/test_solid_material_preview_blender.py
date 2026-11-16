"""Solid previews preserve source images, UVs and shader links, including animation."""
from pathlib import Path
import importlib, os, time
import numpy as np

fixture = Path(__file__).with_name('test_addon_registration_blender.py')
exec(compile(fixture.read_text().split('floor = importlib.import_module')[0], str(fixture), 'exec'))
preview = importlib.import_module(MODULE + '.source.model.material.solid_preview')
eye = importlib.import_module(MODULE + '.source.extras.eye_rig')

# A quad whose second layer uses a different UV mapping.
mesh = bpy.data.meshes.new('Solid preview test')
mesh.from_pydata([(0,0,0),(1,0,0),(1,1,0),(0,1,0)], [], [(0,1,2,3)])
obj = bpy.data.objects.new('Solid preview test', mesh)
bpy.context.scene.collection.objects.link(obj)
for name in ('map1','uvSet'):
    uv = mesh.uv_layers.new(name=name)
    for loop, xy in zip(uv.data, ((0,0),(1,0),(1,1),(0,1))):
        loop.uv = (xy[0]*.5+.5,xy[1]) if name == 'uvSet' else xy
mat = bpy.data.materials.new('EyeL')
mat.use_nodes = True
mesh.materials.append(mat)
mat.sub_matl_data.shader_label = 'SFX_PBS_010002000800824f_opaque'
for name, value in (('CustomVector13',(1,1,1,1)),('CustomVector8',(1,1,1,1)),('CustomVector31',(1,1,0,0))):
    prop = mat.sub_matl_data.vectors.add()
    prop.name = prop.param_id_name = name
    prop.value = value
base = bpy.data.images.new('Base test', 8,8, float_buffer=True)
overlay = bpy.data.images.new('Overlay test', 8,8, float_buffer=True)
a = np.ones((8,8,4),dtype=np.float32)
a[:,:,:3] = (1,0,0)
b = np.zeros((8,8,4),dtype=np.float32)
b[:,4:,:] = (0,0,1,1)
base.pixels.foreach_set(a.reshape(-1)); overlay.pixels.foreach_set(b.reshape(-1))
for name, image in (('Texture0',base),('Texture1',overlay)):
    prop = mat.sub_matl_data.textures.add()
    prop.name = prop.param_id_name = prop.node_name = name
    prop.image = image
    node = mat.node_tree.nodes.new('ShaderNodeTexImage')
    node.name, node.image, node.extension = name,image,'EXTEND'
links = [(l.from_node.name,l.to_node.name) for l in mat.node_tree.links]
uvs = [[tuple(v.uv) for v in layer.data] for layer in mesh.uv_layers]
assert preview.update_material(mat,[obj])
first = preview._pixels(mat.node_tree.nodes[preview.NODE].image).copy()
assert first[4,2,2] > .95, first[4,2]
# Independent second-layer translation exposes the stationary red base.
prop = mat.sub_matl_data.vectors.get('CustomVector31')
prop.value = (1,1,.5,0)
assert preview.update_material(mat,[obj])
second = preview._pixels(mat.node_tree.nodes[preview.NODE].image).copy()
assert second[4,2,0] > .95 and second[4,2,2] < .05, second[4,2]
assert np.array_equal(preview._pixels(base),a)
assert np.array_equal(preview._pixels(overlay),b)
assert links == [(l.from_node.name,l.to_node.name) for l in mat.node_tree.links]
assert uvs == [[tuple(v.uv) for v in layer.data] for layer in mesh.uv_layers]
# The emission-layer eye shader uses Texture5/14 even with a black Texture0.
for texture, node in zip(list(mat.sub_matl_data.textures),('Texture5','Texture14')):
    texture.name = texture.param_id_name = texture.node_name = node
    image = base if node == 'Texture5' else overlay
    tex = mat.node_tree.nodes.new('ShaderNodeTexImage')
    tex.name, tex.image, tex.extension = node,image,'EXTEND'
mat.sub_matl_data.vectors.get('CustomVector13').value = (0,0,0,1)
prop.value = (1,1,0,0)
preview.update_material(mat,[obj])
assert preview._pixels(mat.node_tree.nodes[preview.NODE].image)[4,2,2] > .95
# Frame handlers must update the image from animated material values.
for frame, translation in ((1,0),(2,.5)):
    prop.value = (1,1,translation,0)
    prop.keyframe_insert('value', frame=frame)
solid_open = eye._solid_texture_viewport_open
try:
    eye._solid_texture_viewport_open = lambda: True
    bpy.context.scene.frame_set(1)
    before = preview._pixels(mat.node_tree.nodes[preview.NODE].image).copy()
    bpy.context.scene.frame_set(2)
    after = preview._pixels(mat.node_tree.nodes[preview.NODE].image).copy()
    assert np.max(np.abs(before-after)) > .5
finally:
    eye._solid_texture_viewport_open = solid_open
# Imported samplers clamp eyes even though the Image Texture node says REPEAT.
uv = np.array([[[1.25,.5]]],dtype=np.float32)
assert preview._sample(overlay,uv,('ClampToEdge','ClampToEdge'))[0,0,2] > .95
assert preview._sample(overlay,uv,('Repeat','Repeat'))[0,0,2] < .05
# An unchanged material must not rebuild or upload its preview every timer tick.
publish = preview._publish
try:
    preview._publish = lambda *args: (_ for _ in ()).throw(AssertionError('uncached preview'))
    preview.update_material(mat,[obj])
finally:
    preview._publish = publish
# Tinted textures must keep wrapping for negative/tiled boot UV islands.
boot=bpy.data.materials.new('Tiled boot')
boot.use_nodes=True
boot.sub_matl_data.shader_label='SFX_PBS_0100000008008269_opaque'
texture=boot.sub_matl_data.textures.add()
texture.name=texture.param_id_name=texture.node_name='Texture0'
texture.image=base
source_node=boot.node_tree.nodes.new('ShaderNodeTexImage')
source_node.name,source_node.image='Texture0',base
multiplier=boot.sub_matl_data.vectors.add()
multiplier.name=multiplier.param_id_name='CustomVector8'
multiplier.value=(.5,.5,.5,1)
sampler=boot.sub_matl_data.samplers.add()
sampler.name='Sampler0'
for wrapping,expected in (('Repeat','REPEAT'),('MirroredRepeat','MIRROR'),('ClampToEdge','EXTEND')):
    sampler.wrap_s=sampler.wrap_t=wrapping
    assert preview.update_material(boot,[])
    assert boot.node_tree.nodes[preview.NODE].extension==expected
    boot.node_tree.nodes[preview.NODE].extension='CLIP'
    preview.update_material(boot,[])
    assert boot.node_tree.nodes[preview.NODE].extension==expected
    assert preview._cache[boot.as_pointer()]['uv'] is None
print('SOLID_SYNTHETIC_OK')

reference = os.environ.get('SUB_SOLID_BLEND')
if reference:
    bpy.ops.wm.open_mainfile(filepath=reference,use_scripts=False)
    scene=bpy.context.scene
    groups={}
    for o in scene.objects:
        if o.type == 'MESH':
            for m in o.data.materials:
                if m and m.use_nodes and m.node_tree and m.sub_matl_data.shader_label:
                    groups.setdefault(m,[]).append(o)
    # Nested model groups must not hide the eyes from the rig.
    armatures=[o for o in scene.objects if o.type=='ARMATURE']
    found=[o for arma in armatures for o in eye.eye_meshes(arma)]
    assert len(found)>=4, [(a.name,len(eye.eye_meshes(a))) for a in armatures]
    started=time.perf_counter()
    for m,objects in groups.items():
        assert preview.update_material(m,objects)
        if m.name in ('EyeL','EyeL.001') and os.environ.get('SUB_SOLID_OUTPUT'):
            folder=Path(os.environ['SUB_SOLID_OUTPUT']); folder.mkdir(parents=True, exist_ok=True)
            m.node_tree.nodes[preview.NODE].image.save_render(str(folder/(m.name+'.png')))
    print('SOLID_REFERENCE_MATERIALS',len(groups),'EYE_MESHES',len(found),'SECONDS',time.perf_counter()-started)
    for name in ('EyeL','EyeL.001'):
        material=bpy.data.materials[name]
        image=material.node_tree.nodes[preview.NODE].image
        pixels=preview._pixels(image)
        assert np.max(pixels[:,:,:3])>.5
        assert np.min(pixels[:,:,3])==1
        print('EYE_PREVIEW',name, image.size[:],pixels[:,:,:3].mean(axis=(0,1)))
    shoes=bpy.data.materials['def_goku_003']
    assert min(v.uv.x for o in groups[shoes] for v in o.data.uv_layers['map1'].data)<0
    assert shoes.node_tree.nodes[preview.NODE].extension=='REPEAT'
    # Final color multiplier is visible in the generated clothing texture.
    clothing=next(m for m in groups if m.sub_matl_data.shader_label=='SFX_PBS_010000080800826b_opaque')
    image=clothing.node_tree.nodes[preview.NODE].image
    print('CLOTHING',clothing.name,preview._pixels(image)[0,0])
    # Color changes must update Solid preview after the shader drivers evaluate.
    vector=clothing.sub_matl_data.vectors.get('CustomVector8')
    previous=tuple(vector.value)
    vector.value=(.1,.8,.2,1)
    clothing.update_tag()
    bpy.context.view_layer.update()
    preview.update_material(clothing,groups[clothing])
    pixel=preview._pixels(clothing.node_tree.nodes[preview.NODE].image)[0,0]
    assert np.max(np.abs(pixel[:3]-(.1,.8,.2))) < 1e-4, pixel
    vector.value=previous
    preview.restore(scene)
    assert all(preview.PREVIOUS not in m for m in groups)
print('SOLID_MATERIAL_PREVIEW_OK')
