# One lane out of context (M2)

`lane` = `dot8` (8 × `mul8` + adder tree) + accumulator + post-processing (requant, residual, ReLU),
with registers on all inputs and outputs (`fpga/ooc/lane_ooc.sv`). Vivado 2024.1, xc7a35tfgg484-2,
same method as `results/mul8_ooc/` (area at 100 MHz, separate Fmax search). Reproduce with
`make lane-ooc`; raw numbers in [summary.csv](summary.csv).

After narrowing the requant registers to their exact arithmetic bounds (M2.6, still bit-exact):

| Multiplier in dot8 | Lane LUT | of which dot8 | Accumulator + requant | Lane FF | DSP | Fmax (MHz) | Critical path |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Booth ADDER (chosen) | **1,689** | 650 | 1,039 | 955 | **0** | 110 | `p1` = t × M (31 × 17) |
| Booth CSA42 | 1,711 | 672 | 1,039 | 971 | **0** | 120 | `p1` |
| Vivado `a * w` | 1,709 | 666 | 1,043 | 675 | **0** | 120 | `p1` |

Before narrowing (49-bit residual path, 32-bit t): ADDER 1,866 LUT (requant 1,214), CSA42 1,887,
inferred 1,888. Narrowing saved 177 LUT per lane (−9.5%, −14% of the post-processing).

Narrowed widths: t 31 bit (|acc| < 2^30), t·M 47 bit, main rounding/shift 48 bit, residual r·M_r 24 bit
with a 25-bit rounding/shift and n_r >= 25 forced to 0. See `rtl/core/lane.sv`.

- **0 DSP** in every configuration, requant included (`RQ_USE_DSP = 0`, spec 2), and every lane meets
  100 MHz.
- **Post-processing costs more than the whole dot product** (before narrowing: about twice). One 31 × 17 LUT multiplier (527
  partial-product bits, more than the 8 Booth 8 × 8 multipliers together), two variable
  shifters (main 48-bit, residual 25-bit), rounding adders and clamps. It also holds the critical
  path, not the INT8 multipliers.
- Scaling: P = 8 needs about 13.5k LUT for the lanes alone (spec 2 estimated 8–12k for the whole
  design), and P = 16 about 27k > 20,800 LUT. Remedies from spec 15: narrow the oversized widths (done above), and
  share one requant block between two lanes (each output pixel takes R ≥ 2 cycles).
