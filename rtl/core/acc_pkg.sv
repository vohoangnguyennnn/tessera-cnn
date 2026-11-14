// acc_pkg: constants and the layer descriptor shared by the accelerator (spec 6, 8).
//
// desc_t is declared once here and once in model/export.py (FIELDS), in the same order: the first
// field is the most significant, exactly like this packed struct. model/tests/test_acc_pkg.py checks
// that the two declarations stay identical.
package acc_pkg;
    localparam int ACT_WORDS = 2048;  // words per activation bank (16 KB, spec 6.3)
    localparam int ACT_AW = 11;  // activation word address width
    localparam int W_AW = 12;  // weight ROM address width (D_w <= 2,444, spec 7.3)
    localparam int Q_AW = 7;  // q-param ROM address width (D_q <= 87, spec 6.4)

    typedef struct packed {
        logic [7:0] spare;
        logic [2:0] log2_win;  // Hin = Win = 1 << log2_win
        logic [2:0] log2_wout;  // Hout = Wout
        logic [1:0] log2_c8in;  // input words per pixel
        logic [1:0] log2_c8out;  // output words per pixel
        logic [3:0] k;  // kernel size: 1, 3 or 8
        logic [1:0] stride;  // 1 or 2
        logic pad;  // 0 or 1
        logic [4:0] groups;  // G = ceil(Cout / P)
        logic [1:0] in_bank;
        logic [1:0] out_bank;
        logic [1:0] res_bank;
        logic res_en;
        logic relu_en;
        logic w_shared;  // fc: weights indexed by c only, shared over (ky, kx)
        logic [11:0] w_base;
        logic [6:0] q_base;
        logic [15:0] m_r;
        logic [5:0] n_r;
    } desc_t;  // 80 bits

    localparam int DESC_BITS = $bits(desc_t);
endpackage
