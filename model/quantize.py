"""Post-training quantization of the FP32 ResNet-8 into the integer scheme of spec section 4.

BN folding -> calibration of activation scales on 1,000 training images -> INT8 weights,
INT32 biases and (M, n) requant pairs. The calibration method (max / p99.99 / p99.9) is picked
by integer-model accuracy on the validation split; the test set is evaluated once, at the end.

    python model/quantize.py      -> model/checkpoints/qparams.npz + qparams.json
"""
import json
import math

import numpy as np
import torch
import torch.nn.functional as F

import cifar
import golden
from golden import OPS
from resnet8 import ResNet8
from train import CKPT, accuracy as fp32_accuracy

N_CALIB = 1000
METHODS = {"max": 100.0, "p99.99": 99.99, "p99.9": 99.9}  # percentile of |x| over the calibration set


def fold(model):
    """{op: (W, b)} float64 numpy with BN folded in (spec 4.2), keeping the conv bias:
    W' = W * g/sqrt(var+eps),  b' = beta + (b - mean) * g/sqrt(var+eps)."""
    out = {}
    for op in OPS:
        layer = getattr(model, op.name)
        W, b = layer.weight.detach().double(), layer.bias.detach().double()
        bn = getattr(model, op.name + "_bn", None)
        if bn is not None:
            s = bn.weight.detach().double() / torch.sqrt(bn.running_var.double() + bn.eps)
            W = W * s[:, None, None, None]
            b = bn.bias.detach().double() + (b - bn.running_mean.double()) * s
        out[op.name] = (W.numpy(), b.numpy())
    return out


def fp_forward(folded, x):
    """Float forward pass over the folded network, same graph as golden.run. x: float64 NCHW tensor."""
    a = {"img": x}
    for op in OPS:
        W, b = (torch.from_numpy(t) for t in folded[op.name])
        if op.name == "fc":
            y = (a[op.src].mean((2, 3)) @ W.T + b)[:, :, None, None]
        else:
            y = F.conv2d(a[op.src], W, b, stride=op.stride, padding=op.pad)
        if op.res:
            y = y + a[op.res]
        a[op.name] = F.relu(y) if op.relu else y
    return a


def mn(m):
    """Real multiplier m -> (M, n) with M in [2^15, 2^16), m ~= M / 2^n (spec 4.4)."""
    f, e = math.frexp(m)  # m = f * 2^e, f in [0.5, 1) -> floor(log2 m) = e - 1 exactly
    n, M = 16 - e, round(f * 2**16)
    if M == 2**16:
        M, n = 2**15, n - 1
    assert 2**15 <= M < 2**16 and 1 <= n <= 63, (m, M, n)
    return M, n


def build(folded, S):
    """Integer parameters for scales S = {tensor name: activation scale}."""
    q = {f"S.{k}": np.float64(v) for k, v in S.items()}
    for op in OPS:
        W, b = folded[op.name]
        s_x, s_out = S[op.src], S[op.name]
        s_w = np.abs(W.reshape(len(W), -1)).max(1) / 127
        s_w[s_w == 0] = 1.0  # all-zero channel: any scale works
        bshape = (-1,) + (1,) * (W.ndim - 1)
        q[op.name + ".w"] = np.clip(np.round(W / s_w.reshape(bshape)), -127, 127).astype(np.int8)
        # fc accumulates the SUM over 64 positions and divides by 64 inside M, so its bias is scaled by 64 too
        pos = 64 if op.name == "fc" else 1
        b_q = np.round(pos * b / (s_x * s_w)).astype(np.int64)
        assert np.abs(b_q).max() < 2**30, op.name
        q[op.name + ".b"] = b_q.astype(np.int32)
        Mn = [mn(s_x * sw / (pos * s_out)) for sw in s_w]
        q[op.name + ".M"] = np.array([M for M, _ in Mn], dtype=np.int32)
        q[op.name + ".n"] = np.array([n for _, n in Mn], dtype=np.int32)
        if op.res:
            q[op.name + ".Mr"], q[op.name + ".nr"] = (np.int32(v) for v in mn(S[op.res] / s_out))
    return q


def main():
    model = ResNet8()
    model.load_state_dict(torch.load(CKPT, map_location="cpu"))
    model.eval()
    folded = fold(model)

    xcal = cifar.load("train")[0][:N_CALIB]
    with torch.no_grad():
        acts = fp_forward(folded, cifar.normalize(cifar.to_float(xcal)).double())
    pct = list(METHODS.values())
    stats = {k: np.percentile(v.abs().numpy().ravel(), pct) for k, v in acts.items()}
    del acts
    scales = {m: {k: s[i] / 127 for k, s in stats.items()} for i, m in enumerate(METHODS)}

    xva, yva = cifar.load("val")
    fp32_val = fp32_accuracy(model, cifar.to_float(xva), torch.from_numpy(yva))
    val = {}
    for m in METHODS:
        val[m] = golden.accuracy(build(folded, scales[m]), xva, yva)
        print(f"calib {m:7s} val golden {val[m]:.4f}  (fp32 {fp32_val:.4f})", flush=True)
    best = max(val, key=val.get)
    q = build(folded, scales[best])
    golden.QPARAMS.parent.mkdir(exist_ok=True)
    np.savez(golden.QPARAMS, **q)

    # Test set: once, for reporting only (spec 4.6).
    xte, yte = cifar.load("test")
    fp32_test = json.loads(CKPT.with_suffix(".json").read_text())["test_acc"]
    golden_test = golden.accuracy(q, xte, yte)
    info = {"calibration": best, "n_calib": N_CALIB, "val_fp32": fp32_val, "val_golden": val,
            "test_fp32": fp32_test, "test_golden": golden_test,
            "test_drop_points": round(100 * (fp32_test - golden_test), 2)}
    golden.QPARAMS.with_suffix(".json").write_text(json.dumps(info, indent=2) + "\n")
    print(json.dumps(info, indent=2))


if __name__ == "__main__":
    main()
