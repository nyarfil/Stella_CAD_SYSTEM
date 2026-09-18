---
name: cadquery-cookbook
description: CadQuery patterns cookbook: 11 reusable code patterns (parametric parts, enclosures, constraint/mate assemblies, gears, threads, sweeps, feature-decomposed parts, hierarchical assemblies) plus 8 design principles including the MANDATORY Principle 0 coordinate convention, and 6 anti-patterns. Use when writing, repairing, or reviewing ANY CadQuery code (parts, assemblies, or proposals). Adapt the closest matching pattern instead of composing from raw API calls.
---

# CadQuery Patterns Cookbook

> **Purpose:** Reusable code patterns extracted from golden examples in the CadQuery reference repos.
> Copy and adapt these templates instead of writing CadQuery from scratch.
>
> When generating CadQuery code, check this cookbook first.
> Adapt the closest matching pattern rather than composing from raw API calls.
>
> **⚠️ Fillets are DEFERRED project-wide**: do not add fillets to new designs (they are the #1
> CadQuery failure source).
> Patterns below that show fillets are kept for source fidelity and future reference only.
> Fillets become a later optimization phase.
>
> `Source:` lines below cite upstream CadQuery ecosystem repositories:
> they are provenance labels, not local paths;
> every pattern here is self-contained.

---

## Pattern 1: Parametric Part with Conditional Geometry

**Source:** `cadquery/examples/Ex100_Lego_Brick.py`
**When to use:** Any part where internal structure changes based on dimensions.

```python
# === PARAMETERS (always at top) ===
lbumps = 2       # number of bumps long
wbumps = 2       # number of bumps wide
thin = True      # True for thin, False for thick

# === DERIVED VALUES ===
pitch = 8.0
clearance = 0.1
bumpDiam = 4.8
bumpHeight = 1.8
height = 3.2 if thin else 9.6
t = (pitch - (2 * clearance) - bumpDiam) / 2.0
postDiam = pitch - t
total_length = lbumps * pitch - 2.0 * clearance
total_width = wbumps * pitch - 2.0 * clearance

# === GEOMETRY ===
s = cq.Workplane("XY").box(total_length, total_width, height)
s = s.faces("<Z").shell(-1.0 * t)  # Negative = hollow inward

# Bumps on top via rectangular array
s = (s.faces(">Z").workplane()
    .rarray(pitch, pitch, lbumps, wbumps, True)
    .circle(bumpDiam / 2.0).extrude(bumpHeight))

# Conditional internal posts
if lbumps > 1 and wbumps > 1:
    s = (s.faces("<Z").workplane(invert=True)
        .rarray(pitch, pitch, lbumps - 1, wbumps - 1, center=True)
        .circle(postDiam / 2.0).circle(bumpDiam / 2.0)
        .extrude(height - t))

result = s
```

**Key techniques:** `rarray()`, negative `shell()`, `workplane(invert=True)`, conditional geometry.

---

## Pattern 2: Parametric Enclosure with Snap-Fit Lid

**Source:** `cadquery-contrib/examples/Parametric_Enclosure.py`
**When to use:** Electronics enclosures, boxes with lids, cases with screw posts.

