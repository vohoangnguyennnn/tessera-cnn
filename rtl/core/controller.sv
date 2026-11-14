// controller: runs the ops of the descriptor ROM (desc.hex from export.py) one after another (spec 6.6, 8).
//   IDLE -> FETCH (read descriptor) -> START (pulse the AGU) -> RUN (until the AGU's last tick)
//        -> DRAIN (until pe_array has written the op's last byte: the next op may read that bank)
//        -> FETCH of the next op, or back to IDLE with `done` after stop_after_op / the last op.
// The controller knows nothing about ResNet: changing the network is changing the ROM (spec 8).
// `cycles` counts every cycle from `start` to `done` (READ_CYCLES, spec 9).
module controller import acc_pkg::*; #(
    parameter int P = 8,
    parameter int D_W = 1226,
    parameter int N_OPS = 10,
    parameter string HEX_DIR = "model/export/P8"
) (
    input logic clk,
    input logic rst,
    input logic start,
    input logic [3:0] first_op,  // normally 0; L3 runs a single op k with first = stop = k
    input logic [3:0] stop_after_op,  // debug: stop after op k and let the host dump its bank
    output desc_t d,  // current descriptor, stable from FETCH to the end of DRAIN
    output logic agu_start,
    input logic agu_done,
    input logic pipe_busy,
    output logic busy,
    output logic done,  // one-cycle pulse
    output logic [31:0] cycles
);
    logic [DESC_BITS-1:0] rom [N_OPS];
    initial $readmemh($sformatf("%s/desc.hex", HEX_DIR), rom);

    typedef enum logic [2:0] {IDLE, FETCH, START, RUN, DRAIN} state_t;
    state_t state;
    logic [3:0] op;

    always_ff @(posedge clk) begin
        if (rst) begin
            state <= IDLE;
            done <= 1'b0;
        end else begin
            done <= 1'b0;
            case (state)
                IDLE: if (start) begin
                           op <= first_op;
                           cycles <= '0;
                           state <= FETCH;
                       end
                FETCH: begin
                           d <= rom[op];
                           state <= START;
                       end
                START: state <= RUN;
                RUN: if (agu_done) state <= DRAIN;
                DRAIN: if (!pipe_busy) begin
                           if (op == stop_after_op || op == 4'(N_OPS - 1)) begin
                               done <= 1'b1;
                               state <= IDLE;
                           end else begin
                               op <= op + 1'b1;
                               state <= FETCH;
                           end
                       end
                default: state <= IDLE;
            endcase
            if (state != IDLE) cycles <= cycles + 1'b1;
        end
    end
    assign agu_start = state == START;
    assign busy = state != IDLE;

`ifndef SYNTHESIS
    // descriptor checks of spec 8, on every op start
    always_ff @(posedge clk) if (!rst && state == START) begin
        automatic int c8 = 1 << d.log2_c8in;
        automatic int r = int'(d.k) * int'(d.k) * c8;
        automatic int pg = d.w_shared ? c8 : r;
        assert (d.in_bank != d.out_bank && (!d.res_en || (d.res_bank != d.in_bank && d.res_bank != d.out_bank)))
            else $error("controller: op %0d banks not distinct", op);
        assert (r >= (P + 7) / 8) else $error("controller: op %0d R = %0d < ceil(P/8)", op, r);
        assert (int'(d.w_base) + int'(d.groups) * pg <= D_W) else $error("controller: op %0d weights past D_W", op);
    end
`endif
endmodule
