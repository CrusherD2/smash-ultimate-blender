import bpy

from bpy.types import (
    ShaderNode, ShaderNodeOutputMaterial, ShaderNodeBsdfDiffuse, ShaderNodeEmission,ShaderNodeBsdfPrincipled,
    ShaderNodeAttribute, ShaderNodeUVMap, NodeSocketFloat, NodeSocketColor, Image, ShaderNodeVertexColor, ShaderNodeMixRGB, Material, Operator, NodeSocket)

from math import isclose
import os
import tempfile

from ....dependencies import ssbh_data_py
from .load_from_shader_label import create_sub_matl_data_from_shader_label
from .sub_matl_data import *
from .create_blender_materials_from_matl import create_default_textures
from .texture.convert_textures import create_nor_from_material, create_prm_from_material
ParamId = ssbh_data_py.matl_data.ParamId

def convert_from_no_nodes(operator: bpy.types.Operator, material: bpy.types.Material):
    diffuse_color = material.diffuse_color[:]
    metalness = material.metallic
    specular = material.specular_intensity
    roughness = material.roughness
    create_sub_matl_data_from_shader_label(material, "SFX_PBS_010000000800ba69_opaque") # Mesh-wide PRM, 1 Col, Nor, no ColorSet1
    sub_matl_data: SUB_PG_sub_matl_data = material.sub_matl_data
    cv47: SUB_PG_matl_vector = sub_matl_data.vectors.get(ParamId.CustomVector47.name)
    cv47.value = (metalness, roughness, 1.0, specular)
    cv13: SUB_PG_matl_vector = sub_matl_data.vectors.get(ParamId.CustomVector13.name)
    cv13.value = diffuse_color[:]

def get_vertex_color_count(nodes: list[bpy.types.ShaderNode]) -> int:
    vertex_color_names = set()
    for node in nodes:
        if not isinstance(node, (ShaderNodeAttribute, ShaderNodeVertexColor)):
            # Not the right node type
            continue
        if isinstance(node, ShaderNodeAttribute):
            if node.attribute_type != 'GEOMETRY':
                # Not vertex colors
                continue
            if not node.outputs['Color'].is_linked:
                # Not being used at all, or not used in a standard way
                continue
            if node.attribute_name == "":
                # Not being used at all, or being used incorrectly
                continue
            vertex_color_names.add(node.attribute_name)
        elif isinstance(node, ShaderNodeVertexColor):
            if not node.outputs['Color'].is_linked:
                # Not being used at all, or not used in a standard way
                continue
            if node.layer_name == "":
                # Not being used at all, or being used incorrectly
                continue
            vertex_color_names.add(node.layer_name)
        

    return len(vertex_color_names)

def get_uv_layer_count(nodes: list[bpy.types.ShaderNode]) -> int:
    uv_layer_names = set()
    for node in nodes:
        if not isinstance(node, ShaderNodeUVMap):
            # Not the right node type
            continue
        if node.from_instancer is True:
            # This means its using the 'Active' uv map rather than any specific one
            continue
        if node.uv_map == "":
            # This means its using the 'Active' uv map rather than any specific one.
            # it would be unusual for a user to intentionally use this and then use a manually specified one later
            continue
        uv_layer_names.add(node.uv_map)

    return len(uv_layer_names)

def principled_uses_emission(node: ShaderNodeBsdfPrincipled) -> bool:
    emission_input: NodeSocketColor = node.inputs['Emission Color']
    strength_input: NodeSocketFloat = node.inputs['Emission Strength']
    if emission_input.is_linked or strength_input.is_linked:
        return True
    
    if isclose(strength_input.default_value,0,abs_tol=0.01):
        return False
    
    if all(isclose(emission_input.default_value[col_index],0,abs_tol=0.01) for col_index in (0,1,2)):
        return False 
        
    return True

