"""Host side of the board protocol (spec 9), over the A7-Lite USB-UART (CH340E).

    python host/host.py ping                   [--port /dev/ttyUSB0] [--baud 921600]
    python host/host.py run --n 10000          CIFAR-10 test images; logits compared byte by byte with golden
    python host/host.py classify photo.jpg     any picture, resized to 32x32, top class + latency

`run` writes results/<config>/board_<n>.csv (index, label, pred, match, cycles). On any mismatch it reruns
that image with stop_after_op = 0..9, dumps each op's output bank and reports the first wrong op (spec 9).
Latency comes from the on-chip cycle counter (READ_CYCLES), never from UART timing.
"""
import argparse
import csv
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "model"))
import cifar  # noqa: E402
import export  # noqa: E402
import golden  # noqa: E402
from golden import OPS  # noqa: E402

PING, LOAD_IMG, RUN, READ_LOGITS, READ_CYCLES, DUMP = 0x00, 0x10, 0x20, 0x30, 0x40, 0x50
OK, BAD = 0xA5, 0x5A
CLASSES = ["airplane", "automobile", "bird", "cat", "deer", "dog", "frog", "horse", "ship", "truck"]


def s8(b):
    return b - 256 if b >= 128 else b


def argmax(logits):
    """Lowest index on ties, the same rule as golden.accuracy."""
    return max(range(len(logits)), key=lambda c: (logits[c], -c))


class Board:
    """The 6 commands of spec 9 over any byte stream with read(n) / write(bytes) (pyserial or a fake)."""

    def __init__(self, link):
        self.link = link

    def _rx(self, n):
        data = self.link.read(n)
        if len(data) != n:
            raise TimeoutError(f"expected {n} bytes, got {len(data)}")
        return list(data)

    def ping(self):
        self.link.write(bytes([PING]))
        ok, version = self._rx(2)
        if ok != OK:
            raise IOError(f"PING answered {ok:#x}")
        return version

    def load_image(self, x_q, retries=3):
        """x_q: int8 values as a (3, 32, 32) array -> LOAD_IMG in HWC order with XOR checksum."""
        payload = bytes(int(v) & 0xFF for v in np.asarray(x_q).transpose(1, 2, 0).ravel())
        ck = 0
        for b in payload:
            ck ^= b
        for _ in range(retries):
            self.link.write(bytes([LOAD_IMG]) + payload + bytes([ck]))
            if self._rx(1)[0] == OK:
                return
        raise IOError("LOAD_IMG: checksum rejected after retries")

    def run(self, stop_after_op=9):
        self.link.write(bytes([RUN, stop_after_op]))
        if self._rx(1)[0] != OK:
            raise IOError("RUN not acknowledged")

    def logits(self):
        self.link.write(bytes([READ_LOGITS]))
        return [s8(b) for b in self._rx(10)]

    def cycles(self):
        self.link.write(bytes([READ_CYCLES]))
        b = self._rx(4)
        return b[0] | b[1] << 8 | b[2] << 16 | b[3] << 24

    def dump(self, bank, addr, n):
        self.link.write(bytes([DUMP, bank, addr & 0xFF, addr >> 8, n & 0xFF, n >> 8]))
        raw = self._rx(8 * n)
        return [sum(raw[8 * i + k] << 8 * k for k in range(8)) for i in range(n)]


def first_wrong_op(board, q, x_q, P):
    """Rerun one image op by op (stop_after_op = k) and compare each output bank with golden.run."""
    gold = golden.run(q, x_q[None])
    for k, (op, d) in enumerate(zip(OPS, export.descriptors(q, P))):
        board.load_image(x_q)
        board.run(k)
        want = export.act_words(gold[op.name][0])
        got = board.dump(d["out_bank"], 0, len(want))
        if op.name == "fc":  # only the 10 logits are defined
            got, want = board.logits(), [int(v) for v in gold["fc"][0, :, 0, 0]]
        bad = [i for i, (g, w) in enumerate(zip(got, want)) if g != w]
        if bad:
            return op.name, bad[0], len(bad)
    return None


def cmd_run(board, args):
    q = golden.load_qparams()
    x, y = cifar.load("test")
    x, y = x[:args.n], y[:args.n]
    s_in = float(q["S.img"])
    want = golden.logits(q, x)
    out = ROOT / "results" / args.config / f"board_{args.n}.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    matches, correct_board, correct_golden, cycles = 0, 0, 0, set()
    with out.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["index", "label", "pred", "match", "cycles"])
        for i in range(len(x)):
            x_q = golden.quantize_image(x[i:i + 1], s_in)[0]
            board.load_image(x_q)
            board.run()
            got, c = board.logits(), board.cycles()
            ok = got == [int(v) for v in want[i]]
            pred = argmax(got)
            matches += ok
            correct_board += pred == y[i]
            correct_golden += argmax(list(want[i])) == y[i]
            cycles.add(c)
            w.writerow([i, int(y[i]), pred, int(ok), c])
            if not ok:
                print(f"image {i}: MISMATCH board {got} golden {list(want[i])}; first wrong op: "
                      f"{first_wrong_op(board, q, x_q, args.p)}")
            if (i + 1) % 100 == 0:
                print(f"{i + 1}/{len(x)}: {matches} match, top-1 board {correct_board / (i + 1):.4f}", flush=True)
    n = len(x)
    print(f"{matches}/{n} logits match golden; top-1 board {correct_board / n:.4f}, golden {correct_golden / n:.4f}; "
          f"cycles/image {sorted(cycles)} -> {min(cycles) / (args.f_mhz * 1e3):.3f} ms at {args.f_mhz} MHz; {out}")
    return matches == n


def cmd_classify(board, args):
    from PIL import Image
    q = golden.load_qparams()
    img = np.asarray(Image.open(args.image).convert("RGB").resize((32, 32), Image.BILINEAR), dtype=np.uint8)
    x_q = golden.quantize_image(img[None], float(q["S.img"]))[0]
    board.load_image(x_q)
    board.run()
    got, c = board.logits(), board.cycles()
    gold = [int(v) for v in golden.logits(q, img[None])[0]]
    top = sorted(range(10), key=lambda k: (-got[k], k))[:3]
    print(f"{args.image}: {CLASSES[top[0]]}  (top-3: " + ", ".join(f"{CLASSES[k]} {got[k]}" for k in top) +
          f"; {c} cycles = {c / (args.f_mhz * 1e3):.3f} ms; logits {'match' if got == gold else 'DIFFER FROM'} golden)")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["ping", "run", "classify"])
    ap.add_argument("image", nargs="?")
    ap.add_argument("--port", default="/dev/ttyUSB0")
    ap.add_argument("--baud", type=int, default=921_600)
    ap.add_argument("--n", type=int, default=10_000)
    ap.add_argument("--p", type=int, default=8)
    ap.add_argument("--f-mhz", type=float, default=100.0)
    ap.add_argument("--config", default="P8_LUT_CUSTOM_ADDER_100MHz")
    args = ap.parse_args(argv)
    import serial
    with serial.Serial(args.port, args.baud, timeout=2) as link:
        board = Board(link)
        if args.cmd == "ping":
            print(f"board alive, version {board.ping():#04x}")
        elif args.cmd == "run":
            return 0 if cmd_run(board, args) else 1
        else:
            cmd_classify(board, args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
