# One lane out of context (M2): LUT / FF / DSP of the lane and of its dot8, Fmax, critical path end.
#
#   vivado -mode batch -nojournal -source fpga/tcl/lane_ooc.tcl -tclargs <results_dir>    (make lane-ooc)

source [file join [file dirname [info script]] ooc_lib.tcl]

set out  [file normalize [lindex $argv 0]]
set srcs {rtl/core/booth_r4_mul8.sv rtl/core/mul8.sv rtl/core/dot8.sv rtl/core/lane.sv fpga/ooc/lane_ooc.sv}
# LUT_INFERRED is no longer part of the accelerator experiments (spec Changelog, 2026-11-14); its row in
# summary.csv was measured earlier and can be reproduced with the extra argument LUT_INFERRED:ADDER below.
set configs {{LUT_CUSTOM ADDER} {LUT_CUSTOM CSA42}}
# optional extra args "PE_TYPE:SUM_STYLE ...": run only those and append to an existing summary.csv
set only [lrange $argv 1 end]
if {[llength $only]} { set configs [lmap c $only {split $c :}] }

file mkdir $out
set csv [open $out/summary.csv [expr {[llength $only] ? "a" : "w"}]]
if {![llength $only]} {
    header $csv
    # area columns are measured at 100 MHz; fmax by the search in ooc_lib.tcl
    puts $csv "pe_type,sum_style,l_mul,lane_lut,lane_ff,dot8_lut,dot8_ff,dsp,wns_100mhz_ns,fmax_mhz,wns_at_fmax_ns,fmax_est_mhz,logic_levels_100mhz,critical_path_end_at_fmax"
}
foreach cfg $configs {
    lassign $cfg pe style
    set r [measure lane_ooc $srcs [list PE_TYPE $pe SUM_STYLE $style L_MUL 2] {} $out/${pe}_${style}_L2 {u_lane u_dot}]
    lassign [dict get $r util u_lane] lut ff
    lassign [dict get $r util u_dot] dlut dff
    set row [join [list $pe $style 2 $lut $ff $dlut $dff [dict get $r dsp] [dict get $r wns_100] [dict get $r fmax] \
        [dict get $r wns_fmax] [dict get $r fmax_est] [dict get $r levels] [dict get $r path_end_fmax]] ,]
    puts $csv $row
    flush $csv
    puts "RESULT $row"
}
close $csv
