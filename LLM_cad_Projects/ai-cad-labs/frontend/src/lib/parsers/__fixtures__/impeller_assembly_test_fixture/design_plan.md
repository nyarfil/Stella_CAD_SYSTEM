# Design Plan

## Overview

A small rotating-machinery assembly centered on a centrifugal compressor impeller,
laid out turbocharger-style on ONE through-shaft (per `user_initial_sketch.jpeg`,
which governs composition, not sizing).
Left to right along the shaft axis:
integrated grooved pulley (one turned part with the shaft) →
upright bearing-housing plate gripping the main bearing's OD →
main bearing whose inner race carries a spigot on the impeller's base →
impeller with backswept blades, backplate facing the housing across a
0.5–1.0 mm running clearance →
small lock nut on the shaft nose →
small inlet bearing that must NOT block the inducer inlet →
shaft continues (break line in sketch; downstream support is out of scope).

All sizing is anchored on standard catalog bearing dimensions
(bearings are Buy; shaft, housing bore, and impeller spigot are sized around them,
never the reverse):

- **Main bearing: 6203 deep-groove ball bearing — 17 mm bore × 40 mm OD × 12 mm wide.**
- **Inlet bearing: 688 deep-groove ball bearing — 8 mm bore × 16 mm OD × 5 mm wide.**
- **Lock nut: ISO 4032 hex nut M10 (coarse, 1.5 mm pitch) — 8.4 mm high, 16 mm across flats.**

These three catalog selections are the plan's dimensional anchors.
The sourcing agent's `external/bom.md` must record exactly these
(or an equivalent with IDENTICAL boundary dimensions);
any substitution with different dimensions reopens this plan.

