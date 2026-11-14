// qparam_mem: one {bias[31:0], M[15:0], n[5:0]} ROM per lane, D_Q entries, initialised from
// model/export/P<P>/q_lane<p>.hex (spec 6.4, layout 7.4). Small enough for distributed ROM.
// Read latency 1. Entry q_base + g serves lane p for output channel co = g*P + p: bias at the
// pixel's first chunk, M and n at its last chunk (both of the same g, never in the same cycle).
module qparam_mem import acc_pkg::*; #(
    parameter int P = 8,
    parameter int D_Q = 44,  // export.py: 87 / 44 / 22 for P = 4 / 8 / 16
    parameter string HEX_DIR = "model/export/P8"
) (
    input logic clk,
    input logic [Q_AW-1:0] addr,
    output logic signed [31:0] bias [P],
    output logic [15:0] M [P],
    output logic [5:0] n [P]
);
    for (genvar p = 0; p < P; p++) begin : g_lane
        (* rom_style = "distributed" *) logic [53:0] rom [D_Q];
        initial $readmemh($sformatf("%s/q_lane%0d.hex", HEX_DIR, p), rom);
        always_ff @(posedge clk) {bias[p], M[p], n[p]} <= rom[addr[$clog2(D_Q)-1:0]];  // addresses < D_Q
    end
endmodule
