// wgt_mem: one weight ROM per lane, D_W x 64 bit, initialised from model/export/P<P>/w_lane<p>.hex
// (spec 6.4, layout 7.3). All lanes read the same address (the AGU's w_addr) in the same cycle.
// Read latency 2, the same as act_mem, so weights and activations reach dot8 together.
module wgt_mem import acc_pkg::*; #(
    parameter int P = 8,
    parameter int D_W = 1226,  // export.py: 2,444 / 1,226 / 613 for P = 4 / 8 / 16
    parameter string HEX_DIR = "model/export/P8"  // absolute or relative to the simulator / Vivado cwd
) (
    input logic clk,
    input logic [W_AW-1:0] addr,
    output logic [P-1:0][63:0] w  // w[p]: weights of lane p, 2 cycles after addr
);
    for (genvar p = 0; p < P; p++) begin : g_lane
        (* rom_style = "block" *) logic [63:0] rom [D_W];
        logic [63:0] q1;
        initial $readmemh($sformatf("%s/w_lane%0d.hex", HEX_DIR, p), rom);
        always_ff @(posedge clk) begin
            q1 <= rom[addr[$clog2(D_W)-1:0]];  // addresses are always < D_W
            w[p] <= q1;
        end
    end
endmodule
