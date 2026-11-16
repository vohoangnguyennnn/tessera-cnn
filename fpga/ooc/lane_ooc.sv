// Out-of-context harness for one lane (M2: "synth OOC lane, confirm 0 DSP").
// Registers on every input and output so all timed paths are reg -> lane -> reg; u_lane is kept as
// its own hierarchy so its utilization excludes the harness.
module lane_ooc #(
    parameter string PE_TYPE = "LUT_CUSTOM",
    parameter string SUM_STYLE = "ADDER",
    parameter int L_MUL = 2
) (
    input logic clk,
    input logic rst,
    input logic [63:0] a,
    input logic [63:0] w,
    input logic first,
    input logic last,
    input logic signed [31:0] bias,
    input logic [15:0] M,
    input logic [5:0] n,
    input logic signed [7:0] r,
    input logic res_en,
    input logic relu_en,
    input logic [15:0] m_r,
    input logic [5:0] n_r,
    output logic signed [7:0] y,
    output logic y_valid
);
    logic rst_q, first_q, last_q, res_en_q, relu_en_q, y_valid_d;
    logic [63:0] a_q, w_q;
    logic signed [31:0] bias_q;
    logic [15:0] M_q, m_r_q;
    logic [5:0] n_q, n_r_q;
    logic signed [7:0] r_q, y_d;
    always_ff @(posedge clk) begin
        {rst_q, first_q, last_q, res_en_q, relu_en_q} <= {rst, first, last, res_en, relu_en};
        {a_q, w_q, bias_q, M_q, m_r_q, n_q, n_r_q, r_q} <= {a, w, bias, M, m_r, n, n_r, r};
        {y, y_valid} <= {y_d, y_valid_d};
    end
    (* keep_hierarchy = "yes" *)
    lane #(.PE_TYPE(PE_TYPE), .SUM_STYLE(SUM_STYLE), .L_MUL(L_MUL)) u_lane (
        .clk, .rst(rst_q), .a(a_q), .w(w_q), .first(first_q), .last(last_q), .bias(bias_q), .M(M_q),
        .n(n_q), .r(r_q), .res_en(res_en_q), .relu_en(relu_en_q), .m_r(m_r_q), .n_r(n_r_q),
        .y(y_d), .y_valid(y_valid_d));
endmodule
