# Bill of Materials

| Qty | Part | Specification | Source | Notes |
|-----|------|--------------|--------|-------|
| 2 | Steel dowel pin | ⌀3 x 35 mm, ISO 2338 (tolerance class m6 or h8 — either works here) | Standard (any fastener supplier) | Hinge axles. Press-fit in hinge_block ⌀3.1 bore, rotating in lid lug ⌀3.4 bore. ⌀3 and L=35 are both in the ISO 2338 standard size series. |
| 4 | Pan-head screw M3 x 20 | ISO 7045 / DIN 7985 (cross-recessed pan head) | Standard | Hinge block mounting: grip = 12 mm block + 3 mm wall = 15 mm; ~5 mm thread protrudes inside for the nut. Head envelope ⌀ ≤ 6.0 mm, height ≤ 2.5 mm (see sourcing_notes.md). |
| 2 | Pan-head screw M3 x 10 | ISO 7045 / DIN 7985 (cross-recessed pan head) | Standard | Hasp plate mounting: grip = 3 mm plate + 3 mm wall = 6 mm; ~4 mm thread protrudes inside for the nut. Same head envelope as above. |
| 6 | Hex nut M3 | ISO 4032 (5.5 mm across flats, 2.4 mm high) | Standard | Inside base_box: 4 on rear wall (hinge blocks), 2 on front wall (hasp plate). Loose nuts against the flat interior wall — no nut pockets needed. |

## Interface dimensions consumed by Make parts (all confirmed against plan)

| Plan assumption | Standard value | Verdict |
|---|---|---|
| Pin diameter ⌀3.0 | ISO 2338 ⌀3: h8 = 2.986–3.000 mm, m6 = 3.002–3.008 mm | OK — ⌀3.1 press bore and ⌀3.4 clearance bore both work for either class |
| Press-fit bore ⌀3.1 (hinge_block, FDM) | — | OK — 0.09–0.11 mm nominal clearance; FDM undersizing yields light press fit as planned |
| Pin clearance bore ⌀3.4 (lid lug) | — | OK — 0.4 mm running clearance |
| M3 clearance holes ⌀3.4 | ISO 273 medium fit for M3 = ⌀3.4 | OK — exact match |
| Screw head sits proud (no counterbores planned) | Pan head ⌀ ≤ 6.0 mm, k ≤ 2.5 mm envelope | OK — nearest features clear by > 4 mm on hinge_block and hasp_plate (checked below) |
| Nut seating on flat interior wall | ISO 4032 M3: 5.5 AF (~6.0 across corners), 2.4 mm high | OK — open cavity, no pocket needed |

**No constraints.md dimension changes were required** — every plan assumption matched the standard. Constraints files gained additive "Purchased-part interfaces (sourcing)" blocks only.
