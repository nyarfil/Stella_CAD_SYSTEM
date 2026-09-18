"""CadQuery renderer: bash-callable port of legacy `src/cad/renderer.py` +
the render_views/render_assembly tool wrappers from `src/tools/cadquery.py`.

Produces 8 renders per part/assembly: 4 views x 2 styles, as INDIVIDUAL PNGs
(never composited into a collage):

    {front,top,right,iso}_{wireframe,clean}.png  ->  <target>/renders/

Views: front, top, right, iso
Styles:
  - wireframe (showHidden=True): X-ray view showing all edges including hidden
  - clean (showHidden=False): only visible edges, appears more solid/opaque

CadQuery's SVG exporter does NOT support filled/shaded rendering; it only
draws edges. The "clean" style is the closest to a solid appearance.

Assembly mode renders each part in a distinct stroke color (red, blue, green,
orange, purple, teal, brown, magenta), composited from per-part SVGs that share
a common scale via 0.01mm reference markers at the assembly bounding-box
corners. Hidden lines get a lighter shade + dashed stroke. The color legend is
written to <project>/assembly/renders/color_legend.txt. Falls back to
monochrome rendering when parts cannot be extracted from the exec namespace.

CLI:
    uv run python -m tools.renderer --mode=views --part-path <part-dir> [--code-file <script.py>] [--width 1600 --height 1200]
    uv run python -m tools.renderer --mode=assembly --project <project-dir> [--width 1600 --height 1200]

JSON contract (single object on stdout; human detail on stderr):
    {
      "success": bool,
      "png_paths": [str, ...],                      # 8 paths on success
      "legend": {part: {"color": name, "rgb": [r,g,b]}} | null,   # assembly colored mode only
      "dimension_check": {"pass", "expected", "actual", "deviations"} | null,
      "error_message": str | null                    # full text, never truncated
    }

Exit 0 on tool-success even when the evaluated artifact fails (the JSON
carries the verdict); exit != 0 only on tool malfunction.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

# Ensure cairocffi can find libcairo on macOS (Homebrew installs to /opt/homebrew/lib).
# MUST run before the cairosvg import below.
if sys.platform == "darwin":
    _brew_lib = "/opt/homebrew/lib"
    _fallback = os.environ.get("DYLD_FALLBACK_LIBRARY_PATH", "")
    if _brew_lib not in _fallback:
        os.environ["DYLD_FALLBACK_LIBRARY_PATH"] = f"{_brew_lib}:{_fallback}".rstrip(":")

import cairosvg  # noqa: E402
import cadquery as cq  # noqa: E402

from tools.dimension_checker import (  # noqa: E402
    bbox_of,
    check_dimensions,
    execute_cad_script,
)

# Color palette for per-part assembly rendering — visually distinct on white background
ASSEMBLY_PART_COLORS = [
    (220, 40, 40),    # red
    (40, 40, 220),    # blue
    (40, 160, 40),    # green
    (220, 140, 20),   # orange
    (160, 40, 200),   # purple
    (40, 180, 180),   # teal
    (180, 120, 40),   # brown
    (220, 40, 180),   # magenta
]

# Human-readable names, index-aligned with ASSEMBLY_PART_COLORS (for the legend)
ASSEMBLY_COLOR_NAMES = [
    "red", "blue", "green", "orange", "purple", "teal", "brown", "magenta",
]

# Projection directions for standard engineering views
VIEW_PROJECTIONS: dict[str, tuple[float, float, float]] = {
    "front": (0, -1, 0),
    "back": (0, 1, 0),
    "top": (0, 0, 1),
    "bottom": (0, 0, -1),
    "right": (1, 0, 0),
    "left": (-1, 0, 0),
    "iso": (-1.75, 1.1, 5),
}

# Standard 4 views
STANDARD_VIEWS = ["front", "top", "right", "iso"]

# Two rendering styles
RENDER_STYLES: dict[str, dict] = {
    "wireframe": {
        "showHidden": True,
        "hiddenColor": (180, 180, 180),
        "strokeWidth": 0.8,
    },
    "clean": {
        "showHidden": False,
        "hiddenColor": (180, 180, 180),
        "strokeWidth": 1.0,  # slightly thicker for solid appearance
    },
}


def _log(msg: str) -> None:
    print(msg, file=sys.stderr)


@dataclass
class RenderResult:
    """Result of rendering a solid to multiple views.

    metadata keys: "width", "height", "view_names", "styles",
    "total_renders"; assembly renders add "color_legend"
    ({part_name: (r, g, b)}); failure paths set only "error".
    """

    views: dict[str, Path] = field(default_factory=dict)
    metadata: dict = field(default_factory=dict)


def _extract_svg_paths(svg_str: str) -> tuple[str, str, str]:
    """Extract transform, visible paths, and hidden paths from CadQuery SVG.

    CadQuery SVG structure (actual output, not docs):
      <g transform="scale(...) translate(...)" stroke-width="W" fill="none">
        <g stroke="rgb(H)" stroke-dasharray="..."> [hidden paths] </g>
        <g stroke="rgb(V)"> [visible/solid paths] </g>
      </g>

    Returns (transform_attr_value, visible_path_elements, hidden_path_elements).
    """
    # Extract full transform attribute value (scale + translate)
    transform_match = re.search(r'transform="([^"]+)"', svg_str)
    transform = transform_match.group(1) if transform_match else ""

    # Find all <g stroke="rgb(...)"> groups with attributes + content
    # Hidden group has stroke-dasharray, visible/solid group does not
    stroke_groups = re.findall(
        r'<g\s+stroke="rgb\([^)]+\)"([^>]*?)>\s*(.*?)\s*</g>',
        svg_str, re.DOTALL,
    )

    visible = ""
    hidden = ""
    for attrs, content in stroke_groups:
        if "stroke-dasharray" in attrs:
            hidden = content.strip()
        else:
            visible = content.strip()

    return transform, visible, hidden


def _make_bbox_markers(bb) -> list:
    """Create tiny markers at bounding box corners for viewport scale consistency.

    When rendering parts separately, CadQuery auto-fits each to the viewport.
    Adding these markers forces all renders to use the same bounding box
    (the full assembly envelope), so SVG paths overlay correctly.
    """
    markers = []
    for x in [bb.xmin, bb.xmax]:
        for y in [bb.ymin, bb.ymax]:
            for z in [bb.zmin, bb.zmax]:
                markers.append(
                    cq.Solid.makeBox(0.01, 0.01, 0.01, pnt=cq.Vector(x, y, z))
                )
    return markers


class CadQueryRenderer:
    """Render CadQuery Workplane objects to multi-view PNG images.

    Produces 8 images by default: 4 views x 2 styles (wireframe + clean).
    """

    def __init__(self, width: int = 1600, height: int = 1200):
        self.width = width
        self.height = height

    def render_views(
        self,
        solid: object,
        output_dir: Path,
        views: list[str] | None = None,
    ) -> RenderResult:
        """Render a solid from multiple views in both wireframe and clean styles.

        Produces files like: front_wireframe.png, front_clean.png, etc.
        Total: len(views) x 2 styles = 8 images by default.
        """
        if views is None:
            views = STANDARD_VIEWS

        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        shape = self._extract_shape(solid)
        rendered: dict[str, Path] = {}

        for view_name in views:
            projection = VIEW_PROJECTIONS.get(view_name)
            if projection is None:
                continue

            for style_name, style_opts in RENDER_STYLES.items():
                svg_opts = {
                    "width": self.width,
                    "height": self.height,
                    "marginLeft": 50,
                    "marginTop": 50,
                    "projectionDir": projection,
                    "showAxes": False,
                    "strokeColor": (0, 0, 0),
                    **style_opts,
                }

                from cadquery.occ_impl.exporters.svg import getSVG

                svg_str = getSVG(shape, opts=svg_opts)

                file_name = f"{view_name}_{style_name}"
                png_path = output_dir / f"{file_name}.png"
                cairosvg.svg2png(
                    bytestring=svg_str.encode("utf-8"),
                    write_to=str(png_path),
                    output_width=self.width,
                    output_height=self.height,
                )
                rendered[file_name] = png_path

        return RenderResult(
            views=rendered,
            metadata={
                "width": self.width,
                "height": self.height,
                "view_names": views,
                "styles": list(RENDER_STYLES.keys()),
                "total_renders": len(rendered),
            },
        )

    def render_assembly_views(
        self,
        parts: list[tuple[object, str]],
        assembly_compound: object,
        output_dir: Path,
        views: list[str] | None = None,
    ) -> RenderResult:
        """Render assembly with per-part colored strokes in 8 individual PNGs.

        Produces 8 images: 4 views x 2 styles (clean + wireframe/X-ray).
        Each part gets a distinct stroke color. The wireframe/X-ray style
        includes internal features with lighter, dashed strokes.

        Tiny reference markers at the assembly bounding box corners ensure
        all per-part renders share the same scale.

        Args:
            parts: List of (positioned_shape, part_name) tuples.
            assembly_compound: Full assembly compound (for bounding box).
            output_dir: Where to save PNGs.
            views: View names to render (default: STANDARD_VIEWS).

        Returns:
            RenderResult with views dict mapping view names to file paths,
            and metadata including color_legend: {part_name: (r,g,b)}.
        """
        if not parts or len(parts) < 2:
            return RenderResult(
                views={},
                metadata={"error": "Need at least 2 parts for assembly rendering"},
            )

        if views is None:
            views = STANDARD_VIEWS

        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        from cadquery.occ_impl.exporters.svg import getSVG

        # Get assembly bounding box for consistent scale
        assy_shape = self._extract_shape(assembly_compound)
        try:
            bb = assy_shape.BoundingBox()
        except Exception as e:
            return RenderResult(
                views={},
                metadata={"error": f"Failed to get bounding box: {e}"},
            )

        markers = _make_bbox_markers(bb)

        # Assign colors to parts
        color_map = {}
        for idx, (_, name) in enumerate(parts):
            color_map[name] = ASSEMBLY_PART_COLORS[idx % len(ASSEMBLY_PART_COLORS)]

        rendered: dict[str, Path] = {}

        for view_name in views:
            projection = VIEW_PROJECTIONS.get(view_name)
            if projection is None:
                continue

            for style_name, style_opts in RENDER_STYLES.items():
                # Render each part with its assigned color
                shared_transform: str | None = None
                colored_groups: list[str] = []

                for part_shape, part_name in parts:
                    color = color_map[part_name]

                    try:
                        padded = cq.Compound.makeCompound(
                            [self._extract_shape(part_shape)] + markers
                        )
                    except Exception:
                        continue

                    svg_opts = {
                        "width": self.width,
                        "height": self.height,
                        "marginLeft": 50,
                        "marginTop": 50,
                        "projectionDir": projection,
                        "showAxes": False,
                        "strokeColor": color,
                        **style_opts,
                    }
                    svg_str = getSVG(padded, opts=svg_opts)

                    transform, visible_paths, hidden_paths = _extract_svg_paths(svg_str)
                    if shared_transform is None:
                        shared_transform = transform

                    r, g, b = color

                    # Add visible paths (solid stroke)
                    if visible_paths.strip():
                        stroke_width = style_opts.get("strokeWidth", 1.0)
                        colored_groups.append(
                            f'<g stroke="rgb({r},{g},{b})" fill="none" '
                            f'stroke-width="{stroke_width}">{visible_paths}</g>'
                        )

                    # For wireframe/X-ray style, add hidden paths with lighter color + dashed
                    if style_opts.get("showHidden") and hidden_paths.strip():
                        # Lighter shade: blend with white (85% original + 15% white)
                        lighter_r = int(r * 0.85 + 255 * 0.15)
                        lighter_g = int(g * 0.85 + 255 * 0.15)
                        lighter_b = int(b * 0.85 + 255 * 0.15)
                        stroke_width = style_opts.get("strokeWidth", 0.8)
                        colored_groups.append(
                            f'<g stroke="rgb({lighter_r},{lighter_g},{lighter_b})" '
                            f'fill="none" stroke-width="{stroke_width}" '
                            f'stroke-dasharray="5,3">{hidden_paths}</g>'
                        )

                if not colored_groups or shared_transform is None:
                    continue

                # Composite the colored groups into a single SVG
                composite_svg = (
                    f'<?xml version="1.0" encoding="UTF-8"?>\n'
                    f'<svg xmlns="http://www.w3.org/2000/svg" '
                    f'width="{self.width}" height="{self.height}">\n'
                    f'<rect width="100%" height="100%" fill="white"/>\n'
                    f'<g transform="{shared_transform}" fill="none">'
                    f'{"".join(colored_groups)}'
                    f'</g></svg>'
                )

                file_name = f"{view_name}_{style_name}"
                png_path = output_dir / f"{file_name}.png"
                cairosvg.svg2png(
                    bytestring=composite_svg.encode("utf-8"),
                    write_to=str(png_path),
                    output_width=self.width,
                    output_height=self.height,
                )
                rendered[file_name] = png_path

        return RenderResult(
            views=rendered,
            metadata={
                "width": self.width,
                "height": self.height,
                "view_names": views,
                "styles": list(RENDER_STYLES.keys()),
                "total_renders": len(rendered),
                "color_legend": color_map,
            },
        )

    def _extract_shape(self, solid: object):
        """Extract the underlying OCC shape from a CadQuery object.

        Handles: Workplane (.val()), Assembly (.toCompound()), or raw Shape.
        """
        if isinstance(solid, cq.Workplane):
            return solid.val()
        if hasattr(solid, "toCompound"):
            # cq.Assembly — convert to Compound for SVG rendering
            return solid.toCompound()
        return solid


def _extract_parts_from_namespace(
    namespace: dict | None,
) -> list[tuple[object, str]] | None:
    """Extract positioned parts from an Assembly found in the exec namespace.

    Looks for a cq.Assembly object, then iterates its children to get
    each part's shape at its assembly position. Used for colored rendering.

    Assembly.objects contains UUID-keyed internal bookkeeping nodes with
    obj=None (including the root); those are skipped.

    Returns list of (positioned_shape, part_name) or None if extraction fails.
    """
    if namespace is None:
        _log("[renderer] No namespace available for colored rendering")
        return None

    # Find Assembly object (skip 'result' which is the flattened compound)
    assy = None
    for name, val in namespace.items():
        if isinstance(val, cq.Assembly) and name != "result":
            assy = val
            break

    if assy is None:
        return None

    # Extract children with their assembly positions
    parts: list[tuple[object, str]] = []
    try:
        for child_name, child_assy in assy.objects.items():
            if child_assy.obj is None:
                continue
            shape = child_assy.obj
            if hasattr(shape, "val"):
                shape = shape.val()
            positioned = shape.moved(child_assy.loc)
            parts.append((positioned, child_name))
    except Exception:
        return None

    return parts if len(parts) >= 2 else None


def _legend_with_names(color_map: dict) -> dict:
    """Convert {part: (r,g,b)} to {part: {"color": name, "rgb": [r,g,b]}}."""
    rgb_to_name = {rgb: name for rgb, name in
                   zip(ASSEMBLY_PART_COLORS, ASSEMBLY_COLOR_NAMES)}
    return {
        part: {"color": rgb_to_name.get(tuple(rgb), "unknown"), "rgb": list(rgb)}
        for part, rgb in color_map.items()
    }


def _write_color_legend(renders_dir: Path, legend: dict) -> Path:
    """Write the human/agent-readable color legend text file."""
    lines = ["Assembly color legend (part -> stroke color):"]
    for part, info in legend.items():
        r, g, b = info["rgb"]
        lines.append(f"  {part}: {info['color']} (RGB {r},{g},{b})")
    legend_path = renders_dir / "color_legend.txt"
    legend_path.write_text("\n".join(lines) + "\n")
    return legend_path


def _run_views_mode(args) -> dict:
    """Render 8 views of a single part; deterministic dimension check included."""
    part_dir = Path(args.part_path)
    # --code-file overrides which script is executed (e.g. part.proposal.py);
    # outputs (renders/, dimension check) stay anchored to --part-path.
    code_file = Path(args.code_file) if args.code_file else part_dir / "part.py"

    if not code_file.exists():
        return {"success": False, "png_paths": [], "legend": None,
                "dimension_check": None,
                "error_message": f"No {code_file.name} found at {code_file}"}

    # Infer project root for __project_path__ (canonical layout:
    # projects/<name>/assembly/<part>/); harmless if the layout differs.
    project_path = part_dir.parent.parent if part_dir.parent.name == "assembly" else None

    _log(f"[renderer] Executing {code_file}")
    solid, _namespace, error = execute_cad_script(code_file.read_text(), project_path)
    if solid is None:
        return {"success": False, "png_paths": [], "legend": None,
                "dimension_check": None,
                "error_message": f"{code_file.name} failed to execute: {error}"}

    renders_dir = part_dir / "renders"
    renderer = CadQueryRenderer(width=args.width, height=args.height)
    result = renderer.render_views(solid, renders_dir)
    _log(f"[renderer] Rendered {len(result.views)} views -> {renders_dir}")

    # Deterministic dimension check — runs every time views are rendered.
    # Non-critical: bbox extraction can fail on compounds; check needs constraints.md.
    dimension_check = None
    constraints_file = part_dir / "constraints.md"
    if constraints_file.exists():
        bbox = bbox_of(solid)
        if bbox is not None:
            dimension_check = check_dimensions(bbox, constraints_file.read_text())
            if dimension_check and not dimension_check["pass"]:
                _log(f"[renderer] DIMENSION CHECK FAILED — {dimension_check['deviations']}")

    return {"success": True,
            "png_paths": [str(p) for p in result.views.values()],
            "legend": None,
            "dimension_check": dimension_check,
            "error_message": None}


def _run_assembly_mode(args) -> dict:
    """Render 8 views of the project assembly, colored per part when possible."""
    project_dir = Path(args.project)
    assembly_dir = project_dir / "assembly"
    assembly_py = assembly_dir / "assembly.py"

    if not assembly_py.exists():
        return {"success": False, "png_paths": [], "legend": None,
                "dimension_check": None,
                "error_message": f"No assembly/assembly.py found under {project_dir}"}

    _log(f"[renderer] Executing {assembly_py}")
    solid, namespace, error = execute_cad_script(assembly_py.read_text(), project_dir)
    if solid is None:
        return {"success": False, "png_paths": [], "legend": None,
                "dimension_check": None,
                "error_message": f"assembly.py failed to execute: {error}"}

    renders_dir = assembly_dir / "renders"
    renderer = CadQueryRenderer(width=args.width, height=args.height)

    # Try colored rendering first (extract parts from Assembly), fall back to
    # monochrome when extraction or colored rendering fails.
    legend = None
    parts = _extract_parts_from_namespace(namespace)
    result = None
    if parts:
        try:
            result = renderer.render_assembly_views(parts, solid, renders_dir)
            color_map = result.metadata.get("color_legend")
            if result.views and color_map:
                legend = _legend_with_names(color_map)
                legend_path = _write_color_legend(renders_dir, legend)
                _log(f"[renderer] Colored assembly rendering — {len(parts)} parts, "
                     f"legend -> {legend_path}")
            else:
                _log(f"[renderer] Colored rendering produced no views "
                     f"({result.metadata.get('error')}), falling back to monochrome")
                result = None
        except Exception:
            import traceback
            _log(f"[renderer] Colored rendering failed, falling back to monochrome:\n"
                 f"{traceback.format_exc()}")
            result = None
            legend = None

    if result is None:
        _log("[renderer] Monochrome assembly rendering")
        result = renderer.render_views(solid, renders_dir)

    _log(f"[renderer] Rendered {len(result.views)} views -> {renders_dir}")
    return {"success": True,
            "png_paths": [str(p) for p in result.views.values()],
            "legend": legend,
            "dimension_check": None,
            "error_message": None}


def main(argv: list[str] | None = None) -> int:
    """CLI entry point: dispatch to views or assembly mode, print the JSON verdict."""
    parser = argparse.ArgumentParser(
        prog="python -m tools.renderer",
        description="Render 8 individual PNGs (4 views x 2 styles) for a part or a colored assembly.",
    )
    parser.add_argument("--mode", required=True, choices=["views", "assembly"],
                        help="views = single part (needs --part-path); "
                             "assembly = whole project assembly (needs --project)")
    parser.add_argument("--part-path", help="Part directory containing part.py (views mode)")
    parser.add_argument("--code-file",
                        help="Script to execute instead of <part-path>/part.py "
                             "(e.g. part.proposal.py); PNGs still go to <part-path>/renders/ (views mode)")
    parser.add_argument("--project", help="Project directory containing assembly/assembly.py (assembly mode)")
    parser.add_argument("--width", type=int, default=1600, help="Render width px (default 1600)")
    parser.add_argument("--height", type=int, default=1200, help="Render height px (default 1200)")
    args = parser.parse_args(argv)

    if args.mode == "views" and not args.part_path:
        parser.error("--mode=views requires --part-path")
    if args.mode == "assembly" and not args.project:
        parser.error("--mode=assembly requires --project")

    try:
        output = _run_views_mode(args) if args.mode == "views" else _run_assembly_mode(args)
    except Exception:
        # Tool malfunction (not an artifact failure) — full traceback, exit != 0
        import traceback
        print(json.dumps({"success": False, "png_paths": [], "legend": None,
                          "dimension_check": None,
                          "error_message": f"Renderer tool crashed: {traceback.format_exc()}"}))
        return 1

    print(json.dumps(output, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
