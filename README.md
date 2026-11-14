# tessera-cnn
(WIP) INT8 CNN accelerator designed from scratch in SystemVerilog RTL (no HLS): custom radix-4 Booth LUT multipliers vs. a DSP48 baseline, running ResNet-8 (MLPerf Tiny IC architecture) on CIFAR-10 on an Artix-7. Bit-exact verified against an integer Python golden model (cocotb + Verilator).
