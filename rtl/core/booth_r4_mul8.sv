// booth_r4_mul8: hand-designed radix-4 Booth multiplier, signed INT8 x INT8 -> 16 bit (spec 6.1).
// model/booth_ref.py implements the same stages with the same signal names, including the dot diagram.
//
//   1. Encoder   : per group i = 0..3 of (w[2i+1], w[2i], w[2i-1]), w[-1] = 0: one, two, neg
//   2. Rows      : r[i][j] = ((one & a[j]) | (two & a[j-1])) ^ neg, j = 0..8, a[-1] = 0, a[8] = a[7]
//   3. Placement : 16-bit words R0..R3 plus a lone bit e = neg[3] << 6; sign extension is replaced
//                  by the constants {~s, s, s} / {1, ~s} (s = r[i][8])
//   4. Sum       : ADDER  p = (R0 + R1) + (R2 + R3 + e)
//                  CSA42  one row of 4:2 compressors -> S, C; p = S + C + e (e does not fit the row)
//   5. Pipeline  : L_MUL = 0 combinational; L_MUL = 2 registers after step 3 and after the first sum level
//
// keep_hierarchy keeps this module separate in report_utilization -hierarchical.
(* keep_hierarchy = "yes" *)
module booth_r4_mul8 #(
    parameter string SUM_STYLE = "ADDER",  // "ADDER" | "CSA42"
    parameter int L_MUL = 2  // supported: 0, 2
) (
    input logic clk,
    input logic signed [7:0] a,  // activation
    input logic signed [7:0] w,  // weight
    output logic signed [15:0] p  // a * w, L_MUL cycles later
);
    if (L_MUL != 0 && L_MUL != 2) begin : g_bad_lmul
        $error("booth_r4_mul8: L_MUL = %0d not supported (use 0 or 2)", L_MUL);
    end
    if (SUM_STYLE != "ADDER" && SUM_STYLE != "CSA42") begin : g_bad_style
        $error("booth_r4_mul8: unknown SUM_STYLE %s", SUM_STYLE);
    end

    // 1. Booth encoder
    logic [8:0] wx;  // wx[k+1] = w[k]; wx[0] = w[-1] = 0
    logic [3:0] one, two, neg;
    assign wx = {w, 1'b0};
    for (genvar i = 0; i < 4; i++) begin : g_enc
        logic b2, b1, b0;  // (w[2i+1], w[2i], w[2i-1])
        assign {b2, b1, b0} = wx[2*i+2 -: 3];
        assign one[i] = b1 ^ b0;
        assign two[i] = (b2 & ~b1 & ~b0) | (~b2 & b1 & b0);
        assign neg[i] = b2;
    end

    // 2. PP generator: 9-bit rows
    logic [9:0] ax;  // ax[j+1] = a[j] for j = -1..8: a[-1] = 0, a[8] = a[7]
    logic [8:0] r [4];
    assign ax = {a[7], a, 1'b0};
    for (genvar i = 0; i < 4; i++) begin : g_pp
        assign r[i] = (({9{one[i]}} & ax[9:1]) | ({9{two[i]}} & ax[8:0])) ^ {9{neg[i]}};
    end

    // 3. Placement at absolute columns (dot diagram in model/booth_ref.py)
    logic [15:0] R0, R1, R2, R3, e;
    assign R0 = {5'b0, ~r[0][8], r[0][8], r[0][8], r[0][7:0]};
    assign R1 = {4'b0, 1'b1, ~r[1][8], r[1][7:0], 1'b0, neg[0]};
    assign R2 = {2'b0, 1'b1, ~r[2][8], r[2][7:0], 1'b0, neg[1], 2'b0};
    assign R3 = {1'b1, ~r[3][8], r[3][7:0], 1'b0, neg[2], 4'b0};
    assign e = {9'b0, neg[3], 6'b0};

    // 4. first summation level: leaves two rows u, v and an extra term f for the final add
    logic [15:0] R0_s, R1_s, R2_s, R3_s, e_s;  // stage-3 outputs, registered when L_MUL = 2
    logic [15:0] u, v, f, u_s, v_s, f_s;  // stage-4 outputs, registered when L_MUL = 2
    if (SUM_STYLE == "ADDER") begin : g_adder
        logic [15:0] s01, s23;
        assign s01 = R0_s + R1_s;
        assign s23 = R2_s + R3_s + e_s;
        assign {u, v, f} = {s01, s23, 16'b0};
    end else begin : g_csa42
        logic [15:0] S, C, cin;  // cin[c] = cout of column c-1 (bit 0: none)
        assign cin[0] = 1'b0;
        assign C[0] = 1'b0;
        for (genvar c = 0; c < 16; c++) begin : g_col
            logic s1;  // 4:2 compressor = two full adders
            assign s1 = R0_s[c] ^ R1_s[c] ^ R2_s[c];
            assign S[c] = s1 ^ R3_s[c] ^ cin[c];
            if (c < 15) begin : g_up  // column 15's carry and cout fall off the product
                assign cin[c+1] = (R0_s[c] & R1_s[c]) | (R0_s[c] & R2_s[c]) | (R1_s[c] & R2_s[c]);
                assign C[c+1] = (s1 & R3_s[c]) | (s1 & cin[c]) | (R3_s[c] & cin[c]);
            end
        end
        assign {u, v, f} = {S, C, e_s};
    end

    // 5. pipeline cuts (datapath registers have no reset, spec 11.2) and final add
    if (L_MUL == 2) begin : g_pipe
        always_ff @(posedge clk) begin
            {R0_s, R1_s, R2_s, R3_s, e_s} <= {R0, R1, R2, R3, e};
            {u_s, v_s, f_s} <= {u, v, f};
        end
    end else begin : g_comb
        assign {R0_s, R1_s, R2_s, R3_s, e_s} = {R0, R1, R2, R3, e};
        assign {u_s, v_s, f_s} = {u, v, f};
    end
    assign p = u_s + v_s + f_s;

endmodule