```python
# === PARAMETERS ===
p_outerWidth = 100.0
p_outerLength = 150.0
p_outerHeight = 50.0
p_thickness = 3.0
p_sideRadius = 10.0
p_topAndBottomRadius = 2.0
p_screwpostInset = 12.0
p_screwpostID = 4.0
p_screwpostOD = 10.0
p_lipHeight = 1.0

# === OUTER SHELL ===
oshell = (cq.Workplane("XY")
    .rect(p_outerWidth, p_outerLength)
    .extrude(p_outerHeight + p_lipHeight))

# CRITICAL: Fillet larger radii FIRST to avoid topology failures
if p_sideRadius > p_topAndBottomRadius:
    oshell = oshell.edges("|Z").fillet(p_sideRadius)
    oshell = oshell.edges("#Z").fillet(p_topAndBottomRadius)
else:
    oshell = oshell.edges("#Z").fillet(p_topAndBottomRadius)
    oshell = oshell.edges("|Z").fillet(p_sideRadius)

# === INNER SHELL (subtract to create walls) ===
ishell = (oshell.faces("<Z").workplane(p_thickness, True)
    .rect(p_outerWidth - 2*p_thickness, p_outerLength - 2*p_thickness)
    .extrude(p_outerHeight - 2*p_thickness, False))
ishell = ishell.edges("|Z").fillet(p_sideRadius - p_thickness)
box = oshell.cut(ishell)

# === SCREW POSTS ===
POSTWIDTH = p_outerWidth - 2*p_screwpostInset
POSTLENGTH = p_outerLength - 2*p_screwpostInset
box = (box.faces(">Z").workplane(-p_thickness)
    .rect(POSTWIDTH, POSTLENGTH, forConstruction=True)
    .vertices()
    .circle(p_screwpostOD / 2.0).circle(p_screwpostID / 2.0)
    .extrude(-(p_outerHeight + p_lipHeight - p_thickness), True))

# === SPLIT INTO LID + BOTTOM ===
lid, bottom = (box.faces(">Z")
    .workplane(-p_thickness - p_lipHeight)
    .split(keepTop=True, keepBottom=True).all())

result = lid.union(bottom)
```

**Key techniques:** Fillet order matters, `extrude(dist, False)` for separate solid, `.split().all()` for lid separation, `forConstruction=True` for locating posts.

---

## Pattern 3: Constraint-Based Assembly

**Source:** `cadquery-contrib/examples/door.py`
**When to use:** Multi-part assemblies where components must be precisely positioned.

> **⚠️ Harness note:** `.constrain()/.solve()` are BANNED in this project:
> position parts with direct `cq.Location` instead (see Pattern 11).
> This pattern is retained for reference fidelity
> and for understanding constraint syntax found in external example code.

```python
# === PARTS (each returns a tagged Workplane) ===
def make_part_a():
    part = cq.Workplane().box(20, 20, 20)
    part.faces(">X").tag("mate_face")  # Tag for constraints
    part.faces(">Z").tag("top")
    return part

def make_part_b():
    part = cq.Workplane().cylinder(30, 5)
    part.faces("<Z").tag("bottom")
    return part

# === ASSEMBLY ===
assy = (cq.Assembly()
    .add(make_part_a(), name="block", color=cq.Color("red"))
    .add(make_part_b(), name="pin", color=cq.Color("blue")))

# === CONSTRAINTS ===
# Syntax: "part_name@faces@selector" or "part_name?tag_name"
assy.constrain("block@faces@>Z", "pin@faces@<Z", "Plane")  # Coplanar
assy.constrain("block@faces@>X", "pin@faces@>X", "Axis")   # Aligned axes

# === SOLVE ===
assy.solve()
```

**Key techniques:** `.tag()` faces before adding to assembly, constraint syntax `"name@faces@>Z"` or `"name?tag"`, three constraint types: `"Plane"`, `"Axis"`, `"Point"`.

---

## Pattern 4: Mate-Based Assembly (MAssembly)

**Source:** `cadquery-massembly/examples/cq-editor/1-disk_arm.py`
**When to use:** Kinematic assemblies with pivot/hinge/sliding joints.

> **Harness note (2026-07-21): REFERENCE-ONLY. Do not use in harness runs.** Production assemblies use direct `cq.Location` placement (Pattern 11); `.constrain()/.solve()` are banned in this project. A scoped mate-based approach may be revisited in a future release; until then treat this pattern as reference-only.

