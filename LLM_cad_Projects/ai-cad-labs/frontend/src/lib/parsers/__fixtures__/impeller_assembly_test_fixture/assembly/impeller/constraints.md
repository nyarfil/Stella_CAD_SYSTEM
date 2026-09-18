# Constraints: impeller

## Functional Requirements

- Centrifugal compressor wheel: draw air axially at the inducer eye (+Z end),
  discharge radially at the backplate; 6 backswept blades.
- Seat in the main bearing (BUY 6203, 17 × 40 × 12 mm) by a base spigot in the
  bearing's INNER diameter (per user spec — the shaft does not touch this bearing).
- Set the impeller-backface-to-housing running clearance of 0.8 mm
  (user requirement window 0.5–1.0 mm) via a standoff boss bearing on the
  6203 inner-race face.
- Transmit torque by clamp friction: shaft shoulder against the spigot end face,
  lock nut against the hub nose face (no keyway by design).

## Dimensions

- Overall: ⌀72 x 48.8 mm   (revolved envelope: Ø72 backplate tip; total axial from spigot end face to hub nose face)
- Local coordinates (repo convention): bore axis = Z through origin;
  **Z = 0 at the backplate BACKFACE** (the running-clearance datum); +Z toward the nose.
- Axial stack (locked — the shaft's clamp stack is built against these numbers):
  - Spigot Ø17.0 (`D_MB_BORE`, press-fit intent, model nominal): Z = −14.8 … −0.8 (14.0 long
    = 12.0 bearing width + 2.0 protrusion past the inner race for the shaft-shoulder clamp).
  - Standoff boss Ø22.0 (`D_STANDOFF_BOSS`) × 0.8 thick (`T_STANDOFF_BOSS`): Z = −0.8 … 0.
    Boss contacts ONLY the 6203 inner-race face (race land ≈ Ø22.5). Do not exceed Ø23.
  - Backplate Ø72.0 × 5.0 thick: Z = 0 … 5.
  - Hub contour from backplate front (Z = 5) to nose face at **Z = +34.0**; hub nose Ø18.0
    (`D_HUB_NOSE` — flat annular face for the ISO 4032 M10 lock nut; do not go below Ø18).
  - Through-bore Ø10.0 (`D_SHAFT_IMPELLER_SEAT`, slide fit, model nominal 10.0),
    full length Z = −14.8 … +34.0 → grip length 48.8 (`L_IMP_GRIP`).
- Inducer eye diameter `D_EYE` = 34.0 (blade leading-edge tip circle at the nose end).
- Exducer: blade tip at Ø72, blade height 6.0 above the backplate front face.

## Features

- 6 backswept main blades (equal spacing, backsweep ≈ 30–40° at exducer),
  blade thickness 2.0 mm constant (≥ 1.5 mm metal minimum wall).
  Leading edge near the nose between hub (Ø18) and eye (Ø34);
  trailing edge at Ø72, 6.0 tall.
- Hub: smooth monotonic revolved contour from Ø~20 at the backplate to Ø18 at the nose
  (simple spline or line-arc profile; no undercuts).
- NO fillets — deferred project-wide (most common CadQuery failure mode; geometry first).
- No keyway, no balance features, no blade splitters — keep it to the proven scope.

## Interfaces

- Connects to main_bearing (BUY 6203) via spigot: OD 17.0 press-fit intent
  (model nominal 17.0), engagement 12.0 = full bearing width, +2.0 protrusion.
- Connects to main_bearing inner-race FACE via standoff boss Ø22.0 × 0.8:
  this boss thickness IS the running clearance `CLR_RUN` = 0.8 mm
  (bearing sits flush with the housing face; backface at +0.8 clears the housing).
- Connects to pulley_shaft via Ø10.0 through-bore (slide fit) and two clamp faces:
  spigot end face (Z = −14.8, met by the shaft's Ø14→Ø10 shoulder)
  and nose face (Z = +34.0, met by the lock nut). Grip length 48.8 is LOCKED.
- Faces bearing_housing across the 0.8 mm running clearance for radii 20 … 36
  (no contact permitted anywhere on the backface outside the boss).
- Inlet-blockage contract: hub nose Ø18.0 is the ceiling `OD_INLET_MAX` for the
  inlet bearing (688 OD 16.0 complies) — do not reduce the nose below Ø18.

## Manufacturing

- Primary process: 5_axis_milling
  [REVISED S1] Was `CNC_milling`. A backswept centrifugal wheel is not a 3-axis part and the
  DFM evaluator correctly failed it as one (7 rule failures, all reach/shadowing/thin-standing-
  feature findings). `5_axis_milling` is a real process ID in rules/*.json. See open_issues.md
  ISSUE-005: the evaluator's alias map may still flatten this to CNC_milling, which is a harness
  bug to fix, NOT a reason to straighten the blades.
- Material class: Aluminum 6061
- Secondary processes: none (bore reamed H7 intent; no heat treatment)
- 5-axis milling intent for the blade passages; billet stock Ø75 × 55.
- Min wall checks (pre-verified): spigot wall (17−10)/2 = 3.5 ✓; nose wall (18−10)/2 = 4.0 ✓;
  blade 2.0 ✓; boss 0.8 thick is a turned face step, not a free wall ✓.

## Recommended CadQuery approach (PROVEN — do not experiment)

A pre-launch geometry probe in this repo confirmed the risky blade geometry works
via this primitive chain, yielding ONE valid solid:

1. Build the revolved hub/backplate/spigot/boss body (single revolve of the axial profile).
2. Build ONE backswept blade as a profile swept along a spline path
   (loft-with-rotation between hub-line and tip-line profiles also works).
3. Circular-pattern the blade 6× about Z and union all onto the hub → one solid.
4. Cut the Ø10 through-bore last.

Use this chain rather than experimenting with alternatives.
