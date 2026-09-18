# Design Plan

## Overview
A small treasure chest for FDM 3D printing: a hollow rectangular base box (~180 x 120 x 80 mm, 3 mm walls, open top) closed by a curved half-cylinder lid that matches the base footprint. The lid pivots on two printed hinge blocks screwed to the rear exterior wall of the base, joined by two steel hinge pins passing through integral lugs on the lid. A hasp/latch plate with a padlock boss mounts centered on the front face. No fillets anywhere (deferred project-wide). All geometry FDM-friendly (flat print faces, no overhang-critical features beyond the lid dome, printed flat-face-down).

**Global assembly frame**: base_box centered on XY, bottom at Z=0. Outer envelope X = -90..+90, Y = -60..+60, Z = 0..80. Rear = -Y, front = +Y. Rim plane at Z=80. Hinge pin axis: parallel to X at (Y=-66, Z=80).

## Parts
### 1. base_box
- **Type**: Custom (make) — qty 1
- **Description**: Hollow rectangular box, 3 mm walls and floor, open top. Carries 4 hinge-mount through-holes in the rear wall and 2 hasp-mount through-holes in the front wall.
- **Key dimensions**: 180 x 120 x 80 mm outer; interior 174 x 114 x 77 mm
- **Interfaces**: Connects to hinge_block (x2) via M3 screw holes in rear wall; to hasp_plate via M3 screw holes in front wall; to lid via rim plane at Z=80 (rest contact, no fastener)
- **parallel_safe**: true — all dimensions and interface hole positions fixed numerically in constraints; no dependency on other parts' design outcomes

### 2. lid
- **Type**: Custom (make) — qty 1
- **Description**: Half-cylinder shell lid (R60, length 180, 3 mm wall, flat semicircular end caps) with two integral rear hinge lugs carrying ⌀3.4 mm pin bores. Rests on the base rim when closed; rotates on the hinge pins.
- **Key dimensions**: 180 x 134 x 64 mm bbox (dome 180 x 120 x 60 + lugs projecting 14 mm rearward and 4 mm below rim plane)
- **Interfaces**: Connects to hinge pins (buy) via 2 lug bores ⌀3.4 mm clearance on the hinge axis; rests on base_box rim at Z=80
- **parallel_safe**: true — lug positions, bore diameter, and hinge-axis location fixed numerically; matches fixed pin spec

### 3. hinge_block
- **Type**: Custom (make) — qty 2 (identical, one design)
- **Description**: Rectangular block screwed to the base rear exterior wall; carries the ⌀3.1 mm press-fit bore that fixes the steel hinge pin. Pin rotates in the lid lug, is fixed in this block.
- **Key dimensions**: 20 x 12 x 24 mm
- **Interfaces**: Connects to base_box via 2x M3 screws + nuts; to hinge pin (buy) via ⌀3.1 mm press-fit bore
- **parallel_safe**: true — standard fastener interfaces and fixed pin diameter; mounting hole pattern fixed numerically on both sides

### 4. hasp_plate
- **Type**: Custom (make) — qty 1
- **Description**: Flat latch plate with a raised boss carrying a ⌀8 mm horizontal through-hole for a padlock shackle. Screwed to the base front exterior wall, centered.
- **Key dimensions**: 30 x 40 x 15 mm bbox (3 mm plate + 12 mm boss)
- **Interfaces**: Connects to base_box via 2x M3 screws + nuts
- **parallel_safe**: true — standard fastener interface, fixed hole pattern

### 5. hinge_pin (x2), M3 hardware
- **Type**: Standard (buy) — see Make vs Buy
- **Description**: ⌀3 x 35 mm steel dowel pins (hinge axles); M3 pan-head screws + nuts (hinge block and hasp mounting)

## Interfaces
All positions in the global assembly frame defined above. Both sides of each interface carry the SAME nominal numbers in their constraints.md.

- **base_box ↔ hinge_block (x2)**: hinge_block rear-mounted on base outer rear wall (wall outer face at Y=-60). Blocks centered at X=+55 and X=-55, block bottom at Z=62, top at Z=86. Fastening: per block, 2x M3 screws through ⌀3.4 mm clearance holes in the block (hole axes along Y) into matching ⌀3.4 mm through-holes in the base rear wall at Z=68, X = block-center ±5 (i.e., holes at X = ±50 and ±60). M3 nuts on the inside of the rear wall.
- **hinge_block ↔ hinge_pin (buy)**: ⌀3.1 mm bore through the block along X, axis at (Y=-66, Z=80). Light press fit for ⌀3 steel pin (FDM holes print slightly undersized — designer must NOT compensate; nominal 3.1).
- **lid ↔ hinge_pin (buy)**: 2 lid lugs, 15 mm wide, centered at X = +37 and -37 (spans |X| 29.5..44.5, leaving 0.5 mm axial clearance to the block inner face at |X|=45). Lug bore ⌀3.4 mm clearance, axis at (Y=-66, Z=80) — same axis as block bore. Pin ⌀3 x 35 spans |X| 29.5..64.5 per side, fixed in block, rotating in lug.
- **lid ↔ base_box**: closed-lid rest contact — lid flat rim face sits on base rim plane at Z=80, footprints aligned (both 180 x 120, X/Y centered). No fastener; hasp is external.
- **base_box ↔ hasp_plate**: plate mounted on base outer front wall (outer face at Y=+60), centered at X=0, plate spanning Z=40..80. Fastening: 2x M3 screws through ⌀3.4 mm clearance holes in the plate into matching ⌀3.4 mm through-holes in the base front wall at (X=0, Z=48) and (X=0, Z=72). M3 nuts inside.

## Assembly Order
1. base_box (largest part; all other parts locate off it)
2. hinge_block x2 (print once, use twice) — screw to rear wall
3. hasp_plate — screw to front wall
4. lid — align lugs between the hinge blocks
5. Insert hinge pins: press into block bores, passing through lid lug bores

## Make vs Buy
- **Buy**:
  - 2x steel dowel pin ⌀3 x 35 mm (hinge axles)
  - 4x M3 x 20 pan-head screws + 4x M3 nuts (hinge block mounting; grip = 12 mm block + 3 mm wall + nut)
  - 2x M3 x 10 pan-head screws + 2x M3 nuts (hasp plate mounting; grip = 3 mm plate + 3 mm wall + nut)
- **Make**: base_box, lid, hinge_block (x2), hasp_plate — all FDM 3D printed

## Sub-Assemblies
None — FLAT structure. Although the project has 4 make-parts, there is no natural functional grouping that excludes the base or lid: the hinge joint spans base_box + hinge_block + lid + pin, i.e., it involves the two largest top-level parts, so grouping it as a sub-assembly would just re-wrap the whole chest. All parts are validated at the top level.

## Manufacturing Notes (project-wide)
- Process: 3D_printing (FDM) for all make parts. No fillets (deferred project-wide).
- Print orientations (informative, for DFM sanity): base_box floor-down; lid dome-up on its flat rim face (lugs may need support — acceptable); hinge_block on its mounting face; hasp_plate plate-face-down.
- Minimum wall anywhere: 1.0 mm (hasp boss cheeks) — above the 0.8 mm plastic floor.
- STEP + STL export required for every make part after validation.