```python
from cadquery_massembly import MAssembly, Mate
from collections import OrderedDict as odict

L = lambda *args: cq.Location(cq.Vector(*args))
C = lambda *args: cq.Color(*args)

# === PARTS ===
base = cq.Workplane("XY").box(40, 40, 5)
disk = cq.Workplane("XY").cylinder(5, 15)
arm = cq.Workplane("XY").box(5, 50, 5)

# === ASSEMBLY ===
assy = (MAssembly(base, name="base", color=C("gray"), loc=L(0, 0, 0))
    .add(disk, name="disk", color=C("green"), loc=L(20, 0, 0))
    .add(arm, name="arm", color=C("orange"), loc=L(0, 20, 0)))

# === MATES (coordinate frames at connection points) ===
assy.mate("base@faces@>Z", name="disk_pivot", origin=True, transforms=odict(rz=180))
assy.mate("disk@faces@>Z[-2]", name="disk", origin=True)
assy.mate("arm@faces@>Z", name="arm", origin=True)

# === ASSEMBLE (snap mates together) ===
assy.assemble("disk", "disk_pivot")
assy.assemble("arm", "arm_pivot")
```

**Key techniques:** `MAssembly` extends `cq.Assembly`, `.mate()` defines named coordinate frames, `.assemble()` snaps parts to mates, `transforms=odict(rz=angle)` for rotational mates.

---

## Pattern 5: Parametric Gear (Involute Profile)

**Source:** `cadquery-contrib/examples/cylindrical_gear.py`
**When to use:** Mechanical gears with proper tooth geometry.

```python
from math import cos, sin, sqrt, radians, pi

# === CUSTOM SELECTOR ===
class HollowCylinderSelector(cq.Selector):
    def __init__(self, r_inner, r_outer):
        self.r1, self.r2 = r_inner, r_outer
    def filter(self, objectList):
        return [o for o in objectList
                if self.r1 < sqrt(o.Center().x**2 + o.Center().y**2) < self.r2]

# === INVOLUTE CURVE ===
def involute(r_base):
    def curve(t):
        return (r_base * (cos(t) + t*sin(t)),
                r_base * (sin(t) - t*cos(t)))
    return curve

# === GEAR FUNCTION ===
def make_gear(module, num_teeth, pressure_angle, width):
    r_pitch = module * num_teeth / 2
    r_addendum = r_pitch + module
    r_root = r_pitch - 1.25 * module
    r_base = r_pitch * cos(radians(pressure_angle))
    STOP = sqrt((r_addendum/r_base)**2 - 1)

    # Create tooth profile via parametric curves
    def tooth(loc):
        profile = (cq.Workplane("XY")
            .parametricCurve(involute(r_base), stop=STOP, makeWire=False))
        # ... mirror + close to form complete tooth
        return profile.val().moved(loc)

    # Polar array of teeth
    teeth = (cq.Workplane("XY")
        .polarArray(0, 0, 360, num_teeth)
        .eachpoint(tooth, useLocalCoordinates=True)
        .extrude(width))

    # Hub + fillet root edges
    gear = (cq.Workplane("XY").circle(r_root).extrude(width)
        .union(teeth)
        .edges(HollowCylinderSelector(0, 1.01*r_root)).fillet(0.4*module))
    return gear

result = make_gear(m=1, num_teeth=20, pressure_angle=20, width=5)
```

**Key techniques:** Custom `Selector` subclass, `.parametricCurve()` for mathematical profiles, `.polarArray()` + `.eachpoint()` for circular patterns, `.twistExtrude()` for helical gears.

---

## Pattern 6: Thread via Ruled Surfaces

**Source:** `cadquery-contrib/examples/Thread.py`
**When to use:** Screw threads, helical features, or any surface between parametric curves.

```python
def helix(r0, r_eps, pitch, height, depth_offset=0):
    def func(t):
        z = height * t + depth_offset
        r = r0 + r_eps
        x = r * sin(-2*pi / (pitch/height) * t)
        y = r * cos(2*pi / (pitch/height) * t)
        return x, y, z
    return func

def make_thread(radius, pitch, height, depth, r_eps):
    e1 = cq.Workplane("XY").parametricCurve(helix(radius, 0, pitch, height, -depth)).val()
    e2 = cq.Workplane("XY").parametricCurve(helix(radius, 0, pitch, height, depth)).val()
    e3 = cq.Workplane("XY").parametricCurve(helix(radius, r_eps, pitch, height, 0)).val()
    e4 = cq.Workplane("XY").parametricCurve(helix(radius, r_eps, pitch, height, 0)).val()

    f1 = cq.Face.makeRuledSurface(e1, e2)  # Inner flank
    f2 = cq.Face.makeRuledSurface(e3, e4)  # Outer flank
    f3 = cq.Face.makeRuledSurface(e1, e3)  # Root
    f4 = cq.Face.makeRuledSurface(e2, e4)  # Tip

    shell = cq.Shell.makeShell([f1, f2, f3, f4])
    return cq.Solid.makeSolid(shell)
```

