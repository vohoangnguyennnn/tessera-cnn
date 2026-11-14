"""L0 tests for export.py and agu_ref.py.

The key test runs a bank-level model of the accelerator that only sees what the RTL will see
(hex files read back from disk, unpacked descriptors, the AGU tick stream) and checks every
op's output bank against golden.run byte for byte, for P = 4, 8, 16.
"""
import random

import numpy as np
import pytest

import agu_ref
import export
import golden
from golden import OPS

Q = golden.load_qparams()
CYCLES = {4: 415_232, 8: 207_872, 16: 103_936}  # spec 5.3
D_W = {4: 2444, 8: 1226, 16: 613}  # spec 7.3
D_Q = {4: 87, 8: 44, 16: 22}  # spec 6.4


@pytest.mark.parametrize("P", export.PS)
def test_descriptor_pack_roundtrip(P):
    for d in export.descriptors(Q, P):
        v = export.pack_desc(d)
        assert v < 1 << export.DESC_BITS
        assert export.unpack_desc(v) == {**d, "spare": 0}
    rng = random.Random(P)
    for _ in range(1000):
        d = {name: rng.randrange(1 << w) for name, w in export.FIELDS}
        assert export.unpack_desc(export.pack_desc(d)) == d


def test_export_rejects_n_above_47():
    for key in ("s1a.n", "s1b.nr"):
        q = dict(Q)
        q[key] = np.full_like(Q[key], 48)
        with pytest.raises(AssertionError, match="outside 1..47"):
            export.qparam_words(q, 8), export.descriptors(q, 8)


@pytest.mark.parametrize("P", export.PS)
def test_rom_depths_and_cycles_match_spec(P):
    descs = export.descriptors(Q, P)
    w, qp = export.weight_words(Q, P), export.qparam_words(Q, P)
    assert {len(x) for x in w} == {D_W[P]} and {len(x) for x in qp} == {D_Q[P]}
    last = descs[-1]
    assert last["w_base"] + last["groups"] * (1 << last["log2_c8in"]) == D_W[P]  # w_base + G*C8 <= D_w
    assert sum(sum(1 for _ in agu_ref.agu(d, P)) for d in descs) == CYCLES[P]
    assert sum(agu_ref.op_cycles(d) for d in descs) == CYCLES[P]


@pytest.mark.parametrize("P", export.PS)
def test_first_and_last_once_per_output_pixel(P):
    for d in export.descriptors(Q, P):
        flags = [(t.first, t.last) for t in agu_ref.agu(d, P)]
        R = d["k"] ** 2 * (1 << d["log2_c8in"])  # >= 2, asserted by export.descriptors
        pixels = d["groups"] * (1 << 2 * d["log2_wout"])
        assert flags == ([(True, False)] + [(False, False)] * (R - 2) + [(False, True)]) * pixels


def to_bytes(words):
    """64-bit words -> [N, 8] signed bytes."""
    b = np.array([[(w >> 8 * i) & 0xFF for i in range(8)] for w in words], dtype=np.int64)
    return np.where(b >= 128, b - 256, b)


def decode_q(e):
    """54-bit {bias[31:0], M[15:0], n[5:0]} -> (signed bias, M, n)."""
    b = e >> 22
    return b - (1 << 32) if b >> 31 else b, (e >> 6) & 0xFFFF, e & 0x3F


