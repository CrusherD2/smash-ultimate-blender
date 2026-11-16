"""Event-driven Solid preview updates preserve edit, animation and visibility behavior."""
from pathlib import Path
fixture=Path(__file__).with_name('test_solid_material_preview_blender.py')
exec(compile(fixture.read_text().split('links = [')[0],str(fixture),'exec'))
from types import SimpleNamespace
scene=bpy.context.scene
original_open=eye._solid_texture_viewport_open
eye._solid_texture_viewport_open=lambda:True
preview._load(None)
original_update=preview.update_material
calls=[]
def counted(material,*args,**kwargs):
    calls.append(material.name)
    return original_update(material,*args,**kwargs)
preview.update_material=counted
try:
    preview.sync(scene)
    # Flush the one-time graph tags from creating/activating the preview node.
    for _ in range(3):
        bpy.context.view_layer.update()
        preview.sync(scene)
    calls.clear()
    signature=preview._uv_signature
    def unexpected(*args):raise AssertionError('Unchanged UVs were scanned again')
    preview._uv_signature=unexpected
    try:
        for _ in range(10):preview.sync(scene)
        assert not calls,calls
    finally:
        preview._uv_signature=signature
    before=preview._pixels(mat.node_tree.nodes[preview.NODE].image).copy()
    # Same-frame UV edits invalidate just the mapping, without polling its data.
    for vertex in mesh.uv_layers['uvSet'].data:vertex.uv.x-=.5
    mesh.update()
    bpy.context.view_layer.update()
    preview.sync(scene)
    after=preview._pixels(mat.node_tree.nodes[preview.NODE].image).copy()
    assert np.max(np.abs(before-after))>.5
    # Simulate source Material ID updates from UI edits, without changing frames.
    multiplier=mat.sub_matl_data.vectors.get('CustomVector8')
    multiplier.value=(.25,.5,.75,1)
    mat.update_tag()
    bpy.context.view_layer.update()
    preview.sync(scene)
    tinted=preview._pixels(mat.node_tree.nodes[preview.NODE].image).copy()
    assert np.max(np.abs(tinted-after))>.2
    # Replacing the source image invalidates the preview too.
    prop=mat.sub_matl_data.textures.get('Texture0')
    prop.image=overlay
    mat.update_tag()
    bpy.context.view_layer.update()
    preview.sync(scene)
    replaced=preview._pixels(mat.node_tree.nodes[preview.NODE].image).copy()
    assert np.max(np.abs(replaced-tinted))>.2
    prop.image=base
    for vertex in mesh.uv_layers['uvSet'].data:vertex.uv.x+=.5
    mesh.update()
    bpy.context.view_layer.update()
    # Newly keyed materials are detected when the action binding changes.
    transform=mat.sub_matl_data.vectors.get('CustomVector31')
    for frame,x in ((1,0),(2,.5)):
        transform.value=(1,1,x,0)
        transform.keyframe_insert('value',frame=frame)
    scene.frame_set(1)
    animated=preview._pixels(mat.node_tree.nodes[preview.NODE].image).copy()
    scene.frame_set(2)
    assert np.max(np.abs(animated-preview._pixels(mat.node_tree.nodes[preview.NODE].image)))>.2
    # Hidden eyes do no preview work; revealing them refreshes to the current frame.
    obj.hide_set(True)
    calls.clear()
    scene.frame_set(1)
    preview.sync(scene)
    assert mat.name not in calls,calls
    assert preview.update_eye(obj,None)
    assert mat.name not in calls,calls
    obj.hide_set(False)
    preview.sync(scene)
    assert mat.name in calls,calls
    assert np.max(np.abs(animated-preview._pixels(mat.node_tree.nodes[preview.NODE].image)))<1e-6
    # Removing animation must also refresh a previously animated value.
    mat.animation_data_clear()
    transform.value=(1,1,.5,0)
    mat.update_tag()
    bpy.context.view_layer.update()
    preview.sync(scene)
    assert np.max(np.abs(animated-preview._pixels(mat.node_tree.nodes[preview.NODE].image)))>.2
    # Real imported eye animation is keyed on armature SAP data, independently
    # of the material's own action and the presence of a look-control bone.
    rigdata=bpy.data.armatures.new('SAP eye test')
    rig=bpy.data.objects.new('SAP eye test',rigdata)
    scene.collection.objects.link(rig)
    modifier=obj.modifiers.new('SAP test','ARMATURE')
    modifier.object=rig
    bpy.context.view_layer.objects.active=rig
    track=rigdata.sub_anim_properties.mat_tracks.add()
    track.name=mat.name
    sap=track.properties.add()
    sap.name='CustomVector31'
    for frame,x in ((1,0),(2,.5)):
        sap.custom_vector=(1,1,x,0)
        sap.keyframe_insert('custom_vector',frame=frame)
    scene.frame_set(1)
    preview.sync(scene)
    sap_first=preview._pixels(mat.node_tree.nodes[preview.NODE].image).copy()
    scene.frame_set(2)
    sap_second=preview._pixels(mat.node_tree.nodes[preview.NODE].image).copy()
    assert np.max(np.abs(sap_first-sap_second))>.2
    # Live controls must update at the same frame even without keyed material
    # values. The computation itself is tested by the eye rig; test its routing.
    bpy.ops.object.mode_set(mode='EDIT')
    control=rigdata.edit_bones.new(eye.EYE_CTRL_BONE)
    control.head,control.tail=(0,0,0),(0,1,0)
    bpy.ops.object.mode_set(mode='OBJECT')
    obj.parent=rig
    scene.sub_scene_properties.eye_look_live_preview=True
    compute=eye.compute_cv31
    signature=preview._uv_signature
    eye.compute_cv31=lambda arma,bone,ssp:(bone.location.x,bone.location.x,0,1)
    try:
        for _ in range(3):
            bpy.context.view_layer.update()
            preview.sync(scene)
        live_first=preview._pixels(mat.node_tree.nodes[preview.NODE].image).copy()
        preview._uv_signature=unexpected
        rig.pose.bones[eye.EYE_CTRL_BONE].location.x=.5
        bpy.context.view_layer.update()
        preview.sync(scene)
        assert np.max(np.abs(live_first-preview._pixels(mat.node_tree.nodes[preview.NODE].image)))>.2
    finally:
        eye.compute_cv31=compute
        preview._uv_signature=signature
    # Shading-mode changes restore and re-engage cached previews without a
    # texture rebuild, even when no material/animation input has changed.
    previous=mat.get(preview.PREVIOUS)
    eye._solid_texture_viewport_open=lambda:False
    preview.sync(scene)
    assert preview.PREVIOUS not in mat
    assert (mat.node_tree.nodes.active.name if mat.node_tree.nodes.active else '')==previous
    eye._solid_texture_viewport_open=lambda:True
    preview.sync(scene)
    assert mat.node_tree.nodes.active.name==preview.NODE
    # Reassigning a material on an existing mesh must invalidate the groups,
    # even though scene-object count and viewport visibility are unchanged.
    replacement=bpy.data.materials.new('Replacement tint')
    replacement.use_nodes=True
    replacement.sub_matl_data.shader_label='SFX_PBS_0100000008008269_opaque'
    source=replacement.sub_matl_data.textures.add()
    source.name=source.param_id_name=source.node_name='Texture0'
    source.image=base
    image_node=replacement.node_tree.nodes.new('ShaderNodeTexImage')
    image_node.name,image_node.image='Texture0',base
    color=replacement.sub_matl_data.vectors.add()
    color.name=color.param_id_name='CustomVector8'
    color.value=(.2,.5,.5,1)
    mesh.materials[0]=replacement
    mesh.update()
    bpy.context.view_layer.update()
    preview.sync(scene)
    assert replacement.as_pointer() in preview._index['entries']
    assert mat.as_pointer() not in preview._index['entries']
    assert replacement.node_tree.nodes.active.name==preview.NODE
    assert np.max(np.abs(preview._pixels(replacement.node_tree.nodes.active.image)[0,0,:3]-(.2,0,0)))<1e-6
    mesh.materials[0]=mat
    mesh.update()
    bpy.context.view_layer.update()
    preview.sync(scene)
    print('SOLID_UPDATE_INVALIDATION_OK')
finally:
    preview.update_material=original_update
    eye._solid_texture_viewport_open=original_open
    preview.restore(scene)
