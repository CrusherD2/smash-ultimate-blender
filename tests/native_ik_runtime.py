"""Load the production adapter without requiring addon registration."""
import importlib.util
from pathlib import Path

path = Path(__file__).resolve().parents[1]/'source/extras/ik_native.py'
spec = importlib.util.spec_from_file_location('_native_ik_test_adapter',path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
Solver = module.Solver
Request = module.Request
evaluate_steps = module.evaluate_steps