**Key techniques:** `Face.makeRuledSurface()`, `Shell.makeShell()`, `Solid.makeSolid()`: low-level OCP API for complex geometry.

---

## Pattern 7: Case Lip via Wire Offset

**Source:** `cadquery/examples/Ex026_Case_Seam_Lip.py`
**When to use:** Snap-fit case lips, internal ledges, seating grooves.

```python
from cadquery.selectors import AreaNthSelector

case_bottom = (cq.Workplane("XY")
    .rect(20, 20).extrude(10)
    .edges("|Z or <Z").fillet(2)
    .faces(">Z").shell(2)               # Hollow from top
    .faces(">Z")
    .wires(AreaNthSelector(-1))          # Outermost wire (rim)
    .toPending().workplane()
    .offset2D(-1)                        # Inset by 1mm
    .extrude(1)                          # Temporary lid
    .faces(">Z[-2]")
    .wires(AreaNthSelector(0))           # Inner cross-section
    .toPending().workplane()
    .cutBlind(2))                        # Cut to leave 1mm lip
```

**Key techniques:** `AreaNthSelector(-1)` for outermost wire, `.offset2D()` for inset, `.toPending().workplane()` to convert wire to working surface.

---

## Pattern 8: Sweep Along Path

**Source:** `cadquery/examples/Ex023_Sweep.py`
**When to use:** Tubes, rails, handles, any profile following a 3D path.

```python
# Spline path
path = cq.Workplane("XZ").spline([(0,1), (1,2), (2,4)])

# Circular cross-section swept along path
tube = cq.Workplane("XY").circle(0.5).sweep(path, isFrenet=True)

# Rectangular cross-section
rail = cq.Workplane("XY").rect(1, 0.5).sweep(path)

# Arc path alternative
arc_path = cq.Workplane("XZ").threePointArc((1.0, 1.5), (0.0, 1.0))
curved = cq.Workplane("XY").circle(0.3).sweep(arc_path)
```

**Key techniques:** `isFrenet=True` prevents twist, path can be spline/polyline/arc, profile must be centered on origin.

---

## Pattern 9: Plugin Extension (Monkey-Patch)

**Source:** `cadquery-plugins/plugins/heatserts/heatserts.py`
**When to use:** Reusable operations that should feel like native Workplane methods.

```python
def my_custom_hole(self, diameter, depth, chamfer=0.5):
    """Custom hole at each point on stack."""
    def _one_hole(loc):
        hole = cq.Solid.makeCylinder(diameter/2, depth, cq.Vector(0,0,0), cq.Vector(0,0,-1))
        if chamfer:
            cone = cq.Solid.makeCone(diameter/2 + chamfer, diameter/2, chamfer,
                                     cq.Vector(0,0,0), cq.Vector(0,0,-1))
            hole = hole.fuse(cone)
        return hole.move(loc)
    return self.cutEach(_one_hole, True, True)

# Register on Workplane
cq.Workplane.my_custom_hole = my_custom_hole

# Usage: result = cq.Workplane("XY").box(10,10,5).faces(">Z").my_custom_hole(3, 4)
```

**Key techniques:** Function signature `(self, ...)`, use `cutEach` for boolean cuts at stack points, `eachpoint` for additive, return Workplane for chaining.

---

## Anti-Patterns (Things to AVOID)

### 1. Fillets in wrong order
```python
# WRONG: smaller first causes topology failure
box.edges("#Z").fillet(2).edges("|Z").fillet(5)
# RIGHT: larger radii first
box.edges("|Z").fillet(5).edges("#Z").fillet(2)
```

