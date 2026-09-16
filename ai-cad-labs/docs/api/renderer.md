> Generated from the `tools/renderer.py` docstrings, never hand-edited.
> Regenerate with `uv run --frozen python tests/test_api_docs.py --write`.
<a id="tools.renderer"></a>

# tools.renderer

CadQuery renderer: bash-callable port of legacy `src/cad/renderer.py` +
the render_views/render_assembly tool wrappers from `src/tools/cadquery.py`.

Produces 8 renders per part/assembly: 4 views x 2 styles, as INDIVIDUAL PNGs
(never composited into a collage):

```
{front,top,right,iso}_{wireframe,clean}.png  ->  <target>/renders/
```

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
written to &lt;project&gt;/assembly/renders/color_legend.txt. Falls back to
monochrome rendering when parts cannot be extracted from the exec namespace.

CLI:
    uv run python -m tools.renderer --mode=views --part-path &lt;part-dir&gt; [--code-file &lt;script.py&gt;] [--width 1600 --height 1200]
    uv run python -m tools.renderer --mode=assembly --project &lt;project-dir&gt; [--width 1600 --height 1200]

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

<a id="tools.renderer.RenderResult"></a>

## RenderResult Objects

```python
@dataclass
class RenderResult()
```

Result of rendering a solid to multiple views.

metadata keys: "width", "height", "view_names", "styles",
"total_renders"; assembly renders add "color_legend"
({part_name: (r, g, b)}); failure paths set only "error".

<a id="tools.renderer.CadQueryRenderer"></a>

## CadQueryRenderer Objects

```python
class CadQueryRenderer()
```

Render CadQuery Workplane objects to multi-view PNG images.

Produces 8 images by default: 4 views x 2 styles (wireframe + clean).

<a id="tools.renderer.CadQueryRenderer.render_views"></a>

#### render\_views

```python
def render_views(solid: object,
                 output_dir: Path,
                 views: list[str] | None = None) -> RenderResult
```

Render a solid from multiple views in both wireframe and clean styles.

Produces files like: front_wireframe.png, front_clean.png, etc.
Total: len(views) x 2 styles = 8 images by default.

<a id="tools.renderer.CadQueryRenderer.render_assembly_views"></a>

#### render\_assembly\_views

```python
def render_assembly_views(parts: list[tuple[object, str]],
                          assembly_compound: object,
                          output_dir: Path,
                          views: list[str] | None = None) -> RenderResult
```

Render assembly with per-part colored strokes in 8 individual PNGs.

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

<a id="tools.renderer.main"></a>

#### main

```python
def main(argv: list[str] | None = None) -> int
```

CLI entry point: dispatch to views or assembly mode, print the JSON verdict.