@pytest.mark.parametrize("P", export.PS)
def test_roms_decode_back_to_qparams(P):
    """Static, complete check of ROM contents (the bank-model test cannot see weights whose inputs are 0)."""
    W = np.stack([to_bytes(ws) for ws in export.weight_words(Q, P)])  # [P, D_w, 8]
    qrom = export.qparam_words(Q, P)
    for op, d in zip(OPS, export.descriptors(Q, P)):
        K, C8, G = (1 if d["w_shared"] else d["k"]), 1 << d["log2_c8in"], d["groups"]
        blk = W[:, d["w_base"]:d["w_base"] + G * K * K * C8].reshape(P, G, K, K, 8 * C8)  # lane, g, ky, kx, ci
        w = blk.transpose(1, 0, 4, 2, 3).reshape(G * P, 8 * C8, K, K)  # co = g*P + p
        ref = Q[op.name + ".w"]
        assert np.array_equal(w[:op.cout, :op.cin], ref.reshape(op.cout, op.cin, K, K)), op.name
        assert not w[op.cout:].any() and not w[:, op.cin:].any(), f"{op.name}: pad channels must be 0"
        for g in range(G):
            for p in range(P):
                co = g * P + p
                want = (int(Q[op.name + ".b"][co]), int(Q[op.name + ".M"][co]), int(Q[op.name + ".n"][co])) \
                    if co < op.cout else (0, 2**15, 1)
                assert decode_q(qrom[p][d["q_base"] + g]) == want, (op.name, co)


def run_bank_model(descs, wrom, qrom, img_words, P, rng):
    """Bank-level model of the accelerator: 3 banks of 2048 x 8 bytes, P lanes, driven by agu_ref."""
    W = np.stack([to_bytes(ws) for ws in wrom])  # [P, D_w, 8]
    bias, M, n = (np.array(x, dtype=np.int64) for x in np.moveaxis([[decode_q(e) for e in row] for row in qrom], 2, 0))
    banks = rng.integers(-128, 128, (3, agu_ref.ACT_WORDS, 8))  # stale garbage, like real BRAM
    banks[0, :len(img_words)] = to_bytes(img_words)
    lanes = np.arange(P)
    dumps = []
    for d in descs:
        bi, bo, br = d["in_bank"], d["out_bank"], d["res_bank"]
        for t in agu_ref.agu(d, P):
            if t.first:
                acc = bias[:, d["q_base"] + t.g].copy()
            if t.in_bounds:  # out of bounds: activation replaced by 0 after the BRAM (padding)
                acc += W[:, t.w_addr] @ banks[bi, t.act_addr]
            if t.last:
                qi = d["q_base"] + t.g
                y = np.clip(golden.rq(acc, M[:, qi], n[:, qi]), -2**15, 2**15 - 1)
                co = t.g * P + lanes
                wa, by = t.wr_addr - t.g * P // 8 + co // 8, co % 8
                if d["res_en"]:
                    r = banks[br, wa, by]
                    y = y + np.clip(golden.rq(r, d["m_r"], d["n_r"]), -2**15, 2**15 - 1)
                z = np.clip(y, -128, 127)
                banks[bo, wa, by] = np.maximum(z, 0) if d["relu_en"] else z
        dumps.append(banks[bo].copy())
    return dumps


@pytest.mark.parametrize("P", export.PS)
def test_bank_model_from_hex_files_matches_golden(P, tmp_path, monkeypatch):
    monkeypatch.setattr(export, "EXPORT", tmp_path)
    d = export.export_weights(Q, P)
    descs = [export.unpack_desc(v) for v in export.read_hex(d / "desc.hex")]
    wrom = [export.read_hex(d / f"w_lane{p}.hex") for p in range(P)]
    qrom = [export.read_hex(d / f"q_lane{p}.hex") for p in range(P)]

    rng = np.random.default_rng(P)
    img = rng.integers(-128, 128, (1, 3, 32, 32))  # random image: no dataset needed in CI
    gold = golden.run(Q, img)
    dumps = run_bank_model(descs, wrom, qrom, export.act_words(img[0]), P, rng)

    for op, dump in zip(OPS, dumps):
        ref = to_bytes(export.act_words(gold[op.name][0]))
        if op.name == "fc":  # only the 10 logits are defined; P=4 leaves bytes 12..15 stale
            assert np.array_equal(dump[:2].ravel()[:10], ref.ravel()[:10]), op.name
        else:
            assert np.array_equal(dump[:len(ref)], ref), op.name
