// accel: the accelerator core = controller + AGU + memories + PE array, plus the host port of the
// activation banks (spec 5, 6). top.sv adds the clock, reset synchronizer, UART and host_if around it.
// While !busy the host owns act_mem (load the image into bank 0, read the logits, dump any bank).
module accel import acc_pkg::*; #(
    parameter string PE_TYPE = "LUT_CUSTOM",
    parameter string SUM_STYLE = "ADDER",
    parameter int L_MUL = 2,
    parameter int P = 8,
    parameter int D_W = 1226,
    parameter int D_Q = 44,
    parameter string HEX_DIR = "model/export/P8"
) (
    input logic clk,
    input logic rst,
    input logic start,
    input logic [3:0] first_op,
    input logic [3:0] stop_after_op,
    output logic busy,
    output logic done,
    output logic [31:0] cycles,
    input logic [1:0] host_bank,
    input logic [ACT_AW-1:0] host_addr,
    input logic host_we,
    input logic [7:0] host_be,
    input logic [63:0] host_wdata,
    output logic [63:0] host_rdata
);
    desc_t d;
    logic agu_start, agu_done, pipe_busy;
    controller #(.P(P), .D_W(D_W), .HEX_DIR(HEX_DIR)) u_ctrl (
        .clk, .rst, .start, .first_op, .stop_after_op, .d, .agu_start, .agu_done, .pipe_busy, .busy, .done, .cycles);

    logic t_valid, t_inb, t_first, t_last;
    logic [4:0] t_g;
    logic [ACT_AW-1:0] t_act, t_wr;
    logic [W_AW-1:0] t_w;
    /* verilator lint_off PINCONNECTEMPTY */
    agu #(.P(P)) u_agu (
        .clk, .rst, .start(agu_start), .d, .busy(), .valid(t_valid), .g(t_g), .act_addr(t_act),
        .in_bounds(t_inb), .w_addr(t_w), .first(t_first), .last(t_last), .wr_addr(t_wr), .done(agu_done));
    /* verilator lint_on PINCONNECTEMPTY */

    logic [63:0] act, res_data, wr_data;
    logic [P-1:0][63:0] wgt;
    logic [ACT_AW-1:0] res_addr, wr_addr;
    logic wr_en;
    logic [7:0] wr_be;
    act_mem u_act (
        .clk, .in_bank(d.in_bank), .res_bank(d.res_bank), .out_bank(d.out_bank),
        .rd_addr(t_act), .rd_data(act), .res_addr, .res_data, .wr_en, .wr_addr, .wr_be, .wr_data,
        .host_sel(!busy), .host_bank, .host_addr, .host_we, .host_be, .host_wdata, .host_rdata);
    wgt_mem #(.P(P), .D_W(D_W), .HEX_DIR(HEX_DIR)) u_wgt (.clk, .addr(t_w), .w(wgt));

    logic [Q_AW-1:0] q_addr;
    logic signed [31:0] q_bias [P];
    logic [15:0] q_M [P];
    logic [5:0] q_n [P];
    qparam_mem #(.P(P), .D_Q(D_Q), .HEX_DIR(HEX_DIR)) u_q (.clk, .addr(q_addr), .bias(q_bias), .M(q_M), .n(q_n));

    pe_array #(.PE_TYPE(PE_TYPE), .SUM_STYLE(SUM_STYLE), .L_MUL(L_MUL), .P(P)) u_pe (
        .clk, .rst, .d, .t_valid, .t_g, .t_inb, .t_first, .t_last, .t_wr, .act, .wgt,
        .q_addr, .q_bias, .q_M, .q_n, .res_addr, .res_data, .wr_en, .wr_addr, .wr_be, .wr_data,
        .busy(pipe_busy));
endmodule
