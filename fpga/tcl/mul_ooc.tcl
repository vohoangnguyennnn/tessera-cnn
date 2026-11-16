# Multiplier mini-experiment (spec 12.0): out-of-context synth + place + route of one mul8 with
# registers on all inputs/outputs, for each PE_TYPE / SUM_STYLE, combinational (L_MUL = 0, for logic
# levels) and pipelined (L_MUL = 2). Fmax method: see ooc_lib.tcl.
#
#   vivado -mode batch -nojournal -source fpga/tcl/mul_ooc.tcl -tclargs <results_dir>    (make mul-ooc)

source [file join [file dirname [info script]] ooc_lib.tcl]

set out  [file normalize [lindex $argv 0]]
set srcs {rtl/core/booth_r4_mul8.sv rtl/core/mul8.sv fpga/ooc/mul8_ooc.sv}
# {PE_TYPE SUM_STYLE L_MUL synth_options}. LUT_INFERRED pipelines a*w only at its output, so without
# retiming its registers cannot move into the multiplier; the retiming row is the fair pipelined baseline.
set configs {
    {LUT_CUSTOM   ADDER 0 {}} {LUT_CUSTOM   ADDER 2 {}}
    {LUT_CUSTOM   CSA42 0 {}} {LUT_CUSTOM   CSA42 2 {}}
    {LUT_INFERRED ADDER 0 {}} {LUT_INFERRED ADDER 2 {}} {LUT_INFERRED ADDER 2 {-global_retiming on}}
}

file mkdir $out
set csv [open $out/summary.csv w]
header $csv
# lut/ff/carry4/logic_levels are measured at 100 MHz; fmax by the search in ooc_lib.tcl
puts $csv "pe_type,sum_style,l_mul,synth_opts,lut,ff,carry4,dsp,logic_levels,wns_100mhz_ns,fmax_mhz,wns_at_fmax_ns,fmax_est_mhz"
foreach cfg $configs {
    lassign $cfg pe style lmul opts
    set dir $out/${pe}_${style}_L$lmul[expr {$opts eq "" ? "" : "_retiming"}]
    set r [measure mul8_ooc $srcs [list PE_TYPE $pe SUM_STYLE $style L_MUL $lmul] $opts $dir {u_mul}]
    lassign [dict get $r util u_mul] lut ff
    set row [join [list $pe $style $lmul $opts $lut $ff [dict get $r carry4] [dict get $r dsp] \
        [dict get $r levels] [dict get $r wns_100] [dict get $r fmax] [dict get $r wns_fmax] [dict get $r fmax_est]] ,]
    puts $csv $row
    flush $csv
    puts "RESULT $row"
}
close $csv
