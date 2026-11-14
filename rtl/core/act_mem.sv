// act_mem: 3 activation banks of 2048 x 64 bit (spec 6.3, layout 7.1).
// Each bank is a simple dual-port BRAM (UG901 template): one read port, one write port with an 8-bit
// byte enable, read latency 2 (output register on). Within an op, in_bank, res_bank and out_bank all
// differ (checked by export.py and the controller), so a bank never serves two readers and the writer
// never shares a bank with a reader: there are no port conflicts. When the accelerator is idle the
// host interface owns every port (host_sel).
module act_mem import acc_pkg::*; (
    input logic clk,
    input logic [1:0] in_bank,
    input logic [1:0] res_bank,
    input logic [1:0] out_bank,
    input logic [ACT_AW-1:0] rd_addr,  // main read (AGU), from in_bank
    output logic [63:0] rd_data,  // 2 cycles after rd_addr
    input logic [ACT_AW-1:0] res_addr,  // residual read, from res_bank
    output logic [63:0] res_data,  // 2 cycles after res_addr
    input logic wr_en,  // write to out_bank
    input logic [ACT_AW-1:0] wr_addr,
    input logic [7:0] wr_be,
    input logic [63:0] wr_data,
    input logic host_sel,  // 1: the host owns all ports (accelerator idle)
    input logic [1:0] host_bank,
    input logic [ACT_AW-1:0] host_addr,
    input logic host_we,
    input logic [7:0] host_be,
    input logic [63:0] host_wdata,
    output logic [63:0] host_rdata  // from host_bank, 2 cycles after host_addr
);
    // One module per bank and packed vectors only: the first version (an unpacked q[] written from three
    // generate processes, concatenated unpacked LHS) simulated in Verilator but read X in XSim.
    logic [2:0][63:0] q;
    for (genvar b = 0; b < 3; b++) begin : g_bank
        act_bank u_bank (
            .clk,
            .we(host_sel ? host_we && host_bank == 2'(b) : wr_en && out_bank == 2'(b)),
            .be(host_sel ? host_be : wr_be),
            .waddr(host_sel ? host_addr : wr_addr),
            .wdata(host_sel ? host_wdata : wr_data),
            .raddr(host_sel ? host_addr : (in_bank == 2'(b)) ? rd_addr : res_addr),
            .rdata(q[b]));
    end

    // the output select follows the read by the same 2 cycles as the data, so the bank may change
    // on any cycle (found by test_act_mem: selecting with the current bank returned another bank)
    logic [1:0] in_d1, in_d2, res_d1, res_d2, host_d1, host_d2;
    always_ff @(posedge clk) begin
        in_d1 <= in_bank; in_d2 <= in_d1;
        res_d1 <= res_bank; res_d2 <= res_d1;
        host_d1 <= host_bank; host_d2 <= host_d1;
    end
    function automatic logic [63:0] pick(input logic [1:0] b, input logic [2:0][63:0] qs);
        case (b)
            2'd0: return qs[0];
            2'd1: return qs[1];
            default: return qs[2];
        endcase
    endfunction
    assign rd_data = pick(in_d2, q);
    assign res_data = pick(res_d2, q);
    assign host_rdata = pick(host_d2, q);
endmodule

// One 2048 x 64 bank: simple dual-port BRAM with byte-wide write enable and output register (UG901).
/* verilator lint_off DECLFILENAME */  // kept next to act_mem, its only user
module act_bank import acc_pkg::*; (
    input logic clk,
    input logic we,
    input logic [7:0] be,
    input logic [ACT_AW-1:0] waddr,
    input logic [63:0] wdata,
    input logic [ACT_AW-1:0] raddr,
    output logic [63:0] rdata  // 2 cycles after raddr
);
    (* ram_style = "block" *) logic [63:0] mem [ACT_WORDS];
    logic [63:0] q1;
    always_ff @(posedge clk) begin
        for (int i = 0; i < 8; i++)
            if (we && be[i]) mem[waddr][8*i +: 8] <= wdata[8*i +: 8];
    end
    always_ff @(posedge clk) begin
        q1 <= mem[raddr];
        rdata <= q1;
    end
endmodule