def principled_uses_subsurface(node: ShaderNodeBsdfPrincipled) -> bool:
    subsurface_weight_input: NodeSocketFloat = node.inputs['Subsurface Weight']
    if subsurface_weight_input.is_linked:
        return True
    
    if isclose(subsurface_weight_input.default_value,0,abs_tol=0.01):
        return False

    return True

def rename_mesh_attributes_of_meshes_using_material(operator: bpy.types.Operator, material: Material, preset:str = "FIGHTER"):
    meshes: set[bpy.types.Mesh] = {mesh for mesh in bpy.data.meshes if material in mesh.materials.values()}
    for mesh in meshes:
        if preset == 'FIGHTER':
            if len(mesh.uv_layers) > 2:
                operator.report({'WARNING'}, f"Can't rename UV Layers of mesh '{mesh.name}', theres more than 2 UV Layers! Please rename them manually, or remove the un-needed layers!")
            else:
                if len(mesh.uv_layers) == 2:
                    uv_layer_names = {uv_layer.name for uv_layer in mesh.uv_layers}
                    if 'map1' not in uv_layer_names:
                        mesh.uv_layers[0].name = 'map1'
                    if 'uvSet' not in uv_layer_names:
                        mesh.uv_layers[1].name = 'uvSet'
                if len(mesh.uv_layers) == 1:
                    if mesh.uv_layers[0].name != 'map1':
                        mesh.uv_layers[0].name = 'map1'
            if len(mesh.color_attributes) > 1:
                operator.report({'WARNING'}, f"Can't rename UV Layers of mesh '{mesh.name}', theres more than 2 UV Layers! Please rename them manually, or remove the un-needed layers!")
            else:
                if len(mesh.color_attributes) == 1:
                    if mesh.color_attributes[0].name != 'colorSet1':
                        mesh.color_attributes[0].name = 'colorSet1'
                        # Scale color_set_1 for intuitive results
                        for data in mesh.color_attributes[0].data:
                            data.color = [ value / 2 for value in data.color ]
def get_tex_image_going_to_linked_input(initial_input:NodeSocket, mix_nodes_between: int, layer: int) -> Image | None:
    if not initial_input.is_linked:
        return
    if layer not in (1,2):
        return
    if mix_nodes_between not in (0,1,2):
        return
    
    if mix_nodes_between == 0:
        tex_node = initial_input.links[0].from_node 
        
    elif mix_nodes_between == 1:
        mix_node = initial_input.links[0].from_node
        if not isinstance(mix_node, ShaderNodeMixRGB):
            return
        
        if not mix_node.inputs[f'Color{layer}'].is_linked:
            return
        
        tex_node = mix_node.inputs[f'Color{layer}'].links[0].from_node
        
    elif mix_nodes_between == 2:
        mix_vertex_colors_node = initial_input.links[0].from_node
        if not isinstance(mix_vertex_colors_node, ShaderNodeMixRGB):
            return
        
        if not mix_vertex_colors_node.inputs['Color1'].is_linked:
            return
        
        mix_textures_node = mix_vertex_colors_node.inputs['Color1'].links[0].from_node
        if not isinstance(mix_textures_node, ShaderNodeMixRGB):
            return
        
        if not mix_textures_node.inputs[f'Color{layer}'].is_linked:
            return
        
        tex_node = mix_textures_node.inputs[f'Color{layer}'].links[0].from_node

    if not isinstance(tex_node, ShaderNodeTexImage):
        return
    return tex_node.image   