**Architecture note (per the user's spec, not a planner choice):
the shaft does NOT touch the main bearing directly.**
The impeller's spigot seats in the 6203's bore,
and the shaft passes through the impeller's own Ø10 bore,
clamped by a shaft shoulder and the nose lock nut.
Torque path: pulley → shaft → clamp friction (shoulder + nut) → impeller.
FILLETS ARE DEFERRED PROJECT-WIDE (no constraints file may require them).

## Parts

### 1. pulley_shaft
- **Type**: Custom (make)
- **Description**: The grooved pulley wheel and the stepped shaft as ONE turned part
  from bar stock (no belt modeled).
  Carries, left to right: Ø14 stub, Ø48 pulley with round-belt groove,
  Ø14 mid-section through the housing back-bore,
  a Ø14→Ø10 clamp shoulder, the Ø10 impeller seat,
  the M10×1.5 nose thread for the lock nut,
  and the Ø8 inlet-bearing tail.
- **Key dimensions**: Ø48 max (pulley) × 118 long; seat Ø10 × 45; thread M10×1.5 × 14; tail Ø8 × 15.
- **Interfaces**: impeller bore (Ø10 slide fit + shoulder clamp), lock_nut (M10×1.5),
  inlet_bearing bore (Ø8), clearance through bearing_housing back-bore (Ø14 in Ø34).
- **parallel_safe**: true
  (every interface is a fixed number locked in this plan —
  catalog bearing bores plus the named clamp-stack lengths in §Interfaces;
  no dependency on another part's design outcome)

### 2. bearing_housing
- **Type**: Custom (make)
- **Description**: A simple, straight upright plate the assembly seats on,
  with an integral base foot.
  Its stepped bore grips the main bearing's OD in a 12 mm deep pocket
  (bearing flush with the impeller-side face)
  with a Ø34 back-bore forming the outer-race retention shoulder
  and clearing the Ø14 shaft.
  Its impeller-side face is the reference plane for the running clearance.
- **Key dimensions**: 80 wide × 95 tall × 16 plate thickness; foot 80 × 40 × 10;
  bore center 60 above ground; pocket Ø40 × 12.
- **Interfaces**: main_bearing OD (Ø40 pocket), pulley_shaft clearance (Ø34 back-bore),
  impeller backface (0.8 mm running clearance across its front face).
- **parallel_safe**: true
  (depends only on the 6203's published 40 × 12 boundary dims and fixed plan numbers)

### 3. main_bearing
- **Type**: Standard (buy) — 6203 deep-groove ball bearing, 17 × 40 × 12 mm
- **Description**: Held in the housing pocket by its OD;
  its inner race receives the impeller spigot and its inner-race face
  is the axial datum the impeller's standoff boss registers against.
  Modeled representationally at assembly stage from BOM dims
  (outer race, inner race, simple ball-band).
- **Interfaces**: bearing_housing pocket (OD 40), impeller spigot (bore 17),
  impeller standoff boss (inner-race face contact).
- **parallel_safe**: true (Buy part; all dimensions are catalog-published; sourcing only)

### 4. impeller
- **Type**: Custom (make)
- **Description**: The centrifugal compressor wheel.
  A Ø17 spigot on its base seats in the 6203's inner diameter;
  a Ø22 × 0.8 standoff boss at the spigot root bears on the inner-race face
  and sets the 0.8 mm backface-to-housing running clearance;
  the Ø72 backplate carries 6 backswept blades rising to the Ø34 inducer eye;
  a Ø10 through-bore takes the shaft, clamped shoulder-to-nut.
- **Key dimensions**: Ø72 tip × 48.8 total axial (spigot end to nose face);
  eye Ø34; hub nose Ø18; bore Ø10.
- **Interfaces**: main_bearing bore (spigot Ø17 press fit) and inner-race face (boss),
  pulley_shaft (Ø10 bore + shoulder/nut clamp faces),
  bearing_housing face (0.8 mm running clearance).
- **parallel_safe**: true
  (all interface dims are catalog bearing numbers or fixed plan parameters;
  nothing waits on another part's design)

### 5. lock_nut
- **Type**: Standard (buy) — ISO 4032 hex nut M10, coarse (1.5 pitch), steel class 8
- **Description**: Retains the impeller on the shaft at the inlet end,
  clamping the impeller hub nose face against the shaft shoulder
  (through the spigot end face).
  **Make-vs-Buy decision: BUY** — it is a plain catalog hex nut on a standard
  M10×1.5 spindle-nose thread; custom-making it adds design and validation cost
  with zero functional gain.
  Modeled representationally at assembly stage from BOM dims, like the bearings.
- **Interfaces**: pulley_shaft nose thread (M10×1.5), impeller nose face (Ø18 ≥ nut seat).
- **parallel_safe**: true (Buy part; catalog dimensions fixed)

### 6. inlet_bearing
- **Type**: Standard (buy) — 688 deep-groove ball bearing, 8 × 16 × 5 mm
- **Description**: Supports the shaft's inlet end on the Ø8 tail,
  downstream of the impeller nose.
  **Hard user constraint: must not obstruct the inducer inlet.**
  Ceiling formalized below: OD ≤ 18.0 mm (the hub-nose diameter),
  so the bearing sits entirely within the hub's own flow shadow —
  zero added blockage. 688's OD of 16 complies with margin.
  Its outer support (intake housing) is beyond the sketch's break line — out of scope.
- **Interfaces**: pulley_shaft tail (bore 8), inducer eye clearance (OD 16 ≤ 18 ceiling).
- **parallel_safe**: true (Buy part; catalog dimensions fixed)

## Interfaces

Global assembly convention: shaft axis = global Z axis;
global Z = 0 at the housing's impeller-side face; +Z toward the inlet (right in sketch).
Every named parameter below is LOCKED — parallel designers build against these
without seeing each other. "From BOM" = the value is a catalog bearing/nut dimension
that `external/bom.md` must confirm verbatim.

| Parameter | Value (mm) | Interface | Fit direction |
|---|---|---|---|
| `D_MB_BORE` | 17.0 (from BOM: 6203 bore) | main_bearing ID ↔ impeller spigot OD | press fit (nominal-on-nominal in CAD; interference intent) |
| `D_MB_OD` | 40.0 (from BOM: 6203 OD) | main_bearing OD ↔ bearing_housing pocket | transition fit (H7 housing intent) |
| `W_MB` | 12.0 (from BOM: 6203 width) | bearing width ↔ housing pocket depth | flush with housing impeller-side face |
| `D_SHAFT_IMPELLER_SEAT` | 10.0 | shaft ↔ impeller through-bore | clearance/slide fit (H7/g6 intent; model both at 10.0 nominal). NOTE: this IS the shaft diameter at the main-bearing axial station — the impeller spigot is interposed between shaft and bearing per the user's spec, so the shaft has no direct main-bearing seat |
| `D_SHAFT_SHOULDER` | 14.0 | shaft shoulder ↔ impeller spigot end face | clamp contact (annular face Ø10→Ø14) |
| `L_IMP_GRIP` | 48.8 | impeller bore length (spigot end face → hub nose face) ↔ shaft clamp stack | shaft plain seat 45.0 + thread; nut face lands at 48.8 from the shoulder |
| `THREAD_NOSE` | M10×1.5, 14 long | shaft nose ↔ lock_nut | standard metric coarse; external major = 10.0 = seat Ø (no step-up) |
| `D_SHAFT_INLET_SEAT` | 8.0 (from BOM: 688 bore) | shaft tail ↔ inlet_bearing bore | slide fit (nominal 8.0) |
| `CLR_RUN` | 0.8 (allowed window 0.5–1.0, user requirement) | impeller backplate backface ↔ housing impeller-side face | open running clearance; realized structurally, see below |
| `T_STANDOFF_BOSS` | 0.8 | impeller standoff boss thickness | with the bearing flush in its pocket, boss thickness = `CLR_RUN` exactly |
| `D_STANDOFF_BOSS` | 22.0 | impeller boss ↔ 6203 inner-race face | contacts inner race ONLY (race land ≈ Ø22.5; housing face material starts at Ø40) |
| `D_EYE` | 34.0 | impeller inducer eye diameter | reference for the inlet-blockage ceiling |
| `D_HUB_NOSE` | 18.0 | impeller hub diameter at nose | ≥ lock nut across-corners footprint (~18.5, acceptable overhang <0.3/side) |
| `OD_INLET_MAX` | 18.0 (= `D_HUB_NOSE`) | HARD CEILING on inlet_bearing OD | bearing within the hub's flow shadow → zero added inlet blockage; 688 OD 16.0 complies |
| `D_HOUSING_BACKBORE` | 34.0 | housing back-bore | 3.0 mm outer-race retention shoulder; clears Ø14 shaft by 10/side |

Running-clearance mechanism (so no agent re-derives it differently):
6203 pressed into the housing pocket until flush with the impeller-side face (Z = 0);
impeller spigot pressed into the 6203 until the Ø22 boss contacts the inner-race face at Z = 0;
boss thickness 0.8 puts the backplate backface at Z = +0.8;
gap to the housing face (Z = 0) = 0.8 mm = `CLR_RUN`. ✓

Axial placement table (assembly resolver reference, global Z):

| Component (local datum) | Placement |
|---|---|
| bearing_housing (impeller-side face = local Z=0) | local 0 → global 0 (no rotation; bore axis modeled on Z) |
| main_bearing | spans Z = −12 … 0 |
| impeller (backplate backface = local Z=0) | local 0 → global +0.8 (spigot end at −14.0, nose face at +34.8) |
| pulley_shaft (shoulder face = local Z=0) | local 0 → global −14.0 |
| lock_nut | seats at Z = +34.8, spans to +43.2 |
| inlet_bearing | spans Z = +47 … +52 on the Ø8 tail |

## Assembly Order

1. Press main_bearing (6203) into the bearing_housing pocket, flush with the impeller-side face.
2. Press the impeller spigot into the 6203 inner race until the standoff boss contacts the inner-race face.
3. Insert pulley_shaft from the pulley side through the housing back-bore and the impeller bore,
   until the shoulder contacts the spigot end face.
4. Thread lock_nut onto the M10×1.5 nose; the clamp stack closes
   (shoulder → spigot → impeller body → nut).
5. Slide inlet_bearing onto the Ø8 tail (Z = +47…+52).
6. Verify `CLR_RUN` = 0.8 mm between backplate backface and housing face in the assembly render.

## Make vs Buy

- **Buy** (sourcing agent: write these to `external/bom.md` with the exact boundary dims quoted above):
  - `main_bearing` — deep-groove ball bearing **6203** (17 × 40 × 12 mm), open or 2Z, any major brand.
  - `inlet_bearing` — deep-groove ball bearing **688** (8 × 16 × 5 mm).
  - `lock_nut` — **ISO 4032 hex nut M10** (coarse ×1.5), steel class 8 (8.4 high, 16 A/F).
  - Optional hardware (assembly mounting, not modeled as parts): 4 × M5 bolts for the housing foot.
- **Make**: `pulley_shaft`, `bearing_housing`, `impeller`.
- Buy parts get representational geometry at assembly stage from BOM dims
  (races + ball-band for bearings, hex prism for the nut); they have no part directories.

## Design Order

All three Make parts are `parallel_safe: true`
(every cross-part dimension is locked numerically above),
so they MAY be dispatched in parallel.
If serialized, the recommended fail-fast order is:

1. **impeller** — highest geometric risk (blade sweep); validates the proven CadQuery
   primitive chain first (see its constraints.md) and owns the clamp-stack datum chain.
2. **pulley_shaft** — verifies the clamp stack against the impeller's locked axial numbers.
3. **bearing_housing** — lowest risk; pure prismatic + bores.

No `## Sub-Assemblies` section: 3 Make parts on one axis is a flat structure;
sub-assembly overhead is not warranted.
