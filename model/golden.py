"""Integer-only ResNet-8 inference: this file IS the arithmetic spec (spec section 4).

The RTL must match `run()` bit for bit. Everything here is integer arithmetic on int64
numpy arrays; numpy `>>` on signed ints is an arithmetic (floor) shift, like SystemVerilog `>>>`.
"""
from collections import namedtuple

import numpy as np
import torch
import torch.nn.functional as F

import cifar

QPARAMS = cifar.ROOT / "model" / "checkpoints" / "qparams.npz"

# The 10 ops of spec section 3. src/res name the tensor read as input/residual ("img" = network input).
Op = namedtuple("Op", "name src res cin cout k stride pad hin hout relu")
OPS = [
    Op("conv0", "img", None, 3, 16, 3, 1, 1, 32, 32, True),
    Op("s1a", "conv0", None, 16, 16, 3, 1, 1, 32, 32, True),
    Op("s1b", "s1a", "conv0", 16, 16, 3, 1, 1, 32, 32, True),
    Op("s2a", "s1b", None, 16, 32, 3, 2, 1, 32, 16, True),
    Op("s2s", "s1b", None, 16, 32, 1, 2, 0, 32, 16, False),
    Op("s2b", "s2a", "s2s", 32, 32, 3, 1, 1, 16, 16, True),
    Op("s3a", "s2b", None, 32, 64, 3, 2, 1, 16, 8, True),
    Op("s3s", "s2b", None, 32, 64, 1, 2, 0, 16, 8, False),
    Op("s3b", "s3a", "s3s", 64, 64, 3, 1, 1, 8, 8, True),
    Op("fc", "s3b", None, 64, 10, 8, 1, 0, 8, 1, False),  # GAP 8x8 + FC fused (spec 4.5)
]

MEAN = cifar.MEAN.numpy().astype(np.float64).reshape(3)
STD = cifar.STD.numpy().astype(np.float64).reshape(3)


def rq(t, M, n):
    """RQ(t, M, n) = floor((t*M + 2^(n-1)) / 2^n), round half up (spec 4.4). Fits int64 for n <= 63."""
    return (t * M + (np.int64(1) << (n - 1))) >> n


def conv_acc(x, w, stride, pad):
    """Exact integer conv sum. float64 on CPU is exact: every partial sum is an integer < 2^27 < 2^53."""
    y = F.conv2d(torch.from_numpy(x).double(), torch.from_numpy(w).double(), stride=stride, padding=pad)
    return y.round().long().numpy()


def quantize_image(u8, s_in):
    """Host side: uint8 NHWC image -> normalized -> int8 values (as int64 NCHW), spec 4.6."""
    x = (u8.astype(np.float64) / 255 - MEAN) / STD
    return np.clip(np.floor(x / s_in + 0.5), -128, 127).astype(np.int64).transpose(0, 3, 1, 2)


def run(q, x):
    """x: int64 NCHW input image(s). Returns {tensor name: int64 NCHW int8-valued output of that op}."""
    a = {"img": x}
    for op in OPS:
        w, b = q[op.name + ".w"].astype(np.int64), q[op.name + ".b"].astype(np.int64)
        M, n = q[op.name + ".M"].astype(np.int64)[:, None, None], q[op.name + ".n"].astype(np.int64)[:, None, None]
        if op.name == "fc":  # w_shared: the same W[co, ci] at all 64 positions, no rounding after GAP
            acc = (a[op.src].sum((2, 3)) @ w.T)[:, :, None, None]
        else:
            acc = conv_acc(a[op.src], w, op.stride, op.pad)
        acc = acc + b[:, None, None]
        assert np.abs(acc).max() < 2**30, op.name
        y = np.clip(rq(acc, M, n), -2**15, 2**15 - 1)
        if op.res:
            Mr, nr = q[op.name + ".Mr"].astype(np.int64), q[op.name + ".nr"].astype(np.int64)
            y = y + np.clip(rq(a[op.res], Mr, nr), -2**15, 2**15 - 1)
        z = np.clip(y, -128, 127)
        a[op.name] = np.maximum(z, 0) if op.relu else z
    return a


def logits(q, u8, batch=500):
    """uint8 NHWC images -> int64 [N, 10] logits of the integer network."""
    s_in = float(q["S.img"])
    return np.concatenate([run(q, quantize_image(u8[i:i + batch], s_in))["fc"][:, :, 0, 0]
                           for i in range(0, len(u8), batch)])


def accuracy(q, u8, labels):
    # argmax picks the lowest index on ties; host.py must use the same rule
    return float((logits(q, u8).argmax(1) == labels).mean())


def load_qparams(path=QPARAMS):
    with np.load(path) as f:
        return dict(f)