def convert_emission(emission_node: ShaderNodeEmission, material: Material, vertex_color_count: int, uv_layer_count: int):
    if emission_node.inputs['Color'].is_linked is False:
        emission_color = emission_node.inputs['Color'].default_value[:]
        emission_strength = emission_node.inputs['Strength'].default_value
        emission_strength_linked = emission_node.inputs['Strength'].is_linked
        linked_emission_map: Image = None
        if emission_strength_linked:
            # User may be using a texture for the emission map
            pre_final_node = emission_node.inputs['Strength'].links[0].from_node
            if isinstance(pre_final_node, ShaderNodeTexImage):
                linked_emission_map = pre_final_node.image
        else:
            # User not using a map
            emission_strength = emission_node.inputs['Strength'].default_value   
        
        create_sub_matl_data_from_shader_label(material, "SFX_PBS_0000000000000100_opaque") # 1 Layer Shadeless Emissive
        sub_matl_data: SUB_PG_sub_matl_data = material.sub_matl_data
        cv3: SUB_PG_matl_vector = sub_matl_data.vectors.get(ParamId.CustomVector3.name)
        texture5: SUB_PG_matl_texture = sub_matl_data.textures.get(ParamId.Texture5.name)
        if emission_strength_linked:
            cv3.value = [emission_color[i] for i in (0,1,2,3)]
            texture5.image = linked_emission_map
        else:
            cv3.value = [emission_color[i] * emission_strength for i in (0,1,2,3)]
            texture5.image = bpy.data.images.get('/common/shader/sfxpbs/default_white')
        return
    
    emission_strength = emission_node.inputs['Strength'].default_value if not emission_node.inputs['Strength'].is_linked else 1.0
    emi_layer_1 = None
    emi_layer_2 = None
    if uv_layer_count >= 2:
        if vertex_color_count >= 1:
            # Texture -> Mix -> Mix -> Bsdf
            emi_layer_1 = get_tex_image_going_to_linked_input(emission_node.inputs['Color'], mix_nodes_between=2, layer=1)
            emi_layer_2 = get_tex_image_going_to_linked_input(emission_node.inputs['Color'], mix_nodes_between=2, layer=2)
            create_sub_matl_data_from_shader_label(material, "SFX_PBS_0120000810080100_opaque") # 2 Layer Shadeless + colorSet1
        else:
            # Texture -> Mix -> Bsdf
            emi_layer_1 = get_tex_image_going_to_linked_input(emission_node.inputs['Color'], mix_nodes_between=1, layer=1)
            emi_layer_2 = get_tex_image_going_to_linked_input(emission_node.inputs['Color'], mix_nodes_between=1, layer=2)
            create_sub_matl_data_from_shader_label(material, "SFX_PBS_0120000010008100_opaque") # 2 Layer Shadeless
    else:
        if vertex_color_count >= 1:
            # Texture -> Mix -> Bsdf
            emi_layer_1 = get_tex_image_going_to_linked_input(emission_node.inputs['Color'], mix_nodes_between=1, layer=1)
            create_sub_matl_data_from_shader_label(material, "SFX_PBS_0000000000080100_opaque") # 1 Layer Shadeless Emissive + colorSet1
        else:
            # Texture -> Bsdf
            emi_layer_1 = get_tex_image_going_to_linked_input(emission_node.inputs['Color'], mix_nodes_between=0, layer=1)
            create_sub_matl_data_from_shader_label(material, "SFX_PBS_0000000000000100_opaque") # 1 Layer Shadeless Emissive

    sub_matl_data: SUB_PG_sub_matl_data = material.sub_matl_data
    texture5: SUB_PG_matl_texture = sub_matl_data.textures.get(ParamId.Texture5.name)
    texture14: SUB_PG_matl_texture = sub_matl_data.textures.get(ParamId.Texture14.name)
    if texture5 is not None and emi_layer_1 is not None:
        texture5.image = emi_layer_1
    if texture14 is not None and emi_layer_2 is not None:
        texture14.image = emi_layer_2

