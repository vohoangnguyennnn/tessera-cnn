import torch
import torch.nn.functional as F

from train import augment


def test_augment_is_a_padded_crop_with_optional_flip():
    torch.manual_seed(0)
    x = torch.rand(16, 3, 32, 32)
    out = augment(x)
    xp = F.pad(x, (4, 4, 4, 4))
    for n in range(len(x)):
        crops = [xp[n, :, oy:oy + 32, ox:ox + 32] for oy in range(9) for ox in range(9)]
        assert any(torch.equal(out[n], c) or torch.equal(out[n], c.flip(2)) for c in crops), n
