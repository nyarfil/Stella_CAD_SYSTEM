# Constraints: lid

## Functional Requirements
- Curved half-cylinder lid closing the base box, matching its 180 x 120 footprint
- Rotates on two ⌀3 steel hinge pins via integral rear lugs
- Rests flat on the base rim when closed

## Dimensions
- Overall: 180 x 134 x 64 mm   (dome 180 x 120 x 60, plus hinge lugs projecting 14 mm rearward in -Y and 4 mm below the rim plane)
- Local coordinates: centered on XY, flat rim face at Z=0, dome in +Z. Half-cylinder axis parallel to X at (Y=0, Z=0). Rear (hinge) side = -Y. In the assembly this part is placed at global Z=+80 (rim plane), so local Z=0 == global Z=80; local hinge axis (Y=-66, Z=0) == global (Y=-66, Z=80).
- Dome: outer radius 60 mm, length 180 mm, shell wall 3 mm (inner radius 57 mm), open at the flat bottom
- End caps: flat semicircular walls, 3 mm thick, at X=±90 (outer faces)

## Features
- Half-cylinder shell as above (3 mm wall)
- 2x integral hinge lugs on the rear side:
  - Width 15 mm (along X), centered at X=+37 and X=-37 (each spans |X| 29.5..44.5)
  - Lug body: rectangular tab spanning Y=-74..-60 and Z=-4..+4, merged with the shell at Y≈-60
  - Each lug: ⌀3.4 mm through-bore along X, axis at (Y=-66, Z=0) — clearance fit, pin rotates in lug
- NO fillets (deferred project-wide)

## Interfaces
- Connects to hinge_pin (buy, ⌀3 x 35 steel dowel) via the 2 lug bores: ⌀3.4 mm clearance, axis at local (Y=-66, Z=0) = global (Y=-66, Z=80). Same axis as the hinge_block ⌀3.1 press-fit bores. 0.5 mm axial clearance between lug outer face (|X|=44.5) and hinge_block inner face (|X|=45).
- Connects to base_box via rest contact: flat rim face (local Z=0) sits on the base rim plane (global Z=80), footprints aligned (180 x 120, X/Y centered). No fastener.

## Manufacturing
- Primary process: 3D_printing
- Material class: PLA (or PETG — match base_box)
- Secondary processes: none
- Print rim-face-down (dome up); lugs extend 4 mm below the rim face and will need a small support/brim — acceptable
- Minimum wall thickness: 3 mm shell; lug wall around ⌀3.4 bore >= 2.3 mm (lug is 8 mm thick in Z around the bore) — above the 0.8 mm plastic floor

## Purchased-part interfaces (sourcing)
Sourced components confirmed against standards (see external/bom.md). No dimensional changes to the planner's constraints above — all plan assumptions matched.
- **Hinge pin = ISO 2338 steel dowel pin ⌀3 x 35 mm** (either m6: 3.002–3.008 mm, or h8: 2.986–3.000 mm — both classes acceptable).
- **Lug bore ⌀3.4 mm confirmed**: gives ~0.4 mm running clearance on the ⌀3 pin — pin ROTATES in these lugs (it is fixed in the hinge_block). Model the bore at nominal 3.4, no compensation.
- Pin span check (per side): pin covers |X| 29.5..64.5 → 15 mm through the lug, 0.5 mm gap, 19.5 mm in the block. Lug geometry above is consistent — do not change lug width or position.