def convert_principled_emission(principled_node: ShaderNodeBsdfPrincipled, material: Material, vertex_color_count: int, uv_layer_count: int):
    '''
    The assumption is that the user will use seperate images for the base col layer and the emmission layer
    '''
    col_layer_1 = None
    col_layer_2 = None
    emi_layer_1 = None
    emi_layer_2 = None
    
    emission_input = principled_node.inputs['Emission Color']
    emission_color = emission_input.default_value[:]
    was_emission_input_linked = emission_input.is_linked
    emission_strength_input: NodeSocketFloat = principled_node.inputs['Emission Strength']
    emission_strength = emission_strength_input.default_value if emission_strength_input.is_linked is False else 1

    if uv_layer_count >= 2:
        # No Fighter PBR with 2 diffuse, 2 emission, and colorSet1
        # Texture -> Mix -> Principled
        col_layer_1 = get_tex_image_going_to_linked_input(principled_node.inputs["Base Color"], mix_nodes_between=1, layer=1)
        col_layer_2 = get_tex_image_going_to_linked_input(principled_node.inputs["Base Color"], mix_nodes_between=1, layer=2)
        emi_layer_1 = get_tex_image_going_to_linked_input(principled_node.inputs["Emission Color"], mix_nodes_between=1, layer=1)
        emi_layer_2 = get_tex_image_going_to_linked_input(principled_node.inputs["Emission Color"], mix_nodes_between=1, layer=2)
        create_sub_matl_data_from_shader_label(material, "SFX_PBS_010000001a00824f_opaque") # PBR, 2 Diffuse, 2 Emmissive
    else:
        if vertex_color_count >= 1: 
            # Texture -> Mix -> Principled
            col_layer_1 = get_tex_image_going_to_linked_input(principled_node.inputs["Base Color"], mix_nodes_between=1, layer=1)
            emi_layer_1 = get_tex_image_going_to_linked_input(principled_node.inputs["Emission Color"], mix_nodes_between=1, layer=1)
            create_sub_matl_data_from_shader_label(material, "SFX_PBS_010000000a088269_opaque") # PBR, 1 Diffuse, 1 Emmissive  + colorset1
        else:
            # Texture -> Principled
            col_layer_1 = get_tex_image_going_to_linked_input(principled_node.inputs["Base Color"], mix_nodes_between=0, layer=1)
            emi_layer_1 = get_tex_image_going_to_linked_input(principled_node.inputs["Emission Color"], mix_nodes_between=0, layer=1)
            create_sub_matl_data_from_shader_label(material, "SFX_PBS_010000080a008269_opaque") # PBR, 1 Diffuse, 1 Emmissive
    
    sub_matl_data: SUB_PG_sub_matl_data = material.sub_matl_data
    
    texture0: SUB_PG_matl_texture = sub_matl_data.textures.get(ParamId.Texture0.name)
    texture1: SUB_PG_matl_texture = sub_matl_data.textures.get(ParamId.Texture1.name)
    texture5: SUB_PG_matl_texture = sub_matl_data.textures.get(ParamId.Texture5.name)
    texture14: SUB_PG_matl_texture = sub_matl_data.textures.get(ParamId.Texture14.name) 
    cv3: SUB_PG_matl_vector = sub_matl_data.vectors.get(ParamId.CustomVector3.name)
    
    texture0.image = col_layer_1 if col_layer_1 is not None else bpy.data.images.get('/common/shader/sfxpbs/default_white')
    if texture1 is not None:
        texture1.image = col_layer_2 if col_layer_2 is not None else bpy.data.images.get('/common/shader/sfxpbs/default_white')
        
    if was_emission_input_linked is False:
        cv3.value = [emission_color[i] * emission_strength for i in (0,1,2,3)]
        texture5.image = bpy.data.images.get('/common/shader/sfxpbs/default_white')
        if texture14 is not None:
            texture14.image = bpy.data.images.get('/common/shader/sfxpbs/default_white')
    else:
        cv3.value = [emission_strength for _ in (0,1,2,3)]
        texture5.image = emi_layer_1 if emi_layer_1 is not None else bpy.data.images.get('/common/shader/sfxpbs/default_black')
        if texture14 is not None:
            texture14.image = emi_layer_2 if emi_layer_2 is not None else bpy.data.images.get('/common/shader/sfxpbs/default_black')

