// host_if: command parser between the UART byte stream and the accelerator core (spec 9).
//
//   0x00 PING          -> 0xA5, VERSION
//   0x10 LOAD_IMG      + 3,072 bytes (HWC, 3 channels) + XOR checksum -> 0xA5 (ok) / 0x5A (bad checksum)
//                        writes pixel (y, x) to bank 0 word y*32 + x, bytes 3..7 = 0 (layout 7.1)
//   0x20 RUN           + stop_after_op -> 0xA5 when done (stop_after_op >= 9: whole network)
//   0x30 READ_LOGITS   -> 10 bytes: bank 1, words 0..1
//   0x40 READ_CYCLES   -> 4 bytes, little endian
//   0x50 DUMP          + bank, start word (2 bytes LE), word count (2 bytes LE) -> 8 bytes per word, LSB first
// Unknown command bytes are ignored (the host resynchronises with PING). The host port of act_mem is
// only used while the accelerator is idle: every command runs to completion before the next one.
module host_if import acc_pkg::*; #(
    parameter logic [7:0] VERSION = 8'h01
) (
    input logic clk,
    input logic rst,
    input logic [7:0] rx_data,
    input logic rx_valid,
    output logic [7:0] tx_data,
    output logic tx_send,
    input logic tx_ready,
    output logic start,
    output logic [3:0] stop_after_op,
    input logic acc_done,
    input logic [31:0] cycles,
    output logic [1:0] host_bank,
    output logic [ACT_AW-1:0] host_addr,
    output logic host_we,
    output logic [63:0] host_wdata,
    input logic [63:0] host_rdata  // 2 cycles after host_addr / host_bank
);
    localparam logic [7:0] C_PING = 8'h00, C_LOAD = 8'h10, C_RUN = 8'h20, C_LOGITS = 8'h30,
                           C_CYCLES = 8'h40, C_DUMP = 8'h50, OK = 8'hA5, BAD = 8'h5A;
    localparam int IMG_BYTES = 32 * 32 * 3;

    typedef enum logic [3:0] {IDLE, IMG, IMG_CK, RUN_ARG, RUN_WAIT, DUMP_ARG, RD_ADDR, RD_WAIT, SEND} state_t;
    state_t state;

    logic [11:0] nrx;  // payload bytes received so far
    logic [1:0] ch;  // channel of the next image byte
    logic [15:0] pix;  // channels 0, 1 of the current pixel
    logic [ACT_AW-1:0] wr_pix;
    logic [7:0] ck;  // running XOR checksum
    logic [31:0] args;  // DUMP: first 4 argument bytes, shifted in from the top
    logic [63:0] word;  // response bytes, sent LSB first
    logic [3:0] nsend;  // bytes of `word` still to send
    logic [15:0] mem_bytes;  // bytes still to read from act_mem (READ_LOGITS / DUMP)
    logic [ACT_AW-1:0] rd_addr;
    logic [1:0] wait_cnt;

    assign tx_data = word[7:0];
    assign tx_send = state == SEND && nsend != 0 && tx_ready;

    always_ff @(posedge clk) begin
        start <= 1'b0;
        host_we <= 1'b0;
        if (rst) begin
            state <= IDLE;
        end else begin
            case (state)
                IDLE: if (rx_valid) begin
                    nrx <= '0;
                    case (rx_data)
                        C_PING: begin word <= {48'b0, VERSION, OK}; nsend <= 4'd2; mem_bytes <= '0; state <= SEND; end
                        C_LOAD: begin ch <= '0; ck <= '0; wr_pix <= '0; state <= IMG; end
                        C_RUN: state <= RUN_ARG;
                        C_LOGITS: begin host_bank <= 2'd1; rd_addr <= '0; mem_bytes <= 16'd10; state <= RD_ADDR; end
                        C_CYCLES: begin word <= {32'b0, cycles}; nsend <= 4'd4; mem_bytes <= '0; state <= SEND; end
                        C_DUMP: state <= DUMP_ARG;
                        default: ;  // ignored
                    endcase
                end
                IMG: if (rx_valid) begin
                    ck <= ck ^ rx_data;
                    nrx <= nrx + 1'b1;
                    if (ch == 2'd2) begin  // pixel complete: one word to bank 0
                        host_bank <= 2'd0;
                        host_addr <= wr_pix;
                        host_wdata <= {40'b0, rx_data, pix};
                        host_we <= 1'b1;
                        wr_pix <= wr_pix + 1'b1;
                        ch <= '0;
                    end else begin
                        pix[8*ch +: 8] <= rx_data;
                        ch <= ch + 1'b1;
                    end
                    if (nrx == 12'(IMG_BYTES - 1)) state <= IMG_CK;
                end
                IMG_CK: if (rx_valid) begin
                    word <= {56'b0, rx_data == ck ? OK : BAD};
                    nsend <= 4'd1;
                    mem_bytes <= '0;
                    state <= SEND;
                end
                RUN_ARG: if (rx_valid) begin
                    stop_after_op <= rx_data > 8'd9 ? 4'd9 : rx_data[3:0];
                    start <= 1'b1;
                    state <= RUN_WAIT;
                end
                RUN_WAIT: if (acc_done) begin
                    word <= {56'b0, OK}; nsend <= 4'd1; mem_bytes <= '0; state <= SEND;
                end
                DUMP_ARG: if (rx_valid) begin
                    args <= {rx_data, args[31:8]};
                    nrx <= nrx + 1'b1;
                    if (nrx == 12'd4) begin  // all 5 argument bytes in
                        host_bank <= args[1:0];  // bytes: bank, addr lo, addr hi, n lo
                        rd_addr <= ACT_AW'({args[23:16], args[15:8]});
                        mem_bytes <= {rx_data, args[31:24]} << 3;  // count * 8 bytes
                        state <= ({rx_data, args[31:24]} == 16'd0) ? IDLE : RD_ADDR;
                    end
                end
                RD_ADDR: begin
                    host_addr <= rd_addr;
                    wait_cnt <= 2'd2;
                    state <= RD_WAIT;
                end
                RD_WAIT: if (wait_cnt == 0) begin  // host_rdata is valid now
                    word <= host_rdata;
                    nsend <= mem_bytes >= 16'd8 ? 4'd8 : 4'(mem_bytes);
                    mem_bytes <= mem_bytes >= 16'd8 ? mem_bytes - 16'd8 : '0;
                    rd_addr <= rd_addr + 1'b1;
                    state <= SEND;
                end else wait_cnt <= wait_cnt - 1'b1;
                SEND: if (nsend == 0) state <= mem_bytes != 0 ? RD_ADDR : IDLE;
                      else if (tx_ready) begin
                          word <= word >> 8;
                          nsend <= nsend - 1'b1;
                      end
                default: state <= IDLE;
            endcase
        end
    end
endmodule
