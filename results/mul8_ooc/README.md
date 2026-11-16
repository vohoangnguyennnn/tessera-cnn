# Multiplier mini-experiment (spec 12.0)

Out-of-context synth + place + route of one `mul8` with registers on every input and output
(`fpga/ooc/mul8_ooc.sv`), Vivado 2024.1, xc7a35tfgg484-2 (speed grade -2). Reproduce with `make mul-ooc`
(~25 min); raw numbers in [summary.csv](summary.csv), reports per configuration in the sub-directories.

Method (`fpga/tcl/ooc_lib.tcl`): the clock constraint is read **before** `synth_design` (synthesis is
timing driven). LUT / FF / logic levels are measured with a 10 ns (100 MHz) clock, the accelerator's
real target, because LUT counts change with the constraint. Fmax is a separate search: one run at
2.0 ns gives Fmax_est = 1 / (T − WNS), then the target drops 10 MHz at a time until WNS ≥ 0.

| Multiplier | L_MUL | LUT | FF | CARRY4 | DSP | Logic levels | Fmax (MHz) |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Booth radix-4, ADDER (hand-designed) | 0 | 67 | 0 | 8 | 0 | 9 | 210 |
| Booth radix-4, ADDER (hand-designed) | 2 | **59** | 67 | 10 | 0 | 3 | 470 |
| Booth radix-4, CSA42 (hand-designed) | 0 | 65 | 0 | 4 | 0 | 7 | 280 |
| Booth radix-4, CSA42 (hand-designed) | 2 | 62 | 69 | 4 | 0 | 6 | **510** |
| Vivado `a * w`, `use_dsp = "no"` | 0 | 61 | 0 | 14 | 0 | 8 | 230 |
| Vivado `a * w`, `use_dsp = "no"` | 2 | 61 | 32 | 14 | 0 | 8 | 220 |
| Vivado `a * w`, `-global_retiming on` | 2 | 61 | 32 | 14 | 0 | 8 | 220 |

## Findings

1. **Combinational, the hand-designed multiplier does not beat Vivado on area.** ADDER costs 67 LUT
   against 61 (+10%). The 7-series carry chain makes adders nearly free, and Vivado's own LUT
   multiplier already uses it well (14 CARRY4). This is what spec 6.1 anticipated.
2. **CSA42 trades carry chain for LUT logic.** Half the CARRY4 of ADDER (4 vs 8) and 2 fewer logic
   levels (7 vs 9), so the fastest combinational design (280 vs 210 MHz). On an ASIC the 4:2 row
   would win clearly; on an FPGA the adder it replaces was already cheap.
3. **Only the hand design can be pipelined.** Vivado's L_MUL = 2 puts both registers after `a * w`,
   and global retiming moved nothing ("forward move = 0, backward move = 0" in the log), so the
   inferred multiplier stays at about 220 MHz. The Booth design has explicit cut points (after
   partial-product placement, after the first summation level) and reaches 470–510 MHz, with 2 fewer
   LUTs than inferred for ADDER (59 vs 61) at the cost of 35 more FFs.
4. **At the 100 MHz system target every variant has > 4 ns of slack in isolation.** In a full lane
   the critical path is the 32 × 17 requant multiply, not the INT8 multiplier (`results/lane_ooc/`).

## Decision: `SUM_STYLE = ADDER` for the accelerator

At 100 MHz speed is irrelevant (all variants have ample slack), and the binding resource is LUTs (the
P = 16 LUT ceiling, spec 2). Pipelined ADDER is the smallest variant: 59 LUT against 62 for CSA42 as a
single multiplier, 1,866 against 1,887 LUT for a whole lane. CSA42 stays in the RTL and in L1a as the
measured alternative.
