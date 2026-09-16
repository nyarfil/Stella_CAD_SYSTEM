# Bill of Materials — impeller_assembly

Confirm-or-flag pass on the planner's three Buy selections:
**all three CONFIRMED with boundary dimensions unchanged.**
Every dimension below feeds a LOCKED parameter in `design_plan.md § Interfaces`;
any substitution with different boundary dims reopens the plan.

| Qty | Part | Specification | Boundary dims (mm) | Feeds plan parameters | Source | Approx cost |
|-----|------|--------------|--------------------|----------------------|--------|-------------|
| 1 | main_bearing | Deep-groove ball bearing **6203-2Z** (open 6203 also acceptable per plan; 2Z recommended) | 17 bore × 40 OD × 12 wide | `D_MB_BORE` = 17.0 · `D_MB_OD` = 40.0 · `W_MB` = 12.0 | SKF 6203-2Z · NSK 6203ZZ · NTN 6203ZZ · Schaeffler/FAG 6203-2Z (any major brand — dims are ISO-standardized) | ~$3–10 |
| 1 | inlet_bearing | Deep-groove ball bearing **688-2Z (688ZZ)** — the SHIELDED variant, deliberately: it guarantees the planned 5 mm width (see note 2) | 8 bore × 16 OD × 5 wide | `D_SHAFT_INLET_SEAT` = 8.0 · OD 16.0 ≤ `OD_INLET_MAX` = 18.0 ✓ | EZO / NMB / NSK 688ZZ-class miniature lines; exact vendor SKU: needs catalog lookup at purchase (designation is generic across makers) | ~$2–6 |
| 1 | lock_nut | Hex nut **ISO 4032, M10 × 1.5 coarse, steel property class 8**, zinc-plated or plain. **Do NOT substitute DIN 934** (see note 3) | height 8.4 max / 8.04 min · 16.0 across flats · across corners 17.77 min – 18.48 max | `THREAD_NOSE` = M10×1.5 · seats on `D_HUB_NOSE` = 18.0 (worst-case corner overhang 0.24/side < 0.3 ✓) | Any fastener house (Bossard, Würth, fabory-class distributors) — specify "ISO 4032" explicitly | <$0.50 |
| 4 | foot bolt (optional hardware, not modeled) | Socket head cap screw **M5×16 DIN 912** (hex head DIN 933 equally fine), class 8.8 | M5×0.8 thread; fits the housing's 4 × Ø5.5 clearance holes | bearing_housing foot mounting (plan § Make vs Buy, optional) | Standard | pennies |

## Per-part details

### main_bearing — 6203(-2Z), 17 × 40 × 12

- Tolerance class: normal (ISO P0 / ABEC-1) is sufficient for this duty.
- Load ratings (SKF catalog values; other majors within a few %):
  C ≈ 9.95 kN dynamic, C0 ≈ 4.75 kN static.
- Limiting speed: on the order of 17,000–22,000 rpm grease-lubricated,
  brand/cage dependent — verify against the chosen brand's catalog
  if the duty point exceeds ~15,000 rpm.
- Inner-ring shoulder (race land) ≈ Ø22.3–22.6 brand-dependent:
  the impeller's Ø22.0 standoff boss stays inside it ✓
  (contacts inner race only, as the plan requires).
- Outer-ring land ≈ Ø35.5–36: the housing's Ø34 back-bore shoulder
  retains the outer race with margin ✓.

### inlet_bearing — 688-2Z, 8 × 16 × 5

- **Variant pinned to 688-2Z / 688ZZ**: the plain OPEN 688 is commonly
  cataloged at 8 × 16 × **4**; the shielded variant is the 8 × 16 × 5 the plan
  dimensioned around (axial span Z = +47…+52). Bore and OD are identical either way.
- Load rating: miniature class, roughly 1.3–1.9 kN dynamic —
  **UNVERIFIED: needs catalog lookup** for the exact brand figure.
  Duty here is a lightly loaded pilot/support bearing, far below any plausible rating.
- Tolerance class: normal (ABEC-1) sufficient.

### lock_nut — ISO 4032 M10×1.5, class 8

- Bearing (washer/chamfer) face d_w ≥ 14.6 mm:
  sits fully on the impeller's Ø10→Ø18 nose annulus ✓.
- Modeled height 8.4 is the ISO max; a real nut may be up to 0.36 shorter —
  nut top then ≥ Z +56.84 local on the shaft, still inside the thread span 45…59 ✓.
- **Retention on a rotating spindle nose: apply medium-strength threadlocker
  (Loctite 243 class) at assembly** — geometry unchanged;
  see sourcing_notes.md for why a prevailing-torque nut was NOT specified.
