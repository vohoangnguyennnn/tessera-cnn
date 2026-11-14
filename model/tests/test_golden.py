"""L0 tests for the integer arithmetic spec (golden.py) and quantization (quantize.py)."""
import math
import random
from fractions import Fraction

import numpy as np
import torch

import golden
from quantize import fold, fp_forward, mn
from resnet8 import ResNet8


def rq_exact(t, M, n):
    """Independent reference: floor(t*M / 2^n + 1/2) with exact rationals."""
    return math.floor(Fraction(t * M, 2**n) + Fraction(1, 2))


def test_rq_matches_exact_rational_rounding():
    rng = random.Random(0)
    cases = [(t, M, n) for t in (0, 1, -1, 2**29, -2**29, 2**31 - 1, -2**31)
             for M in (2**15, 2**16 - 1) for n in (1, 2, 15, 31, 47, 48, 63)]
    cases += [(rng.randrange(-2**31, 2**31), rng.randrange(2**15, 2**16), rng.randrange(1, 64))
              for _ in range(20000)]
    # exact half cases: t*M = (2k+1) * 2^(n-1) must round up (toward +inf), also for negatives
    cases += [(-3, 2**15, 16), (-1, 2**15, 16), (1, 2**15, 16), (3, 2**15, 16)]
    t, M, n = (np.array(c, dtype=np.int64) for c in zip(*cases))
    got = golden.rq(t, M, n)
    assert got.tolist() == [rq_exact(*c) for c in cases]


def test_mn_range_and_precision():
    rng = random.Random(1)
    ms = [2.0**rng.uniform(-40, 13) for _ in range(5000)]
    ms += [2.0**k for k in range(-40, 14)] + [math.nextafter(2.0**k, 0) for k in range(-40, 14)]
    for m in ms:
        M, n = mn(m)
        assert 2**15 <= M < 2**16 and 1 <= n <= 63
        assert abs(M / 2**n - m) <= m * 2**-15


def test_conv_acc_is_exact_integer_conv():
    rng = np.random.default_rng(2)
    x = rng.integers(-128, 128, (2, 16, 8, 8))
    w = rng.integers(-127, 128, (4, 16, 3, 3))
    got = golden.conv_acc(x, w, stride=2, pad=1)
    xp = np.pad(x, ((0, 0), (0, 0), (1, 1), (1, 1)))
    ref = np.zeros_like(got)
    for oy in range(got.shape[2]):
        for ox in range(got.shape[3]):
            patch = xp[:, :, 2 * oy:2 * oy + 3, 2 * ox:2 * ox + 3]
            ref[:, :, oy, ox] = np.einsum("nchw,ochw->no", patch, w)
    assert np.array_equal(got, ref)


def test_bn_folding_preserves_fp32_output():
    torch.manual_seed(3)
    m = ResNet8()
    for mod in m.modules():  # non-trivial BN statistics and affine params
        if isinstance(mod, torch.nn.BatchNorm2d):
            mod.running_mean.uniform_(-0.5, 0.5), mod.running_var.uniform_(0.5, 2.0)
            mod.weight.data.uniform_(0.5, 1.5), mod.bias.data.uniform_(-0.2, 0.2)
    m.eval()
    x = torch.randn(4, 3, 32, 32)
    with torch.no_grad():
        ref = m(x).double()
        got = fp_forward(fold(m), x.double())["fc"][:, :, 0, 0]
    assert torch.allclose(got, ref, atol=1e-4, rtol=1e-4)


def test_ops_table_matches_model_shapes():
    m = ResNet8()
    for op in golden.OPS:
        w = getattr(m, op.name).weight
        if op.name == "fc":
            assert tuple(w.shape) == (op.cout, op.cin)
        else:
            assert tuple(w.shape) == (op.cout, op.cin, op.k, op.k)
        assert op.hout == (op.hin + 2 * op.pad - op.k) // op.stride + 1
