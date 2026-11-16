"""Build and run one cocotb test module on Verilator from pytest (shared by the tb/unit tests)."""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RTL = ROOT / "rtl" / "core"
MUL_SRCS = ["booth_r4_mul8.sv", "mul8.sv"]


def run(toplevel, sources, parameters, test_module, extra_env=None, test_dir=None):
    """parameters become both HDL parameters and environment variables of the cocotb test."""
    # ~/.bashrc points these at an old 5.020 build; let verilator find its own root (docs/journal.md)
    os.environ.pop("VERILATOR_ROOT", None)
    os.environ.pop("VERILATOR", None)
    # verilated.mk runs `python3` from PATH; it must be this interpreter, not oss-cad-suite's 3.11
    os.environ["PATH"] = str(Path(sys.executable).parent) + os.pathsep + os.environ["PATH"]
    from cocotb_tools.runner import get_runner

    tag = "_".join(f"{k}{Path(str(v)).name}" for k, v in parameters.items())  # paths: last component only
    build_dir = ROOT / "build" / "sim" / f"{toplevel}_{tag}"
    hdl_params = {k: f'"{v}"' if isinstance(v, str) else v for k, v in parameters.items()}
    env = {k: str(v) for k, v in {**parameters, **(extra_env or {})}.items()}
    runner = get_runner("verilator")
    runner.build(sources=[RTL / s for s in sources], hdl_toplevel=toplevel, parameters=hdl_params,
                 build_args=["--assert"], build_dir=build_dir, always=True, timescale=("1ns", "1ps"))
    runner.test(test_module=test_module, hdl_toplevel=toplevel, build_dir=build_dir,
                test_dir=test_dir or Path(__file__).parent, extra_env=env)


def pack(bytes8):
    """8 signed bytes -> 64-bit word, byte i at bits [8i+7 : 8i] (spec 7.1)."""
    return sum((b & 0xFF) << 8 * i for i, b in enumerate(bytes8))