def convert_principled_subsurface(operator: Operator, principled_node: ShaderNodeBsdfPrincipled, material: Material, vertex_color_count: int, uv_layer_count: int):
    col_layer_1 = None
    col_layer_2 = None
    sub_surface_color = None
    # Smash handles SSS differently and doesn't have a texture input for SSS color, its just uniform.
    # As of blender 4.0, the 'Subsurface Color' input no longer exists, instead the subsurface uses the "Radius" vector input for making the RGB transmit further into the mesh.
    """
    if principled_node.inputs['Subsurface Color'].is_linked:
        operator.report({'INFO'}, f"Material {material.name} converted to Ult PBR Mat w/ SSS, but please be aware the SSS color in smash is uniform (mesh-wide, set by CustomVector11), it can't be a map.")
    else:
        sub_surface_color = principled_node.inputs['Subsurface Color'].default_value[:]
    """

    # The factor multiplies the subsurf radius, it doesn't really "mix", so will ignore and set CV30.x to .5 as a reasonable starting point
    # sub_surface_factor = None 
    
    if uv_layer_count >= 2:
        # No shader for fighters with support for 2 UV maps and colorSet1
        # Texture -> Mix -> Principled
        col_layer_1 = get_tex_image_going_to_linked_input(principled_node.inputs["Base Color"], mix_nodes_between=1, layer=1)
        col_layer_2 = get_tex_image_going_to_linked_input(principled_node.inputs["Base Color"], mix_nodes_between=1, layer=2)
        create_sub_matl_data_from_shader_label(material, "SFX_PBS_010000000800824f_opaque") # PBR Fake SSS, 2 Layer
    else:
        if vertex_color_count >= 1:
            # Texture -> Mix -> Principled
            col_layer_1 = get_tex_image_going_to_linked_input(principled_node.inputs["Base Color"], mix_nodes_between=1, layer=1)
            create_sub_matl_data_from_shader_label(material, "SFX_PBS_010000080808826b_opaque") # PBR Fake SSS, 1 Layer + colorSet1
        else:
            # Texture -> Principled
            col_layer_1 = get_tex_image_going_to_linked_input(principled_node.inputs["Base Color"], mix_nodes_between=0, layer=1)
            create_sub_matl_data_from_shader_label(material, "SFX_PBS_010000080800826b_opaque") # PBR Fake SSS, 1 Layer
    
    sub_matl_data: SUB_PG_sub_matl_data = material.sub_matl_data
    texture0: SUB_PG_matl_texture = sub_matl_data.textures.get(ParamId.Texture0.name)
    texture1: SUB_PG_matl_texture = sub_matl_data.textures.get(ParamId.Texture1.name)
    cv11: SUB_PG_matl_vector = sub_matl_data.vectors.get(ParamId.CustomVector11.name)
    cv30: SUB_PG_matl_vector = sub_matl_data.vectors.get(ParamId.CustomVector30.name)
    if col_layer_1 is not None:
        texture0.image = col_layer_1
    if texture1 is not None and col_layer_2 is not None:
        texture1.image = col_layer_2
    if sub_surface_color is not None:
        cv11.value = [sub_surface_color[i] for i in (0,1,2,3)]
    cv30.value[0] = 0.5
    cv30.value[1] = 1.5

