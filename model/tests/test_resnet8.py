import torch
import torch.nn as nn

from resnet8 import ResNet8

# op -> (Cout, Hout) from the table in spec section 3
OUT_SHAPE = {
    "conv0": (16, 32), "s1a": (16, 32), "s1b": (16, 32),
    "s2a": (32, 16), "s2s": (32, 16), "s2b": (32, 16),
    "s3a": (64, 8), "s3s": (64, 8), "s3b": (64, 8),
}


def test_param_count_matches_mlperf_tiny():
    # Keras counts BN moving mean/var as (non-trainable) params; PyTorch keeps them as buffers.
    m = ResNet8()
    trainable = sum(p.numel() for p in m.parameters())
    bn_stats = sum(b.numel() for n, b in m.named_buffers() if n.endswith(("running_mean", "running_var")))
    assert (trainable, bn_stats) == (78_186, 480)
    assert trainable + bn_stats == 78_666


def test_op_output_shapes():
    m, got = ResNet8(), {}
    for op in OUT_SHAPE:
        getattr(m, op).register_forward_hook(lambda mod, i, o, op=op: got.__setitem__(op, tuple(o.shape[1:])))
    assert m(torch.zeros(2, 3, 32, 32)).shape == (2, 10)
    assert got == {op: (c, h, h) for op, (c, h) in OUT_SHAPE.items()}


def test_bn_on_main_path_only():
    bns = {n for n, mod in ResNet8().named_modules() if isinstance(mod, nn.BatchNorm2d)}
    assert bns == {op + "_bn" for op in OUT_SHAPE if op not in ("s2s", "s3s")}
