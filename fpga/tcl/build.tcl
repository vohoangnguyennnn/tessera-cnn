# Bitstream build, non-project mode (spec 11.1):
#   vivado -mode batch -nojournal -source fpga/tcl/build.tcl -tclargs P PE_TYPE SUM_STYLE F_MHZ BAUD BUILD_DIR RESULTS_DIR
#   (make bit P=8 PE_TYPE=LUT_CUSTOM SUM_STYLE=ADDER F_MHZ=100 BAUD=115200)
#
# BUILD_DIR receives the bitstream, the IP and the L5 netlist (not committed); RESULTS_DIR receives every
# report plus build_info.txt (git commit, Vivado version, configuration) and summary.csv.

set part xc7a35tfgg484-2
set root [file normalize [file join [file dirname [info script]] .. ..]]
lassign $argv P PE SUM F_MHZ BAUD bdir rdir
set bdir [file normalize $bdir]
set rdir [file normalize $rdir]
file mkdir $bdir $rdir
array set depth {4 {2444 87} 8 {1226 44} 16 {613 22}}
lassign $depth($P) D_W D_Q
set clk_hz [expr {int(round($F_MHZ * 1e6))}]

create_project -in_memory -part $part

# ---- clock: Clocking Wizard IP "clk_core", recreated from these settings on every build --------------
file mkdir $bdir/ip
create_ip -name clk_wiz -vendor xilinx.com -library ip -module_name clk_core -dir $bdir/ip -force
set_property -dict [list \
    CONFIG.PRIMITIVE {MMCM} CONFIG.PRIM_IN_FREQ {50.000} CONFIG.PRIM_SOURCE {Single_ended_clock_capable_pin} \
    CONFIG.CLKOUT1_REQUESTED_OUT_FREQ $F_MHZ CONFIG.USE_RESET {true} CONFIG.RESET_TYPE {ACTIVE_HIGH} \
    CONFIG.USE_LOCKED {true}] [get_ips clk_core]
generate_target {synthesis instantiation_template} [get_ips clk_core]
set_property GENERATE_SYNTH_CHECKPOINT false [get_files clk_core.xci]
set achieved [get_property CONFIG.CLKOUT1_REQUESTED_OUT_FREQ [get_ips clk_core]]

# ---- sources -------------------------------------------------------------------------------------------
foreach m {acc_pkg booth_r4_mul8 mul8 dot8 lane agu act_mem wgt_mem qparam_mem pe_array controller accel} {
    read_verilog -sv $root/rtl/core/$m.sv
}
foreach m {uart_rx uart_tx host_if soc top} { read_verilog -sv $root/rtl/soc/$m.sv }
read_xdc $root/fpga/xdc/a7_lite.xdc

synth_design -top top -part $part \
    -generic PE_TYPE=\"$PE\" -generic SUM_STYLE=\"$SUM\" -generic L_MUL=2 -generic P=$P \
    -generic D_W=$D_W -generic D_Q=$D_Q -generic HEX_DIR=\"$root/model/export/P$P\" \
    -generic CLK_HZ=$clk_hz -generic BAUD=$BAUD
report_utilization -hierarchical -file $rdir/post_synth_util_hier.rpt
report_utilization -file $rdir/post_synth_util.rpt
# L5: functional netlist of the accelerator core, simulated by tb/net/tb_accel_xsim.sv (make l5)
write_verilog -mode funcsim -force -cell [get_cells u_soc/u_core] $bdir/accel_funcsim.v

# ---- implementation (default strategies, spec 12.1) -------------------------------------------------------
opt_design
place_design
phys_opt_design
route_design

report_utilization -file $rdir/util.rpt
report_utilization -hierarchical -file $rdir/util_hier.rpt
report_timing_summary -max_paths 10 -file $rdir/timing_summary.rpt
report_timing -max_paths 10 -file $rdir/timing_paths.rpt
report_methodology -file $rdir/methodology.rpt
report_drc -file $rdir/drc.rpt
report_power -file $rdir/power.rpt
report_high_fanout_nets -max_nets 10 -file $rdir/high_fanout.rpt
report_clocks -file $rdir/clocks.rpt

write_bitstream -force $bdir/top.bit

# ---- summary (numbers read from the standard utilization report) ------------------------------------------
set util [report_utilization -return_string]
proc util_value {util name} {
    if {[regexp "\\|\\s*$name\\*?\\s*\\|\\s*(\[0-9.\]+)" $util -> v]} { return $v }
    return NA
}
set path [lindex [get_timing_paths -setup -max_paths 1] 0]
set hold [lindex [get_timing_paths -hold -max_paths 1] 0]
set row [list $P $PE $SUM $F_MHZ [util_value $util "Slice LUTs"] [util_value $util "Slice Registers"] \
    [util_value $util "Register as Latch"] [util_value $util "DSPs"] [util_value $util "Block RAM Tile"] \
    [get_property SLACK $path] [get_property SLACK $hold]]
set csv [open $rdir/summary.csv w]
puts $csv "p,pe_type,sum_style,f_mhz,lut,ff,latch,dsp,bram36_tiles,wns_ns,whs_ns"
puts $csv [join $row ,]
close $csv
set f [open $rdir/build_info.txt w]
puts $f "git      [exec git -C $root describe --always --dirty]"
puts $f "vivado   [version -short]"
puts $f "part     $part"
puts $f "config   P=$P PE_TYPE=$PE SUM_STYLE=$SUM F_MHZ=$F_MHZ (clk_core requested $achieved MHz) BAUD=$BAUD"
puts $f "bit      $bdir/top.bit"
close $f
puts "BUILD_DONE [join $row ,]"
