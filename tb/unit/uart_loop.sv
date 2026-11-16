// Simulation-only wrapper for the L1b UART loopback test: uart_tx drives uart_rx directly, and the
// receiver can also be driven from the testbench (ext_rx) to check baud tolerance.
module uart_loop #(
    parameter int CLK_HZ = 100_000_000,
    parameter int BAUD = 6_250_000
) (
    input logic clk,
    input logic rst,
    input logic [7:0] tx_data,
    input logic tx_send,
    output logic tx_ready,
    output logic tx,
    input logic use_ext,  // 1: the receiver listens to ext_rx instead of tx
    input logic ext_rx,
    output logic [7:0] rx_data,
    output logic rx_valid,
    output logic rx_frame_err
);
    uart_tx #(.CLK_HZ(CLK_HZ), .BAUD(BAUD)) u_tx (.clk, .rst, .data(tx_data), .send(tx_send), .ready(tx_ready), .tx);
    uart_rx #(.CLK_HZ(CLK_HZ), .BAUD(BAUD)) u_rx (.clk, .rst, .rx(use_ext ? ext_rx : tx), .data(rx_data),
                                                  .valid(rx_valid), .frame_err(rx_frame_err));
endmodule
