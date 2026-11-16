"""L3: one op at a time on the accelerator core (controller + AGU + memories + PE array) against
golden.run (spec 10). For op k: write its input bank (and residual bank) through the host port, run with
first_op = stop_after_op = k, read the output bank back and compare byte for byte. 10 ops x P in {4, 8, 16}.
The image is random (fixed seed), so the test needs no dataset; L4 uses real CIFAR-10 test images."""
import os
import sys
from pathlib import Path

import cocotb
import numpy as np
import pytest
from cocotb.clock import Clock
from cocotb.triggers import FallingEdge, RisingEdge, with_timeout

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "unit"))
import sim  # noqa: E402

sys.path.insert(0, str(sim.ROOT / "model"))
import agu_ref  # noqa: E402
import export  # noqa: E402
import golden  # noqa: E402
from golden import OPS  # noqa: E402

DEPTH = {4: (2444, 87), 8: (1226, 44), 16: (613, 22)}  # (D_W, D_Q)
OVERHEAD = 40  # allowed cycles per op beyond the AGU ticks: FETCH/START + pipeline drain


async def host_write(dut, bank, words):
    dut.host_bank.value, dut.host_we.value, dut.host_be.value = bank, 1, 0xFF
    for addr, w in enumerate(words):
        dut.host_addr.value, dut.host_wdata.value = addr, w
        await FallingEdge(dut.clk)
    dut.host_we.value = 0


async def host_read(dut, bank, n):
    """Address set in iteration j is sampled at the next rising edge; the data (read latency 2)
    is visible after the edge that ends iteration j + 1."""
    dut.host_bank.value, dut.host_we.value = bank, 0
    out = []
    for j in range(n + 1):
        if j < n:
            dut.host_addr.value = j
        await FallingEdge(dut.clk)
        if j >= 1:
            out.append(int(dut.host_rdata.value))
    return out


async def run_op(dut, k):
    dut.first_op.value, dut.stop_after_op.value, dut.start.value = k, k, 1
    await FallingEdge(dut.clk)
    dut.start.value = 0
    await with_timeout(RisingEdge(dut.done), 2_000_000, "ns")
    await FallingEdge(dut.clk)
    return int(dut.cycles.value)


def bytes_of(words):
    return np.array([[(w >> 8 * i) & 0xFF for i in range(8)] for w in words], dtype=np.uint8)


@cocotb.test()
async def ops_match_golden(dut):
    P = int(os.environ["P"])
    q = golden.load_qparams()
    img = np.random.default_rng(int(os.environ.get("SEED", "1"))).integers(-128, 128, (1, 3, 32, 32))
    gold = golden.run(q, img)
    descs = export.descriptors(q, P)
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    dut.rst.value, dut.start.value, dut.host_we.value = 1, 0, 0
    for _ in range(3):
        await FallingEdge(dut.clk)
    dut.rst.value = 0
    report = []
    for k, (op, d) in enumerate(zip(OPS, descs)):
        await host_write(dut, d["in_bank"], export.act_words(gold[op.src][0]))
        if op.res:
            await host_write(dut, d["res_bank"], export.act_words(gold[op.res][0]))
        cycles = await run_op(dut, k)
        want = export.act_words(gold[op.name][0])
        got = await host_read(dut, d["out_bank"], len(want))
        g, w = bytes_of(got), bytes_of(want)
        if op.name == "fc":  # only the 10 logits are defined (P = 4 leaves bytes 12..15 stale)
            g, w = g.ravel()[:10], w.ravel()[:10]
        bad = np.argwhere(g != w)
        assert not len(bad), (f"P={P} op {op.name}: {len(bad)} bytes wrong, first at (word, byte) "
                              f"{bad[0].tolist()}: got {g[tuple(bad[0])]}, expected {w[tuple(bad[0])]}")
        ticks = agu_ref.op_cycles(d)
        assert ticks <= cycles <= ticks + OVERHEAD, f"P={P} op {op.name}: {cycles} cycles for {ticks} ticks"
        report.append(f"{op.name} {cycles}/{ticks}")
    dut._log.info(f"P={P}: all 10 ops match golden; cycles/ticks: " + ", ".join(report))


@pytest.mark.parametrize("P", [4, 8, 16])
def test_op(P):
    d_w, d_q = DEPTH[P]
    srcs = ["acc_pkg.sv", "booth_r4_mul8.sv", "mul8.sv", "dot8.sv", "lane.sv", "agu.sv", "act_mem.sv",
            "wgt_mem.sv", "qparam_mem.sv", "pe_array.sv", "controller.sv", "accel.sv"]
    params = {"PE_TYPE": "LUT_CUSTOM", "SUM_STYLE": "ADDER", "L_MUL": 2, "P": P, "D_W": d_w, "D_Q": d_q,
              "HEX_DIR": str(export.EXPORT / f"P{P}")}
    sim.run("accel", srcs, params, "test_op", test_dir=Path(__file__).parent)
