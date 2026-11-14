"""L0: the Booth reference is exact for all 65,536 INT8 pairs, stage by stage (spec 10, M2)."""
import pytest

import booth_ref as B

PAIRS = [(a, w) for a in range(-128, 128) for w in range(-128, 128)]


def test_encoder_digits_rebuild_w():
    for w in range(-128, 128):
        enc = B.encode(w)
        assert all(not (one and two) for one, two, _ in enc), w
        assert sum(B.digit(*e) * 4**i for i, e in enumerate(enc)) == w


def test_pp_row_plus_neg_is_digit_times_a():
    for a in range(-128, 128):
        for e in {B.encode(w)[i] for w in range(-128, 128) for i in range(4)}:  # all 8 encodings
            r = B.pp_row(a, *e)
            signed9 = r - 512 if r >> 8 else r
            assert signed9 + e[2] == B.digit(*e) * a, (a, e)


@pytest.mark.parametrize("style", ["ADDER", "CSA42"])
def test_product_exhaustive(style):
    bad = [(a, w) for a, w in PAIRS if B.to_signed16(B.mul(a, w, style)["p"]) != a * w]
    assert not bad, f"{style}: {len(bad)} wrong, first {bad[:5]}"


def test_compressor_42_identity_and_cout_independent_of_cin():
    for x in range(32):
        bits = [(x >> k) & 1 for k in range(5)]
        s, carry, cout = B.c42(*bits)
        assert sum(bits) == s + 2 * (carry + cout)
        assert cout == B.c42(*bits[:4], 1 - bits[4])[2]  # flipping cin never changes cout


def test_rows_stay_inside_the_dot_diagram():
    """Pins the column layout the RTL must reproduce: no row ever sets a bit outside its slot."""
    allowed = [0x7FF, 0xFFD, 0x3FF4, 0xFFD0]  # R0: 0..10; R1: 0, 2..11; R2: 2, 4..13; R3: 4, 6..15
    seen = [0, 0, 0, 0]
    for a, w in PAIRS:
        for i, x in enumerate(B.mul(a, w)["R"]):
            seen[i] |= x
    assert seen == allowed, [hex(s) for s in seen]
