// uart_rx: 8N1 receiver with a 2-FF input synchronizer and 16x oversampling (spec 9).
// The 16x tick comes from a 24-bit phase accumulator, so any baud rate is exact to ~1e-7: an integer
// divider from 100 MHz would be 3% off at 921,600 baud (100e6 / (16 * 921600) = 6.78).
// Each bit is sampled once, in its middle (tick 8 of 16); a low start bit is re-checked there.
module uart_rx #(
    parameter int CLK_HZ = 100_000_000,
    parameter int BAUD = 115_200
) (
    input logic clk,
    input logic rst,
    input logic rx,  // asynchronous pin
    output logic [7:0] data,
    output logic valid,  // one-cycle pulse per received byte
    output logic frame_err  // one-cycle pulse: stop bit was 0 (byte dropped)
);
    localparam longint CLK = longint'(CLK_HZ);
    localparam longint INC = (longint'(16) * BAUD * (longint'(1) << 24) + CLK / 2) / CLK;

    logic [23:0] phase;
    logic tick;
    always_ff @(posedge clk) {tick, phase} <= {1'b0, phase} + 25'(INC);

    (* ASYNC_REG = "TRUE" *) logic [1:0] sync;  // 2-FF synchronizer; idle line is high
    always_ff @(posedge clk) sync <= rst ? 2'b11 : {sync[0], rx};
    wire rxs = sync[1];

    typedef enum logic [1:0] {IDLE, START, DATA, STOP} state_t;
    state_t state;
    logic [3:0] os;  // oversampling counter inside a bit
    logic [2:0] nbit;
    logic [7:0] sh;

    always_ff @(posedge clk) begin
        valid <= 1'b0;
        frame_err <= 1'b0;
        if (rst) begin
            state <= IDLE;
        end else if (tick) begin
            case (state)
                IDLE: if (!rxs) begin state <= START; os <= 4'd0; end
                START: if (os == 4'd7) begin  // middle of the start bit
                           if (rxs) state <= IDLE;  // glitch, not a start bit
                           else begin state <= DATA; os <= 4'd0; nbit <= 3'd0; end
                       end else os <= os + 1'b1;
                DATA: if (os == 4'd15) begin  // middle of data bit nbit
                           os <= 4'd0;
                           sh <= {rxs, sh[7:1]};  // LSB first
                           if (nbit == 3'd7) state <= STOP;
                           nbit <= nbit + 1'b1;
                       end else os <= os + 1'b1;
                STOP: if (os == 4'd15) begin  // middle of the stop bit
                           state <= IDLE;
                           if (rxs) begin data <= sh; valid <= 1'b1; end
                           else frame_err <= 1'b1;
                       end else os <= os + 1'b1;
            endcase
        end
    end
endmodule
