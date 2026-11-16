"""L1b: lane (dot8 + accumulator + post-processing) against golden.rq (spec 4.4, 6.2, 10).

Random output pixels with R chunks each, streamed back to back exactly as the AGU would
(no gaps inside an op), plus corners: all -128 / all 127 chunks, n = 1 and n = 47, int16 and
int8 saturation on both sides, residual on/off, ReLU on/off. Every y must appear at exactly
last + L_POST with the golden value.
"""
import os
import random
import sys

import cocotb
import pytest
from cocotb.clock import Clock
from cocotb.triggers import FallingEdge

import sim

sys.path.insert(0, str(sim.ROOT / "model"))
import golden  # noqa: E402

L_POST = 6
RESET_CYCLES = 3
R_CHOICES = [2, 4, 9, 18, 36, 72, 512]  # chunks per pixel: 2 = s2s (minimum, spec 5.4) ... 512 = fc
CORNER = [[-128] * 8, [127] * 8, [-128, 127] * 4]
CHUNKS_PER_OP = 12_000  # 9 ops -> > 10^5 vectors
CONFIGS = [("LUT_CUSTOM", "ADDER", 2)]


def clamp(x, lo, hi):
    return max(lo, min(hi, x))


def expected(px, op):
    """Spec 4.4, using golden.rq itself."""
    t = px["bias"] + sum(sum(x * y for x, y in zip(a, w)) for a, w in px["chunks"])
    assert abs(t) < 2**30
    y = clamp(int(golden.rq(t, px["M"], px["n"])), -2**15, 2**15 - 1)
    if op["res_en"]:
        y += clamp(int(golden.rq(px["r"], op["m_r"], op["n_r"])), -2**15, 2**15 - 1)
    z = clamp(y, -128, 127)
    return max(z, 0) if op["relu_en"] else z


def make_ops(rng):
    ops = [dict(res_en=re, relu_en=rl, m_r=rng.randrange(2**15, 2**16), n_r=rng.choice([17, 18, rng.randrange(1, 48)]))
           for re in (0, 1) for rl in (0, 1)]
    ops.append(dict(res_en=1, relu_en=0, m_r=2**16 - 1, n_r=1))  # y_res saturates int16 both ways
    ops.append(dict(res_en=1, relu_en=1, m_r=2**15, n_r=47))  # largest shift: y_res = 0
    # edges of the narrowed 25-bit residual path: 23 is the last shift with a non-zero result,
    # 24 the last one computed, 25 the first one forced to 0 (lane.sv)
    ops += [dict(res_en=1, relu_en=0, m_r=2**16 - 1, n_r=k) for k in (23, 24, 25)]
    return ops


def make_pixel(rng):
    R = rng.choices(R_CHOICES, weights=[3, 3, 3, 3, 2, 1, 0.3])[0]  # fc-sized pixels are rare
    if rng.random() < 0.05:  # saturating corner: the same extreme chunk R times
        a, w = rng.choice(CORNER), rng.choice(CORNER)
        chunks = [(a, w)] * R
    else:
        chunks = [([rng.randrange(-128, 128) for _ in range(8)], [rng.randrange(-128, 128) for _ in range(8)])
                  for _ in range(R)]
    u = rng.random()
    if u < 0.03:  # |t| close to the 2^30 bound that sizes the 31-bit t and 47-bit t*M registers
        bias = rng.choice([1, -1]) * (2**30 - 2**27 + rng.randrange(2**20))
    elif u < 0.13:
        bias = rng.randrange(-2**28, 2**28)
    else:
        bias = rng.randrange(-2**16, 2**16)
    M = rng.randrange(2**15, 2**16)
    t = bias + sum(sum(x * y for x, y in zip(a, w)) for a, w in chunks)
    if rng.random() < 0.15:
        n = rng.choice([1, 2, 46, 47])  # extremes: heavy saturation / everything rounds to 0
    else:  # like real layers: |t*M| / 2^n lands around the int8 range, so rounding is visible
        n = min(max((abs(t) * M).bit_length() - rng.randrange(3, 9), 1), 47)
    return dict(chunks=chunks, bias=bias, M=M, n=n, r=rng.randrange(-128, 128))


def schedule(rng, l_dot):
    """Per-cycle stimulus: aw[t], ctl[t] (= chunk t - L_DOT), op[t]; expect[t] = y seen at falling edge t."""
    aw, ctl, opc, expect = {}, {}, {}, {}
    t = RESET_CYCLES + 1
    for op in make_ops(rng):
        start, chunks = t, 0
        while chunks < CHUNKS_PER_OP:
            px = make_pixel(rng)
            for k, (a, w) in enumerate(px["chunks"]):
                last = k == len(px["chunks"]) - 1
                aw[t] = (sim.pack(a), sim.pack(w))
                ctl[t + l_dot] = dict(first=int(k == 0), last=int(last), bias=px["bias"], M=px["M"], n=px["n"], r=px["r"])
                if last:
                    expect[t + l_dot + L_POST] = (expected(px, op), px, op)
                t += 1
            chunks += len(px["chunks"])
        t += l_dot + L_POST + 2  # drain before the op-constant inputs change (controller DRAIN, spec 6.6)
        for u in range(start, t):
            opc[u] = op
    return aw, ctl, opc, expect, t


@cocotb.test()
async def lane_random(dut):
    l_dot = int(os.environ["L_MUL"]) + 3
    aw, ctl, opc, expect, T = schedule(random.Random(7), l_dot)
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    idle_ctl = dict(first=0, last=0, bias=0, M=2**15, n=1, r=0)
    driven, got = {}, {}

    def drive(name, value):  # writing only changed values keeps the 10^5-cycle run fast
        if driven.get(name) != value:
            getattr(dut, name).value = value
            driven[name] = value

    for t in range(T + 1):
        await FallingEdge(dut.clk)
        if t > RESET_CYCLES and dut.y_valid.value:
            got[t] = dut.y.value.to_signed()
        drive("rst", int(t < RESET_CYCLES))
        a, w = aw.get(t, (0, 0))
        drive("a", a), drive("w", w)
        for k, v in ctl.get(t, idle_ctl).items():
            drive(k, v)
        for k, v in opc.get(t, opc[RESET_CYCLES + 1]).items():
            drive(k, v)

    errors = [f"cycle {t}: expected {e[0]}, got {got.get(t, 'no y_valid')}  (bias={e[1]['bias']} M={e[1]['M']} "
              f"n={e[1]['n']} r={e[1]['r']} R={len(e[1]['chunks'])} op={e[2]})"
              for t, e in expect.items() if got.get(t) != e[0]]
    errors += [f"cycle {t}: unexpected y_valid (y={y})" for t, y in got.items() if t not in expect]
    n_vec = sum(1 for _ in aw)
    assert not errors, f"{len(errors)} errors over {len(expect)} pixels / {n_vec} vectors; first:\n" + "\n".join(errors[:5])
    dut._log.info(f"{len(expect)} pixels, {n_vec} vectors: all match golden at last + {L_POST}")


@pytest.mark.parametrize("pe_type,sum_style,l_mul", CONFIGS)
def test_lane(pe_type, sum_style, l_mul):
    sim.run("lane", sim.MUL_SRCS + ["dot8.sv", "lane.sv"],
            {"PE_TYPE": pe_type, "SUM_STYLE": sum_style, "L_MUL": l_mul}, "test_lane")
