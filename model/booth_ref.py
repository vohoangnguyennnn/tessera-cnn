"""Bit-accurate reference of booth_r4_mul8: signed INT8 x INT8 -> 16-bit product (spec 6.1).

Same stages as the RTL, with the same signal names, so a failing RTL case can be debugged
signal by signal against `mul()`:

  1. Booth encoder   w -> one[i], two[i], neg[i]   for the 4 radix-4 digits d_i in {-2..+2}
  2. PP generator    r[i] = 9-bit row ((one & a[j]) | (two & a[j-1])) ^ neg,  a[-1]=0, a[8]=a[7]
  3. Placement       rows R0..R3 (16-bit words, absolute bit columns) + the lone bit e = n3 << 6
  4. Sum, ADDER     s01 = R0 + R1;  s23 = R2 + R3 + e;  p = s01 + s23   (mod 2^16, carry chains)
     Sum, CSA42     one row of 4:2 compressors over R0..R3 (column c: x1..x4 = R0[c]..R3[c],
                    cin = cout of column c-1) -> sum row S and carry row C;  p = S + C + e

Dot diagram (column 15 .. 0). Sign extension is removed by inverting each row's sign bit s_i and
folding the correction constant into the rows ("variant B"): row 0 gets s0 s0 ~s0 at columns
8, 9, 10; rows 1..3 get ~s_i and a constant 1 on top. Each row's "+1" of negation (n_i = neg[i])
sits in the empty low slot of the row below; n3 has no row below, hence the extra bit e.

  col  15 14 13 12 11 10  9  8  7  6  5  4  3  2  1  0
  R0                   ~s  s  s  r  r  r  r  r  r  r  r
  R1                 1 ~s  r  r  r  r  r  r  r  r     n0
  R2             1 ~s  r  r  r  r  r  r  r  r     n1
  R3         1 ~s  r  r  r  r  r  r  r  r     n2
  e                                n3
  height  1  1  2  2  3  4  4  4  4  5  3  4  2  3  1  2

Why e survives into the final adder in both styles: column 6 holds 5 real bits (R0..R3 + n3), but
one 4:2 row takes only 4 own bits per column (+ the chained cin). The cin of column 6 is not free
either: column 4 has 4 bits, so it always sends a cout to column 5, which sends one to column 6.

Verified exhaustively over all 65,536 (a, w) pairs by model/tests/test_booth_ref.py.
"""

MASK16 = 0xFFFF


def bit(x, j):
    """Bit j of x (two's complement); bit -1 is 0 (the w[-1] = 0 / a[-1] = 0 convention)."""
    return (x >> j) & 1 if j >= 0 else 0


def encode(w):
    """Radix-4 Booth encoder: w (INT8) -> [(one, two, neg)] for digits i = 0..3.
    Group (w[2i+1], w[2i], w[2i-1]): 000,111 -> 0; 001,010 -> +1; 011 -> +2; 100 -> -2; 101,110 -> -1.
    Group 111 gives neg=1 with one=two=0: row = ~0 = -1, and the +1 bit makes it 0 again."""
    out = []
    for i in range(4):
        b2, b1, b0 = bit(w, 2 * i + 1), bit(w, 2 * i), bit(w, 2 * i - 1)
        one = b1 ^ b0
        two = (b2 & (1 - b1) & (1 - b0)) | ((1 - b2) & b1 & b0)
        out.append((one, two, b2))
    return out


def digit(one, two, neg):
    return (-1 if neg else 1) * (2 if two else 1 if one else 0)


def pp_row(a, one, two, neg):
    """9-bit partial-product row: bit j = ((one & a[j]) | (two & a[j-1])) ^ neg, a[8] = a[7].
    As a signed 9-bit value, row + neg == digit * a (the +1 of the negation is added outside)."""
    ax = lambda j: bit(a, 7) if j == 8 else bit(a, j)
    return sum((((one & ax(j)) | (two & ax(j - 1))) ^ neg) << j for j in range(9))


def place(r, neg):
    """Rows r[0..3] (9-bit) + neg bits -> 16-bit words R0..R3 and the extra bit e, at absolute columns."""
    s = [(x >> 8) & 1 for x in r]
    low = [x & 0xFF for x in r]
    R0 = low[0] | s[0] << 8 | s[0] << 9 | (1 - s[0]) << 10
    R1 = neg[0] | low[1] << 2 | (1 - s[1]) << 10 | 1 << 11
    R2 = neg[1] << 2 | low[2] << 4 | (1 - s[2]) << 12 | 1 << 13
    R3 = neg[2] << 4 | low[3] << 6 | (1 - s[3]) << 14 | 1 << 15
    return [R0, R1, R2, R3], neg[3] << 6


def fa(x, y, z):
    """Full adder: (sum, carry)."""
    return x ^ y ^ z, (x & y) | (x & z) | (y & z)


def c42(x1, x2, x3, x4, cin):
    """4:2 compressor from two full adders: x1+x2+x3+x4+cin = s + 2*(carry + cout).
    cout depends only on x1..x3, never on cin, so the cin -> cout chain does not ripple."""
    s1, cout = fa(x1, x2, x3)
    s, carry = fa(s1, x4, cin)
    return s, carry, cout


def compress42(R):
    """One row of 4:2 compressors over the 16 columns of R0..R3 -> (S, C), S + C == sum(R) mod 2^16."""
    S = C = cin = 0
    for c in range(16):
        s, carry, cin = c42(*(bit(x, c) for x in R), cin)
        S |= s << c
        C |= carry << (c + 1)  # the carry and cout of column 15 fall off the 16-bit product
    return S, C & MASK16


def mul(a, w, style="ADDER"):
    """Product with every intermediate signal of the chosen SUM_STYLE; p is the 16-bit product."""
    enc = encode(w)
    one, two, neg = ([e[k] for e in enc] for k in range(3))
    r = [pp_row(a, *e) for e in enc]
    R, e = place(r, neg)
    out = dict(one=one, two=two, neg=neg, r=r, R=R, e=e)
    if style == "ADDER":
        s01 = (R[0] + R[1]) & MASK16
        s23 = (R[2] + R[3] + e) & MASK16
        return dict(out, s01=s01, s23=s23, p=(s01 + s23) & MASK16)
    if style == "CSA42":
        S, C = compress42(R)
        return dict(out, S=S, C=C, p=(S + C + e) & MASK16)
    raise ValueError(style)


def to_signed16(x):
    return x - (1 << 16) if x >> 15 else x
