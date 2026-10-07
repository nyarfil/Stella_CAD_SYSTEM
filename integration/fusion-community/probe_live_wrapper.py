"""Live, guarded Fusion verification for Stella's community MCP wrapper.

``guard`` proves that modeling is refused when no document is allowlisted.
``sandbox`` creates one 20 x 10 x 5 mm history-based box only in the explicitly
named active Fusion document, measures it, and exports a STEP artifact.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from pathlib import Path
from typing import Any

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client


def text_content(result: Any) -> str:
    return "\n".join(
        item.text for item in result.content if getattr(item, "type", None) == "text"
    )


def text_number(text: str, label: str) -> float:
    match = re.search(rf"^  {re.escape(label)}: ([+-]?[0-9.]+)$", text, re.MULTILINE)
    if not match:
        raise RuntimeError(f"Could not read {label!r} from Fusion response: {text}")
    return float(match.group(1))


def text_vector(text: str, label: str) -> list[float]:
    match = re.search(rf"^  {re.escape(label)}: \[([^]]+)\]$", text, re.MULTILINE)
    if not match:
        raise RuntimeError(f"Could not read {label!r} from Fusion response: {text}")
    return [float(value.strip()) for value in match.group(1).split(",")]


def assert_close(actual: list[float] | float, expected: list[float] | float) -> None:
    actual_values = actual if isinstance(actual, list) else [actual]
    expected_values = expected if isinstance(expected, list) else [expected]
    if len(actual_values) != len(expected_values) or any(
        abs(a - b) > 1e-9 for a, b in zip(actual_values, expected_values)
    ):
        raise RuntimeError(
            "Fusion measurement mismatch: "
            f"expected {expected_values}, got {actual_values}"
        )


async def call(session: ClientSession, name: str, arguments: dict) -> dict:
    result = await session.call_tool(name, arguments)
    text = text_content(result)
    if result.isError:
        raise RuntimeError(f"{name} failed: {text}")
    return {"tool": name, "text": text}


async def run_probe(stage: str, document: str | None, output: Path) -> None:
    wrapper = Path(__file__).with_name("stella_fusion_mcp.py")
    arguments = [str(wrapper), "--mode", "socket", "--profile", "modeling"]
    if stage == "sandbox":
        if not document:
            raise ValueError("sandbox stage requires --document")
        arguments.extend(["--allow-document", document])
    params = StdioServerParameters(
        command=sys.executable,
        args=arguments,
        cwd=str(wrapper.parent),
    )
    record: dict[str, Any] = {"stage": stage, "document": document, "steps": []}
    async with stdio_client(params) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            listed_tools = await session.list_tools()
            record["tools"] = sorted(tool.name for tool in listed_tools.tools)
            record["steps"].append(await call(session, "ping", {}))
            scene = await call(session, "get_scene_info", {})
            record["steps"].append(scene)

            if stage == "guard":
                rejected = await session.call_tool("create_sketch", {"plane": "xy"})
                if not rejected.isError:
                    raise RuntimeError(
                        "default-deny document guard accepted create_sketch"
                    )
                record["guard_rejection"] = text_content(rejected)
            else:
                if document not in scene["text"]:
                    raise RuntimeError(
                        "active Fusion document does not report the allowed name "
                        f"{document!r}"
                    )
                body_name = "StellaCommunityProbeBox"
                if body_name in scene["text"]:
                    record["existing_body"] = body_name
                else:
                    record["steps"].append(
                        await call(
                            session,
                            "create_box_parametric",
                            {
                                "length": 2.0,
                                "width": 1.0,
                                "height": 0.5,
                                "plane": "xy",
                                "body_name": body_name,
                            },
                        )
                    )
                physical = await call(
                    session,
                    "get_physical_properties",
                    {"body_name": body_name, "accuracy": "high"},
                )
                record["steps"].append(physical)
                bounds = await call(
                    session, "get_bounding_box", {"name": body_name}
                )
                record["steps"].append(bounds)
                measured_volume_cm3 = text_number(physical["text"], "volume")
                measured_size_cm = text_vector(bounds["text"], "size")
                assert_close(measured_volume_cm3, 1.0)
                assert_close(measured_size_cm, [2.0, 1.0, 0.5])
                record["measurements"] = {
                    "volume_cm3": measured_volume_cm3,
                    "volume_mm3": measured_volume_cm3 * 1000,
                    "size_cm": measured_size_cm,
                    "size_mm": [value * 10 for value in measured_size_cm],
                }
                record["measurement_assertions"] = "passed"
                step_path = output / "stella-community-20x10x5mm.step"
                record["steps"].append(
                    await call(
                        session,
                        "export_step",
                        {"body_name": body_name, "file_path": str(step_path)},
                    )
                )
                record["expected"] = {
                    "dimensions_mm": [20.0, 10.0, 5.0],
                    "volume_mm3": 1000.0,
                    "step_path": str(step_path),
                }
    output.mkdir(parents=True, exist_ok=True)
    (output / f"live-wrapper-{stage}.json").write_text(
        json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps({"stage": stage, "result": "passed"}, ensure_ascii=False))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=("guard", "sandbox"))
    parser.add_argument("--document")
    parser.add_argument(
        "--output", type=Path, default=Path(__file__).with_name("verification")
    )
    args = parser.parse_args()
    asyncio.run(run_probe(args.stage, args.document, args.output))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