### 2. Forgetting .end() after .tag()
```python
# WRONG: breaks the chain
part.faces(">Z").tag("top")  # Returns face, not workplane
# RIGHT
part.faces(">Z").tag("top").end()
```

### 3. Using split() without .all()
```python
# WRONG: returns compound, not separate parts
result = box.split(keepTop=True, keepBottom=True)
# RIGHT
top, bottom = box.split(keepTop=True, keepBottom=True).all()
```

### 4. Wrong shell direction
```python
# shell(positive) = outward, shell(negative) = inward (hollow)
box.faces(">Z").shell(-2)  # Hollow with 2mm walls, top removed
```

### 5. Selector confusion
```python
"|Z"  # Edges PARALLEL to Z (vertical edges)
"#Z"  # Edges PERPENDICULAR to Z (horizontal edges)
">Z"  # Face with MAX Z value (top face)
"<Z"  # Face with MIN Z value (bottom face)
```

### 6. Negative dimensions in arrays
```python
# WRONG: undefined behavior
w.rarray(10, 10, -3, 3)
# RIGHT: always positive counts, use translate for offset
w.rarray(10, 10, 3, 3)
```

---

## Design Principles (from Research Repos)

Extracted from MPI-SWS research repos (`ipcad`, `prodmcad`):
production-grade parametric CadQuery patterns from real Thingiverse designs.

### Principle 0: Standard Origin Convention (MANDATORY)

All parts MUST follow this origin placement to simplify assembly positioning:

**Revolved/Cylindrical parts** (shafts, bores, discs, pistons, pins):
```python
# Axis of revolution = Z-axis, center at origin
# This is the natural result of circle().extrude() on XY
shaft = cq.Workplane("XY").circle(shaft_dia / 2).extrude(shaft_length)
# Shaft runs from Z=0 to Z=shaft_length, centered on X=0, Y=0
```

**Prismatic parts** (brackets, plates, blocks):
```python
# Centered on XY, bottom at Z=0
block = cq.Workplane("XY").box(length, width, height)
# .box() centers on all axes; use .translate((0, 0, height/2)) to put bottom at Z=0
```

**Parts with a primary bore** (housings, bearings):
```python
# Primary bore axis = Z through origin
housing = cq.Workplane("XY").circle(outer_dia / 2).extrude(height)
housing = housing.faces(">Z").workplane().hole(bore_dia)
# Bore is at X=0, Y=0: aligns directly with shaft's Z-axis
```

**Why**: When both a shaft and its housing have their axes at Z-origin,
assembly is just `cq.Location(cq.Vector(0, 0, z_offset))`.
No guessing where features are relative to part corners.

### Principle 1: Defensive Offsets for Geometry Stability
Small offsets prevent face coincidence failures in extrude chains:
```python
# WRONG: faces exactly coincide, causing geometry errors
shaft = flange.faces(">Z").workplane().circle(r).extrude(length)

# RIGHT: tiny offset prevents Z-fighting
shaft = flange.faces(">Z").workplane(offset=-0.01).circle(r).extrude(length + 0.01)
```
Source: `prodmcad/Experiment/Thingiverse/LockShaft/LockShaft.py`

### Principle 2: Loft-for-Cones (Taper Transitions)
Create cone-like shapes by lofting between a large circle and a tiny one:
```python
# Tapered bolt hole (cone shape)
cone = (cq.Workplane("XY")
    .circle(bolt_rad)
    .workplane(offset=bolt_rad)
    .circle(0.00001)
    .loft())
```
Source: `prodmcad/Experiment/Thingiverse/BoltCap/BoltCap.py`

### Principle 3: Intersect for Hybrid Shapes
Combine primitives via intersection to create complex forms:
```python
# Rounded-bottom box: intersect cube with sphere
cube = cq.Workplane("XY").box(w, w, h, centered=(True, True, False))
sphere = cq.Workplane("XY").sphere(w * ratio / 2.0)
base = cube.intersect(sphere)
```
Source: `prodmcad/Experiment/Thingiverse/GoProScrew/GoProScrew.py`

