"""Load the production adapter without requiring addon registration.

`ik_native` imports a sibling at module scope (`from . import ik_match_diag`),
so it cannot be exec'd under a bare module name -- doing so raised
"attempted relative import with no known parent package" and took
test_native_ik_singular_blender and test_native_ik_synthetic_blender down with
it, silently, from the commit that added that import until this one.

So give it a package to be relative to: a synthetic parent whose __path__ is
source/extras. Siblings then resolve normally, while the addon still does not
have to be registered, which is the whole point of loading it this way.

`ik_native` also reaches two levels up, for the add-on preference, and that one
genuinely cannot resolve here -- it is outside this synthetic package. It is
already wrapped so that any failure means "enabled", which is the default and
what a headless test wants, so it degrades rather than breaking.
"""
import importlib.util
import sys
from pathlib import Path

_EXTRAS = Path(__file__).resolve().parents[1]/'source/extras'
_PACKAGE = '_native_ik_test_extras'


def _package():
    existing = sys.modules.get(_PACKAGE)
    if existing is not None:
        return existing
    spec = importlib.util.spec_from_loader(_PACKAGE, None, is_package=True)
    package = importlib.util.module_from_spec(spec)
    package.__path__ = [str(_EXTRAS)]
    sys.modules[_PACKAGE] = package
    return package


def load(name):
    """Import `source/extras/<name>.py` as a submodule of the synthetic package."""
    _package()
    qualified = f'{_PACKAGE}.{name}'
    cached = sys.modules.get(qualified)
    if cached is not None:
        return cached
    spec = importlib.util.spec_from_file_location(qualified, _EXTRAS/f'{name}.py')
    module = importlib.util.module_from_spec(spec)
    # Registered before exec so a sibling importing back into this package
    # during module setup finds it instead of loading a second copy.
    sys.modules[qualified] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        del sys.modules[qualified]
        raise
    return module


module = load('ik_native')
Solver = module.Solver
Request = module.Request
evaluate_steps = module.evaluate_steps
