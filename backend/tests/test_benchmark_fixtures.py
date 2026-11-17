"""Only trusted checked-in fixtures execute here; model/repository code uses Docker."""
from pathlib import Path
import importlib.util
import sys
import pytest

CASES = sorted((Path(__file__).resolve().parents[2] / 'benchmarks').glob('*/issue.json'))


@pytest.mark.parametrize('case', CASES, ids=lambda p: p.parent.name)
def test_baseline_fails_and_reference_passes(case, monkeypatch):
    # These five fixed functions are authored test data, never an LLM patch.
    for filename, should_pass in [('calculator.py', False), ('reference.py', True)]:
        spec = importlib.util.spec_from_file_location('calculator', case.parent / filename)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        monkeypatch.setitem(sys.modules, 'calculator', module)
        test_spec = importlib.util.spec_from_file_location('benchmark_test', case.parent / 'test_calculator.py')
        tests = importlib.util.module_from_spec(test_spec)
        test_spec.loader.exec_module(tests)
        test = next(value for name, value in vars(tests).items() if name.startswith('test_'))
        if should_pass:
            test()
        else:
            with pytest.raises(AssertionError):
                test()