### Principle 4: Face-Chain Assembly
Build multi-feature parts by chaining through face selections:
```python
# Each feature selects the top face, creates workplane, extends
base = cq.Workplane("XY").polygon(6, d).extrude(key_length)
flange = base.faces(">Z").circle(flange_r).extrude(flange_length)
shaft = flange.faces(">Z").workplane(offset=-0.01).circle(shaft_r).extrude(shaft_length)
drive = shaft.faces(">Z").workplane().transformed(rotate=(0,0,30)).polygon(6, d).cutBlind(-depth)
```
Source: `prodmcad/Experiment/Thingiverse/LockShaft/LockShaft.py`

### Principle 5: Parameter Hierarchy
Always organize parameters in dependency order:
```python
# PRIMARY dimensions (independent)
nut_across_flats_mm = 19.4
bolt_diameter_mm = 13.2

# DERIVED values (computed from primary)
bolt_rad = bolt_diameter_mm / 2.0
nut_internal_rad = nut_across_flats_mm / (2 * cos(pi/6))

# TOLERANCES (explicit, never magic numbers)
bolt_clearance_mm = 0.5
wall_thickness_mm = 2.0
```

### Principle 6: Symmetric Feature Iteration
Apply the same operation to multiple faces using loops:
```python
# Hole on all 6 faces of a cube
for face_sel in [">X", "<X", ">Y", "<Y", ">Z", "<Z"]:
    cube = cube.faces(face_sel).workplane().hole(diameter, depth=computed_depth)
```
Source: `prodmcad/Experiment/Thingiverse/Turners Cube/Turners_Cube.py`

### Principle 7: Export with Standard Tolerance
```python
cq.exporters.exportShape(shape=result, fileLike=f, exportType="STL", tolerance=0.002777)
```
Standard across all production CadQuery scripts.

---

## Pattern 10: Feature-Decomposed Part (Semantic Code Structure)

For parts with 3+ distinct features, extract each feature into a named function.
Function names describe WHAT the feature IS (engineering term), not HOW it's made.

```python
import cadquery as cq

# === PARAMETERS ===
piston_od = 80.0
piston_height = 60.0
wall_thickness = 5.0
crown_thickness = 8.0
wrist_pin_diameter = 22.0
wrist_pin_center_z = 28.0
boss_od = 34.0

# === FEATURE FUNCTIONS ===
def piston_blank(od, height):
    """Solid cylindrical body: the starting stock."""
    return cq.Workplane("XY").circle(od / 2).extrude(height)

def crown_cavity(body, od, wall_t, crown_t, height):
    """Hollow interior leaving solid crown at top."""
    inner_r = od / 2 - wall_t
    cutter = (
        cq.Workplane("XY")
        .workplane(offset=height)
        .circle(inner_r)
        .extrude(-(height - crown_t))
    )
    return body.cut(cutter), cutter

def wrist_pin_bosses(body, cavity_cutter, boss_od, pin_z, od):
    """Internal support bosses for the wrist pin bearing surface."""
    boss = (
        cq.Workplane("YZ")
        .workplane(offset=pin_z)
        .circle(boss_od / 2)
        .extrude(od, both=True)
    )
    clipped_boss = boss.intersect(cavity_cutter)
    return body.union(clipped_boss)

def wrist_pin_bore(body, pin_dia, pin_z, od, fillet_r=1.0):
    """Through-hole for wrist pin with stress-relief entry fillets."""
    cutter = (
        cq.Workplane("YZ")
        .workplane(offset=pin_z)
        .circle(pin_dia / 2)
        .extrude(od + 4, both=True)
    )
    cutter = cutter.edges("%CIRCLE").fillet(fillet_r)
    return body.cut(cutter)

def crown_edge_fillets(body, r=1.0):
    """Stress-relief fillets on crown top and skirt bottom edges."""
    body = body.faces(">Z").edges("%CIRCLE").fillet(r)
    return body.faces("<Z").edges("%CIRCLE").fillet(r)

# === COMPOSE (read top-to-bottom as a build sequence) ===
body = piston_blank(piston_od, piston_height)
body, cavity = crown_cavity(body, piston_od, wall_thickness, crown_thickness, piston_height)
body = wrist_pin_bosses(body, cavity, boss_od, wrist_pin_center_z, piston_od)
body = wrist_pin_bore(body, wrist_pin_diameter, wrist_pin_center_z, piston_od)
result = crown_edge_fillets(body)
```

