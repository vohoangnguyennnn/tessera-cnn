"""L1a: mul8 exhaustive over all 65,536 (a, w) pairs, cocotb + Verilator (spec 10).

    .venv/bin/python -m pytest tb/unit/test_mul8.py        (or: make test-mul8)

One pair per clock, back to back, so a pipelined DUT is also checked at full throughput.
On a mismatch the report includes every booth_ref intermediate for the first failing pairs.
"""
import os
import sys

import cocotb
import pytest
from cocotb.clock import Clock
from cocotb.triggers import FallingEdge

import sim

sys.path.insert(0, str(sim.ROOT / "model"))
import booth_ref  # noqa: E402

# (PE_TYPE, SUM_STYLE, L_MUL)
CONFIGS = [
    ("LUT_INFERRED", "ADDER", 0), ("LUT_INFERRED", "ADDER", 2),
    ("LUT_CUSTOM", "ADDER", 0), ("LUT_CUSTOM", "ADDER", 2),
    ("LUT_CUSTOM", "CSA42", 0), ("LUT_CUSTOM", "CSA42", 2),
]


def describe(a, w, got, style):
    ref = booth_ref.mul(a, w, style)
    h = lambda xs: "[" + ", ".join(f"0x{x:04x}" for x in xs) + "]"
    level = " ".join(f"{k}=0x{ref[k]:04x}" for k in ("s01", "s23", "S", "C") if k in ref)
    return (f"a={a} w={w}: got {got}, expected {a * w}\n"
            f"      booth_ref: one={ref['one']} two={ref['two']} neg={ref['neg']} r={h(ref['r'])}\n"
            f"                 R={h(ref['R'])} e=0x{ref['e']:04x} {level}")


@cocotb.test()
async def mul8_exhaustive(dut):
    """Drive pair t at falling edge t; p must equal a*w at falling edge t + max(L_MUL, 1)."""
    delay = max(int(os.environ["L_MUL"]), 1)
    pairs = [(a, w) for a in range(-128, 128) for w in range(-128, 128)]
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    errors = []
    for t in range(len(pairs) + delay):
        await FallingEdge(dut.clk)
        if t >= delay:
            a, w = pairs[t - delay]
            got = dut.p.value.to_signed()
            if got != a * w:
                errors.append((a, w, got))
        if t < len(pairs):
            dut.a.value, dut.w.value = pairs[t]
    report = "\n".join(describe(*e, os.environ["SUM_STYLE"]) for e in errors[:5])
    assert not errors, f"{len(errors)} of {len(pairs)} pairs wrong; first ones:\n{report}"


@pytest.mark.parametrize("pe_type,sum_style,l_mul", CONFIGS)
def test_mul8(pe_type, sum_style, l_mul):
    sim.run("mul8", sim.MUL_SRCS, {"PE_TYPE": pe_type, "SUM_STYLE": sum_style, "L_MUL": l_mul}, "test_mul8")
