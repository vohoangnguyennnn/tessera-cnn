# Shared out-of-context flow for the M2 mini-experiments (spec 12.0): synth + place + route one
# harness (registers on all inputs/outputs) on the project part, then search for Fmax.
#
# Fmax (spec 11.3): one run at an aggressive 2.0 ns target gives Fmax_est = 1 / (T - WNS); then the
# target starts at floor(Fmax_est) rounded down to 10 MHz and drops 10 MHz at a time until WNS >= 0.
# Reported Fmax = highest target that met timing; Fmax_est is kept only as a reference.

set part xc7a35tfgg484-2
set root [file normalize [file join [file dirname [info script]] .. ..]]

proc util_of {inst} {
    # {total_luts ffs} of one instance (leaf name as printed), from the hierarchical utilization table
    set cols {}
    foreach l [split [report_utilization -hierarchical -return_string] "\n"] {
        set c [lmap x [split $l |] {string trim $x}]
        if {[lsearch $c "Total LUTs"] >= 0} { set cols $c }
        if {[llength $cols] && [lindex $c 1] eq $inst} {
            return [list [lindex $c [lsearch $cols "Total LUTs"]] [lindex $c [lsearch $cols "FFs"]]]
        }
    }
    error "instance $inst not found in report_utilization -hierarchical"
}

# generics: {name value ...}; string values are quoted for Verilog string parameters.
proc implement {top srcs generics opts period rpt_dir insts} {
    global part root
    create_project -in_memory -part $part
    foreach f $srcs { read_verilog -sv [file join $root $f] }
    # the clock must be known before synth_design: synthesis is timing driven, and retiming needs it
    file mkdir $rpt_dir
    set xdc [open $rpt_dir/clk.xdc w]
    puts $xdc "create_clock -name clk -period $period \[get_ports clk\]"
    close $xdc
    read_xdc $rpt_dir/clk.xdc
    set gargs {}
    foreach {k v} $generics {
        lappend gargs -generic [expr {[string is integer -strict $v] ? "$k=$v" : "$k=\"$v\""}]
    }
    synth_design -mode out_of_context -top $top -part $part {*}$gargs {*}$opts
    opt_design
    place_design
    route_design
    set path [lindex [get_timing_paths -setup -max_paths 1] 0]
    set r [dict create wns [get_property SLACK $path] levels [get_property LOGIC_LEVELS $path] \
        path_end [get_property NAME [get_property ENDPOINT_PIN $path]] \
        dsp [llength [get_cells -hier -filter {REF_NAME =~ DSP48*}]] \
        carry4 [llength [get_cells -hier -filter "REF_NAME == CARRY4 && NAME =~ [lindex $insts 0]/*"]]]
    foreach i $insts { dict set r util $i [util_of $i] }
    report_utilization -hierarchical -file $rpt_dir/util_hier.rpt
    report_timing_summary -file $rpt_dir/timing_summary.rpt
    report_timing -max_paths 10 -file $rpt_dir/timing_paths.rpt
    close_project
    return $r
}

proc fmax_search {top srcs generics opts rpt_dir insts} {
    set probe [implement $top $srcs $generics $opts 2.000 $rpt_dir $insts]
    set est [expr {1000.0 / (2.0 - [dict get $probe wns])}]
    set f [expr {int($est / 10) * 10}]
    while {1} {
        set r [implement $top $srcs $generics $opts [format %.3f [expr {1000.0 / $f}]] $rpt_dir $insts]
        if {[dict get $r wns] >= 0} break
        incr f -10
    }
    return [dict merge $r [dict create fmax $f fmax_est [format %.0f $est]]]
}

proc header {csv} {
    global root part
    puts $csv "# vivado [version -short], part $part, git [exec git -C $root describe --always --dirty]"
}

# Area and logic levels at the accelerator's real 100 MHz target (LUT counts depend on the clock
# constraint: synthesis trades area for speed), plus the separate Fmax search.
proc measure {top srcs generics opts rpt_dir insts} {
    set u [implement $top $srcs $generics $opts 10.000 $rpt_dir/at_100mhz $insts]
    set f [fmax_search $top $srcs $generics $opts $rpt_dir/at_fmax $insts]
    return [dict merge $u [dict create wns_100 [dict get $u wns] fmax [dict get $f fmax] \
        wns_fmax [dict get $f wns] fmax_est [dict get $f fmax_est] path_end_fmax [dict get $f path_end]]]
}
