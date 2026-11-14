"""Export the integer network as hex files for $readmemh (spec 7, 8).

    python model/export.py [--images N]
      model/export/P<P>/w_lane<p>.hex   per-lane weight ROM, 64-bit words        (committed)
      model/export/P<P>/q_lane<p>.hex   per-lane {bias, M, n} ROM, 54-bit words  (committed)
      model/export/P<P>/desc.hex        10 layer descriptors, 80-bit words       (committed)
      model/vectors/img_<i>.hex         input image, bank B0 layout             (regenerated, not committed)
      model/vectors/golden_<i>_<op>.hex output bank of each op, golden.run      (regenerated, not committed)

Hex format: one word per line, most significant byte first (byte 7 ... byte 0).
"""
import argparse

import numpy as np

import cifar
import golden
from golden import OPS

PS = (4, 8, 16)
EXPORT = cifar.ROOT / "model" / "export"
VECTORS = cifar.ROOT / "model" / "vectors"

# op -> (in_bank, res_bank, out_bank), spec 7.2
BANKS = {
    "conv0": (0, None, 1), "s1a": (1, None, 2), "s1b": (2, 1, 0),
    "s2a": (0, None, 1), "s2s": (0, None, 2), "s2b": (1, 2, 0),
    "s3a": (0, None, 1), "s3s": (0, None, 2), "s3b": (1, 2, 0),
    "fc": (0, None, 1),
}

# Descriptor fields, MSB first: the same order as the packed struct in acc_pkg.sv (spec 8).
FIELDS = [
    ("spare", 8), ("log2_win", 3), ("log2_wout", 3), ("log2_c8in", 2), ("log2_c8out", 2),
    ("k", 4), ("stride", 2), ("pad", 1), ("groups", 5), ("in_bank", 2), ("out_bank", 2),
    ("res_bank", 2), ("res_en", 1), ("relu_en", 1), ("w_shared", 1), ("w_base", 12),
    ("q_base", 7), ("m_r", 16), ("n_r", 6),
]
DESC_BITS = 80
assert sum(w for _, w in FIELDS) == DESC_BITS

# Requant shift limit (spec 4.4, changed at G1): the RTL adds 2^(n-1) to a 49-bit signed t*M,
# which only fits for n <= 47. Real n are 17..35; n >= 48 would make every output 0 anyway.
N_MAX = 47


def check_n(n, what):
    assert 1 <= n <= N_MAX, f"{what}: n = {n} outside 1..{N_MAX}"


def pack_desc(d):
    v = 0
    for name, width in FIELDS:
        x = d.get(name, 0)
        assert 0 <= x < 1 << width, (name, x)
        v = v << width | x
    return v


def unpack_desc(v):
    d = {}
    for name, width in reversed(FIELDS):
        d[name], v = v & ((1 << width) - 1), v >> width
    return d


