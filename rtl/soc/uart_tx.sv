// uart_tx: 8N1 transmitter (spec 9). Same 16x phase-accumulator tick as uart_rx: one bit = 16 ticks.
// `send` is accepted only when `ready`; `ready` drops in the same cycle, so a caller that checks it
// can never start two bytes at once.
module uart_tx #(
    parameter int CLK_HZ = 100_000_000,
    parameter int BAUD = 115_200
) (
    input logic clk,
    input logic rst,
    input logic [7:0] data,
    input logic send,
    output logic ready,
    output logic tx
);
    localparam longint CLK = longint'(CLK_HZ);
    localparam longint INC = (longint'(16) * BAUD * (longint'(1) << 24) + CLK / 2) / CLK;

    logic [23:0] phase;
    logic tick;
    always_ff @(posedge clk) {tick, phase} <= {1'b0, phase} + 25'(INC);

    logic busy, pending;
    logic [9:0] frame;  // {stop, data[7:0], start}, shifted out LSB first
    logic [3:0] os, nbit;
    assign ready = !busy && !pending;

    always_ff @(posedge clk) begin
        if (rst) begin
            busy <= 1'b0;
            pending <= 1'b0;
            tx <= 1'b1;
        end else begin
            if (send && ready) begin
                frame <= {1'b1, data, 1'b0};
                pending <= 1'b1;  // start at the next tick, aligned to the bit grid
            end
            if (tick) begin
                if (pending) begin
                    pending <= 1'b0;
                    busy <= 1'b1;
                    os <= 4'd0;
                    nbit <= 4'd0;
                    tx <= frame[0];
                end else if (busy) begin
                    if (os == 4'd15) begin
                        os <= 4'd0;
                        if (nbit == 4'd9) begin
                            busy <= 1'b0;
                            tx <= 1'b1;
                        end else begin
                            nbit <= nbit + 1'b1;
                            tx <= frame[nbit + 1];
                        end
                    end else os <= os + 1'b1;
                end
            end
        end
    end
endmodule
