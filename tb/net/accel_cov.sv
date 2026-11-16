// Functional coverage of the accelerator core, XSim only (Verilator ignores covergroups: COVERIGN).
// Subset of docs/coverage_plan.md: CG_CTRL, CG_OP (4.1, 4.2), CG_AGU padding (4.3), CG_LANE SAT8/RELU (4.4).
// Attached with `bind` (module accel_cov_bind, elaborated as a second top): no RTL line changes.
// Report: make cov -> results/cov/ (xcrg).

// controller FSM, run start/end, and one sample per op descriptor
module ctrl_cov import acc_pkg::*; (
    input logic clk,
    input logic rst,
    input logic start,
    input logic done,
    input logic [2:0] state,  // controller state_t: IDLE, FETCH, START, RUN, DRAIN
    input logic [3:0] op,
    input logic [3:0] first_op,
    input desc_t d
);
    localparam logic [2:0] IDLE = 0, FETCH = 1, START = 2, RUN = 3, DRAIN = 4;

    // CG_CTRL (plan 4.1)
    covergroup cg_ctrl @(posedge clk iff !rst);
        cp_state: coverpoint state {
            bins idle = {IDLE}; bins fetch = {FETCH}; bins start = {START}; bins run = {RUN}; bins drain = {DRAIN};
        }
        cp_trans: coverpoint state {
            bins t1_idle_fetch = (IDLE => FETCH);
            bins t2_fetch_start_run = (FETCH => START => RUN);
            bins t3_run_drain = (RUN => DRAIN);
            bins t4_drain_wait = (DRAIN [*2]);  // pipe_busy really held the FSM in DRAIN
            bins t5_drain_fetch = (DRAIN => FETCH);
            bins t6_drain_idle = (DRAIN => IDLE);
        }
    endgroup

    // CTRL.T6/T7: which op a run ended on (done pulses the cycle after DRAIN => IDLE, op still holds it)
    covergroup cg_run_end @(posedge clk iff !rst && done);
        cp_last_op: coverpoint op {
            bins t6_after_last_op = {9};
            bins t7_stop_after_op = {[0:8]};  // early stop, the board debug mode (spec 8, 9)
        }
    endgroup

    // CTRL.T8: which op a run started from
    covergroup cg_run_start @(posedge clk iff !rst && state == IDLE && start);
        cp_first_op: coverpoint first_op {
            bins from_op0 = {0};
            bins t8_from_later_op = {[1:9]};
        }
    endgroup

    // CG_OP (plan 4.2): sampled once per op, at START like the descriptor SVA in controller.sv
    typedef enum logic [2:0] {CONV3_S1, CONV3_S2, CONV1_S2, FC, OTHER} kind_t;
    kind_t kind;
    always_comb begin
        if (d.w_shared && d.k == 8) kind = FC;
        else if (d.k == 3 && d.pad && d.stride == 1) kind = CONV3_S1;
        else if (d.k == 3 && d.pad && d.stride == 2) kind = CONV3_S2;
        else if (d.k == 1 && !d.pad && d.stride == 2) kind = CONV1_S2;
        else kind = OTHER;
    end

    covergroup cg_op @(posedge clk iff !rst && state == START);
        cp_op: coverpoint op { bins op[] = {[0:9]}; }
        cp_kind: coverpoint kind {
            bins conv3_s1 = {CONV3_S1}; bins conv3_s2 = {CONV3_S2}; bins conv1_s2 = {CONV1_S2}; bins fc = {FC};
            ignore_bins other = {OTHER};  // legal for the generic controller, not used by the ResNet-8 ROM
        }
        cp_res: coverpoint d.res_en;
        x_kind_res: cross cp_kind, cp_res {
            // residual add only follows a stride-1 3x3 conv in ResNet-8 (s1b, s2b, s3b; spec 7.2)
            ignore_bins res_not_in_rom = binsof(cp_kind) intersect {CONV3_S2, CONV1_S2, FC} && binsof(cp_res) intersect {1};
        }
    endgroup

    cg_ctrl cg_ctrl_i = new();
    cg_run_end cg_run_end_i = new();
    cg_run_start cg_run_start_i = new();
    cg_op cg_op_i = new();
endmodule

