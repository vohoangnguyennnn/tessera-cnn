`timescale 1ns / 1ps
// Plain SystemVerilog testbench for XSim (cocotb has no XSim support):
//   L4 cross-check "XSim cho 2-3 ảnh" (spec 10) on the RTL, and later L5 on the post-synthesis netlist.
// For each image: write img_<i>.hex into bank 0 through the host port, run all 10 ops, read the 10
// logits from bank 1 and compare them with golden_<i>_fc.hex. Prints "XSIM PASS" / "XSIM FAIL".
// Paths are relative to the run directory build/xsim (make xsim).
// Plusargs (make cov, docs/coverage_plan.md 5): +IMG0=<first image> +N_IMG=<count> override the defaults;
// +STEP first runs image IMG0 op by op (first_op = stop_after_op = k) and checks every op's output bank.
module tb_accel_xsim;
    parameter string HEX_DIR = "../../model/export/P8";
    parameter string VEC_DIR = "../../model/vectors";
    parameter int N_IMG = 3;

    logic clk = 1'b0, rst = 1'b1, start = 1'b0;
    logic busy, done;
    logic [31:0] cycles;
    logic [1:0] host_bank = '0;
    logic [10:0] host_addr = '0;
    logic host_we = 1'b0;
    logic [63:0] host_wdata = '0, host_rdata;
    logic [3:0] first_op = 4'd0, stop_after_op = 4'd9;
    always #5 clk = ~clk;  // 100 MHz

`ifdef NETLIST
    // L5: post-synthesis functional netlist from build.tcl (parameters and ROM contents are baked in)
    accel dut (
`else
    accel #(.PE_TYPE("LUT_CUSTOM"), .SUM_STYLE("ADDER"), .L_MUL(2), .P(8), .D_W(1226), .D_Q(44),
            .HEX_DIR(HEX_DIR)) dut (
`endif
        .clk, .rst, .start, .first_op, .stop_after_op, .busy, .done, .cycles,
        .host_bank, .host_addr, .host_we, .host_be(8'hFF), .host_wdata, .host_rdata);

    logic [63:0] img [1024];
    logic [63:0] gold [2048];
    logic [63:0] got [2048];
    int errors = 0;
    int img0 = 0, n_img = N_IMG;

    // per op of the ROM: golden file name, output bank (spec 7.2), output words (Hout * Wout * C8out)
    // a variable, not a localparam: XSim 2024.1 reads a localparam string array as garbage
    string OP_NAME [10] = '{"conv0", "s1a", "s1b", "s2a", "s2s", "s2b", "s3a", "s3s", "s3b", "fc"};
    localparam int OP_BANK [10] = '{1, 2, 0, 1, 2, 0, 1, 2, 0, 1};
    localparam int OP_WORDS [10] = '{2048, 2048, 2048, 1024, 1024, 1024, 512, 512, 512, 2};

    task automatic load_image(input int i);
        $readmemh($sformatf("%s/img_%0d.hex", VEC_DIR, i), img);
        host_bank = 2'd0;
        for (int a = 0; a < 1024; a++) begin
            host_addr = 11'(a); host_wdata = img[a]; host_we = 1'b1;
            @(negedge clk);
        end
        host_we = 1'b0;
    endtask

    task automatic run_ops(input int first, input int last);
        first_op = 4'(first); stop_after_op = 4'(last);
        start = 1'b1;
        @(negedge clk);
        start = 1'b0;
        @(posedge done);
        @(negedge clk);
    endtask

    // n words of a bank into got[], pipelined: the data of address a arrives 2 negedges after it is set
    task automatic read_bank(input logic [1:0] bank, input int n);
        host_bank = bank;
        for (int a = 0; a <= n; a++) begin
            host_addr = 11'(a < n ? a : 0);
            @(negedge clk);
            if (a >= 1) got[a-1] = host_rdata;
        end
    endtask

    initial begin
        void'($value$plusargs("IMG0=%d", img0));
        void'($value$plusargs("N_IMG=%d", n_img));
        // > 100 ns: in the netlist sim (L5) glbl holds every flip-flop in GSR for the first 100 ns,
        // so earlier host writes are lost (it dropped the first 7 pixels and 2 logits were off by 1)
        repeat (20) @(negedge clk);
        rst = 1'b0;
        if ($test$plusargs("STEP")) begin
            // each op alone, on the memory state the previous op left (like L4 in cocotb, test_net.py)
            load_image(img0);
            for (int k = 0; k < 10; k++) begin
                run_ops(k, k);
                $readmemh($sformatf("%s/golden_%0d_%s.hex", VEC_DIR, img0, OP_NAME[k]), gold);
                read_bank(2'(OP_BANK[k]), OP_WORDS[k]);
                for (int a = 0; a < OP_WORDS[k]; a++) begin
                    // fc: only the 10 logit bytes are meaningful
                    if (k == 9 && a == 1 ? got[a][15:0] !== gold[a][15:0] : got[a] !== gold[a]) begin
                        errors++;
                        $display("image %0d op %s: MISMATCH word %0d %h, golden %h", img0, OP_NAME[k], a, got[a], gold[a]);
                        break;
                    end
                end
            end
            $display("image %0d: step mode, %0d ops checked", img0, 10);
        end
        for (int i = img0; i < img0 + n_img; i++) begin
            $readmemh($sformatf("%s/golden_%0d_fc.hex", VEC_DIR, i), gold);
            load_image(i);
            run_ops(0, 9);
            // read logits: words 0 and 1 of bank 1 (read latency 2)
            host_bank = 2'd1;
            host_addr = 11'd0; @(negedge clk);
            host_addr = 11'd1; @(negedge clk);
            got[0] = host_rdata; @(negedge clk);
            got[1] = host_rdata;
            if (got[0] !== gold[0] || got[1][15:0] !== gold[1][15:0]) begin
                errors++;
                $display("image %0d: MISMATCH logits %h_%h, golden %h_%h", i, got[1][15:0], got[0],
                         gold[1][15:0], gold[0]);
            end else begin
                $display("image %0d: logits %h_%h match golden, %0d cycles", i, got[1][15:0], got[0], cycles);
            end
        end
        if (errors == 0) $display("XSIM PASS: %0d images", n_img);
        else $display("XSIM FAIL: %0d errors, %0d images", errors, n_img);
        $finish;
    end
endmodule
