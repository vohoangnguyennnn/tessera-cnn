// agu: the loop nest of spec 5.1 as nested counters (spec 6.5).
// After a `start` pulse it emits one tick per cycle, with no bubbles, in the order
// g -> oy -> ox -> ky -> kx -> c, exactly the sequence of model/agu_ref.py (checked by L2).
// Outputs are registered and qualified by `valid`; `done` is high with the op's final tick.
// `d` must stay stable while `busy` (the controller holds the current descriptor).
module agu import acc_pkg::*; #(
    parameter int P = 8  // lanes: output channel of lane p in group g = g*P + p
) (
    input logic clk,
    input logic rst,
    input logic start,
    /* verilator lint_off UNUSEDSIGNAL */  // banks, flags and requant fields are for other units
    input desc_t d,
    /* verilator lint_on UNUSEDSIGNAL */
    output logic busy,
    output logic valid,
    output logic [4:0] g,
    output logic [ACT_AW-1:0] act_addr,  // meaningful only when in_bounds
    output logic in_bounds,  // 0: padding, the activation is replaced by 0
    output logic [W_AW-1:0] w_addr,
    output logic first,  // first tick of an output pixel
    output logic last,  // last tick of an output pixel
    output logic [ACT_AW-1:0] wr_addr,  // output word holding channel g*P
    output logic done
);
    // loop counters
    logic run;
    logic [4:0] cg;
    logic [4:0] coy, cox;
    logic [2:0] cky, ckx, cc;
    logic [9:0] pix;  // output pixel index inside the group: oy*Wout + ox
    logic [W_AW-1:0] w_g, w_off;  // weight base of the group, offset inside the pixel

    logic [4:0] wo_max;
    logic [2:0] k_max, c_max;
    logic c_last, kx_last, ky_last, px_last, ox_last, oy_last, g_last, final_tick;
    assign wo_max = 5'((1 << d.log2_wout) - 1);
    assign k_max = 3'(d.k - 4'd1);
    assign c_max = 3'((1 << d.log2_c8in) - 1);
    assign c_last = cc == c_max;
    assign kx_last = ckx == k_max;
    assign ky_last = cky == k_max;
    assign px_last = c_last && kx_last && ky_last;  // last tick of the current output pixel
    assign ox_last = cox == wo_max;
    assign oy_last = coy == wo_max;
    assign g_last = cg == d.groups - 5'd1;
    assign final_tick = px_last && ox_last && oy_last && g_last;

    // weights per group: C8 when shared (fc), K*K*C8 otherwise (small constant-size product)
    (* use_dsp = "no" *) logic [W_AW-1:0] per_g;
    assign per_g = d.w_shared ? W_AW'(1 << d.log2_c8in) : W_AW'((d.k * d.k) << d.log2_c8in);

    always_ff @(posedge clk) begin
        if (rst) begin
            run <= 1'b0;
        end else if (start) begin
            run <= 1'b1;
            {cg, coy, cox, cky, ckx, cc, pix, w_off} <= '0;
            w_g <= d.w_base;
        end else if (run) begin
            w_off <= px_last ? '0 : w_off + 1'b1;
            if (!c_last) cc <= cc + 1'b1;
            else begin
                cc <= '0;
                if (!kx_last) ckx <= ckx + 1'b1;
                else begin
                    ckx <= '0;
                    if (!ky_last) cky <= cky + 1'b1;
                    else begin  // output pixel done
                        cky <= '0;
                        pix <= pix + 1'b1;
                        if (!ox_last) cox <= cox + 1'b1;
                        else begin
                            cox <= '0;
                            if (!oy_last) coy <= coy + 1'b1;
                            else begin  // group done
                                coy <= '0;
                                pix <= '0;
                                w_g <= w_g + per_g;
                                if (g_last) run <= 1'b0;
                                else cg <= cg + 1'b1;
                            end
                        end
                    end
                end
            end
        end
    end
    assign busy = run;

    // tick from the counters
    logic signed [7:0] iy, ix;  // -1 .. 69
    logic [ACT_AW-1:0] act_c, wr_c;
    logic inb_c;
    assign iy = 8'(coy << (d.stride - 2'd1)) + 8'(cky) - 8'(d.pad);
    assign ix = 8'(cox << (d.stride - 2'd1)) + 8'(ckx) - 8'(d.pad);
    assign inb_c = iy >= 0 && ix >= 0 && iy < (8'sd1 <<< d.log2_win) && ix < (8'sd1 <<< d.log2_win);
    // two's complement wrap-around in 11 bits = agu_ref's "% 2048" for out-of-bounds pixels
    assign act_c = ((((ACT_AW'(iy) << d.log2_win) + ACT_AW'(ix)) << d.log2_c8in) + ACT_AW'(cc));
    assign wr_c = (ACT_AW'(pix) << d.log2_c8out) + ACT_AW'((32'(cg) * P) >> 3);

    always_ff @(posedge clk) begin
        if (rst) begin
            valid <= 1'b0;
            done <= 1'b0;
        end else begin
            valid <= run;
            done <= run && final_tick;
        end
        g <= cg;
        act_addr <= act_c;
        in_bounds <= inb_c;
        w_addr <= w_g + (d.w_shared ? W_AW'(cc) : w_off);
        first <= run && cc == '0 && ckx == '0 && cky == '0;
        last <= run && px_last;
        wr_addr <= wr_c;
    end
endmodule