def convert_principled_standard(principled_node: ShaderNodeBsdfPrincipled, material: Material, vertex_color_count: int, uv_layer_count: int):
    col_layer_1 = None
    col_layer_2 = None
    if uv_layer_count >= 2:
        # No shader for fighters with support for 2 UV maps and colorSet1
        col_layer_1 = get_tex_image_going_to_linked_input(principled_node.inputs["Base Color"], mix_nodes_between=1, layer=1)
        col_layer_2 = get_tex_image_going_to_linked_input(principled_node.inputs["Base Color"], mix_nodes_between=1, layer=2)
        create_sub_matl_data_from_shader_label(material, "SFX_PBS_010000000800824f_opaque") # PBR, 2 Layer
    else:
        if vertex_color_count >= 1:
            col_layer_1 = get_tex_image_going_to_linked_input(principled_node.inputs["Base Color"], mix_nodes_between=1, layer=1)
            create_sub_matl_data_from_shader_label(material,"SFX_PBS_0100000008088269_opaque") # PBR, 1 Layer + colorSet1
        else:
            col_layer_1 = get_tex_image_going_to_linked_input(principled_node.inputs["Base Color"], mix_nodes_between=0, layer=1)
            create_sub_matl_data_from_shader_label(material, "SFX_PBS_0100000008008269_opaque") # PBR, 1 Layer
    sub_matl_data: SUB_PG_sub_matl_data = material.sub_matl_data
    texture0: SUB_PG_matl_texture = sub_matl_data.textures.get(ParamId.Texture0.name)
    texture1: SUB_PG_matl_texture = sub_matl_data.textures.get(ParamId.Texture1.name)
    if col_layer_1 is not None:
        texture0.image = col_layer_1
    if texture1 is not None and col_layer_2 is not None:
        texture1.image = col_layer_2

def convert_from_nodes(operator: bpy.types.Operator, material: bpy.types.Material):
    '''
    Just trys to handle common simple shader node setups, anything too complicated or broken
    will just be assigned a standard PBR material.
    '''
    # Gets the output node, prioritizing the EEVEE-specific node if multiple are present
    output_node: ShaderNodeOutputMaterial = material.node_tree.get_output_node('EEVEE')
    
    # This would mean the model isn't rendering in eevee, which indicates the material is incomplete.
    if output_node is None:
        operator.report({'WARNING'}, f'The material "{material.name}" has no eevee output! Converting to default PBR material.')
        create_sub_matl_data_from_shader_label(material, "SFX_PBS_0100000008008269_opaque")
        return
    
    # An eevee output with no links to its surface indicates the material is incomplete.
    if len(output_node.inputs['Surface'].links) == 0:
        operator.report({'WARNING'}, f'The material "{material.name}" has an eevee output but nothing connected to it! Converting to default PBR material.')
        create_sub_matl_data_from_shader_label(material, "SFX_PBS_0100000008008269_opaque")
        return
    
    # For now, will handle vertex color counts of 0 or 1, as those can get assigned a standard PBR material.
    # Assume 1st is `colorSet1`
    # 2+ is a more advanced material, the user can just create from the needed shader label manually.
    vertex_color_count = get_vertex_color_count(material.node_tree.nodes)

    # For now, will handle 1 or 2 UV maps, assume 1st is `map1` and 2nd `uvSet`
    # 3+ is a more advanced material, the user can just create from the needed shader label manually.
    uv_layer_count = get_uv_layer_count(material.node_tree.nodes)

    final_node:ShaderNode = output_node.inputs['Surface'].links[0].from_node
    if isinstance(final_node, ShaderNodeEmission):
        convert_emission(final_node, material, vertex_color_count, uv_layer_count)
    elif isinstance(final_node, ShaderNodeBsdfPrincipled):
        if principled_uses_emission(final_node):
            convert_principled_emission(final_node, material, vertex_color_count, uv_layer_count)
        elif principled_uses_subsurface(final_node):
            convert_principled_subsurface(operator, final_node, material, vertex_color_count, uv_layer_count)
        else:
            convert_principled_standard(final_node, material, vertex_color_count, uv_layer_count)
    else: # More complex node setup
        if uv_layer_count >= 2:
            create_sub_matl_data_from_shader_label(material, "SFX_PBS_010000000800824f_opaque") # PBR, 2 Layer
        else:
            if vertex_color_count >= 1:
                create_sub_matl_data_from_shader_label(material,"SFX_PBS_0100000008088269_opaque") # PBR, 1 Layer + colorSet1
            else:
                create_sub_matl_data_from_shader_label(material, "SFX_PBS_0100000008008269_opaque") # PBR, 1 Layer
   
