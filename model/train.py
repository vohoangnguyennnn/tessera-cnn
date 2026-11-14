"""Train FP32 ResNet-8 on CIFAR-10 (spec section 3, milestone M0).

Recipe: random crop 32 (pad 4) + horizontal flip, SGD momentum 0.9, cosine LR, 200 epochs.
The whole dataset lives on the GPU and augmentation runs there, so the tiny model is not
starved by CPU data loading. The test set is evaluated once, after training.

    python model/train.py [--epochs N] [--resume]
"""
import argparse
import json
import time

import torch
import torch.nn.functional as F

import cifar
from resnet8 import ResNet8

SEED = 0
BATCH = 128
LR = 0.1
WEIGHT_DECAY = 5e-4  # conv/fc weights only; BN params and biases are not decayed
CKPT = cifar.ROOT / "model" / "checkpoints" / "resnet8_fp32.pt"
STATE = cifar.ROOT / "build" / "train_last.pt"  # per-epoch state for --resume (not committed)


def augment(x):
    """Random crop 32x32 from the zero-padded 40x40 image + random horizontal flip, per image."""
    n, dev = x.shape[0], x.device
    xp = F.pad(x, (4, 4, 4, 4))
    oy = torch.randint(0, 9, (n, 1, 1), device=dev)
    ox = torch.randint(0, 9, (n, 1, 1), device=dev)
    r = torch.arange(32, device=dev)
    idx = ((oy + r.view(1, 32, 1)) * 40 + (ox + r.view(1, 1, 32))).view(n, 1, 1024).expand(n, 3, 1024)
    out = xp.flatten(2).gather(2, idx).view(n, 3, 32, 32)
    flip = torch.rand(n, device=dev) < 0.5
    return torch.where(flip.view(n, 1, 1, 1), out.flip(3), out)


@torch.no_grad()
def accuracy(model, x, y):
    model.eval()
    correct = sum((model(cifar.normalize(x[i:i + 1000])).argmax(1) == y[i:i + 1000]).sum().item()
                  for i in range(0, len(x), 1000))
    return correct / len(x)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--epochs", type=int, default=200)
    ap.add_argument("--resume", action="store_true", help=f"continue from {STATE}")
    args = ap.parse_args()

    torch.manual_seed(SEED)
    torch.backends.cudnn.deterministic, torch.backends.cudnn.benchmark = True, False
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    (xtr, ytr), (xva, yva) = cifar.load("train"), cifar.load("val")
    xtr, ytr = cifar.to_float(xtr).to(dev), torch.from_numpy(ytr).to(dev)
    xva, yva = cifar.to_float(xva).to(dev), torch.from_numpy(yva).to(dev)

    model = ResNet8().to(dev)
    decay = [p for p in model.parameters() if p.ndim > 1]
    no_decay = [p for p in model.parameters() if p.ndim <= 1]
    opt = torch.optim.SGD([{"params": decay, "weight_decay": WEIGHT_DECAY},
                           {"params": no_decay, "weight_decay": 0.0}], lr=LR, momentum=0.9)
    sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, T_max=args.epochs)
    start = 0
    if args.resume:
        s = torch.load(STATE, map_location=dev)
        model.load_state_dict(s["model"])
        opt.load_state_dict(s["opt"])
        sched.load_state_dict(s["sched"])
        torch.set_rng_state(s["rng"])
        if dev == "cuda":
            torch.cuda.set_rng_state(s["cuda_rng"])
        start = s["epoch"]
        print(f"resumed at epoch {start}")

    STATE.parent.mkdir(exist_ok=True)
    t0 = time.time()
    for ep in range(start, args.epochs):
        model.train()
        te = time.time()
        perm = torch.randperm(len(xtr), device=dev)
        for k in range(0, len(xtr), BATCH):
            i = perm[k:k + BATCH]
            loss = F.cross_entropy(model(cifar.normalize(augment(xtr[i]))), ytr[i])
            opt.zero_grad(set_to_none=True)
            loss.backward()
            opt.step()
        sched.step()
        torch.save({"model": model.state_dict(), "opt": opt.state_dict(), "sched": sched.state_dict(),
                    "rng": torch.get_rng_state(), "epoch": ep + 1,
                    "cuda_rng": torch.cuda.get_rng_state() if dev == "cuda" else None}, STATE)
        if (ep + 1) % 10 == 0 or ep == start or ep + 1 == args.epochs:
            print(f"epoch {ep + 1:3d}  loss {loss.item():.3f}  val {accuracy(model, xva, yva):.4f}  "
                  f"lr {sched.get_last_lr()[0]:.4f}  {time.time() - te:.1f}s/epoch", flush=True)

    # Test set: evaluated once here, for reporting only (spec 4.6).
    xte, yte = cifar.load("test")
    test_acc = accuracy(model, cifar.to_float(xte).to(dev), torch.from_numpy(yte).to(dev))
    CKPT.parent.mkdir(exist_ok=True)
    torch.save(model.state_dict(), CKPT)
    info = {"epochs": args.epochs, "seed": SEED, "batch": BATCH, "lr": LR, "weight_decay": WEIGHT_DECAY,
            "val_acc": accuracy(model, xva, yva), "test_acc": test_acc,
            "train_minutes": round((time.time() - t0) / 60, 1), "device": torch.cuda.get_device_name() if dev == "cuda" else "cpu"}
    CKPT.with_suffix(".json").write_text(json.dumps(info, indent=2) + "\n")
    print(json.dumps(info, indent=2))


if __name__ == "__main__":
    main()
