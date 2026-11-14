"""host.py against a fake board that speaks the spec 9 byte protocol and computes with golden.run,
including an injected fault: the debug path must name the op where the fault was put."""
import numpy as np

import export
import golden
import host
from golden import OPS

Q = golden.load_qparams()
P = 8


class FakeBoard:
    """Byte-level model of host_if + accel: 3 banks, bank rotation from the descriptors."""

    def __init__(self, fault_op=None):
        self.banks = [[0] * 2048 for _ in range(3)]
        self.out, self.cycles, self.img, self.fault_op = b"", 0, None, fault_op
        self.descs = export.descriptors(Q, P)

    def write(self, data):
        cmd, arg = data[0], data[1:]
        if cmd == host.PING:
            self.out += bytes([host.OK, 0x01])
        elif cmd == host.LOAD_IMG:
            payload, ck = arg[:3072], arg[3072]
            x = np.frombuffer(payload, dtype=np.int8).reshape(32, 32, 3).transpose(2, 0, 1).astype(np.int64)
            self.img = x
            self.banks[0][:1024] = export.act_words(x)
            c = 0
            for b in payload:
                c ^= b
            self.out += bytes([host.OK if c == ck else host.BAD])
        elif cmd == host.RUN:
            a = golden.run(Q, self.img[None])
            for k, (op, d) in enumerate(zip(OPS, self.descs)):
                words = export.act_words(a[op.name][0])
                if k == self.fault_op:
                    words[3] ^= 1 << 13  # one flipped bit in this op's output
                self.banks[d["out_bank"]][:len(words)] = words
                if k == min(arg[0], 9):
                    break
            self.cycles = 208_052
            self.out += bytes([host.OK])
        elif cmd == host.READ_LOGITS:
            w = self.banks[1]
            self.out += bytes((w[i // 8] >> 8 * (i % 8)) & 0xFF for i in range(10))
        elif cmd == host.READ_CYCLES:
            self.out += self.cycles.to_bytes(4, "little")
        elif cmd == host.DUMP:
            bank, addr, n = arg[0], arg[1] | arg[2] << 8, arg[3] | arg[4] << 8
            self.out += b"".join(self.banks[bank][addr + i].to_bytes(8, "little") for i in range(n))

    def read(self, n):
        data, self.out = self.out[:n], self.out[n:]
        return data


def test_protocol_roundtrip_matches_golden():
    board = host.Board(FakeBoard())
    assert board.ping() == 0x01
    x = np.random.default_rng(0).integers(-128, 128, (3, 32, 32))
    board.load_image(x)
    board.run()
    assert board.logits() == [int(v) for v in golden.run(Q, x[None])["fc"][0, :, 0, 0]]
    assert board.cycles() == 208_052


def test_debug_finds_the_first_wrong_op():
    x = np.random.default_rng(1).integers(-128, 128, (3, 32, 32))
    assert host.first_wrong_op(host.Board(FakeBoard()), Q, x, P) is None
    op, word, nbad = host.first_wrong_op(host.Board(FakeBoard(fault_op=4)), Q, x, P)
    assert (op, word, nbad) == (OPS[4].name, 3, 1)
