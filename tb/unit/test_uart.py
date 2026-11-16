"""L1b: UART (spec 9, 10). Loopback tx -> rx of 2,000 random bytes back to back, then the receiver
alone driven bit by bit at +-2.5% baud error, and a bad stop bit that must raise frame_err."""
import random

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import FallingEdge, RisingEdge, Timer

import sim

CLK_NS = 10  # 100 MHz
BAUD = 6_250_000  # 16 clocks per bit in simulation; the phase accumulator works the same at any baud


async def setup(dut):
    cocotb.start_soon(Clock(dut.clk, CLK_NS, unit="ns").start())
    dut.rst.value, dut.tx_send.value, dut.use_ext.value, dut.ext_rx.value = 1, 0, 0, 1
    for _ in range(4):
        await FallingEdge(dut.clk)
    dut.rst.value = 0


async def collect(dut, n, out):
    while len(out) < n:
        await RisingEdge(dut.clk)
        if dut.rx_valid.value:
            out.append(int(dut.rx_data.value))
        assert not dut.rx_frame_err.value, "unexpected framing error"


@cocotb.test()
async def loopback(dut):
    await setup(dut)
    data = [random.Random(5).randrange(256) for _ in range(2000)]
    got = []
    cocotb.start_soon(collect(dut, len(data), got))
    for b in data:
        while True:
            await FallingEdge(dut.clk)
            if dut.tx_ready.value:
                break
        dut.tx_data.value, dut.tx_send.value = b, 1
        await FallingEdge(dut.clk)
        dut.tx_send.value = 0
    for _ in range(40 * 16):
        await FallingEdge(dut.clk)
    assert got == data, f"{sum(a != b for a, b in zip(got, data))} bytes differ, {len(got)}/{len(data)} received"


async def bitbang(dut, byte, bit_ns, stop=1):
    for b in [0] + [(byte >> i) & 1 for i in range(8)] + [stop]:
        dut.ext_rx.value = b
        await Timer(bit_ns, unit="ns")
    dut.ext_rx.value = 1


@cocotb.test()
async def rx_baud_tolerance_and_framing(dut):
    await setup(dut)
    dut.use_ext.value = 1
    rng = random.Random(6)
    nominal = 1e9 / BAUD
    for err in (-0.025, 0.0, +0.025):
        data = [rng.randrange(256) for _ in range(200)]
        got = []
        task = cocotb.start_soon(collect(dut, len(data), got))
        for b in data:
            await bitbang(dut, b, round(nominal * (1 + err), 3))
        await Timer(5 * nominal, unit="ns")
        task.cancel()
        assert got == data, f"baud error {err:+.1%}: {len(got)}/{len(data)} received, {sum(a != b for a, b in zip(got, data))} wrong"
    # stop bit 0 -> frame_err pulse and no byte
    seen_err, seen_valid = [], []

    async def watch():
        while True:
            await RisingEdge(dut.clk)
            seen_err.append(int(dut.rx_frame_err.value))
            seen_valid.append(int(dut.rx_valid.value))
    w = cocotb.start_soon(watch())
    await bitbang(dut, 0x5A, nominal, stop=0)
    await Timer(3 * nominal, unit="ns")
    w.cancel()
    assert sum(seen_err) == 1 and sum(seen_valid) == 0, "bad stop bit must give one frame_err and no byte"


def test_uart():
    sim.run("uart_loop", ["../../rtl/soc/uart_rx.sv", "../../rtl/soc/uart_tx.sv", "../../tb/unit/uart_loop.sv"],
            {"CLK_HZ": 100_000_000, "BAUD": BAUD}, "test_uart")
