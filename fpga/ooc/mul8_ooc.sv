// Out-of-context harness for the multiplier experiment (spec 12.0).
// Registers on every input and output, so timing sees only reg -> mul8 -> reg paths, and the
// utilization of u_mul (kept as its own hierarchy) is the multiplier alone.
module mul8_ooc #(
    parameter string PE_TYPE = "LUT_CUSTOM",
    parameter string SUM_STYLE = "ADDER",
    parameter int L_MUL = 2
) (
    input logic clk,
    input logic [7:0] a,
    input logic [7:0] w,
    output logic [15:0] p
);
    logic signed [7:0] a_q, w_q;
    logic signed [15:0] p_d;
    always_ff @(posedge clk) begin
        a_q <= a;
        w_q <= w;
        p <= p_d;
    end
    (* keep_hierarchy = "yes" *)
    mul8 #(.PE_TYPE(PE_TYPE), .SUM_STYLE(SUM_STYLE), .L_MUL(L_MUL)) u_mul (.clk, .a(a_q), .w(w_q), .p(p_d));
endmodule
