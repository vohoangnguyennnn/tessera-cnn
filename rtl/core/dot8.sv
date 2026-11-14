// dot8: sum = sum_i a_i * w_i over 8 INT8 pairs (spec 6.1).
// 8 x mul8 in parallel, then a 3-level adder tree 8 -> 4 -> 2 -> 1 with a register after each
// level. The tree is identical for every PE_TYPE, so configurations differ only in the multiplier.
// Latency L_DOT = L_MUL + 3. Datapath registers have no reset (spec 11.2).
module dot8 #(
    parameter string PE_TYPE = "LUT_CUSTOM",
    parameter string SUM_STYLE = "ADDER",
    parameter int L_MUL = 2
) (
    input logic clk,
    input logic [63:0] a,  // byte i (bits [8i+7:8i]) = activation of channel 8*c8 + i, signed
    input logic [63:0] w,  // byte i = weight for the same channel, signed
    output logic signed [18:0] sum  // |a_i * w_i| <= 2^14, so the sum of 8 fits in 19 bits signed
);
    logic signed [15:0] prod [8];
    for (genvar i = 0; i < 8; i++) begin : g_mul
        mul8 #(.PE_TYPE(PE_TYPE), .SUM_STYLE(SUM_STYLE), .L_MUL(L_MUL)) u_mul (
            .clk, .a(a[8*i +: 8]), .w(w[8*i +: 8]), .p(prod[i]));
    end

    logic signed [16:0] s1 [4];
    logic signed [17:0] s2 [2];
    always_ff @(posedge clk) begin
        for (int i = 0; i < 4; i++) s1[i] <= prod[2*i] + prod[2*i+1];
        for (int i = 0; i < 2; i++) s2[i] <= s1[2*i] + s1[2*i+1];
        sum <= s2[0] + s2[1];
    end
endmodule
