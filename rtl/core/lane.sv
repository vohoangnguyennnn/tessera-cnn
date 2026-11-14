// lane: one output channel = dot8 + accumulator + post-processing (spec 6.2, arithmetic spec 4.4).
//
// Timing contract (fixed latency, no handshake, spec 6):
//   cycle c         : a, w of one chunk (8 input channels at one input pixel)
//   cycle c + L_DOT : first/last/bias/M/n/r describing that same chunk. The caller (pe_array) delays
//                     these once for all P lanes, which is cheaper than delaying them inside each lane.
//   last + L_POST   : y, y_valid for the finished output pixel.
// res_en, relu_en, m_r, n_r are constant for a whole op: the controller drains between ops (6.6).
//
// Post-processing, in the order of spec 4.4, one register per stage:
//   S0 capture t = acc + sum     S1 t*M, r*M_r      S2 + 2^(n-1), >>> n (both paths)
//   S3 clamp16 -> y_main, y_res  S4 clamp8(y_main + y_res)   S5 ReLU -> y
module lane #(
    parameter string PE_TYPE = "LUT_CUSTOM",
    parameter string SUM_STYLE = "ADDER",
    parameter int L_MUL = 2,
    parameter bit RQ_USE_DSP = 0  // only 0 (requant in LUTs, 0 DSP) is implemented
) (
    input logic clk,
    input logic rst,  // synchronous, active high: valid pipeline only
    input logic [63:0] a,
    input logic [63:0] w,
    input logic first,  // first chunk of an output pixel: acc starts at bias
    input logic last,  // last chunk: acc + sum goes to post-processing
    input logic signed [31:0] bias,  // used when first
    input logic [15:0] M,  // used when last; M in [2^15, 2^16)
    input logic [5:0] n,  // used when last; 1 <= n <= 47 (spec 4.4, v1.1)
    input logic signed [7:0] r,  // residual byte at the same (y, x, co), used when last
    input logic res_en,
    input logic relu_en,
    input logic [15:0] m_r,
    input logic [5:0] n_r,
    output logic signed [7:0] y,
    output logic y_valid
);
    localparam int L_POST = 6;  // (L_DOT = L_MUL + 3 is the dot8 latency the caller aligns to)

    if (RQ_USE_DSP) begin : g_bad_dsp
        $error("lane: RQ_USE_DSP = 1 is not implemented (all configurations use 0, spec 2)");
    end

    function automatic logic signed [15:0] clamp16(input logic signed [47:0] x);
        if (x > 48'sd32767) return 16'sd32767;
        if (x < -48'sd32768) return -16'sd32768;
        return x[15:0];
    endfunction

    // dot product and accumulator
    logic signed [18:0] sum;
    dot8 #(.PE_TYPE(PE_TYPE), .SUM_STYLE(SUM_STYLE), .L_MUL(L_MUL)) u_dot (.clk, .a, .w, .sum);

    logic signed [31:0] acc, acc_next;
    assign acc_next = (first ? bias : acc) + 32'(sum);
    always_ff @(posedge clk) acc <= acc_next;

`ifndef SYNTHESIS
    // every widths choice below relies on |acc| < 2^30 at the end of a pixel (spec 4.3 and 10)
    always_ff @(posedge clk) if (!rst && last)
        assert (acc_next < 32'sd1073741824 && acc_next > -32'sd1073741824)
            else $error("lane: |acc| = %0d >= 2^30", acc_next);
`endif

    // post-processing (datapath registers without reset)
    // Widths are the exact bounds of spec 4.4 arithmetic, so results stay bit-exact with golden.rq:
    //   |t| < 2^30 -> 31 bits;  |t*M| < 2^46 -> 47 bits;  + 2^(n-1) with n <= 47 -> 48 bits.
    //   |r*M_r| <= 128 * 65535 < 2^23 -> 24 bits (+1 for rounding); any n_r >= 24 gives 0, and for
    //   n_r >= 25 the rounding bit 2^(n_r-1) would not even fit in 25 bits, so that case is forced to 0.
    logic signed [30:0] t0;  // S0
    logic [15:0] M0;
    logic [5:0] n0, n1;
    logic signed [7:0] r0;
    (* use_dsp = "no" *) logic signed [46:0] p1;  // S1: 31 x 17 signed
    (* use_dsp = "no" *) logic signed [23:0] q1;  // S1: 8 x 17 signed
    logic signed [47:0] p2;  // S2
    logic signed [24:0] q2;
    logic signed [15:0] y_main3, y_res3;  // S3
    logic signed [7:0] z4;  // S4
    logic signed [16:0] s3;

    always_ff @(posedge clk) begin
        if (last) begin
            t0 <= acc_next[30:0];
            M0 <= M;
            n0 <= n;
            r0 <= r;
        end
        p1 <= t0 * $signed({1'b0, M0});
        q1 <= r0 * $signed({1'b0, m_r});
        n1 <= n0;
        p2 <= (48'(p1) + (48'sd1 <<< (n1 - 6'd1))) >>> n1;
        q2 <= (n_r >= 6'd25) ? 25'sd0 : (25'(q1) + (25'sd1 <<< (n_r - 6'd1))) >>> n_r;
        y_main3 <= clamp16(p2);
        y_res3 <= res_en ? clamp16(48'(q2)) : 16'sd0;
        z4 <= (s3 > 17'sd127) ? 8'sd127 : (s3 < -17'sd128) ? -8'sd128 : s3[7:0];
        y <= (relu_en && z4[7]) ? 8'sd0 : z4;
    end
    assign s3 = y_main3 + y_res3;

    // valid tag, travelling with the data
    logic [L_POST-1:0] v;
    always_ff @(posedge clk) begin
        if (rst) v <= '0;
        else v <= {v[L_POST-2:0], last};
    end
    assign y_valid = v[L_POST-1];
endmodule
