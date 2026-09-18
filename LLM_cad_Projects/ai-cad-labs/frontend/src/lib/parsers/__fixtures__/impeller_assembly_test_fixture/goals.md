# Goals — impeller_assembly

Design a small rotating-machinery assembly
centered on a **centrifugal compressor impeller**.

## Design brief (user's spec — verbatim intent)

- **Integrated pulley-shaft**: the pulley wheel and the shaft are ONE part,
  machined from the same bar stock.
  No belt needs to be modeled.
- **Bearing housing**: fairly simple and straight —
  a platform the assembly seats on.
  It contains the bearing,
  gripping the bearing's OUTER diameter.
- **Bearing**: its inner race interfaces with a lip/ridge (shoulder)
  on the impeller's base.
- **Centrifugal compressor impeller**: its base flange seats on the bearing's
  INNER diameter;
  the flange thickness spaces the impeller away from the housing face —
  roughly 0.5 to 1 mm of running clearance, sized as makes sense.
- **Lock nut and inlet bearing: small.**
  The inlet-end bearing must stay small enough that it does not block
  the impeller inlet (see sketch annotation).

## Input sketch (first-class design input)

`user_initial_sketch.jpeg` in this project directory is the user's hand-drawn
cross-section of the intended assembly.
**Agents should Read the image directly** (the Read tool renders it).

Interpretation rules, per the user:

- Treat the sketch as guidance about **sub-assembly composition** —
  which parts exist and how they stack —
  **not** about sizing.
- **Size everything sensibly and proportionally.**

### Sketch reading (composition along the shaft axis, left to right)

1. **Integrated pulley wheel on shaft** (sketch: green, annotated) —
   a grooved pulley integral with the shaft; one machined part.
2. **Bearing housing / impeller seat** (sketch: blue, annotated
   "representative bearing house, impeller seat") —
   an upright platform/plate the assembly seats on;
   its bore grips the main bearing's outer diameter.
3. **Main bearing** (sketch: orange, rolling elements drawn) —
   held in the housing bore by its OD;
   its inner race contacts a shoulder on the impeller's base.
4. **Impeller** (sketch: green/red, annotated) —
   centrifugal compressor wheel with backswept blades;
   its base flange has a spigot/shoulder seating in the bearing's inner
   diameter, and the flange thickness sets the running clearance
   (0.5–1.0 mm) between the impeller backface and the housing face.
5. **Small lock bolt/nut** (sketch: black, annotated "small lock bolt") —
   retains the impeller on the shaft at the inlet end.
6. **Small inlet bearing** (sketch: orange, annotated
   "small bearing (don't block …)") —
   supports the shaft's inlet end;
   deliberately small so it does not obstruct the inducer inlet.
   The shaft continues past it (break line in the sketch).

## Sizing guidance

- No target dimensions were given:
  choose a sensible small-machinery scale and keep all parts proportional
  to each other and to the sketch's composition.
- Anchor sizing on **standard catalog bearing dimensions**
  (bearings are Buy parts; size the shaft, housing bore, and impeller
  shoulder around the chosen bearings, not the other way around).
- Respect the stated 0.5–1.0 mm impeller-backface-to-housing running
  clearance.

## Success criteria

- All parts modeled as parametric CadQuery code, validated with renders.
- A complete `assembly.py` placing every part in its sketch position,
  with assembly renders proving the stack fits:
  pulley-shaft → housing-held main bearing → impeller shoulder on the
  bearing inner race → lock nut → small inlet bearing.
- Interfaces consistent: bearing OD ↔ housing bore, bearing ID ↔ impeller
  spigot, shaft diameter ↔ bearing bores, running clearance present.
- STEP/STL exports for all validated parts.
