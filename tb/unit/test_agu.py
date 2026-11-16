"""L2: agu emits exactly the agu_ref tick sequence, cycle by cycle, for the 10 exported descriptors
x P in {4, 8, 16} (spec 10). act_addr is compared only when in_bounds (it is don't-care otherwise).
Ops run back to back with a few idle cycles in between, as under the controller."""
import os
import sys

import cocotb
import pytest
from cocotb.clock import Clock
from cocotb.triggers import FallingEdge

import sim

sys.path.insert(0, str(sim.ROOT / "model"))
import agu_ref  # noqa: E402
import export  # noqa: E402

FIELDS = ("g", "act_addr", "in_bounds", "w_addr", "first", "last", "wr_addr")


@cocotb.test()
async def agu_matches_ref(dut):
    P = int(os.environ["P"])
    descs = [export.unpack_desc(v) for v in export.read_hex(export.EXPORT / f"P{P}" / "desc.hex")]
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    dut.rst.value, dut.start.value = 1, 0
    for _ in range(3):
        await FallingEdge(dut.clk)
    dut.rst.value = 0
    total = 0
    for op, d in enumerate(descs):
        want = list(agu_ref.agu(d, P))
        dut.d.value = export.pack_desc(d)
        dut.start.value = 1
        await FallingEdge(dut.clk)
        dut.start.value = 0
        got, cycles = [], 0
        while True:
            await FallingEdge(dut.clk)
            cycles += 1
            assert cycles < len(want) + 10, f"op {op}: done never came"
            if dut.valid.value:
                t = agu_ref.Tick(*(int(getattr(dut, f).value) for f in FIELDS))
                got.append(t)
                if dut.done.value:
                    break
            else:
                assert not got, f"op {op}: bubble after {len(got)} ticks"
        assert len(got) == len(want), f"op {op}: {len(got)} ticks, expected {len(want)}"
        for i, (a, b) in enumerate(zip(got, want)):
            if b.in_bounds:
                same = a == b._replace(in_bounds=1)
            else:
                same = a._replace(act_addr=0) == b._replace(act_addr=0, in_bounds=0)
            assert same, f"op {op} tick {i}: got {a}, expected {b}"
        assert got[-1].last, f"op {op}: done not on a last tick"
        total += len(got)
        for _ in range(3):  # idle cycles between ops, like controller FETCH_DESC / DRAIN
            await FallingEdge(dut.clk)
    dut._log.info(f"P={P}: {total} ticks match agu_ref")


@pytest.mark.parametrize("P", [4, 8, 16])
def test_agu(P):
    sim.run("agu", ["acc_pkg.sv", "agu.sv"], {"P": P}, "test_agu")
