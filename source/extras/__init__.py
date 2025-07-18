from . import attribute_renamer
from . import create_meshes
from . import eye_material_custom_vector_31_modal
from . import misc_panel
from . import set_linear_vertex_color
from . import create_ik_arms
from . import create_ik_armsandlegs
from . import create_ik_legs
from . import bone_removal
from . import apply_ik_animation
from . import hip_animation_transfer
from . import idle_pose_library
from . import ik_influence_toggle
from . import limit_weights
from . import fk_to_ik
from . import rename_utils

# Import reset_animation module and ensure it's properly registered
from . import reset_animation
from . import mirror_animation

# Import animation_scroll module
from . import animation_scroll

# Explicit registration function for the package
def register():
    # Register reset_animation first to ensure it's available for the panel
    reset_animation.register()
    
    # Register mirror_animation
    mirror_animation.register()
    
    # Register rename_utils
    rename_utils.register()
    
    # Register animation_scroll
    animation_scroll.register()
    
    # Register misc_panel's new operator
    misc_panel.register()
    
def unregister():
    # Unregister animation_scroll
    animation_scroll.unregister()
    
    # Unregister rename_utils
    rename_utils.unregister()
    
    # Unregister reset_animation
    reset_animation.unregister()
    
    # Unregister mirror_animation
    mirror_animation.unregister()
    
    # Unregister misc_panel's new operator
    misc_panel.unregister()