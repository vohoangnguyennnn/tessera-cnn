// pe_array: P lanes sharing one broadcast activation word, plus the control tags that travel next to
// the data (spec 5, 6, 6.7). Lane p of group g computes output channel co = g*P + p.
//
// Fixed-latency schedule, t = cycle of an AGU tick on its (registered) outputs:
//   t + 2         act_mem / wgt_mem data (read latency 2)
//   t + L_IN      broadcast register: lanes see a (zeroed when out of bounds) and w     L_IN = 3
//   t + L_CTL     lanes see first/last/bias/M/n/r of that tick                           L_CTL = L_IN + L_DOT
//   t + L_WR      y of the pixel whose last tick was t; written to act_mem               L_WR = L_CTL + L_POST
// NW = ceil(P/8) words per output pixel: P = 16 reads its residual and writes its output as two words
// on two consecutive cycles, which always fits because every pixel lasts R >= 2 cycles (spec 5.4).
// P = 4 writes half a word with the byte enable.
module pe_array import acc_pkg::*; #(
    parameter string PE_TYPE = "LUT_CUSTOM",
    parameter string SUM_STYLE = "ADDER",
    parameter int L_MUL = 2,
    parameter int P = 8
) (
    input logic clk,
    input logic rst,
    /* verilator lint_off UNUSEDSIGNAL */  // geometry and bank fields are for the AGU / act_mem
    input desc_t d,
    /* verilator lint_on UNUSEDSIGNAL */
    // AGU tick
    input logic t_valid,
    input logic [4:0] t_g,
    input logic t_inb,
    input logic t_first,
    input logic t_last,
    input logic [ACT_AW-1:0] t_wr,
    // memory data, 2 cycles after the tick
    input logic [63:0] act,
    input logic [P-1:0][63:0] wgt,
    // q-param ROM (latency 1)
    output logic [Q_AW-1:0] q_addr,
    input logic signed [31:0] q_bias [P],
    input logic [15:0] q_M [P],
    input logic [5:0] q_n [P],
    // residual read port of act_mem (latency 2)
    output logic [ACT_AW-1:0] res_addr,
    input logic [63:0] res_data,
    // output write port of act_mem
    output logic wr_en,
    output logic [ACT_AW-1:0] wr_addr,
    output logic [7:0] wr_be,
    output logic [63:0] wr_data,
    output logic busy  // a tick or its result is still in the pipeline
);
    localparam int L_DOT = L_MUL + 3;
    localparam int L_IN = 3;
    localparam int L_CTL = L_IN + L_DOT;
    localparam int L_POST = 6;
    localparam int L_WR = L_CTL + L_POST;
    localparam int NW = (P + 7) / 8;
    localparam int DEPTH = L_WR + NW - 1;

    // control tags: tag[k] is the tick of k cycles ago
    typedef struct packed {
        logic v, first, last;
        logic [4:0] g;
        logic [ACT_AW-1:0] wr;
    } tag_t;
    tag_t tag [DEPTH+1];
    assign tag[0] = '{v: t_valid, first: t_valid && t_first, last: t_valid && t_last, g: t_g, wr: t_wr};
    always_ff @(posedge clk) begin
        for (int k = 1; k <= DEPTH; k++) tag[k] <= rst ? '0 : tag[k-1];
    end
    always_comb begin
        busy = 1'b0;
        for (int k = 0; k <= DEPTH; k++) busy |= tag[k].v;
    end

    // broadcast register (spec 6.7): out-of-bounds activations become 0 (padding)
    logic [1:0] inb_d;
    logic [63:0] a_q;
    logic [P-1:0][63:0] w_q;
    always_ff @(posedge clk) begin
        inb_d <= {inb_d[0], t_inb};
        a_q <= inb_d[1] ? act : '0;
        w_q <= wgt;
    end

    // q-params: read one cycle ahead so they arrive with the lane's control
    assign q_addr = d.q_base + Q_AW'(tag[L_CTL-1].g);

    // residual: word j of a pixel is read 2 cycles before it is needed -
    logic [63:0] res_hold;  // word 0 when NW = 2
    if (NW == 1) begin : g_res1
        assign res_addr = tag[L_CTL-2].wr;
        assign res_hold = '0;
    end else begin : g_res2
        assign res_addr = tag[L_CTL-2].last ? tag[L_CTL-2].wr + 1'b1 : tag[L_CTL-3].wr;
        always_ff @(posedge clk) if (tag[L_CTL-1].last) res_hold <= res_data;
    end
    // byte offset of channel g*P inside its word: non-zero only for P = 4 (odd groups use bytes 4..7)
    logic [2:0] boff_ctl, boff_wr;
    assign boff_ctl = 3'((32'(tag[L_CTL].g) * P) % 8);
    assign boff_wr = 3'((32'(tag[L_WR].g) * P) % 8);

    // lanes
    logic signed [7:0] y [P];
    logic y_valid [P];
    for (genvar p = 0; p < P; p++) begin : g_lane
        logic [63:0] rw;
        logic [2:0] rb;
        assign rw = (NW == 2 && p < 8) ? res_hold : res_data;
        assign rb = 3'(boff_ctl + 3'(p % 8));
        lane #(.PE_TYPE(PE_TYPE), .SUM_STYLE(SUM_STYLE), .L_MUL(L_MUL)) u_lane (
            .clk, .rst, .a(a_q), .w(w_q[p]),
            .first(tag[L_CTL].first), .last(tag[L_CTL].last),
            .bias(q_bias[p]), .M(q_M[p]), .n(q_n[p]), .r(rw[8*rb +: 8]),
            .res_en(d.res_en), .relu_en(d.relu_en), .m_r(d.m_r), .n_r(d.n_r),
            .y(y[p]), .y_valid(y_valid[p]));
    end

    // write back: NW words, byte enables for P = 4
    logic [63:0] word0;
    always_comb begin
        word0 = '0;
        for (int p = 0; p < P && p < 8; p++) word0[8*(int'(boff_wr) + p) +: 8] = y[p];
    end
    if (NW == 1) begin : g_wr1
        assign wr_en = tag[L_WR].last;
        assign wr_addr = tag[L_WR].wr;
        assign wr_be = (P >= 8) ? 8'hFF : 8'((1 << P) - 1) << boff_wr;
        assign wr_data = word0;
    end else begin : g_wr2
        logic [63:0] word1_q;  // lanes 8..15, written one cycle after lanes 0..7
        always_ff @(posedge clk) begin
            for (int p = 8; p < P; p++) word1_q[8*(p-8) +: 8] <= y[p];
        end
        assign wr_en = tag[L_WR].last || tag[L_WR+1].last;
        assign wr_addr = tag[L_WR+1].last ? tag[L_WR+1].wr + 1'b1 : tag[L_WR].wr;
        assign wr_be = 8'hFF;
        assign wr_data = tag[L_WR+1].last ? word1_q : word0;
    end

`ifndef SYNTHESIS
    // the control tags and the lanes' own valid pipelines must agree (fixed-latency design, spec 6)
    always_ff @(posedge clk) if (!rst)
        assert (y_valid[0] == tag[L_WR].last) else $error("pe_array: lane y_valid and tag disagree");
`endif
endmodule
