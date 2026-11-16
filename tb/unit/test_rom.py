"""L1b: wgt_mem / qparam_mem contain exactly the exported hex files, read back through the RTL
($readmemh path, latency, lane order, field packing) for P in {4, 8, 16}."""
import os
import sys

import cocotb
import pytest
from cocotb.clock import Clock
from cocotb.triggers import FallingEdge

import sim

sys.path.insert(0, str(sim.ROOT / "model"))
import export  # noqa: E402

DEPTH = {"wgt_mem": {4: 2444, 8: 1226, 16: 613}, "qparam_mem": {4: 87, 8: 44, 16: 22}}


@cocotb.test()
async def rom_matches_hex(dut):
    top, P = os.environ["TOP"], int(os.environ["P"])
    d = export.EXPORT / f"P{P}"
    lat = 2 if top == "wgt_mem" else 1
    prefix = "w_lane" if top == "wgt_mem" else "q_lane"
    want = [export.read_hex(d / f"{prefix}{p}.hex") for p in range(P)]
    depth = len(want[0])
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    errors = []
    for t in range(depth + lat):
        await FallingEdge(dut.clk)
        if t >= lat:
            a = t - lat
            for p in range(P):
                if top == "wgt_mem":
                    got = (int(dut.w.value) >> 64 * p) & (2**64 - 1)
                else:
                    got = (int(dut.bias[p].value) << 22) | (int(dut.M[p].value) << 6) | int(dut.n[p].value)
                if got != want[p][a]:
                    errors.append(f"lane {p} addr {a}: got {got:x}, expected {want[p][a]:x}")
        if t < depth:
            dut.addr.value = t
    assert not errors, f"{len(errors)} wrong; first:\n" + "\n".join(errors[:5])


@pytest.mark.parametrize("top", ["wgt_mem", "qparam_mem"])
@pytest.mark.parametrize("P", [4, 8, 16])
def test_rom(top, P):
    params = {"P": P, "D_W" if top == "wgt_mem" else "D_Q": DEPTH[top][P], "HEX_DIR": str(export.EXPORT / f"P{P}")}
    sim.run(top, ["acc_pkg.sv", f"{top}.sv"], params, "test_rom", extra_env={"TOP": top})