**When to use**: Any part with 3+ distinct geometric features (bores, bosses, pockets,
flanges, grooves). Simple parts (pins, washers, spacers) can stay inline.

**Key techniques**:
- Function names are engineering terms: `wrist_pin_bore`, NOT `cut_hole_1`
- Parameters at top, features in middle, composition at bottom
- Each function takes the current body and returns the modified body
- The COMPOSE section reads like a manufacturing process plan
- Validator and repair agents can reference features by name

---

## Pattern 11: Hierarchical Assembly (Sub-Assembly Composition)

For assemblies with functional sub-groups (e.g., a bolted joint, a piston group),
compose sub-assemblies into the top-level assembly.

```python
import cadquery as cq
from pathlib import Path

def load_sub_assembly(sub_name: str) -> object:
    """Execute a sub-assembly's assembly.py and return its compound solid.

    Sub-assemblies live at assembly/{sub_name}/assembly.py and compose
    their own parts internally. The top-level assembly treats each
    sub-assembly as a single compound solid.
    """
    asm_file = __project_path__ / "assembly" / sub_name / "assembly.py"
    if not asm_file.exists():
        raise FileNotFoundError(f"Sub-assembly not found: {asm_file}")
    ns = {"__project_path__": __project_path__, "cq": cq, "Path": Path}
    exec(asm_file.read_text(), ns)
    return ns["result"]

def load_part(part_name: str) -> object:
    """Load an individual part (for parts not in a sub-assembly)."""
    part_file = __project_path__ / "assembly" / part_name / "part.py"
    ns = {}
    exec(part_file.read_text(), ns)
    return ns["result"]

# Load sub-assemblies as pre-composed compound solids
piston_group = load_sub_assembly("piston_group")
crank_group = load_sub_assembly("crank_group")

# Position sub-assemblies relative to each other
con_rod_length = 150.0
wrist_pin_z = 28.0

assy = (
    cq.Assembly()
    .add(piston_group, name="piston_group", color=cq.Color("gray"))
    .add(crank_group, name="crank_group",
         loc=cq.Location(cq.Vector(0, 0, wrist_pin_z - con_rod_length)),
         color=cq.Color("lightgray"))
)
result = assy.toCompound()
```

**When to use**: Assemblies with 4+ parts that form natural functional groups.
A sub-assembly = parts that are ALWAYS assembled together
before joining the larger assembly (e.g., connecting rod + big end cap + bolts).

**Key techniques**:
- `load_sub_assembly()` executes the sub-assembly's own `assembly.py`
- `__project_path__` always points to the PROJECT ROOT (not the sub-assembly dir)
- Sub-assembly `assembly.py` uses the same `load_part()` pattern
  but with paths relative to `__project_path__ / "assembly" / sub_name / part_name / "part.py"`
- Each sub-assembly gets its own validation round before top-level composition
- Top-level assembly only needs to position sub-assemblies, not individual parts

---

## Bundled Reference Files (read on demand)

These live alongside this SKILL.md in the same directory:

| File | Read it when you need |
|---|---|
| `API_SURFACE.md` | To verify a method EXISTS before using it: every public method on Workplane (112), Assembly (15), and Sketch (59) with signatures. **If a method is not listed there, it DOES NOT EXIST.** |
| `cadquery_shape_primitives.md` | A code snippet for a specific primitive: cone, torus, helix, wedge, sphere, text, and all Sketch shapes. |
| `cadquery_array_operations.md` | Pattern/array features: `polarArray`, `rarray`, `eachpoint` with visual examples. |

Also see the `cadquery-anti-hallucination` skill
for the catalog of commonly hallucinated methods and their correct alternatives.
