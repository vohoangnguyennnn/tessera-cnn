"""L1b: act_mem against a Python model of the 3 banks (spec 6.3, 10): byte enables, read latency 2,
bank routing by in/res/out bank (all distinct inside an op), and host mode owning every port."""
import random

import cocotb
import pytest
from cocotb.clock import Clock
from cocotb.triggers import FallingEdge

import sim

N_CYCLES = 60_000
WORDS = 2048


@cocotb.test()
async def act_mem_random(dut):
    rng = random.Random(3)
    mem = [[None] * WORDS for _ in range(3)]  # None: never fully written -> not checked
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    pending = []  # (cycle when data is due, signal, expected word)
    host = False
    errors, checks = [], 0

    def write(b, addr, be, data):
        old = mem[b][addr] or [None] * 8
        mem[b][addr] = [(data >> 8 * i) & 0xFF if be >> i & 1 else old[i] for i in range(8)]

    def word(b, addr):
        w = mem[b][addr]
        return None if w is None or None in w else sum(x << 8 * i for i, x in enumerate(w))

    banks = [0, 1, 2]
    for t in range(N_CYCLES):
        await FallingEdge(dut.clk)
        for due, sig, want in [p for p in pending if p[0] == t]:
            checks += 1
            got = int(getattr(dut, sig).value)
            if got != want:
                errors.append(f"cycle {t} {sig}: got {got:016x}, expected {want:016x}")
        pending = [p for p in pending if p[0] > t]
        if t % 500 == 0:  # new "op" or host session: re-route the banks
            host = rng.random() < 0.3
            rng.shuffle(banks)
            dut.host_sel.value = int(host)
            dut.in_bank.value, dut.res_bank.value, dut.out_bank.value = banks
        if host:
            b, addr = rng.randrange(3), rng.randrange(WORDS)
            we = rng.random() < 0.5
            be, data = rng.randrange(256), rng.getrandbits(64)
            dut.host_bank.value, dut.host_addr.value, dut.host_we.value = b, addr, int(we)
            dut.host_be.value, dut.host_wdata.value = be, data
            dut.wr_en.value = 1  # must be ignored in host mode
            if we:
                write(b, addr, be, data)
            elif (w := word(b, addr)) is not None:
                pending.append((t + 2, "host_rdata", w))
        else:
            ib, rb, ob = banks
            ra, rs = rng.randrange(WORDS), rng.randrange(WORDS)
            dut.rd_addr.value, dut.res_addr.value = ra, rs
            for sig, b, a in (("rd_data", ib, ra), ("res_data", rb, rs)):
                if (w := word(b, a)) is not None:
                    pending.append((t + 2, sig, w))
            we = rng.random() < 0.7
            wa, be, data = rng.randrange(WORDS), rng.randrange(256), rng.getrandbits(64)
            dut.wr_en.value, dut.wr_addr.value, dut.wr_be.value, dut.wr_data.value = int(we), wa, be, data
            dut.host_we.value = 1  # must be ignored when the accelerator owns the ports
            if we:
                write(ob, wa, be, data)
    assert not errors, f"{len(errors)} of {checks} reads wrong; first:\n" + "\n".join(errors[:5])
    assert checks > 20_000, f"only {checks} reads checked"
    dut._log.info(f"{checks} reads checked over {N_CYCLES} cycles")


def test_act_mem():
    sim.run("act_mem", ["acc_pkg.sv", "act_mem.sv"], {}, "test_act_mem")
