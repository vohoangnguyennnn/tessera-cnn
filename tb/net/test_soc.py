"""System test of soc (UART + host_if + accelerator) through the serial line, as host.py will drive
the board (spec 9): the testbench bit-bangs uart_rx and decodes uart_tx at 16 clocks per bit.
PING; LOAD_IMG with a wrong then a right checksum; RUN; READ_LOGITS vs golden; READ_CYCLES;
RUN with stop_after_op = 2 + DUMP of its output bank vs golden; an unknown command is ignored."""
import sys
from pathlib import Path

import cocotb
import numpy as np
from cocotb.clock import Clock
from cocotb.queue import Queue
from cocotb.triggers import FallingEdge, Timer, with_timeout

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "unit"))
import sim  # noqa: E402

sys.path.insert(0, str(sim.ROOT / "model"))
import export  # noqa: E402
import golden  # noqa: E402

CLK_NS, BAUD, VERSION = 10, 6_250_000, 0x01
BIT_NS = 1e9 / BAUD
P = 8


async def send(dut, data):
    for byte in data:
        for b in [0] + [(byte >> i) & 1 for i in range(8)] + [1]:
            dut.uart_rx.value = b
            await Timer(BIT_NS, unit="ns")


async def receiver(dut, q):
    while True:
        await FallingEdge(dut.uart_tx)  # start bit
        await Timer(1.5 * BIT_NS, unit="ns")  # middle of bit 0
        byte = 0
        for i in range(8):
            byte |= int(dut.uart_tx.value) << i
            await Timer(BIT_NS, unit="ns")
        assert int(dut.uart_tx.value) == 1, "stop bit"
        await q.put(byte)


async def recv(q, n, timeout_us=20_000):
    return [await with_timeout(q.get(), timeout_us, "us") for _ in range(n)]


def image_bytes(img):
    """int8 NCHW (1, 3, 32, 32) -> 3,072 bytes in HWC order, the LOAD_IMG payload."""
    return [int(v) & 0xFF for v in img[0].transpose(1, 2, 0).ravel()]


@cocotb.test()
async def soc_protocol(dut):
    q = golden.load_qparams()
    img = np.random.default_rng(4).integers(-128, 128, (1, 3, 32, 32))
    gold = golden.run(q, img)
    payload = image_bytes(img)
    ck = 0
    for b in payload:
        ck ^= b

    cocotb.start_soon(Clock(dut.clk, CLK_NS, unit="ns").start())
    rxq = Queue()
    cocotb.start_soon(receiver(dut, rxq))
    dut.uart_rx.value, dut.rst.value = 1, 1
    await Timer(100, unit="ns")
    dut.rst.value = 0
    await Timer(5 * BIT_NS, unit="ns")

    await send(dut, [0x77])  # unknown command: ignored
    await send(dut, [0x00])
    assert await recv(rxq, 2) == [0xA5, VERSION], "PING"

    await send(dut, [0x10] + payload + [ck ^ 0xFF])
    assert await recv(rxq, 1) == [0x5A], "LOAD_IMG with a bad checksum must answer 0x5A"
    await send(dut, [0x10] + payload + [ck])
    assert await recv(rxq, 1) == [0xA5], "LOAD_IMG"

    await send(dut, [0x20, 9])
    assert await recv(rxq, 1) == [0xA5], "RUN"
    await send(dut, [0x30])
    logits = [b - 256 if b >= 128 else b for b in await recv(rxq, 10)]
    want = [int(v) for v in gold["fc"][0, :, 0, 0]]
    assert logits == want, f"READ_LOGITS {logits} vs golden {want}"
    await send(dut, [0x40])
    c = await recv(rxq, 4)
    cycles = c[0] | c[1] << 8 | c[2] << 16 | c[3] << 24
    assert cycles == 208_052, f"READ_CYCLES {cycles}"

    # debug path: stop after op 2 (s1b writes bank 0) and dump the first 64 words of that bank
    await send(dut, [0x10] + payload + [ck])
    assert await recv(rxq, 1) == [0xA5]
    await send(dut, [0x20, 2])
    assert await recv(rxq, 1) == [0xA5], "RUN stop_after_op=2"
    n = 64
    await send(dut, [0x50, 0, 0, 0, n & 0xFF, n >> 8])
    raw = await recv(rxq, 8 * n)
    words = [sum(raw[8 * i + k] << 8 * k for k in range(8)) for i in range(n)]
    assert words == export.act_words(gold["s1b"][0])[:n], "DUMP of bank 0 after s1b"
    dut._log.info(f"PING, LOAD_IMG (bad/good checksum), RUN, READ_LOGITS {logits}, READ_CYCLES {cycles}, "
                  f"RUN(stop=2) + DUMP {n} words: all as expected")


def test_soc():
    rtl = ["acc_pkg.sv", "booth_r4_mul8.sv", "mul8.sv", "dot8.sv", "lane.sv", "agu.sv", "act_mem.sv", "wgt_mem.sv",
           "qparam_mem.sv", "pe_array.sv", "controller.sv", "accel.sv"]
    soc = ["../soc/uart_rx.sv", "../soc/uart_tx.sv", "../soc/host_if.sv", "../soc/soc.sv"]
    params = {"PE_TYPE": "LUT_CUSTOM", "SUM_STYLE": "ADDER", "L_MUL": 2, "P": P, "D_W": 1226, "D_Q": 44,
              "HEX_DIR": str(export.EXPORT / f"P{P}"), "CLK_HZ": 100_000_000, "BAUD": BAUD}
    sim.run("soc", rtl + soc, params, "test_soc", test_dir=Path(__file__).parent)
