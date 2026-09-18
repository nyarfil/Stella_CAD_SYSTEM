# CadQuery Ecosystem Reference Index

> **Purpose:** This index maps the CadQuery ecosystem:
> 9 upstream repos, their golden examples, API patterns, and selectors.
> Use it to find existing implementations, patterns, and examples
> BEFORE writing new CadQuery code.
> Do not reinvent what already exists.
>
> **For Claude agents:** ALWAYS consult this index before generating CadQuery code.
> Grep within this file for the API method or technique you need.
> The distilled implementations ship as this directory's sibling docs:
> `API_SURFACE.md` (every public method), `COOKBOOK.md` (reusable patterns),
> `cadquery_shape_primitives.md` and `cadquery_array_operations.md` (visual cheatsheets),
> and each index entry names its upstream source file as provenance.
>
> **Path notation:** entries like `cadquery/examples/Ex001_Simple_Block.py`
> are *upstream* paths inside the GitHub repos linked in §1.
> They do NOT ship in this repository (only the five distilled docs above do).
> Browse them on GitHub when you want the full original source.

---

## 1. Repository Overview

| Repo | Upstream | Purpose | Key Value |
|------|----------|---------|-----------|
| **cadquery** | [CadQuery/cadquery](https://github.com/CadQuery/cadquery) | Core CadQuery library | API source code + 28 official examples |
| **cadquery-contrib** | [CadQuery/cadquery-contrib](https://github.com/CadQuery/cadquery-contrib) | Community examples & tutorials | 22 real-world examples + MCP server |
| **cadquery-plugins** | [CadQuery/cadquery-plugins](https://github.com/CadQuery/cadquery-plugins) | Extension plugins | 9 plugins showing how to extend CadQuery |
| **cadquery-massembly** | [bernhard-42/cadquery-massembly](https://github.com/bernhard-42/cadquery-massembly) | Mate-based assembly system | Assembly constraints + 6 examples |
| **cqparts** | [cqparts/cqparts](https://github.com/cqparts/cqparts) | Parametric component framework | Fastener library + parametric type system |
| **awesome-cadquery** | [CadQuery/awesome-cadquery](https://github.com/CadQuery/awesome-cadquery) | Curated resource directory | Ecosystem taxonomy + external links |
| **cq-cli** | [CadQuery/cq-cli](https://github.com/CadQuery/cq-cli) | Command-line interface | Export codec implementations |
| **CQ-editor** | [CadQuery/CQ-editor](https://github.com/CadQuery/CQ-editor) | GUI editor (PyQt) | CadQuery execution wrapper |
| **cadquery-server** | [lypwig/cadquery-server](https://github.com/lypwig/cadquery-server) | Web-based CadQuery IDE | Flask server + live reload |

---

## 2. Upstream Repository Layouts

For orientation when browsing the upstream sources on GitHub:

### cadquery (Core Library)
```
cadquery/
  cadquery/               # Source code
    cq.py                 # Workplane class (4,550 lines): THE core API
    assembly.py           # Assembly class (845 lines)
    selectors.py          # Selector DSL (896 lines, 7 selector types)
    sketch.py             # 2D Sketch API (1,368 lines)
    shapes.py             # Shape wrapper types
    __init__.py           # Public API surface (80 lines)
    occ_impl/             # OpenCascade wrapper layer
      shapes.py           # Low-level shape operations (189KB)
      geom.py             # Geometry primitives (35KB)
      assembly.py         # Assembly solver (27KB)
      solver.py           # Constraint solver (18KB)
      exporters/          # SVG, STL, STEP, DXF, etc.
      importers/          # DXF, STEP import
    plugins/              # Plugin extension point (empty: plugins in separate repo)
  examples/               # 28 official examples (Ex001-Ex026, Ex100-Ex101)
  tests/                  # 20+ test suites
  doc/                    # Sphinx documentation (28+ .rst files)
```

### cadquery-contrib (Community Examples)
```
cadquery-contrib/
  examples/               # 22 practical examples
    3D_Printer_Extruder_Support.py   # Real mechanical part with helpers
    Braille.py                       # Algorithmic design pattern
    Classic_OCC_Bottle.py            # Tutorial bottle
    cylindrical_gear.py              # Advanced gear with custom selector
    door.py                          # Assembly with constraints
    Involute_Gear.py                 # Mathematical involute profile
    Parametric_Enclosure.py          # Snap-fit electronics enclosure
    Remote_Enclosure.py              # Ergonomic remote control case
    Resin_Mold.py                    # Mold for resin casting
    Thread.py                        # Parametric screw threads
    Tetrakaidecahedron.py            # Foam cell + NumPy integration
    tray.py                          # Storage tray with DXF export
    hexagonal_drawers/               # Multi-part 3D-printable assembly
      assembly.py
      drawer.py, clip.py, insert.py, rail.py
    ...
  tutorials/              # 2 Jupyter notebooks
  mcp-server/             # AI assistant integration for CadQuery
```

### cadquery-plugins (Extensions)
```
cadquery-plugins/
  plugins/
    sampleplugin/         # Template for creating new plugins
    gear_generator/       # Spur, helical, planetary gears
    heatserts/            # Heat-insert placement (M3-M6)
    more_selectors/       # Additional selector functions
    localselectors/       # Enhanced face/edge selection
    apply_to_each_face/   # Apply operations to multiple faces
    cq_cache/             # Caching for expensive operations
    fragment/             # Boolean ops on multiple shapes
    freecad_import/       # Import FreeCAD models
    teardrop/             # Teardrop holes for 3D printing
  tests/                  # One test file per plugin
```

### cadquery-massembly (Assembly Mates)
```
cadquery-massembly/
  cadquery_massembly/
    massembly.py          # MAssembly class extending CadQuery Assembly
    mate.py               # Mate coordinate system (origin + axes + transforms)
    geom.py               # Geometry utilities (Circle class)
    cq_editor.py          # CQ-Editor visualization integration
  examples/cq-editor/
    1-disk_arm.py         # Simple mechanism with pivot
    2-hexapod.py          # 6-legged robot (243 lines, 40+ mates)
    3-jansen-linkage.py   # Walking mechanism (kinematics + numpy)
    4-bearing.py          # Radial bearing with ball packing
    5-door.py             # Door with V-slot extrusions + DXF import
    6-nested-assemblies.py # Hierarchical assembly patterns
```

### cqparts (Parametric Framework)
```
cqparts/
  src/cqparts/
    component.py          # Component base class (111 lines)
    part.py               # Part with make()/make_simple() (164 lines)
    assembly.py           # Assembly with make_components/make_constraints (442 lines)
    params/               # Parametric type system
      parameter.py        # Parameter descriptor base
      parametric_object.py # Metaclass for parametric objects
      types/              # Float, Int, Boolean, String, ComponentRef, etc.
    constraint/
      mate.py             # Mate attachment point (93 lines)
      constraints.py      # Fixed, Coincident constraints (82 lines)
      solver.py           # Constraint solver
    codec/                # Export format registry (SVG, STL, STEP, GLTF, etc.)
    display/              # Web rendering (three.js templates)
    catalogue/            # Hierarchical part library system
  src/cqparts_fasteners/  # Extensive fastener library
    bolts.py, screws.py, nuts.py
    fasteners/            # Nut-bolt, screw assembly classes
    solidtypes/           # Head shapes, thread profiles, drive types
  examples/
    toy_car.py            # Complete parametric car assembly (211 lines)
    servo.py, logo.py, fastener_easyinstall.py
```

### Smaller Repos
```
awesome-cadquery/   # Pure markdown: curated ecosystem directory
  README.md                   # Links to editors, plugins, libraries, tutorials

cq-cli/             # Command-line CadQuery runner
  src/cq_cli/
    main.py                   # CLI entry point
    cqcodecs/                 # Export format plugins (SVG, STL, STEP, DXF, etc.)

CQ-editor/          # PyQt GUI editor
  cq_editor/
    main_window.py            # Main editor UI
    cq_utils.py               # CadQuery execution wrapper

cadquery-server/    # Web-based IDE
  cq_server/
    server.py                 # Flask app with live-reload
    exporter.py               # Multi-format export orchestration
    module_manager.py         # Dynamic CadQuery script loading
  examples/                   # 4 web-ready examples
```

---

## 3. Golden Examples (Study These First)

These are the highest-quality, most instructive examples across all repos.
Ordered from foundational to advanced.

### Tier 1: Foundational (Start Here)
| File | What It Builds | Key Techniques |
|------|---------------|----------------|
| `cadquery/examples/Ex001_Simple_Block.py` | Basic box (80x60x10mm) | `Workplane("XY")`, `.box()`, parametric variables |
| `cadquery/examples/Ex003_Pillow_Block_With_Counterbored_Holes.py` | Block with 4 corner holes | `.cboreHole()`, `.rect(forConstruction=True)`, `.vertices()`, `.fillet()` |
| `cadquery/examples/Ex012_Creating_Workplanes_on_Faces.py` | Box with hole on top face | `.faces(">Z")`, `.workplane()` |

### Tier 2: Parametric Design Patterns
| File | What It Builds | Key Techniques |
|------|---------------|----------------|
| `cadquery/examples/Ex100_Lego_Brick.py` | Any 1xN Lego brick with studs | `.rarray()`, conditional logic, thin-wall shells, stud patterns |
| `cadquery-contrib/examples/Parametric_Enclosure.py` | Snap-fit electronics enclosure | `.split()` for lid, lip creation, screw posts |
| `cadquery-contrib/examples/3D_Printer_Extruder_Support.py` | 3D printer hotend bracket | Helper functions, `.rarray()`, advanced face/edge selection |

### Tier 3: Advanced Geometry
| File | What It Builds | Key Techniques |
|------|---------------|----------------|
| `cadquery/examples/Ex101_InterpPlate.py` | Complex curved surfaces (4 demos) | `.interpPlate()`, edge wires, surface points, hex patterns |
| `cadquery-contrib/examples/cylindrical_gear.py` | Involute gear with helicity | Custom `HollowCylinderSelector`, `.parametricCurve()`, `.twistExtrude()` |
| `cadquery-contrib/examples/Thread.py` | Parametric screw threads | `.parametricCurve()` helix, `Face.makeRuledSurface()` |

### Tier 4: Assembly & Constraints
| File | What It Builds | Key Techniques |
|------|---------------|----------------|
| `cadquery-contrib/examples/door.py` | Door frame with panel + handle | `cq.Assembly()`, `.constrain()`, `.solve()`, DXF import |
| `cadquery-massembly/examples/cq-editor/2-hexapod.py` | 6-legged walking robot | `MAssembly`, 40+ mates, nested assemblies, kinematics |
| `cqparts/examples/toy_car.py` | Wheeled car (chassis, axles, wheels) | cqparts `Part`/`Assembly`, `make_components()`/`make_constraints()` |
| `cadquery-massembly/examples/cq-editor/5-door.py` | Door with V-slot extrusions | DXF profile import, `.sweep()` for handle, constraint chains |

### Tier 5: Specialized Techniques
| File | What It Builds | Key Techniques |
|------|---------------|----------------|
| `cadquery-contrib/examples/Braille.py` | Embossed braille text plate | Algorithmic design, Unicode bit patterns, `.pushPoints()` |
| `cadquery-massembly/examples/cq-editor/3-jansen-linkage.py` | Walking mechanism | Kinematics + numpy, link callbacks |
| `cadquery-contrib/examples/tray.py` | Divider tray with DXF export | `Assembly` with `Location`/`Color`, numpy linspace, manufacturing-ready |

---

## 4. Full Example Catalog by Domain

### Basic Primitives & Shapes
| File | Complexity | LOC | Parametric |
|------|-----------|-----|-----------|
| `cadquery/examples/Ex001_Simple_Block.py` | Beginner | 20 | Yes |
| `cadquery/examples/Ex002_Block_With_Bored_Center_Hole.py` | Beginner | 26 | Yes |
| `cadquery/examples/Ex004_Extruded_Cylindrical_Plate.py` | Beginner | 32 | Yes |
| `cadquery/examples/Ex008_Polygon_Creation.py` | Beginner | 43 | Yes |

### Workplane Manipulation
| File | Complexity | LOC | Parametric |
|------|-----------|-----|-----------|
| `cadquery/examples/Ex006_Moving_the_Current_Working_Point.py` | Beginner | 36 | Yes |
| `cadquery/examples/Ex007_Using_Point_Lists.py` | Beginner | 33 | Yes |
| `cadquery/examples/Ex012_Creating_Workplanes_on_Faces.py` | Beginner | 17 | Yes |
| `cadquery/examples/Ex013_Locating_a_Workplane_on_a_Vertex.py` | Beginner | 22 | Yes |
| `cadquery/examples/Ex014_Offset_Workplanes.py` | Intermediate | 21 | Yes |
| `cadquery/examples/Ex015_Rotated_Workplanes.py` | Intermediate | 29 | Yes |
| `cadquery/examples/Ex016_Using_Construction_Geometry.py` | Intermediate | 27 | Yes |

### Sketching (2D Profiles → 3D)
| File | Complexity | LOC | Parametric |
|------|-----------|-----|-----------|
| `cadquery/examples/Ex005_Extruded_Lines_and_Arcs.py` | Intermediate | 50 | Yes |
| `cadquery/examples/Ex009_Polylines.py` | Intermediate | 37 | Yes |
| `cadquery/examples/Ex010_Defining_an_Edge_with_a_Spline.py` | Intermediate | 27 | Yes |
| `cadquery/examples/Ex011_Mirroring_Symmetric_Geometry.py` | Intermediate | 37 | Yes |

### Boolean & Shell Operations
| File | Complexity | LOC | Parametric |
|------|-----------|-----|-----------|
| `cadquery/examples/Ex017_Shelling_to_Create_Thin_Features.py` | Intermediate | 15 | Yes |
| `cadquery/examples/Ex019_Counter_Sunk_Holes.py` | Intermediate | 26 | Yes |
| `cadquery/examples/Ex020_Rounding_Corners_with_Fillets.py` | Beginner | 14 | Yes |
| `cadquery/examples/Ex021_Splitting_an_Object.py` | Intermediate | 25 | Yes |

### Revolution, Sweep & Loft
| File | Complexity | LOC | Parametric |
|------|-----------|-----|-----------|
| `cadquery/examples/Ex018_Making_Lofts.py` | Intermediate | 26 | Yes |
| `cadquery/examples/Ex022_Revolution.py` | Advanced | 22 | Yes |
| `cadquery/examples/Ex023_Sweep.py` | Advanced | 37 | Yes |
| `cadquery/examples/Ex024_Sweep_With_Multiple_Sections.py` | Advanced | 89 | Yes |
| `cadquery/examples/Ex025_Swept_Helix.py` | Advanced | 21 | Yes |

### Mechanical Parts
| File | Complexity | LOC | Parametric |
|------|-----------|-----|-----------|
| `cadquery-contrib/examples/Involute_Gear.py` | Intermediate | 83 | Yes |
| `cadquery-contrib/examples/cylindrical_gear.py` | Advanced | 133 | Yes |
| `cadquery-contrib/examples/Thread.py` | Advanced | 66 | Yes |
| `cadquery-massembly/examples/cq-editor/4-bearing.py` | Intermediate | 81 | Yes |
| `cadquery-plugins/plugins/gear_generator/` | Advanced | - | Yes |

### Enclosures & Housings
| File | Complexity | LOC | Parametric |
|------|-----------|-----|-----------|
| `cadquery-contrib/examples/Parametric_Enclosure.py` | Advanced | 77 | Yes |
| `cadquery-contrib/examples/Remote_Enclosure.py` | Advanced | 86 | Yes |
| `cadquery/examples/Ex026_Case_Seam_Lip.py` | Advanced | 48 | Yes |
| `cadquery/examples/Ex100_Lego_Brick.py` | Advanced | 71 | Yes |

### Assemblies & Mechanisms
| File | Complexity | LOC | Parametric |
|------|-----------|-----|-----------|
| `cadquery-contrib/examples/door.py` | Advanced | 145 | Yes |
| `cadquery-massembly/examples/cq-editor/1-disk_arm.py` | Intermediate | 87 | Yes |
| `cadquery-massembly/examples/cq-editor/2-hexapod.py` | Advanced | 243 | Yes |
| `cadquery-massembly/examples/cq-editor/3-jansen-linkage.py` | Advanced | 136 | Yes |
| `cadquery-massembly/examples/cq-editor/5-door.py` | Advanced | 174 | Yes |
| `cadquery-massembly/examples/cq-editor/6-nested-assemblies.py` | Intermediate | 98 | No |
| `cqparts/examples/toy_car.py` | Advanced | 211 | Yes |

### Special Techniques
| File | Complexity | LOC | Parametric |
|------|-----------|-----|-----------|
| `cadquery-contrib/examples/Braille.py` | Advanced | 185 | Yes |
| `cadquery-contrib/examples/Tetrakaidecahedron.py` | Advanced | 100 | Yes |
| `cadquery-contrib/examples/Resin_Mold.py` | Intermediate | 61 | Yes |
| `cadquery-contrib/examples/tray.py` | Advanced | 110 | Yes |
| `cadquery/examples/Ex101_InterpPlate.py` | Advanced | 176 | Yes |

---

## 5. API Pattern → File Lookup Table

When you need to use a specific CadQuery API, find the best reference file here.

### Shape Creation
| API Method | Best Reference File | Line | Notes |
|-----------|-------------------|------|-------|
| `.box()` | `cadquery/examples/Ex001_Simple_Block.py` | 12 | Basic 3D box |
| `.circle()` | `cadquery/examples/Ex004_Extruded_Cylindrical_Plate.py` | 26 | Circle for extrusion |
| `.polygon()` | `cadquery/examples/Ex008_Polygon_Creation.py` | 37 | N-sided polygon |
| `.rect()` | `cadquery/examples/Ex016_Using_Construction_Geometry.py` | 20 | Rectangle (also forConstruction) |
| `.sphere()` | `cq-cli/tests/testdata/sphere.py` | - | Sphere primitive |
| `.torus()` | `cadquery-massembly/examples/cq-editor/4-bearing.py` | - | Via `Solid.makeTorus()` |

### 3D Operations
| API Method | Best Reference File | Line | Notes |
|-----------|-------------------|------|-------|
| `.extrude()` | `cadquery/examples/Ex004_Extruded_Cylindrical_Plate.py` | 28 | Extrude 2D → 3D |
| `.revolve()` | `cadquery/examples/Ex022_Revolution.py` | 11 | Revolve profile around axis |
| `.sweep()` | `cadquery/examples/Ex023_Sweep.py` | 10 | Sweep along path |
| `.sweep()` multisection | `cadquery/examples/Ex024_Sweep_With_Multiple_Sections.py` | 15 | Multi-section sweep |
| `.sweep()` helix | `cadquery/examples/Ex025_Swept_Helix.py` | - | Sweep on helix path |
| `.loft()` | `cadquery/examples/Ex018_Making_Lofts.py` | 21 | Loft between profiles |
| `.shell()` | `cadquery/examples/Ex017_Shelling_to_Create_Thin_Features.py` | 11 | Hollow out solid |
| `.split()` | `cadquery/examples/Ex021_Splitting_an_Object.py` | - | Split solid with plane |
| `.interpPlate()` | `cadquery/examples/Ex101_InterpPlate.py` | - | Complex curved surfaces |

### Boolean Operations
| API Method | Best Reference File | Line | Notes |
|-----------|-------------------|------|-------|
| `.cut()` | `cadquery-contrib/examples/Resin_Mold.py` | 41 | Subtract solid from solid |
| `.cutThruAll()` | `cadquery/examples/Ex008_Polygon_Creation.py` | 38 | Cut through entire part |
| `.cutBlind()` | `cadquery/examples/Ex026_Case_Seam_Lip.py` | 22 | Cut to specific depth |
| `.union()` | `cadquery-massembly/examples/cq-editor/1-disk_arm.py` | 21 | Join solids |
| `.combine()` | `cadquery/examples/Ex018_Making_Lofts.py` | 21 | Combine with base |

### Edge Treatments
| API Method | Best Reference File | Line | Notes |
|-----------|-------------------|------|-------|
| `.fillet()` | `cadquery/examples/Ex020_Rounding_Corners_with_Fillets.py` | 10 | Round edges |
| `.fillet()` large | `cadquery-contrib/examples/Resin_Mold.py` | 39 | Fillet radius 18 |
| `.chamfer()` | `cadquery-contrib/examples/Shelled_Cube_Inside_Chamfer_With_Logical_Selector_Operators.py` | 8 | Bevel edges |

### Holes
| API Method | Best Reference File | Line | Notes |
|-----------|-------------------|------|-------|
| `.hole()` | `cadquery/examples/Ex002_Block_With_Bored_Center_Hole.py` | 21 | Simple through-hole |
| `.cboreHole()` | `cadquery/examples/Ex003_Pillow_Block_With_Counterbored_Holes.py` | 38 | Counterbored hole |
| `.cskHole()` | `cadquery/examples/Ex019_Counter_Sunk_Holes.py` | 21 | Countersunk hole |
| `.heatsert()` | `cadquery-plugins/plugins/heatserts/heatserts.py` | - | Heat-insert hole (M3-M6) |

### Workplane Navigation
| API Method | Best Reference File | Line | Notes |
|-----------|-------------------|------|-------|
| `.workplane()` | `cadquery/examples/Ex002_Block_With_Bored_Center_Hole.py` | 13 | New workplane on face |
| `.workplane(offset=)` | `cadquery/examples/Ex014_Offset_Workplanes.py` | - | Offset from face |
| `.transformed(rotate=)` | `cadquery/examples/Ex015_Rotated_Workplanes.py` | - | Rotated workplane |
| `.center()` | `cadquery-contrib/examples/Resin_Mold.py` | 55 | Move workplane origin |
| `.pushPoints()` | `cadquery/examples/Ex008_Polygon_Creation.py` | 36 | Array of points |
| `.rarray()` | `cadquery/examples/Ex100_Lego_Brick.py` | - | Rectangular array |
| `.tag()` / `.end()` | `cadquery-contrib/examples/door.py` | 36 | Tag objects for later reference |

### Sketching (2D Wire Construction)
| API Method | Best Reference File | Line | Notes |
|-----------|-------------------|------|-------|
| `.lineTo()` | `cadquery/examples/Ex005_Extruded_Lines_and_Arcs.py` | - | Line to absolute point |
| `.polyline()` | `cadquery-contrib/examples/door.py` | 69 | Multi-segment line |
| `.spline()` | `cadquery/examples/Ex010_Defining_an_Edge_with_a_Spline.py` | 21 | Spline through points |
| `.threePointArc()` | `cadquery/examples/Ex005_Extruded_Lines_and_Arcs.py` | 41 | Arc through 3 points |
| `.sagittaArc()` | `cadquery/examples/Ex005_Extruded_Lines_and_Arcs.py` | 42 | Arc by sagitta |
| `.radiusArc()` | `cadquery/examples/Ex005_Extruded_Lines_and_Arcs.py` | 43 | Arc by radius |
| `.mirrorY()` | `cadquery/examples/Ex011_Mirroring_Symmetric_Geometry.py` | - | Mirror across Y axis |
| `.close()` | `cadquery/examples/Ex010_Defining_an_Edge_with_a_Spline.py` | 21 | Close wire |
| `.offset2D()` | `cadquery/examples/Ex026_Case_Seam_Lip.py` | 16 | 2D offset of wire |
| `.parametricCurve()` | `cadquery-contrib/examples/Thread.py` | 29 | Mathematical parametric curves |

### Assembly Operations
| API Method | Best Reference File | Line | Notes |
|-----------|-------------------|------|-------|
| `cq.Assembly()` | `cadquery-contrib/examples/door.py` | 91 | Create assembly |
| `.add()` | `cadquery-contrib/examples/door.py` | 92 | Add part to assembly |
| `.constrain()` | `cadquery-contrib/examples/door.py` | 116 | Plane/Axis/Point constraints |
| `.solve()` | `cadquery-contrib/examples/door.py` | 143 | Solve constraints |
| `MAssembly()` | `cadquery-massembly/examples/cq-editor/1-disk_arm.py` | 64 | Mate-based assembly |
| `.mate()` | `cadquery-massembly/examples/cq-editor/1-disk_arm.py` | 72 | Define assembly mates |
| `.assemble()` | `cadquery-massembly/examples/cq-editor/1-disk_arm.py` | 83 | Solve mate alignment |

### Export & Import
| API Method | Best Reference File | Notes |
|-----------|-------------------|-------|
| `.toSvg()` | `cadquery/cadquery/occ_impl/exporters/svg.py` | SVG export source |
| `exportStep()` | `cq-cli/src/cq_cli/cqcodecs/cq_codec_step.py` | STEP codec |
| `exportStl()` | `cq-cli/src/cq_cli/cqcodecs/cq_codec_stl.py` | STL codec |
| `exportDxf()` | `cq-cli/src/cq_cli/cqcodecs/cq_codec_dxf.py` | DXF codec |
| `importDXF()` | `cadquery-contrib/examples/door.py` | DXF profile import |
| All codecs | `cq-cli/src/cq_cli/cqcodecs/` | Complete codec directory |

---

## 6. Selector Patterns Reference

Selectors are how CadQuery queries geometry.
Master these for precise feature targeting.

### Direction Selectors
| Selector | Meaning | Example File |
|----------|---------|-------------|
| `">Z"` | Face/edge with max Z (top) | `cadquery/examples/Ex002_Block_With_Bored_Center_Hole.py` |
| `"<Z"` | Face/edge with min Z (bottom) | - |
| `">X"`, `"<X"` | Max/min X faces | `cadquery/examples/Ex026_Case_Seam_Lip.py` |
| `">Y"`, `"<Y"` | Max/min Y faces | - |
| `"\|Z"` | Edges parallel to Z axis | `cadquery/examples/Ex020_Rounding_Corners_with_Fillets.py` |
| `"\|X"`, `"\|Y"` | Edges parallel to X/Y | `cadquery-massembly/examples/cq-editor/1-disk_arm.py` |

### Nth Selectors
| Selector | Meaning | Example File |
|----------|---------|-------------|
| `">Z[-2]"` | 2nd from top Z face | `cadquery/examples/Ex026_Case_Seam_Lip.py` |

### Logical Selectors
| Selector | Meaning | Example File |
|----------|---------|-------------|
| `"not(<X or >X or >Y)"` | Logical NOT + OR | `cadquery-contrib/examples/Shelled_Cube_Inside_Chamfer_With_Logical_Selector_Operators.py` |

### Type Selectors
| Selector | Meaning | Example File |
|----------|---------|-------------|
| `"%CIRCLE"` | Circular edges/faces | `cadquery-contrib/examples/door.py` |

### Programmatic Selectors
| Selector Class | Purpose | Example File |
|---------------|---------|-------------|
| `BoxSelector(p1, p2)` | Select by bounding box | `cadquery-contrib/examples/Resin_Mold.py` |
| `NearestToPointSelector(pt)` | Select nearest to point | `cadquery-massembly/examples/cq-editor/1-disk_arm.py` |
| `AreaNthSelector(n)` | Select by area ranking | `cadquery/examples/Ex026_Case_Seam_Lip.py` |
| Custom subclass | Extend `Selector.filter()` | `cadquery-contrib/examples/cylindrical_gear.py` (HollowCylinderSelector) |

### Selector Source Code
| File | What It Contains |
|------|-----------------|
| `cadquery/cadquery/selectors.py` | All 7 base selector classes (896 lines) |
| `cadquery-plugins/plugins/more_selectors/` | Additional community selectors |
| `cadquery-plugins/plugins/localselectors/` | Enhanced face/edge selection |

---

## 7. Architecture Patterns

### Pattern 1: Fluent Builder (CadQuery Core)
CadQuery's `Workplane` methods return `self` for method chaining.
```
Source: cadquery/cadquery/cq.py (4,550 lines)
```
- Every method returns `Workplane` for chaining
- Internal stack tracks pending wires/edges/objects
- `CQContext` provides shared mutable state across chain
- `.tag()` / `.end()` for branching and returning to previous state

### Pattern 2: Parametric Component (cqparts)
Descriptor-based parameters with type checking and defaults.
```
Source: cqparts/src/cqparts/part.py (164 lines)
Source: cqparts/src/cqparts/params/parametric_object.py
```
- Parameters defined as class attributes: `diameter = PositiveFloat(5.0)`
- `make()` method generates geometry: override in subclass
- `make_simple()` optional simplified version for rendering
- Caching: `local_obj` and `world_obj` computed lazily

### Pattern 3: Assembly Build Cycle (cqparts)
Three-phase assembly construction.
```
Source: cqparts/src/cqparts/assembly.py (442 lines)
```
1. `make_components()` → returns `Dict[str, Component]`
2. `make_constraints()` → returns `List[Constraint]`
3. `make_alterations()` → optional post-solve modifications
- Best example: `cqparts/examples/toy_car.py`

### Pattern 4: Mate-Based Assembly (cadquery-massembly)
Coordinate-system mates with transformation chains.
```
Source: cadquery-massembly/cadquery_massembly/mate.py (150 lines)
Source: cadquery-massembly/cadquery_massembly/massembly.py (150+ lines)
```
- `Mate(origin, x_dir, z_dir)` defines attachment point
- Transforms: `.rx()`, `.ry()`, `.rz()`, `.tx()`, `.ty()`, `.tz()`
- Hierarchical: parent transforms propagate to children
- Best example: `cadquery-massembly/examples/cq-editor/2-hexapod.py`

### Pattern 5: Plugin Extension (cadquery-plugins)
Monkey-patching new methods onto `cq.Workplane`.
```
Source: cadquery-plugins/plugins/sampleplugin/sampleplugin.py
Source: cadquery-plugins/plugins/heatserts/heatserts.py
```
- Define function `(self, *args) -> Workplane`
- Assign: `cq.Workplane.method_name = function`
- Use `self.eachpoint()` for multi-point operations
- Use `self.cutEach()` for boolean cuts at each point

### Pattern 6: Constraint Solver (CadQuery vs cqparts vs massembly)
Three different approaches to assembly constraints exist in the ecosystem:

| System | Source | Approach |
|--------|--------|----------|
| CadQuery Assembly | `cadquery/cadquery/assembly.py` | OCCT solver, binary constraints (Plane/Axis/Point) |
| cqparts | `cqparts/src/cqparts/constraint/` | Custom solver, Fixed/Coincident constraints |
| MAssembly | `cadquery-massembly/cadquery_massembly/` | DOF-based, mate alignment with transforms |

### Pattern 7: Common Import Patterns
```python
# Standard CadQuery
import cadquery as cq
result = cq.Workplane("XY").box(10, 10, 10)

# Assembly
assy = cq.Assembly()
assy.add(part, name="part1", color=cq.Color("red"))
assy.constrain("part1@faces@>Z", "part2@faces@<Z", "Plane")
assy.solve()

# cqparts parametric
from cqparts import Part, Assembly
from cqparts.params import PositiveFloat
from cqparts.constraint import Mate, Coincident, Fixed

# MAssembly
from cadquery_massembly import MAssembly, Mate
```

---

## 8. Key Source Files Quick Reference

The most instructive upstream source files, in priority order
(browse them in the repos linked in §1):

| Priority | File | Lines | What You Learn |
|----------|------|-------|---------------|
| 1 | `cadquery/cadquery/cq.py` | 4,550 | Complete Workplane API: every method available |
| 2 | `cadquery/cadquery/selectors.py` | 896 | Selector DSL: how to target faces/edges/vertices |
| 3 | `cadquery/examples/Ex100_Lego_Brick.py` | 71 | Best parametric design pattern |
| 4 | `cadquery-contrib/examples/door.py` | 145 | Assembly constraints workflow |
| 5 | `cadquery/cadquery/assembly.py` | 845 | Assembly API internals |
| 6 | `cqparts/src/cqparts/part.py` | 164 | Parametric Part pattern |
| 7 | `cadquery-massembly/cadquery_massembly/mate.py` | 150 | Mate coordinate system |
| 8 | `cadquery-plugins/plugins/sampleplugin/sampleplugin.py` | ~20 | Plugin extension pattern |
| 9 | `cadquery/cadquery/sketch.py` | 1,368 | 2D Sketch API |
| 10 | `cadquery-contrib/examples/cylindrical_gear.py` | 133 | Custom selectors + parametric curves |

---

## 9. Visual Cheatsheets (Standalone References)

Two standalone markdown cheatsheets (**shipped in this repo**)
with code + visual output for every primitive:

| File | What It Covers |
|------|---------------|
| `reference/cadquery_shape_primitives.md` | Every shape: Box, Cone (`Solid.makeCone`), Cylinder, Sphere, Text, Torus (`Solid.makeTorus`), Wedge, Helix (`Wire.makeHelix`), all Sketch shapes, all 2D shapes, operations (chamfer, extrude, fillet, hole, loft, shell, sweep, translate, twistExtrude), hole types (cboreHole, cskHole) |
| `reference/cadquery_array_operations.md` | Array patterns: `polarArray`, `rarray`, `eachpoint` with visual examples |

These fill the gap for primitives that had no examples in the main repos
(cone, torus, helix, wedge, text).

---

## 10. Research Repos (Design Best Practices)

Two MPI-SWS research repos (`ipcad`, `prodmcad`)
on automatic CadQuery code synthesis were surveyed during development.
They do not ship here and are not used for code reuse,
but the design patterns and evaluation techniques distilled from them
(see "Design Best Practices Extracted" below, and the Design Principles in `COOKBOOK.md`)
are load-bearing.
Paths in this section are provenance:
locations within those research repos, kept so the extracted principles stay traceable.

### ipcad (Interactive Programming for CAD)
```
ipcad/
  prodm/
    synthesize.py             # Query synthesis engine (955 lines): decision tree selector optimization
    shape_analyzer.py         # Shape tracking + geometric predicate aggregation
    comparator.py             # Shape comparison via hashing (edges, faces, vertices)
    gui_observer.py           # FreeCAD GUI → CadQuery code bridge
  Experiment/Thingiverse/     # 12 real-world parametric CadQuery designs
```

### prodmcad (Programmatic Debugging & Modification of CAD)
```
prodmcad/
  prodm/                      # Core synthesis engine (2005 LOC, same architecture)
  Examples/Misc/              # Example enclosure, bottle, FreeCAD models
  Experiment/
    Thingiverse/              # 12 benchmark designs (BoltCap, LockShaft, GoProScrew, etc.)
    UserStudies/              # 24 original CadQuery examples + 63 participant queries
  cmp.py                      # Mesh comparison harness (Hausdorff distance, RMS error)
```

### Key Research-Repo Files (provenance for the extracted practices)
| File | What You Learn |
|------|---------------|
| `prodmcad/Examples/Misc/Example_Enclosure.py` | Fillet ordering, parametric screwposts, conditional holes |
| `prodmcad/Experiment/Thingiverse/BoltCap/BoltCap.py` | Loft-for-cones, hex geometry, constrained random params |
| `prodmcad/Experiment/Thingiverse/LockShaft/LockShaft.py` | Face-chain assembly, defensive offsets (±0.01) |
| `prodmcad/Experiment/Thingiverse/GoProScrew/GoProScrew.py` | Intersect for hybrid shapes, rotation loops |
| `ipcad/prodm/shape_analyzer.py` | Geometric predicate aggregation (all selector semantics) |
| `prodmcad/cmp.py` | Mesh comparison metrics (Hausdorff, RMS), future evaluation use |

### Design Best Practices Extracted
1. **Parameter hierarchy**: primary dims → derived values → tolerances (always named, never magic numbers)
2. **Face-chain assembly**: `.faces(">Z").workplane()...` is idiomatic for multi-feature parts
3. **Defensive offsets**: `±0.01` prevents face coincidence failures in extrude chains
4. **Loft for cones/tapers**: `.circle(r).workplane(offset=h).circle(0.00001).loft()` creates cones
5. **Intersect for hybrid shapes**: `box.intersect(sphere)` creates rounded-bottom boxes
6. **Export tolerance**: `tolerance=0.002777` mm is standard for STL export
7. **`combine=False`**: Explicit when geometry should NOT auto-union with existing solid

---

## 11. Patterns Previously Missing (Now Covered)

These CadQuery features previously had no examples, now covered by cheatsheets:

| Feature | Cheatsheet Reference | Code |
|---------|---------------------|------|
| Cone | `cadquery_shape_primitives.md` | `cq.Solid.makeCone(3, 1, 3)` |
| Torus | `cadquery_shape_primitives.md` | `cq.Solid.makeTorus(3, 1.5)` |
| Wedge | `cadquery_shape_primitives.md` | `cq.Workplane("XY").wedge(3,3,3,1.5,1.5,1.5,1.5)` |
| Text | `cadquery_shape_primitives.md` | `cq.Workplane("XY").text("Test", 10, 2)` |
| Helix | `cadquery_shape_primitives.md` | `cq.Wire.makeHelix(1, 4, 3)` |
| Trapezoid (Sketch) | `cadquery_shape_primitives.md` | `cq.Sketch().trapezoid(4, 3, 70)` |
| Slot (Sketch) | `cadquery_shape_primitives.md` | `cq.Sketch().slot(1.5, 0.5, angle=90)` |

Still no examples for: `.thread()`, not a built-in;
Thread.py implements manually via `.parametricCurve()`

---

## 12. Ecosystem Links (from awesome-cadquery)

For the broader ecosystem of tools and libraries, see the upstream
[awesome-cadquery](https://github.com/CadQuery/awesome-cadquery) directory.

Key external projects listed there:
- **cq_warehouse**: parametric parts library (bearings, chains, drafting)
- **cq-kit**: utilities for CadQuery (selectors, exporters)
- **cqMore**: additional operations (polyhedra, spline surfaces)
- **cq_gears**: gear generation library
- **Gridfinity**: parametric storage system
- **cadquery-freecad-module**: FreeCAD integration
