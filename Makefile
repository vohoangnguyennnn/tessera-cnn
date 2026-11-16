# ~/.bashrc points VERILATOR_ROOT/VERILATOR at an old 5.020 build; use the verilator in PATH (oss-cad-suite 5.049).
unexport VERILATOR_ROOT VERILATOR

PY        ?= .venv/bin/python
P         ?= 8
PE_TYPE   ?= LUT_CUSTOM
SUM_STYLE ?= ADDER
F_MHZ     ?= 100

.PHONY: help venv train quantize export test test-py test-mul8 xsim cov l5 mul-ooc lane-ooc bit board sweep

help:
	@echo "Targets: venv train quantize export test test-py test-mul8 xsim cov l5 mul-ooc lane-ooc bit board sweep"
	@echo "Config:  P=$(P) PE_TYPE=$(PE_TYPE) SUM_STYLE=$(SUM_STYLE) F_MHZ=$(F_MHZ)"

venv:
	python3.10 -m venv .venv
	.venv/bin/pip install -r requirements.txt

train:
	$(PY) model/train.py
quantize:
	$(PY) model/quantize.py
export:
	$(PY) model/export.py --images 82  # make cov uses test image 81
# test: the whole regression (L0 Python, L1 unit, L2 op, L3/L4 network), ~7 min
test:
	$(PY) -m pytest
test-py:
	$(PY) -m pytest model/tests
test-mul8:
	$(PY) -m pytest tb/unit/test_mul8.py
VIVADO ?= vivado
CORE_SRCS = acc_pkg booth_r4_mul8 mul8 dot8 lane agu act_mem wgt_mem qparam_mem pe_array controller accel
# L5 (spec 10): the post-synthesis netlist of the accelerator core from `make bit` (it includes glbl), 1 image in XSim
l5:
	mkdir -p build/l5
	cd build/l5 && xvlog -d NETLIST -sv ../bit/$(CONFIG)/accel_funcsim.v ../../tb/net/tb_accel_xsim.sv > xvlog.log \
		&& xelab tb_accel_xsim glbl -L unisims_ver -s l5_snap -timescale 1ns/1ps -generic_top N_IMG=1 > xelab.log \
		&& xsim l5_snap -R | tee xsim.log && grep -q "XSIM PASS" xsim.log
# L4 cross-check on Vivado's simulator: 3 real images through the RTL (needs make export)
xsim:
	mkdir -p build/xsim
	cd build/xsim && xvlog -sv $(CORE_SRCS:%=../../rtl/core/%.sv) ../../tb/net/tb_accel_xsim.sv > xvlog.log \
		&& xelab tb_accel_xsim -s tb_snap -timescale 1ns/1ps > xelab.log && xsim tb_snap -R | tee xsim.log \
		&& grep -q "XSIM PASS" xsim.log
# functional coverage (docs/coverage_plan.md): covergroups bound in by tb/net/accel_cov.sv, 3 tests, ~5 min.
# A test fails on a golden mismatch or on any illegal_bins hit (XSim only prints those as ERROR).
#   base = images 0-2 as in make xsim; step = op by op with stop_after_op (closes CTRL.T7/T8);
#   sat = image 81, the first test image that saturates int8 both ways (closes LANE.SAT8; needs export --images 82)
# Reports: results/cov/base (before closure) and results/cov/merged (all 3 tests merged).
COV_TESTS = base: step:+STEP sat:+IMG0=81+N_IMG=1
cov:
	rm -rf build/cov/xsim.covdb && mkdir -p build/cov
	cd build/cov && xvlog -sv $(CORE_SRCS:%=../../rtl/core/%.sv) ../../tb/net/tb_accel_xsim.sv ../../tb/net/accel_cov.sv > xvlog.log \
		&& xelab tb_accel_xsim accel_cov_bind -s cov_snap -timescale 1ns/1ps > xelab.log
	cd build/cov && for t in $(COV_TESTS); do name=$${t%%:*}; args=$${t#*:}; \
		xsim cov_snap -R -cov_db_name $$name $$(echo $$args | tr '+' '\n' | sed '/^$$/d; s/^/-testplusarg /') > $$name.log; \
		grep -a "XSIM\|image\|WARNING: File" $$name.log; \
		grep -aq "XSIM PASS" $$name.log || exit 1; \
		if grep -aq "Illegal" $$name.log; then echo "$$name: illegal coverage bin hit"; exit 1; fi; done
	cd build/cov && xcrg -cov_db_dir . -cov_db_name base -report_format all -report_dir ../../results/cov/base > xcrg_base.log \
		&& xcrg -cov_db_dir . -report_format all -report_dir ../../results/cov/merged > xcrg_merged.log
# spec 12.0: OOC synth + implement of each multiplier -> results/mul8_ooc/summary.csv (~10-20 min)
mul-ooc:
	mkdir -p build/vivado
	cd build/vivado && $(VIVADO) -mode batch -nojournal -log mul_ooc.log \
		-source ../../fpga/tcl/mul_ooc.tcl -tclargs ../../results/mul8_ooc
# M2: one lane OOC (LUT/FF/DSP, Fmax, critical path) -> results/lane_ooc/summary.csv
lane-ooc:
	mkdir -p build/vivado
	cd build/vivado && $(VIVADO) -mode batch -nojournal -log lane_ooc.log \
		-source ../../fpga/tcl/lane_ooc.tcl -tclargs ../../results/lane_ooc
BAUD   ?= 921600
CONFIG  = P$(P)_$(PE_TYPE)_$(SUM_STYLE)_$(F_MHZ)MHz
# spec 11: synth -> place -> route -> bitstream; reports to results/$(CONFIG)/, bitstream to build/bit/$(CONFIG)/
bit:
	mkdir -p build/bit/$(CONFIG)
	cd build/bit/$(CONFIG) && $(VIVADO) -mode batch -nojournal -log build.log -source ../../../fpga/tcl/build.tcl \
		-tclargs $(P) $(PE_TYPE) $(SUM_STYLE) $(F_MHZ) $(BAUD) . ../../../results/$(CONFIG)
	cp build/bit/$(CONFIG)/build.log results/$(CONFIG)/build.log
	grep -q "inferred latch" results/$(CONFIG)/build.log && echo "LATCH INFERRED" && exit 1 || true
# 10,000 CIFAR-10 images over UART against the golden model (board programmed, USB-UART connected)
board:
	$(PY) host/host.py run --n 10000
# deferred to phase 2 (P x PE_TYPE sweep); fails on purpose so nothing mistakes it for done
sweep:
	@echo "deferred: 9-config sweep is phase 2"; exit 1
