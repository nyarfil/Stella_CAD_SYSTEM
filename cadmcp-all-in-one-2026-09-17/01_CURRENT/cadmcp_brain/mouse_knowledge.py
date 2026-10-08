"""Read-only bridge to the standalone computer-mouse knowledge library.

The library is deliberately an optional runtime dependency.  Keeping the
import inside ``_handler`` lets the core CAD brain start without the library,
while still reporting an actionable error instead of silently using a stale
or reduced fallback catalog.
"""
from __future__ import annotations

from typing import Any, Callable

from .errors import BrainError


def _handler(name: str) -> Callable[[dict[str, Any]], dict[str, Any]]:
    """Resolve one standalone library handler without importing at startup."""
    try:
        from mouse_library import __main__ as library
    except (ImportError, ModuleNotFoundError) as exc:
        raise BrainError(
            "MOUSE_LIBRARY_UNAVAILABLE",
            "The mouse knowledge library is not importable. Install it or add "
            "integration/mouse-library to PYTHONPATH before starting Stella.",
            {"handler": name, "required_module": "mouse_library", "cause": type(exc).__name__},
        ) from exc
    handler = getattr(library, name, None)
    if not callable(handler):
        raise BrainError(
            "MOUSE_LIBRARY_UNAVAILABLE",
            "The installed mouse knowledge library does not expose the required handler.",
            {"handler": name, "required_module": "mouse_library"},
        )
    return handler