def convert_blender_material(operator: bpy.types.Operator, material: bpy.types.Material, bake_size=1024):
    """
    Convert a Blender material to Smash Ultimate format with PRM and normal textures
    
    Args:
        operator: The operator calling this function (for reporting)
        material: The Blender material to convert
        bake_size: The size of textures to bake
    
    Returns:
        True if successful, False otherwise
    """
    original_engine = bpy.context.scene.render.engine
    
    # Check if Cycles render engine is available and active
    try:
        cycles_available = 'CYCLES' in [getattr(render, 'bl_idname', '') for render in bpy.types.RenderEngine.__subclasses__()]
        if not cycles_available:
            operator.report({'WARNING'}, "Cycles render engine is required for baking textures but is not available")
            # We'll still try to convert but without baking
        
        # Look for existing textures
        normal_map_img = None
        if material.use_nodes and material.node_tree:
            for node in material.node_tree.nodes:
                if node.type == 'NORMAL_MAP':
                    if node.inputs['Color'].links:
                        tex_node = node.inputs['Color'].links[0].from_node
                        if tex_node.type == 'TEX_IMAGE' and tex_node.image:
                            normal_map_img = tex_node.image
                            break
                elif node.type == 'TEX_IMAGE' and node.image:
                    # Check if the image name contains common normal map identifiers
                    if any(x in node.image.name.lower() for x in ['normal', 'nor', '_n.', '_n_']):
                        normal_map_img = node.image
                        break
        
        # Create the PRM texture
        prm_path = os.path.join(tempfile.gettempdir(), f"{material.name}_PRM.png")
        if cycles_available:
            try:
                operator.report({'INFO'}, f"Creating PRM texture for material '{material.name}'")
                # Use the new direct image creation approach
                prm_img = create_prm_from_material(material, None, bake_size=bake_size)
                
                # No path means it returned the image object directly
                if isinstance(prm_img, bpy.types.Image):
                    operator.report({'INFO'}, f"Successfully created PRM texture as internal Blender image")
                else:
                    operator.report({'INFO'}, f"Successfully created PRM texture at: {prm_img}")
            except Exception as e:
                operator.report({'WARNING'}, f"Failed to create PRM texture: {str(e)}")
                # Try to create a default PRM texture
                try:
                    # Create a default PRM texture with reasonable values
                    operator.report({'INFO'}, "Creating default PRM texture")
                    prm_img = bpy.data.images.new(f"{material.name}_PRM", width=bake_size, height=bake_size, alpha=True)
                    prm_img.colorspace_settings.name = 'Non-Color'
                    
                    # Fill with default values
                    # R: Metalness (0)
                    # G: Roughness (0.5)
                    # B: AO (1.0)
                    # A: Specular (0.16)
                    pixels = [0.0, 0.5, 1.0, 0.16] * (bake_size * bake_size)
                    prm_img.pixels = pixels
                    
                    # Pack the image
                    if not prm_img.packed_file:
                        prm_img.pack()
                except Exception as e2:
                    operator.report({'ERROR'}, f"Failed to create default PRM texture: {str(e2)}")
                    prm_img = None
        else:
            # If Cycles is not available, create a simple PRM texture with default values
            operator.report({'INFO'}, "Creating simple PRM texture (Cycles not available)")
            try:
                prm_img = bpy.data.images.new(f"{material.name}_PRM", width=bake_size, height=bake_size, alpha=True)
                prm_img.colorspace_settings.name = 'Non-Color'
                
                # Fill with default values
                # R: Metalness (0)
                # G: Roughness (0.5)
                # B: AO (1.0)
                # A: Specular (0.16)
                pixels = [0.0, 0.5, 1.0, 0.16] * (bake_size * bake_size)
                prm_img.pixels = pixels
                
                # Pack the image
                if not prm_img.packed_file:
                    prm_img.pack()
            except Exception as e:
                operator.report({'ERROR'}, f"Failed to create simple PRM texture: {str(e)}")
                prm_img = None
    except Exception as e:
        operator.report({'WARNING'}, f"Error during material processing: {str(e)}")
        prm_img = None
    finally:
        # Restore original render engine
        bpy.context.scene.render.engine = original_engine
    
    # Now convert the material
    if material.use_nodes is False:
        convert_from_no_nodes(operator, material)
    else:
        convert_from_nodes(operator, material)
    
    # Assign the normal map if we found one
    if normal_map_img:
        operator.report({'INFO'}, f"Assigning existing normal map: {normal_map_img.name}")
        # Make sure the image is packed and has correct color space
        if not normal_map_img.packed_file:
            normal_map_img.pack()
        normal_map_img.colorspace_settings.name = 'Non-Color'
        
        # Find the right texture parameter and assign the image
        sub_matl_data = material.sub_matl_data
        for texture in sub_matl_data.textures:
            if texture.param_id_name == "Texture4":  # NOR texture
                texture.image = normal_map_img
                break
    else:
        # Assign a default normal map
        try:
            operator.report({'INFO'}, "Creating default normal map")
            # Create a flat normal map (neutral blue)
            nor_img = bpy.data.images.new(f"{material.name}_NOR", width=bake_size, height=bake_size, alpha=True)
            nor_img.colorspace_settings.name = 'Non-Color'
            
            # Fill with default normal values (0.5, 0.5, 1.0, 1.0)
            pixels = [0.5, 0.5, 1.0, 1.0] * (bake_size * bake_size)
            nor_img.pixels = pixels
            
            # Pack the image
            if not nor_img.packed_file:
                nor_img.pack()
                
            # Assign to material
            sub_matl_data = material.sub_matl_data
            for texture in sub_matl_data.textures:
                if texture.param_id_name == "Texture4":  # NOR texture
                    texture.image = nor_img
                    break
        except Exception as e:
            operator.report({'WARNING'}, f"Failed to create default normal map: {str(e)}")
    
    # Assign the PRM texture if we created one
    if prm_img:
        operator.report({'INFO'}, f"Assigning PRM texture: {prm_img.name}")
        
        # Find the right texture parameter and assign the image
        sub_matl_data = material.sub_matl_data
        for texture in sub_matl_data.textures:
            if texture.param_id_name == "Texture6":  # PRM texture
                texture.image = prm_img
                break
    
    return False