// CG_AGU (plan 4.3): where each tick's input pixel falls relative to the image, per stride.
// Sampled on the loop counters (iy/ix are combinational from them), not on the registered outputs,
// which are one cycle later. Data independent: one image hits every bin.
module agu_cov import acc_pkg::*; (
    input logic clk,
    input logic rst,
    input logic run,  // a tick is being generated this cycle
    input logic signed [7:0] iy,
    input logic signed [7:0] ix,
    input desc_t d
);
    typedef enum logic [1:0] {LOW_PAD, INSIDE, HIGH_PAD} side_t;  // LOW: -1, HIGH: >= Hin
    side_t row, col;
    logic signed [7:0] hin;
    assign hin = 8'sd1 <<< d.log2_win;  // Hin = Win
    assign row = iy < 0 ? LOW_PAD : iy >= hin ? HIGH_PAD : INSIDE;
    assign col = ix < 0 ? LOW_PAD : ix >= hin ? HIGH_PAD : INSIDE;

    covergroup cg_agu @(posedge clk iff !rst && run);
        cp_stride: coverpoint d.stride { bins s1 = {1}; bins s2 = {2}; }
        cp_row: coverpoint row { bins top = {LOW_PAD}; bins mid = {INSIDE}; bins bottom = {HIGH_PAD}; }
        cp_col: coverpoint col { bins left = {LOW_PAD}; bins mid = {INSIDE}; bins right = {HIGH_PAD}; }
        // 9 cells per stride: 4 corners, 4 edges, inside. Stride 2 (32 -> 16, k = 3, pad = 1) reads
        // iy = 2*oy + ky - 1 <= 2*15 + 2 - 1 = 31 < 32: it can never reach the bottom or right padding.
        // illegal, not ignore: if it ever happens the AGU is wrong, and ignore_bins would hide it.
        x_pad: cross cp_stride, cp_row, cp_col {
            illegal_bins s2_bottom_right = binsof(cp_stride.s2) && (binsof(cp_row.bottom) || binsof(cp_col.right));
        }
    endgroup
    cg_agu cg_agu_i = new();
endmodule

// CG_LANE lives in a package so that the 8 lanes share one covergroup type and its type coverage answers
// "did any lane saturate". Declared inside lane_cov, XSim reports one covergroup per module instance.
package lane_cov_pkg;
    covergroup cg_lane with function sample(bit v3, int s3, bit v4, bit [1:0] relu_z);
        // type coverage = union of the 8 lanes' bins; the default (0) is the average of their scores
        type_option.merge_instances = 1;
        cp_sat8: coverpoint s3 iff (v3) {
            bins sat_pos = {[128:65535]};  // clamped to +127
            bins sat_neg = {[-65536:-129]};  // clamped to -128
            bins in_range = {[-128:127]};
        }
        cp_relu: coverpoint relu_z iff (v4) {  // {relu_en, z4 < 0}
            bins relu_zeroed = {2'b11};  // ReLU really acted
            bins relu_pos = {2'b10};
            bins no_relu_neg = {2'b01};  // negative value passed through (shortcuts, fc)
            bins no_relu_pos = {2'b00};
        }
    endgroup
endpackage

// one lane's post-processing; each coverpoint samples the pipeline stage its value belongs to (plan 4.4)
module lane_cov (
    input logic clk,
    input logic rst,
    input logic [5:0] v,  // lane valid tags: v[k] = stage k+1 register holds a real pixel
    input logic signed [16:0] s3,  // y_main3 + y_res3, valid with v[3]
    input logic signed [7:0] z4,  // after clamp8, valid with v[4]
    input logic relu_en
);
    lane_cov_pkg::cg_lane cg = new();
    // unique instance names: with 8 instances all called "cg", xcrg mixes their counts when merging tests
    initial cg.set_inst_name($sformatf("%m"));
    always @(posedge clk) if (!rst) cg.sample(v[3], s3, v[4], {relu_en, z4[7]});
endmodule

module accel_cov_bind;
    bind controller ctrl_cov u_ctrl_cov (.clk, .rst, .start, .done, .state, .op, .first_op, .d);
    bind agu agu_cov u_agu_cov (.clk, .rst, .run, .iy, .ix, .d);
    bind lane lane_cov u_lane_cov (.clk, .rst, .v, .s3, .z4, .relu_en);
endmodule
