// soc: everything that runs on the core clock: UART + host_if + accelerator core (spec 6, 9).
// top.sv adds the clock (clk_core MMCM), the reset synchronizer and the LEDs; soc is what the
// cocotb system test simulates (the MMCM IP has no Verilator model).
module soc import acc_pkg::*; #(
    parameter string PE_TYPE = "LUT_CUSTOM",
    parameter string SUM_STYLE = "ADDER",
    parameter int L_MUL = 2,
    parameter int P = 8,
    parameter int D_W = 1226,
    parameter int D_Q = 44,
    parameter string HEX_DIR = "model/export/P8",
    parameter int CLK_HZ = 100_000_000,
    parameter int BAUD = 115_200,
    parameter logic [7:0] VERSION = 8'h01
) (
    input logic clk,
    input logic rst,
    input logic uart_rx,
    output logic uart_tx,
    output logic busy,  // accelerator running (for an LED)
    output logic done  // pulse when a RUN completes
);
    logic [7:0] rx_data, tx_data;
    logic rx_valid, tx_send, tx_ready;
    /* verilator lint_off PINCONNECTEMPTY */
    uart_rx #(.CLK_HZ(CLK_HZ), .BAUD(BAUD)) u_rx (.clk, .rst, .rx(uart_rx), .data(rx_data), .valid(rx_valid), .frame_err());
    /* verilator lint_on PINCONNECTEMPTY */
    uart_tx #(.CLK_HZ(CLK_HZ), .BAUD(BAUD)) u_tx (.clk, .rst, .data(tx_data), .send(tx_send), .ready(tx_ready), .tx(uart_tx));

    logic start;
    logic [3:0] stop_after_op;
    logic [31:0] cycles;
    logic [1:0] host_bank;
    logic [ACT_AW-1:0] host_addr;
    logic host_we;
    logic [63:0] host_wdata, host_rdata;
    host_if #(.VERSION(VERSION)) u_host (
        .clk, .rst, .rx_data, .rx_valid, .tx_data, .tx_send, .tx_ready, .start, .stop_after_op,
        .acc_done(done), .cycles, .host_bank, .host_addr, .host_we, .host_wdata, .host_rdata);

    // keep_hierarchy: the core keeps its RTL ports in the post-synthesis netlist, so L5 can simulate it
    (* keep_hierarchy = "yes" *)
    accel #(.PE_TYPE(PE_TYPE), .SUM_STYLE(SUM_STYLE), .L_MUL(L_MUL), .P(P), .D_W(D_W), .D_Q(D_Q),
            .HEX_DIR(HEX_DIR)) u_core (
        .clk, .rst, .start, .first_op(4'd0), .stop_after_op, .busy, .done, .cycles,
        .host_bank, .host_addr, .host_we, .host_be(8'hFF), .host_wdata, .host_rdata);
endmodule
