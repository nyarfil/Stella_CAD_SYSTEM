---
name: cadquery-anti-hallucination
description: Catalog of CadQuery methods that DO NOT EXIST (commonly hallucinated by LLMs) with the correct alternative for each, plus the runtime error-to-hint enrichment table the executor applies. Use when a CadQuery execution fails (especially AttributeError on Workplane or selectors), when repairing failed code, when an error message contains "HINT:", and as a final check before finalizing any generated CadQuery code.
---

# CadQuery Anti-Hallucination Catalog

LLMs reliably hallucinate the same non-existent CadQuery methods (often confusing
CadQuery with Build123d, OpenSCAD, or imagined APIs).
This catalog lists every known hallucination and its correct replacement.
Ground truth for what exists:
`cadquery-cookbook/API_SURFACE.md`: **if a method is not listed there, it DOES NOT EXIST.**

## Methods That DO NOT EXIST, with correct alternatives

| Hallucinated | Reality: use instead |
|---|---|
| `.hull()`, `Wire.makeHull()` | No hull operation exists. Draw the profile with `.polyline()` + `.close()` + `.extrude()`, or compose solids with boolean `.union()`. For I-beam/H-beam sections: polyline the profile. For connecting two circular ends with a tapered beam: create each cylinder separately, then `.union()` them with a rectangular beam body. |
| `.cone()` | Not a Workplane method. Use `cq.Solid.makeCone(radius1, radius2, height)`, or loft a large circle to a tiny one (COOKBOOK Principle 2). |
| `.torus()` | Use `cq.Solid.makeTorus(r1, r2)`. |
| `.helix()` | Use `cq.Wire.makeHelix(pitch, height, radius)`. |
| `.thread()`, `.threadedHole()` | No thread methods. Build threads manually via `.parametricCurve()` + ruled surfaces (COOKBOOK Pattern 6). |
| `.scale()` | Does not exist on Workplane. Recompute dimensions parametrically instead of scaling. |
| `.offset3D()` | Does not exist. Use `.shell()` for wall offsets or `.offset2D()` on wires. |
| `.hole_pattern()` | Does not exist. Use `.rarray()` / `.polarArray()` + `.hole()` (see `cadquery_array_operations.md`). |
| `.fillet2D()` | Does not exist. Apply `.fillet()` to 3D edges AFTER extrude. (Note: fillets are deferred project-wide anyway.) |
| `cq.selectors.And` | Does not exist. Use string combinations `.edges('|Z and >Y')` or `cq.selectors.AndSelector(sel1, sel2)`. |
| `cq.selectors.OrSelector` | Does not exist. Use string selectors with `or`: `.edges('|Z or |X')`. |
| `cq.Circle` | Does not exist. Use `.circle(radius)` on a Workplane. |
| `cq.selectors.EdgeCylinderSelector` | Does not exist. Use the string selector `"%CIRCLE"` for circular edges. |
| `.extrude(centered=True)` | CadQuery's `extrude()` has NO `centered` kwarg: that is Build123d. Signature: `extrude(until, combine=True, clean=True, both=False, taper=None)`. Use `.extrude(length)` + `.translate()` to center. Note: `both=True` IS valid. |
| Color names `'silver'`, `'gold'`, CSS names | Valid `cq.Color` names: red, green, blue, gray, lightgray, white, black, yellow, orange, cyan, magenta, brown, pink. |

## Runtime error enrichment (what the executor appends)

The CadQuery executor tool (`uv run python -m tools.cadquery_executor`)
matches failed executions against the patterns below
and appends a corrective `HINT:` to the error message,
breaking the hallucination loop. **When you see `HINT:` in an execution error, follow it:
it names the correct API.** The 10 pattern→hint pairs:

| Error contains | Appended hint (summary) |
|---|---|
| `has no attribute 'hull'` | `.hull()` doesn't exist → `.polyline()`+`.close()`+`.extrude()`, or boolean `.union()` of separate solids |
| `has no attribute 'fillet2D'` | `.fillet2D()` doesn't exist → `.fillet()` on 3D edges after extrude |
| `has no attribute 'cone'` | `.cone()` doesn't exist → `cq.Solid.makeCone(radius1, radius2, height)` |
| `has no attribute 'And'` | `cq.selectors.And` doesn't exist → `.edges('|Z and >Y')` or `AndSelector(sel1, sel2)` |
| `has no attribute 'OrSelector'` | doesn't exist → string selectors with `or`: `.edges('|Z or |X')` |
| `has no attribute 'Circle'` | `cq.Circle` doesn't exist → `.circle(radius)` on a Workplane |
| `has no attribute 'makeHull'` | `Wire.makeHull()` doesn't exist → `.polyline()` + `.close()` |
| `Unknown color name` | Only the 13 valid color names above; never 'silver'/'gold'/CSS names |
| `unexpected keyword argument 'centered'` | `extrude()` has no `centered` kwarg (Build123d confusion) → `.extrude(length)` + `.translate()` |
| `has no attribute 'EdgeCylinderSelector'` | doesn't exist → string selector `"%CIRCLE"` |

## Other execution contract facts (same failure family)

- **Result discovery:** the executor looks for a variable named `result`,
  falling back to the last `cq.Workplane` in the namespace.
  Always assign your final shape to `result`.
- **"Code executed successfully but produced no CadQuery Workplane"** → you forgot `result`.
- **Timeout** (default 30s) → the code likely has an infinite loop
  or pathologically expensive operation;
  simplify the geometry.
- `__project_path__` is injected into the exec namespace (assembly code uses it to locate
  `part.py` files). Never hardcode absolute paths.

## Pre-finalization checklist

Before declaring any generated CadQuery code done:
1. Grep your code for every method in the DO-NOT-EXIST table above.
2. For any method you are less than certain about, verify it against
   `cadquery-cookbook/API_SURFACE.md`.
3. Confirm the final shape is assigned to `result`.
4. Confirm no fillets were added (deferred project-wide).
