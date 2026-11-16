"""L1b: dot8 against the Python dot product, >= 10^5 vectors + corners (spec 10)."""
import os
import random

import cocotb
import pytest
from cocotb.clock import Clock
from cocotb.triggers import FallingEdge

import sim

N_RANDOM = 100_000
CORNERS = [[-128] * 8, [127] * 8, [-128, 127] * 4, [127, -128] * 4, [0] * 8, [-1] * 8, [1] * 8]
CONFIGS = [("LUT_CUSTOM", "ADDER", 2), ("LUT_CUSTOM", "ADDER", 0)]


def vectors(seed):
    rng = random.Random(seed)
    yield from ((a, w) for a in CORNERS for w in CORNERS)  # all -128 x all -128 = +131072, etc.
    for _ in range(N_RANDOM):
        yield [rng.randrange(-128, 128) for _ in range(8)], [rng.randrange(-128, 128) for _ in range(8)]


@cocotb.test()
async def dot8_random(dut):
    delay = int(os.environ["L_MUL"]) + 3  # L_DOT
    vecs = list(vectors(seed=1))
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    errors = []
    for t in range(len(vecs) + delay):
        await FallingEdge(dut.clk)
        if t >= delay:
            a, w = vecs[t - delay]
            want, got = sum(x * y for x, y in zip(a, w)), dut.sum.value.to_signed()
            if got != want:
                errors.append(f"a={a} w={w}: got {got}, expected {want}")
        if t < len(vecs):
            dut.a.value, dut.w.value = sim.pack(vecs[t][0]), sim.pack(vecs[t][1])
    assert not errors, f"{len(errors)} of {len(vecs)} wrong; first:\n" + "\n".join(errors[:5])


@pytest.mark.parametrize("pe_type,sum_style,l_mul", CONFIGS)
def test_dot8(pe_type, sum_style, l_mul):
    sim.run("dot8", sim.MUL_SRCS + ["dot8.sv"],
            {"PE_TYPE": pe_type, "SUM_STYLE": sum_style, "L_MUL": l_mul}, "test_dot8")
