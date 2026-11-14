"""Reference AGU (spec 5.1, 6.5): the exact per-cycle tuple sequence the RTL AGU must emit.

One Tick per cycle, in loop-nest order g -> oy -> ox -> ky -> kx -> c. L2 compares the RTL
against this cycle by cycle; act_addr is only meaningful (and only compared) when in_bounds.
"""
from collections import namedtuple

ACT_WORDS = 2048  # words per activation bank -> 11-bit act_addr

# g is not in the spec's tuple list but the lanes need it for the q-param address and byte lanes
Tick = namedtuple("Tick", "g act_addr in_bounds w_addr first last wr_addr")


def agu(d, P):
    """d: unpacked descriptor dict (see export.FIELDS); P: number of lanes."""
    l2w, l2c = d["log2_win"], d["log2_c8in"]
    win, wout = 1 << l2w, 1 << d["log2_wout"]
    c8, c8o = 1 << l2c, 1 << d["log2_c8out"]
    K, s, pad, shared = d["k"], d["stride"], d["pad"], d["w_shared"]
    per_g = c8 if shared else K * K * c8
    for g in range(d["groups"]):
        w_g = d["w_base"] + g * per_g
        for oy in range(wout):
            for ox in range(wout):
                wr_addr = (oy * wout + ox) * c8o + g * P // 8  # word holding channel co = g*P
                for ky in range(K):
                    iy = oy * s + ky - pad
                    for kx in range(K):
                        ix = ox * s + kx - pad
                        in_bounds = 0 <= iy < win and 0 <= ix < win
                        for c in range(c8):
                            yield Tick(
                                g=g,
                                act_addr=((((iy << l2w) + ix) << l2c) + c) % ACT_WORDS,
                                in_bounds=in_bounds,
                                w_addr=w_g + (c if shared else (ky * K + kx) * c8 + c),
                                first=ky == 0 and kx == 0 and c == 0,
                                last=ky == K - 1 and kx == K - 1 and c == c8 - 1,
                                wr_addr=wr_addr,
                            )


def op_cycles(d):
    """Closed form of len(list(agu(d, P))): G * Wout^2 * K^2 * C8 (spec 5.3)."""
    return d["groups"] * (1 << 2 * d["log2_wout"]) * d["k"] ** 2 * (1 << d["log2_c8in"])