def _call(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    try:
        result = _handler(name)(arguments)
    except BrainError:
        raise
    except ValueError as exc:
        # The standalone library uses ToolError(ValueError) for both input and
        # catalog loading.  Catalog absence is unavailable; input details are
        # intentionally not echoed because they may contain user data.
        message = str(exc)
        if type(exc).__name__ == "ToolError" and message.startswith(("Knowledge ", "Packaged measurements")):
            raise BrainError(
                "MOUSE_LIBRARY_UNAVAILABLE",
                "The mouse knowledge library data is unavailable or invalid.",
                {"handler": name, "cause": type(exc).__name__},
            ) from exc
        raise BrainError(
            "MOUSE_LIBRARY_INPUT",
            "The mouse knowledge library rejected the supplied arguments.",
            {"handler": name, "cause": type(exc).__name__},
        ) from exc
    except Exception as exc:
        raise BrainError(
            "MOUSE_LIBRARY_UNAVAILABLE",
            "The mouse knowledge library handler failed before producing a result.",
            {"handler": name, "cause": type(exc).__name__},
        ) from exc
    if not isinstance(result, dict):
        raise BrainError(
            "MOUSE_LIBRARY_UNAVAILABLE",
            "The mouse knowledge library returned a non-object result.",
            {"handler": name, "result_type": type(result).__name__},
        )
    return result


def _native_schema_validation(result: dict[str, Any]) -> dict[str, Any]:
    """Validate only the bridge's typed drafts against this Stella runtime."""
    from pydantic import ValidationError

    from .studio.recipe import DesignBasis
    from .studio.synthesis import FirstPrinciplesBasis, FunctionBrief

    checks = (
        ("function_brief", FunctionBrief),
        ("recipe_design_basis", DesignBasis),
        ("concept_design_basis", FirstPrinciplesBasis),
    )
    errors: list[dict[str, Any]] = []
    passed: list[str] = []
    for field, model in checks:
        value = result.get(field)
        try:
            model.model_validate(value)
        except ValidationError as exc:
            for item in exc.errors(include_url=False, include_context=False, include_input=False):
                errors.append({
                    "field": field,
                    "loc": [str(part) for part in item.get("loc", ())],
                    "type": item.get("type", "validation_error"),
                    "message": item.get("msg", "Schema validation failed"),
                })
        else:
            passed.append(model.__name__)
    if errors:
        raise BrainError(
            "MOUSE_LIBRARY_BRIDGE_SCHEMA",
            "The mouse library bridge draft does not match the installed Stella schemas.",
            {"errors": errors[:24], "checked_fields": [field for field, _ in checks]},
        )
    return {
        "passed": True,
        "validated_fields": [field for field, _ in checks],
        "validated_models": passed,
        "meaning": "Typed draft validation only; this does not validate a Recipe, CAD, fit, or physical behavior.",
    }


class MouseKnowledgeToolsMixin:
    """Native Stella read-only tools backed by the standalone library."""

    def brain_mouse_knowledge_status(self) -> dict[str, Any]:
        """Read mouse-library coverage and evidence state; never opens CAD."""
        return _call("mouse_library_status", {})

    def brain_mouse_knowledge_search(
        self, query: str, subsystem: str | None = None, limit: int = 8
    ) -> dict[str, Any]:
        """Search source-grounded mouse knowledge; results are not fit evidence."""
        arguments: dict[str, Any] = {"query": query, "limit": limit}
        if subsystem is not None:
            arguments["subsystem"] = subsystem
        return _call("mouse_library_search", arguments)

    def brain_mouse_knowledge_schema(self, name: str = "requirements") -> dict[str, Any]:
        """Return the standalone requirements schema and library metadata."""
        if name not in ("requirements", "click_window"):
            raise BrainError(
                "MOUSE_LIBRARY_INPUT",
                "Unknown mouse knowledge schema.",
                {"allowed": ["requirements", "click_window"]},
            )
        library_module = _handler("mouse_library_plan").__module__
        try:
            from mouse_library import __main__ as library
            tool_name = "mouse_library_plan" if name == "requirements" else "mouse_library_click_window"
            tool = next(item for item in library.TOOLS if item.get("name") == tool_name)
            requirements = tool["inputSchema"]["properties"]["requirements"] if name == "requirements" else tool["inputSchema"]
        except (ImportError, ModuleNotFoundError, StopIteration, KeyError, TypeError) as exc:
            raise BrainError(
                "MOUSE_LIBRARY_UNAVAILABLE",
                "The standalone mouse knowledge library does not publish its requirements schema.",
                {"handler": "mouse_library_plan", "module": library_module, "cause": type(exc).__name__},
            ) from exc
        status = _call("mouse_library_status", {})
        provenance = status.get("library_provenance")
        if not isinstance(provenance, dict):
            raise BrainError(
                "MOUSE_LIBRARY_UNAVAILABLE",
                "The standalone mouse knowledge library did not return provenance metadata.",
                {"handler": "mouse_library_status"},
            )
        return {
            "name": name,
            "schema": requirements,
            "library": {
                "server_version": status.get("server_version"),
                "schema_version": provenance.get("schema_version"),
                "library_version": provenance.get("library_version"),
                "content_sha256": provenance.get("content_sha256"),
                "entry_count": status.get("entry_count"),
            },
            "source": "mouse_library_plan.inputSchema.properties.requirements" if name == "requirements" else "mouse_library_click_window.inputSchema",
        }

    def brain_mouse_knowledge_get(self, record_id: str) -> dict[str, Any]:
        """Read one complete mouse knowledge entry and its evidence."""
        return _call("mouse_library_get", {"id": record_id})

    def brain_mouse_knowledge_plan(self, requirements: dict[str, Any]) -> dict[str, Any]:
        """Create CAD-agnostic staged guidance; call brain_mouse_knowledge_schema first."""
        return _call("mouse_library_plan", {"requirements": requirements})

    def brain_mouse_knowledge_brief(self, requirements: dict[str, Any]) -> dict[str, Any]:
        """Create a draft; call brain_mouse_knowledge_schema before validation."""
        result = _call("mouse_library_stella_bridge", {"requirements": requirements})
        result["native_schema_validation"] = _native_schema_validation(result)
        return result

    def brain_mouse_knowledge_click_window(self, assessment: dict[str, Any]) -> dict[str, Any]:
        """Evaluate compression bounds; read schema(click_window). Not a physical acceptance gate."""
        return _call("mouse_library_click_window", assessment)
