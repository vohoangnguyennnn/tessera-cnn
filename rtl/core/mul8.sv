// mul8: INT8 x INT8 multiplier wrapper (spec 6.1).
// Every PE_TYPE has the same ports and the same latency L_MUL, so switching the multiplier
// never touches dot8 or anything above it. DSP_INFERRED is added at M6.
module mul8 #(
    parameter string PE_TYPE = "LUT_CUSTOM",  // "LUT_CUSTOM" (booth_r4_mul8) | "LUT_INFERRED"
    parameter string SUM_STYLE = "ADDER",  // booth_r4_mul8 only: "ADDER" | "CSA42"
    parameter int L_MUL = 2  // latency in clock cycles, 0 = combinational
) (
    input logic clk,
    input logic signed [7:0] a,
    input logic signed [7:0] w,
    output logic signed [15:0] p
);
    if (PE_TYPE == "LUT_CUSTOM") begin : g_booth
        booth_r4_mul8 #(.SUM_STYLE(SUM_STYLE), .L_MUL(L_MUL)) u_mul (.clk, .a, .w, .p);

    end else if (PE_TYPE == "LUT_INFERRED") begin : g_lut
        (* use_dsp = "no" *) logic signed [15:0] prod;
        assign prod = a * w;
        if (L_MUL == 0) begin : g_comb
            assign p = prod;
        end else begin : g_pipe
            logic signed [15:0] pipe [L_MUL];
            always_ff @(posedge clk) begin
                pipe[0] <= prod;
                for (int i = 1; i < L_MUL; i++) pipe[i] <= pipe[i-1];
            end
            assign p = pipe[L_MUL-1];
        end

    end else begin : g_bad
        $error("mul8: unknown PE_TYPE %s", PE_TYPE);
    end
endmodule
