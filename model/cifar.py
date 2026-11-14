"""CIFAR-10 loading, train/val/test split and input normalization (spec 4.6).

The split is fixed: train images [0, 45000) train the model, [45000, 50000) are the
validation split used to pick calibration settings; the test set is only for reporting.
"""
from pathlib import Path

import numpy as np
import torch
import torchvision

ROOT = Path(__file__).resolve().parents[1]
N_TRAIN = 45000
MEAN = torch.tensor([0.4914, 0.4822, 0.4465]).view(1, 3, 1, 1)
STD = torch.tensor([0.2470, 0.2435, 0.2616]).view(1, 3, 1, 1)


def load(split):
    """split in {"train", "val", "test"} -> (uint8 NHWC images, int64 labels)."""
    ds = torchvision.datasets.CIFAR10(ROOT / "data", train=split != "test", download=True)
    x, y = ds.data, np.array(ds.targets, dtype=np.int64)
    if split == "train":
        return x[:N_TRAIN], y[:N_TRAIN]
    if split == "val":
        return x[N_TRAIN:], y[N_TRAIN:]
    return x, y


def to_float(u8):
    """uint8 NHWC numpy -> float32 NCHW tensor in [0, 1]."""
    return torch.from_numpy(u8).permute(0, 3, 1, 2).float().div(255)


def normalize(x):
    """Per-channel mean/std normalization of a [0, 1] NCHW tensor (done on the host, spec 4.6)."""
    return (x - MEAN.to(x.device)) / STD.to(x.device)
