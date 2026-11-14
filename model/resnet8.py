"""ResNet-8 (MLPerf Tiny IC architecture) in PyTorch, spec section 3.

Conv modules are named after the 10 ops of the spec; the BN after op X is `X_bn`,
so BN folding and quantization map 1:1 onto the hardware op list.

Deliberate difference from the Keras reference (mlcommons/tiny resnet_v1_eembc,
conv_filters=16): stride-2 convs use symmetric padding=1 instead of Keras 'same',
which pads only bottom/right.
"""
import torch.nn as nn
import torch.nn.functional as F


class ResNet8(nn.Module):
    def __init__(self):
        super().__init__()
        # (Cin, Cout, kernel, stride, pad) per op; bias=True as in Keras -> 78,666 params
        self.conv0, self.conv0_bn = nn.Conv2d(3, 16, 3, 1, 1), nn.BatchNorm2d(16)
        self.s1a, self.s1a_bn = nn.Conv2d(16, 16, 3, 1, 1), nn.BatchNorm2d(16)
        self.s1b, self.s1b_bn = nn.Conv2d(16, 16, 3, 1, 1), nn.BatchNorm2d(16)
        self.s2a, self.s2a_bn = nn.Conv2d(16, 32, 3, 2, 1), nn.BatchNorm2d(32)
        self.s2s = nn.Conv2d(16, 32, 1, 2, 0)  # shortcut: no BN, no ReLU
        self.s2b, self.s2b_bn = nn.Conv2d(32, 32, 3, 1, 1), nn.BatchNorm2d(32)
        self.s3a, self.s3a_bn = nn.Conv2d(32, 64, 3, 2, 1), nn.BatchNorm2d(64)
        self.s3s = nn.Conv2d(32, 64, 1, 2, 0)  # shortcut: no BN, no ReLU
        self.s3b, self.s3b_bn = nn.Conv2d(64, 64, 3, 1, 1), nn.BatchNorm2d(64)
        self.fc = nn.Linear(64, 10)
        for m in self.modules():  # Keras reference: he_normal kernels, zero bias
            if isinstance(m, (nn.Conv2d, nn.Linear)):
                nn.init.kaiming_normal_(m.weight, nonlinearity="relu")
                nn.init.zeros_(m.bias)

    def forward(self, x):
        x = F.relu(self.conv0_bn(self.conv0(x)))
        # stack 1: residual = input of s1a (identity); ReLU after the add
        y = F.relu(self.s1a_bn(self.s1a(x)))
        x = F.relu(self.s1b_bn(self.s1b(y)) + x)
        # stack 2: residual = output of s2s, which reads the same input as s2a
        y = F.relu(self.s2a_bn(self.s2a(x)))
        x = F.relu(self.s2b_bn(self.s2b(y)) + self.s2s(x))
        # stack 3: same pattern as stack 2
        y = F.relu(self.s3a_bn(self.s3a(x)))
        x = F.relu(self.s3b_bn(self.s3b(y)) + self.s3s(x))
        # op "fc": GAP 8x8 + FC; returns logits (no softmax, hardware outputs logits too)
        return self.fc(F.avg_pool2d(x, 8).flatten(1))