def has_principled_bsdf_node(material):
    """Check if the material has a Principled BSDF node"""
    if not material or not material.node_tree:
        return False
    
    for node in material.node_tree.nodes:
        if node.type == 'BSDF_PRINCIPLED':
            return True
    
    return False

def load_and_assign_texture(material, texture_path, param_id_name):
    """Load a texture from a file and assign it to the appropriate texture parameter in the material"""
    if not os.path.exists(texture_path):
        print(f"Texture path does not exist: {texture_path}")
        return None
    
    # Load the image
    image_name = os.path.basename(texture_path)
    try:
        # Check if image is already loaded
        if image_name in bpy.data.images:
            image = bpy.data.images[image_name]
        else:
            image = bpy.data.images.load(texture_path)
            image.name = image_name
            
        # Pack the image into the .blend file
        if not image.packed_file:
            image.pack()
        
        # Set correct color space for NOR/PRM
        if param_id_name in ["Texture4", "Texture6"]:  # NOR and PRM
            image.colorspace_settings.name = 'Non-Color'
            
        # Assign the image to the material's texture parameter
        sub_matl_data = material.sub_matl_data
        
        # Debug info
        print(f"Available textures in material:")
        for texture in sub_matl_data.textures:
            print(f"  - {texture.param_id_name}")
            
        for texture in sub_matl_data.textures:
            if texture.param_id_name == param_id_name:
                print(f"Found matching texture param: {param_id_name}")
                texture.image = image
                return image
        
        print(f"No matching texture parameter found: {param_id_name}")
        
    except Exception as e:
        print(f"Error loading texture {texture_path}: {str(e)}")
        return None
    
    return None




    