def c8(c):
    return -(-c // 8)


def log2(x):
    assert x & (x - 1) == 0, f"{x} is not a power of 2"
    return x.bit_length() - 1


def descriptors(q, P):
    """The 10 descriptors for P lanes, with the checks of spec 8."""
    out, w_base, q_base = [], 0, 0
    for op in OPS:
        G, C8, shared = -(-op.cout // P), c8(op.cin), op.name == "fc"
        bi, br, bo = BANKS[op.name]
        banks = [bi, bo] + ([br] if op.res else [])
        assert len(set(banks)) == len(banks), f"{op.name}: banks must differ"
        assert op.k**2 * C8 >= -(-P // 8), f"{op.name}: R < ceil(P/8) would stall the write port"
        if op.res:
            check_n(int(q[op.name + ".nr"]), op.name + ".nr")
        out.append(dict(
            log2_win=log2(op.hin), log2_wout=log2(op.hout), log2_c8in=log2(C8), log2_c8out=log2(c8(op.cout)),
            k=op.k, stride=op.stride, pad=op.pad, groups=G, in_bank=bi, out_bank=bo, res_bank=br or 0,
            res_en=int(op.res is not None), relu_en=int(op.relu), w_shared=int(shared),
            w_base=w_base, q_base=q_base,
            m_r=int(q[op.name + ".Mr"]) if op.res else 0, n_r=int(q[op.name + ".nr"]) if op.res else 0,
        ))
        w_base += G * (C8 if shared else op.k**2 * C8)
        q_base += G
    return out


def word(b):
    """8 signed bytes -> one 64-bit word, byte i at bits [8i+7 : 8i]."""
    return sum((int(x) & 0xFF) << 8 * i for i, x in enumerate(b))


def weight_words(q, P):
    """Per lane: words in order op -> g -> (ky, kx, c8); word = W[co = gP + p, ky, kx, 8c8 .. 8c8+7] (spec 7.3)."""
    lanes = [[] for _ in range(P)]
    for op in OPS:
        w = q[op.name + ".w"].astype(np.int64)
        if op.name == "fc":
            w = w[:, :, None, None]  # w_shared: one (ky, kx) slot for all 64 positions
        G, C8 = -(-op.cout // P), c8(op.cin)
        wp = np.zeros((G * P, 8 * C8) + w.shape[2:], dtype=np.int64)  # pad channels have weight 0
        wp[:op.cout, :op.cin] = w
        for p in range(P):
            for g in range(G):
                for ky in range(w.shape[2]):
                    for kx in range(w.shape[3]):
                        for c in range(C8):
                            lanes[p].append(word(wp[g * P + p, 8 * c:8 * c + 8, ky, kx]))
    return lanes


def qparam_words(q, P):
    """Per lane: entries in order op -> g; entry = {bias[31:0], M[15:0], n[5:0]} of co = gP + p (spec 7.4)."""
    lanes = [[] for _ in range(P)]
    for op in OPS:
        b, M, n = (q[op.name + s] for s in (".b", ".M", ".n"))
        for p in range(P):
            for g in range(-(-op.cout // P)):
                co = g * P + p
                bias, m, sh = (int(b[co]), int(M[co]), int(n[co])) if co < op.cout else (0, 2**15, 1)
                check_n(sh, f"{op.name}.n[{co}]")
                lanes[p].append((bias & 0xFFFFFFFF) << 22 | m << 6 | sh)
    return lanes


def act_words(a):
    """One image's activation [C, H, W] -> bank words, addr = (y*W + x)*C8 + c8, byte b = channel 8*c8 + b (spec 7.1)."""
    C, H, W = a.shape
    ap = np.zeros((8 * c8(C), H, W), dtype=np.int64)
    ap[:C] = a
    return [word(ap[8 * c:8 * c + 8, y, x]) for y in range(H) for x in range(W) for c in range(c8(C))]


def write_hex(path, words, bits):
    path.write_text("".join(f"{w:0{-(-bits // 4)}x}\n" for w in words))


def read_hex(path):
    return [int(line, 16) for line in path.read_text().split()]


def export_weights(q, P):
    d = EXPORT / f"P{P}"
    d.mkdir(parents=True, exist_ok=True)
    for p, ws in enumerate(weight_words(q, P)):
        write_hex(d / f"w_lane{p}.hex", ws, 64)
    for p, qs in enumerate(qparam_words(q, P)):
        write_hex(d / f"q_lane{p}.hex", qs, 54)
    write_hex(d / "desc.hex", [pack_desc(x) for x in descriptors(q, P)], DESC_BITS)
    return d


def export_vectors(q, n_images):
    VECTORS.mkdir(parents=True, exist_ok=True)
    x, y = cifar.load("test")
    a = golden.run(q, golden.quantize_image(x[:n_images], float(q["S.img"])))
    for i in range(n_images):
        write_hex(VECTORS / f"img_{i}.hex", act_words(a["img"][i]), 64)
        for op in OPS:
            write_hex(VECTORS / f"golden_{i}_{op.name}.hex", act_words(a[op.name][i]), 64)
    (VECTORS / "labels.txt").write_text("".join(f"{i} {y[i]}\n" for i in range(n_images)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--images", type=int, default=50, help="number of test images to export as vectors")
    args = ap.parse_args()
    q = golden.load_qparams()
    for P in PS:
        d = export_weights(q, P)
        print(f"P={P:2d}: D_w={len(read_hex(d / 'w_lane0.hex'))} D_q={len(read_hex(d / 'q_lane0.hex'))} -> {d}")
    export_vectors(q, args.images)
    print(f"{args.images} test images -> {VECTORS}")


if __name__ == "__main__":
    main()
