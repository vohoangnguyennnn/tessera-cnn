"""L4: the full network on real CIFAR-10 test images against the golden vectors of export.py (spec 10).

- First N_STEP images: ops run one by one on the same memory state (op k reads what op k-1 wrote),
  and the output bank is dumped after every op and compared with golden_<i>_<op>.hex.
- All N_IMAGES images: one uninterrupted run of the 10 ops, as on the board; the 10 logits must match
  golden_<i>_fc.hex and the cycle count must be the same for every image.
Needs model/vectors/ (make export). P = 8, the main configuration.
"""
import os
import sys
from pathlib import Path

import cocotb
import pytest
from cocotb.clock import Clock
from cocotb.triggers import FallingEdge, RisingEdge, with_timeout

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "unit"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "op"))
import sim  # noqa: E402

sys.path.insert(0, str(sim.ROOT / "model"))
import export  # noqa: E402
import golden  # noqa: E402
from golden import OPS  # noqa: E402
from test_op import host_read, host_write, run_op  # noqa: E402

P, D_W, D_Q = 8, 1226, 44
N_IMAGES, N_STEP = 50, 10


def logits(words):
    b = [(words[i // 8] >> 8 * (i % 8)) & 0xFF for i in range(10)]
    return [x - 256 if x >= 128 else x for x in b]


async def run_all(dut):
    dut.first_op.value, dut.stop_after_op.value, dut.start.value = 0, 9, 1
    await FallingEdge(dut.clk)
    dut.start.value = 0
    await with_timeout(RisingEdge(dut.done), 5_000_000, "ns")
    await FallingEdge(dut.clk)
    return int(dut.cycles.value)


@cocotb.test()
async def network_matches_golden(dut):
    vec = export.VECTORS
    descs = export.descriptors(golden.load_qparams(), P)
    labels = [int(l.split()[1]) for l in (vec / "labels.txt").read_text().splitlines()]
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    dut.rst.value, dut.start.value, dut.host_we.value = 1, 0, 0
    for _ in range(3):
        await FallingEdge(dut.clk)
    dut.rst.value = 0
    cycles, correct = set(), 0
    for i in range(N_IMAGES):
        img = export.read_hex(vec / f"img_{i}.hex")
        if i < N_STEP:  # op by op, dumping every intermediate bank
            await host_write(dut, 0, img)
            for k, (op, d) in enumerate(zip(OPS, descs)):
                await run_op(dut, k)
                want = export.read_hex(vec / f"golden_{i}_{op.name}.hex")
                got = await host_read(dut, d["out_bank"], len(want))
                if op.name == "fc":
                    assert logits(got) == logits(want), f"image {i} fc: {logits(got)} vs {logits(want)}"
                else:
                    bad = [a for a, (g, w) in enumerate(zip(got, want)) if g != w]
                    assert not bad, f"image {i} op {op.name}: {len(bad)} words wrong, first word {bad[0]}"
        await host_write(dut, 0, img)
        cycles.add(await run_all(dut))
        got = logits(await host_read(dut, 1, 2))
        want = logits(export.read_hex(vec / f"golden_{i}_fc.hex"))
        assert got == want, f"image {i}: logits {got}, golden {want}"
        correct += max(range(10), key=lambda c: (got[c], -c)) == labels[i]  # argmax, lowest index on ties
    assert len(cycles) == 1, f"cycle count differs between images: {cycles}"
    dut._log.info(f"{N_IMAGES} images: logits match golden ({N_STEP} with every intermediate bank); "
                  f"{cycles.pop()} cycles/image; top-1 {correct}/{N_IMAGES}")


def test_net():
    if not (export.VECTORS / f"img_{N_IMAGES - 1}.hex").exists():
        pytest.skip("model/vectors/ missing: run `make export` (needs the CIFAR-10 dataset)")
    srcs = ["acc_pkg.sv", "booth_r4_mul8.sv", "mul8.sv", "dot8.sv", "lane.sv", "agu.sv", "act_mem.sv",
            "wgt_mem.sv", "qparam_mem.sv", "pe_array.sv", "controller.sv", "accel.sv"]
    params = {"PE_TYPE": "LUT_CUSTOM", "SUM_STYLE": "ADDER", "L_MUL": 2, "P": P, "D_W": D_W, "D_Q": D_Q,
              "HEX_DIR": str(export.EXPORT / f"P{P}")}
    sim.run("accel", srcs, params, "test_net", test_dir=Path(__file__).parent)
