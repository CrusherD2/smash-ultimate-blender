from . import changelog
from . import ui
from . import version_check
from . import prompt

def register():
    """Register updater components"""
    version_check.register_properties()

def unregister():
    """Unregister updater components"""
    prompt.cancel_startup()
    version_check.unregister_properties()
