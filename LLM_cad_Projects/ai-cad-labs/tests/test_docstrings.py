"""Mechanical documentation gates for the tools package (stdlib-only).

Three invariants:
  1. every module in the tools package carries a module docstring;
  2. every public top-level function/class in every tools module carries a
     docstring (public = not underscore-prefixed; main() counts);
  3. the layer's known twin surfaces stay byte-honest:
     parse_overall_dimensions is source-identical between spec_validator and
     dimension_checker, and the manufacturing-process vocabulary agrees
     between spec_validator and dfma_evaluator.

The twin assertions gate deliberate duplication instead of refactoring it
away: if a twin is edited on one side only, this file fails loudly.
"""

from __future__ import annotations

import importlib
import inspect
import pkgutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import tools  # noqa: E402
from tools import dfma_evaluator, dimension_checker, spec_validator  # noqa: E402

TOOL_MODULES = sorted(m.name for m in pkgutil.iter_modules(tools.__path__))


def _public_top_level_defs(mod):
    """Yield (name, obj) for public top-level functions/classes defined in mod."""
    for name, obj in vars(mod).items():
        if name.startswith("_"):
            continue
        if not (inspect.isfunction(obj) or inspect.isclass(obj)):
            continue
        if getattr(obj, "__module__", None) != mod.__name__:
            continue  # imported, not defined here
        yield name, obj


def test_tools_package_is_discoverable():
    """The walk found the tool modules (guards against a silent empty sweep)."""
    assert TOOL_MODULES, "pkgutil found no modules in the tools package"


def test_every_tools_module_has_a_module_docstring():
    missing = []
    for mod_name in TOOL_MODULES:
        mod = importlib.import_module(f"tools.{mod_name}")
        if not (mod.__doc__ or "").strip():
            missing.append(mod_name)
    assert not missing, f"tools modules without a module docstring: {missing}"


def test_every_public_top_level_def_has_a_docstring():
    missing = []
    for mod_name in TOOL_MODULES:
        mod = importlib.import_module(f"tools.{mod_name}")
        for name, obj in _public_top_level_defs(mod):
            if not (inspect.getdoc(obj) or "").strip():
                missing.append(f"{mod_name}.{name}")
    assert not missing, f"public defs without a docstring: {missing}"


def test_parse_overall_dimensions_twins_are_source_identical():
    """spec_validator and dimension_checker carry byte-identical copies."""
    assert inspect.getsource(
        spec_validator.parse_overall_dimensions
    ) == inspect.getsource(dimension_checker.parse_overall_dimensions), (
        "parse_overall_dimensions diverged between spec_validator and "
        "dimension_checker; edit both copies together"
    )


def test_process_vocabulary_twins_agree():
    """The manufacturing-process vocabulary is shared across the layer.

    dfma_evaluator has no CANONICAL_PROCESSES tuple of its own; its canonical
    set is the value set of its _PROCESS_KEYWORDS. So the strongest true
    invariants are: keyword dicts equal, and spec_validator's canonical tuple
    covering exactly that value set.
    """
    assert spec_validator._PROCESS_KEYWORDS == dfma_evaluator._PROCESS_KEYWORDS, (
        "_PROCESS_KEYWORDS diverged between spec_validator and dfma_evaluator; "
        "edit both copies together"
    )
    assert set(spec_validator.CANONICAL_PROCESSES) == set(
        dfma_evaluator._PROCESS_KEYWORDS.values()
    ), (
        "spec_validator.CANONICAL_PROCESSES no longer matches the canonical "
        "process IDs implied by dfma_evaluator._PROCESS_KEYWORDS"
    )
