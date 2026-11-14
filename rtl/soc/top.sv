// top: board top level for the MicroPhase A7-Lite 35T (spec 6, 11.2; pins in fpga/xdc/a7_lite.xdc).
//   clk_core : Clocking Wizard IP (MMCM), 50 MHz oscillator -> core clock; created by fpga/tcl/build.tcl
//   reset    : asserted asynchronously (MMCM not locked, or key K1 pressed), released synchronously
//   led[0]   : heartbeat, about 1.5 Hz at 100 MHz: the clock runs and the design is out of reset
//   led[1]   : toggles after every completed RUN
module top #(
    parameter string PE_TYPE = "LUT_CUSTOM",
    parameter string SUM_STYLE = "ADDER",
    parameter int L_MUL = 2,
    parameter int P = 8,
    parameter int D_W = 1226,
    parameter int D_Q = 44,
    parameter string HEX_DIR = "model/export/P8",
    parameter int CLK_HZ = 100_000_000,  // must match the clk_core output frequency
    parameter int BAUD = 921_600
) (
    input logic clk_50m,
    input logic rst_key_n,  // key K1, active low
    input logic uart_rx,
    output logic uart_tx,
    output logic [1:0] led
);
    logic clk, locked;
    clk_core u_clk (.clk_in1(clk_50m), .reset(1'b0), .clk_out1(clk), .locked(locked));

    logic rst_async;
    assign rst_async = !locked || !rst_key_n;
    (* ASYNC_REG = "TRUE" *) logic [1:0] rst_sync;
    always_ff @(posedge clk or posedge rst_async) begin
        if (rst_async) rst_sync <= 2'b11;
        else rst_sync <= {rst_sync[0], 1'b0};
    end
    logic rst;
    assign rst = rst_sync[1];

    logic busy, done;
    soc #(.PE_TYPE(PE_TYPE), .SUM_STYLE(SUM_STYLE), .L_MUL(L_MUL), .P(P), .D_W(D_W), .D_Q(D_Q),
          .HEX_DIR(HEX_DIR), .CLK_HZ(CLK_HZ), .BAUD(BAUD)) u_soc (.clk, .rst, .uart_rx, .uart_tx, .busy, .done);

    logic [25:0] hb;
    logic run_led;
    always_ff @(posedge clk) begin
        hb <= rst ? '0 : hb + 1'b1;
        if (rst) run_led <= 1'b0;
        else if (done) run_led <= ~run_led;
    end
    assign led = {run_led, hb[25]};
endmodule
