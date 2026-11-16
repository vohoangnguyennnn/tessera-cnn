# Coverage Plan: Tessera CNN Accelerator

Tài liệu này là **verification plan phần functional coverage** cho accelerator. Nó trả lời bốn câu hỏi: đo cái gì, đo ở đâu, khi nào thì đủ, và các bin chưa đạt được xử lý ra sao. Nó bổ sung cho §10 của [Spec.md](Spec.md), không thay thế: §10 nói *kiểm tra kết quả đúng thế nào* (scoreboard so với golden), còn tài liệu này nói *stimulus đã đi tới đâu*.

Cột "Dự đoán" ghi trạng thái **trước khi chạy**, suy ra từ RTL và 10 descriptor thật trong `model/export/P8/desc.hex`. Sau lần chạy đầu tiên, so dự đoán với số thật và ghi lại chỗ sai. Chỗ đoán sai thường là chỗ học được nhiều nhất.

---

## 1. Kiến thức nền (đọc trước khi phỏng vấn)

| Khái niệm | Ý nghĩa | Ví dụ trong project này |
| --- | --- | --- |
| **Code coverage** | Tool tự đo: dòng, nhánh, điều kiện, toggle nào của RTL đã chạy. Không cần viết gì. | Nhánh `n_r >= 25` trong `lane.sv` có chạy hay chưa |
| **Functional coverage** | Người verify tự định nghĩa *tình huống quan trọng theo spec*, rồi đo xem tình huống đó đã xảy ra chưa. | "Có output nào bị saturate về −128 chưa?" |
| **Coverpoint / bin** | Coverpoint là một biến được theo dõi. Bin là một nhóm giá trị (hoặc một chuỗi chuyển trạng thái) mà ta muốn thấy ít nhất một lần. | Coverpoint `state`, bin `RUN => DRAIN` |
| **Transition bin** | Bin của *chuỗi* giá trị theo thời gian, cú pháp `(a => b)`. | `DRAIN => IDLE`: op cuối kết thúc |
| **Cross** | Tích Descartes của hai hoặc nhiều coverpoint. Bắt các *tổ hợp*, không chỉ từng giá trị riêng lẻ. | `stride × padding side` |
| **ignore_bins** | Tổ hợp không thể xảy ra hoặc nằm ngoài scope. Loại khỏi mẫu số, *phải ghi lý do*. | stride 2 không bao giờ chạm padding dưới/phải (§4.3) |
| **illegal_bins** | Tổ hợp *cấm*. Nếu xảy ra, simulator báo lỗi. | stride 2 chạm padding cạnh dưới/phải nghĩa là AGU sai (§6) |
| **Sampling event** | Thời điểm covergroup chụp giá trị. **Chọn sai thời điểm thì coverage sai**, dù code coverage vẫn đẹp. | `lane` có pipeline 6 tầng: mỗi tầng phải sample đúng bit valid của nó |
| **Coverage hole** | Bin chưa được hit sau khi chạy. | `stop_after_op < 9` chưa bao giờ được dùng trong XSim TB |
| **Coverage closure** | Quá trình xử lý mọi hole: thêm stimulus, hoặc chứng minh bin không thể xảy ra và đưa vào ignore, kèm lý do. | §5 |

**Ba ý quan trọng nhất:**

1. **Coverage đo stimulus, không đo tính đúng.** Coverage 100% với một checker yếu vẫn bỏ lọt bug. Project này mạnh ở chỗ checker là bit-exact golden (scoreboard), nên coverage chỉ cần trả lời "đã thử đủ tình huống chưa".
2. **Code coverage 100% không đủ.** Ví dụ: dòng `z4 <= (s3 > 127) ? 127 : ...` chạy ở *mọi* cycle, nên code coverage đạt 100% ngay cả khi chưa từng có giá trị nào thực sự saturate. Chỉ functional coverage (bin `s3 > 127`) mới thấy được điều đó.
3. **Coverage plan đến từ spec, không đến từ RTL.** Mỗi bin dưới đây đều ghi nguồn gốc là mục nào của Spec. Nếu chỉ đọc RTL để đặt bin, bạn sẽ chỉ kiểm cái RTL đang làm, không kiểm cái RTL *phải* làm.

---

## 2. Scope và quyết định kiến trúc

### 2.1 Đo ở đâu

| Môi trường | Covergroup SV? | Vai trò |
| --- | --- | --- |
| Verilator 5.049 + cocotb (L1–L4, `make test`) | **Không.** Đã thử ngày 2026-11-16: Verilator cảnh báo `COVERIGN` và bỏ qua toàn bộ `covergroup`, `coverpoint`, `bins`, `=>` | Regression chính, không đổi |
| **XSim (Vivado 2024.1), `tb_accel_xsim.sv`** | Có. Báo cáo bằng `xcrg` | **Nơi đo functional coverage** |

**Hệ quả quan trọng:** coverage được đo ở mức *integration* (cả mạng 10 op, ảnh CIFAR-10 thật, P = 8). Các corner số học như n = 1, n = 47, acc gần 2^30 đã được *test* ở L1 (`test_lane.py` dùng directed stimulus) nhưng *không được đo* bằng covergroup. Trong plan, các bin này được đánh dấu **L1** (closed ở mức unit, có trỏ tới test cụ thể). Phase 2 (§7) có thể đo chúng bằng Python ngay trong cocotb.

### 2.2 Scope của cấu hình

- **Trong scope:** P = 8, `LUT_CUSTOM`/`ADDER`/`L_MUL = 2`, ROM descriptor ResNet-8 thật. Đây đúng là cấu hình `tb_accel_xsim.sv` đang chạy.
- **Ngoài scope (phase 2):** P = 4 (ghi nửa word bằng byte-enable 0x0F/0xF0) và P = 16 (NW = 2, ghi hai word liên tiếp). Các bin này chỉ tồn tại khi đổi P.
- **Quyết định scope descriptor:** controller được thiết kế tổng quát ("không biết gì về ResNet", Spec §8), nhưng sản phẩm chỉ chạy một ROM. Plan cover **những gì ROM dùng**. Các tổ hợp hợp lệ theo spec mà ROM không dùng (ví dụ `res_bank = 0` khi `res_en = 1`) được đưa vào ignore với lý do "ngoài workload". Ghi rõ điều này nghĩa là: **tính tổng quát của controller chưa được verify.** Đây là một câu trả lời phỏng vấn tốt về chuyện đánh đổi scope.

### 2.3 Cách gắn coverage vào thiết kế

- Covergroup nằm trong các module riêng, gắn vào RTL bằng **`bind`**. **Không sửa một dòng RTL nào.** Coverage là code của verification, RTL là code của design: tách hai thứ thì synthesis không bao giờ thấy covergroup, và người làm design không phải đọc code DV.
- File dự kiến: `tb/net/accel_cov.sv` (các module coverage và các câu `bind`). Target dự kiến: `make cov`, chạy XSim, rồi `xcrg` xuất HTML vào `results/cov/`.
- Coverage của host port (đọc bank nào) nằm **trong testbench**, không bind vào RTL. Lý do: `act_mem` không có tín hiệu read-enable, nên "host đọc bank 1" không phải là một sự kiện ở mức RTL mà là một *transaction* của testbench. Đây là ví dụ phân biệt *RTL-level coverage* với *transaction-level coverage*.

---

## 3. Phân tích trước: dữ liệu thật trông thế nào

10 op ở P = 8 (giải mã từ `desc.hex`). R = K² · C8 là số cycle cho mỗi pixel output.

| # | Op | Kind | k | stride | pad | in→out (res) | res_en | relu_en | w_shared | R | groups |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | conv0 | CONV3_S1 | 3 | 1 | 1 | 0→1 | 0 | 1 | 0 | 9 | 2 |
| 1 | s1a | CONV3_S1 | 3 | 1 | 1 | 1→2 | 0 | 1 | 0 | 18 | 2 |
| 2 | s1b | CONV3_S1 | 3 | 1 | 1 | 2→0 (1) | 1 | 1 | 0 | 18 | 2 |
| 3 | s2a | CONV3_S2 | 3 | 2 | 1 | 0→1 | 0 | 1 | 0 | 18 | 4 |
| 4 | s2s | CONV1_S2 | 1 | 2 | 0 | 0→2 | 0 | 0 | 0 | **2** | 4 |
| 5 | s2b | CONV3_S1 | 3 | 1 | 1 | 1→0 (2) | 1 | 1 | 0 | 36 | 4 |
| 6 | s3a | CONV3_S2 | 3 | 2 | 1 | 0→1 | 0 | 1 | 0 | 36 | 8 |
| 7 | s3s | CONV1_S2 | 1 | 2 | 0 | 0→2 | 0 | 0 | 0 | 4 | 8 |
| 8 | s3b | CONV3_S1 | 3 | 1 | 1 | 1→0 (2) | 1 | 1 | 0 | 72 | 8 |
| 9 | fc | FC | 8 | 1 | 0 | 0→1 | 0 | 0 | 1 | **512** | 2 |

Những gì rút ra được *trước khi chạy một cycle nào*:

1. **Phần control không phụ thuộc dữ liệu ảnh.** Chuỗi trạng thái của controller, chuỗi tick của AGU và các tổ hợp descriptor là như nhau với mọi ảnh. Chạy 1 ảnh hay 10,000 ảnh cho cùng coverage control. Muốn đóng hole ở phần control thì phải đổi *loại* stimulus (directed test), chạy thêm ảnh random không giúp gì.
2. **Chỉ phần số học trong `lane` phụ thuộc dữ liệu.** Đây là nơi duy nhất chạy thêm ảnh có thể tăng coverage.
3. **Có những vùng không thể đạt bằng cấu trúc.** Với stride 2, pad 1, k = 3, Win = 32, Wout = 16: iy = 2·oy + ky − 1 nằm trong −1..31. Vậy padding *chỉ có thể* xảy ra ở cạnh trên và cạnh trái, không bao giờ ở cạnh dưới hay cạnh phải. Bin `stride2 × bottom` là ignore, không phải hole.
4. **Có những vùng không thể đạt với ROM này.** Residual dùng M_r ∈ {44659, 54150, 41119} và n_r ∈ {17, 18}, nên |y_res| ≤ 128 · 54150 / 2^17 ≈ 53. Vì vậy `clamp16` của nhánh residual không bao giờ kích hoạt ở mức network. Corner này chỉ đóng được ở L1.

---

## 4. Các covergroup

Ký hiệu cột "Dự đoán":

- **HIT**: chắc chắn hit với 1 ảnh.
- **HIT?**: phụ thuộc dữ liệu, có khả năng hit.
- **HOLE**: dự đoán không hit, cần đóng ở §5.
- **IGN**: ignore_bins, có lý do.
- **L1**: closed ở unit test, không đo ở đây.

### 4.1 CG_CTRL: FSM của controller

- **Gắn vào:** `controller`. **Sample:** `@(posedge clk iff !rst)` trên `state`.
- **Nguồn spec:** §6.6, §8 (chế độ debug `stop_after_op`), §9 (host chỉ dùng bank khi idle).

| ID | Coverpoint / bin | Ý nghĩa | Dự đoán |
| --- | --- | --- | --- |
| CTRL.S1–S5 | `state ∈ {IDLE, FETCH, START, RUN, DRAIN}` | Mọi trạng thái đều được thăm | HIT |
| CTRL.T1 | `IDLE => FETCH` | Bắt đầu một lần chạy | HIT |
| CTRL.T2 | `FETCH => START => RUN` | Chuỗi khởi động op đúng thứ tự | HIT |
| CTRL.T3 | `RUN => DRAIN` | AGU xong | HIT |
| CTRL.T4 | `DRAIN [*2]` (hai sample DRAIN liên tiếp, tức ở lại ≥ 2 cycle) | Thực sự phải chờ pipeline xả (`pipe_busy`) | HIT |
| CTRL.T5 | `DRAIN => FETCH` | Chuyển sang op kế tiếp | HIT |
| CTRL.T6 | `DRAIN => IDLE` khi `op == 9` | Kết thúc bình thường | HIT |
| CTRL.T7 | `DRAIN => IDLE` khi `op < 9` | **Dừng sớm bằng `stop_after_op`**, tính năng debug của Spec §8 | **HOLE**: TB luôn đặt `stop_after_op = 9` |
| CTRL.T8 | `IDLE => FETCH` với `first_op ≠ 0` | Chạy một op lẻ (L3 dùng cách này trong cocotb) | **HOLE**: TB luôn đặt `first_op = 0` |
| CTRL.T9 | `start = 1` khi `state ≠ IDLE` | Start trong lúc bận phải bị bỏ qua | **HOLE**: TB không bao giờ làm việc này |
| CTRL.T10 | `done => … => IDLE => FETCH` (chạy liên tiếp) | Chạy lại sau `done` mà không reset | HIT (TB chạy 3 ảnh liên tiếp) |

**Vì sao T7 đáng quan tâm:** `host.py` dùng đúng tính năng này trên board để tìm op sai đầu tiên (Spec §9). Một tính năng dùng để debug board mà chưa từng được mô phỏng là rủi ro thật. `test_soc.py` (cocotb) có chạy `stop_after_op = 2`, nhưng không đo coverage.

### 4.2 CG_OP: descriptor của mỗi op

- **Gắn vào:** `controller`. **Sample:** một lần mỗi op, khi `state == START`, cùng thời điểm với SVA có sẵn ở `controller.sv:70`.
- **Nguồn spec:** §7.2 (phân bổ bank), §8 (bảng field).

| ID | Coverpoint / bin | Dự đoán |
| --- | --- | --- |
| OP.IDX | `op ∈ 0..9`, mỗi giá trị một bin | HIT |
| OP.KIND | `{CONV3_S1, CONV3_S2, CONV1_S2, FC}`, suy ra từ (k, stride, pad, w_shared); tổ hợp khác là IGN (ngoài workload) | HIT |
| OP.R | R = K²·C8 ∈ `{2, 4, 9, 18, 36, 72, 512}`; R = 2 là giới hạn dưới của Spec §5.4 | HIT |
| OP.BANK | Bộ (in, out, res) ∈ {(0,1,–), (1,2,–), (2,0,1), (0,2,–), (1,0,2)}; mọi bộ khác là IGN | HIT |
| OP.G | `groups ∈ {2, 4, 8}` | HIT |
| X_KIND_RES | `OP.KIND × res_en`: chỉ `CONV3_S1 × 1` hợp lệ cho res; `{CONV3_S2, CONV1_S2, FC} × 1` là IGN | HIT |
| X_KIND_RELU | `OP.KIND × relu_en`: `CONV1_S2 × 1` và `FC × 1` là IGN (shortcut và logits không có ReLU, Spec §3) | HIT |

**Bài học khi phỏng vấn:** toàn bộ CG_OP sẽ đạt 100% với 1 ảnh, nên trông rất đẹp. Nhưng nó chỉ chứng minh "ROM đã chạy hết", không chứng minh controller tổng quát đúng. Hãy nói thẳng điều này, đừng khoe con số.

### 4.3 CG_AGU: tick của loop nest

- **Gắn vào:** `agu`. **Sample:** `@(posedge clk iff run)` trên các counter (`cg`, `coy`, `cox`, `cky`, `ckx`, `cc`) và `iy`/`ix` (tổ hợp, cùng cycle với counter). Đừng sample trên các output đã đăng ký (`in_bounds`, `first`…): chúng trễ 1 cycle so với counter, sample lệch là sai.
- **Nguồn spec:** §5.1 (loop nest), §6.5, §6.7 (padding thay bằng 0).

| ID | Coverpoint / bin | Ý nghĩa | Dự đoán |
| --- | --- | --- | --- |
| AGU.INB | `inb_c ∈ {0, 1}` | Có cả tick trong ảnh và tick padding | HIT |
| AGU.SIDE | `{TOP (iy = −1), BOTTOM (iy = Hin), LEFT (ix = −1), RIGHT (ix = Win), CORNER (cả hai ngoài)}` | Padding ở từng cạnh. Off-by-one ở cạnh dưới/phải là bug kinh điển | HIT |
| X_STRIDE_SIDE | `stride × AGU.SIDE`: `stride2 × {BOTTOM, RIGHT}` không thể xảy ra (chứng minh ở §3 ý 3). Khi triển khai, đặt thành **illegal_bins** chứ không phải ignore, xem §6 | | HIT / ILLEGAL |
| AGU.PIX | `first` và `last` riêng biệt; `first && last` cùng tick là **không thể** (R ≥ 2) nên đưa vào assertion, không phải bin | | HIT |
| AGU.GRP | `cg == 0`, `0 < cg < groups−1`, `cg == groups−1` | Group đầu, giữa, cuối (w_base nhảy `per_g` mỗi group) | HIT |
| AGU.WS | `w_shared × (cky, ckx)`: FC dùng lại cùng weight trên 64 vị trí | | HIT |

### 4.4 CG_LANE: số học hậu xử lý (phần duy nhất phụ thuộc dữ liệu)

- **Gắn vào:** `lane` (8 instance ở P = 8). Dùng **coverage theo type, tính hợp các bin của 8 lane**. Câu hỏi là "có lane nào saturate chưa", không phải "lane 5 đã saturate chưa". Cần hai thứ, cả hai đều phát hiện được khi chạy thật (§8):
  1. Covergroup khai báo trong **package**, sample bằng `sample()`. Nếu khai báo trong module, XSim coi mỗi instance của module là một covergroup riêng.
  2. `type_option.merge_instances = 1`. Mặc định (0), IEEE 1800 §19.7 tính coverage của type là *trung bình* điểm các instance, không phải *hợp* các bin.
- **Sample:** mỗi coverpoint sample đúng tầng pipeline của nó, dùng shift register valid `v[]` có sẵn trong `lane.sv`:

| Tầng | Thanh ghi | Valid khi | Coverpoint |
| --- | --- | --- | --- |
| S0 | `t0`, `n0` | `v[0]` | LANE.N, LANE.T |
| S1 | `p1`, `n1` | `v[1]` | LANE.TIE |
| S2 | `p2` | `v[2]` | LANE.CLAMP16 |
| S3 | `s3 = y_main3 + y_res3` | `v[3]` | LANE.SAT8, LANE.RES |
| S4 | `z4` | `v[4]` | LANE.RELU |

Nếu sample tất cả ở `y_valid`, các giá trị S0–S3 lúc đó đã thuộc về *pixel khác*. Đây là lỗi sampling điển hình với datapath có pipeline.

- **Nguồn spec:** §4.3 (chặn trên acc), §4.4 (RQ, clamp, residual, ReLU).

| ID | Coverpoint / bin | Ý nghĩa | Dự đoán |
| --- | --- | --- | --- |
| LANE.N | `n ∈ {[1:16], [17:35], [36:47]}` | Model thực tế chỉ dùng 17..35 (Spec §4.4) | `[17:35]` HIT; hai bin còn lại **L1** (`test_lane` có n = 1, 2, 46, 47) |
| LANE.T | `\|t\| ∈ {0, nhỏ < 2^16, vừa < 2^24, lớn ≥ 2^24}` | Biên độ accumulator. Spec chứng minh \|Σ\| < 2^24, cộng thêm bias | `≥ 2^24` HOLE hoặc IGN (cần đo); gần 2^30 là **L1** + SVA |
| LANE.TIE | Phần dư `p1 mod 2^n1 == 2^(n1−1)`, chia theo dấu `p1 ≥ 0` / `p1 < 0` | **Tie khi làm tròn.** Half-up cho −2.5 → −2; half-away-from-zero cho −3. Chỉ tie *âm* phân biệt được hai cách | **HOLE**: xác suất tie ≈ 2^−n với n ≥ 17, coi như bằng 0 trên dữ liệu thật |
| LANE.CLAMP16 | `p2 > 32767`, `p2 < −32768`, trong khoảng | Clamp 16-bit của nhánh main (Spec §4.4 bước 1) | Hai bin clamp: HIT? (phải đo) |
| LANE.SAT8 | `s3 > 127`, `s3 < −128`, trong khoảng | Saturation int8 hai phía (Spec §10 dòng L1b ghi rõ "saturation hai phía") | HIT? |
| LANE.RES | `res_en × sign(y_res3) {âm, 0, dương}`; `y_res` clamp16 | Residual cộng đủ dấu | Dấu: HIT. Clamp16: **IGN ở network** (\|y_res\| ≤ 53, §3 ý 4) + **L1** |
| LANE.RELU | `relu_en && z4 < 0` (bị kẹp về 0), `relu_en && z4 ≥ 0`, `!relu_en && z4 < 0` (âm đi qua) | ReLU bật/tắt, có tác dụng thật | HIT |
| LANE.NR | `n_r ≥ 25` (nhánh ép về 0) | | **IGN ở network** (n_r ∈ {17, 18}) + **L1** (`test_lane` có n_r = 23, 24, 25) |
| X_SAT_RES | `LANE.SAT8 × res_en` | Saturation xảy ra cả khi có và không có residual. Phép cộng residual là chỗ dễ tràn nhất | HIT? |

**Vì sao LANE.TIE là bin hay nhất để kể khi phỏng vấn:** nếu ai đó implement nhầm thành round-half-away-from-zero, mọi test random ở mức network vẫn pass, vì tie âm gần như không bao giờ xảy ra với n ≥ 17. Hole này chỉ có directed test với n nhỏ mới bắt được. Đây là lý do một kiến trúc verify nhiều tầng tồn tại: **coverage ở mức network chứng minh được rằng unit test là cần thiết**, không chỉ là "cho chắc".

### 4.5 CG_HOST: host port (transaction-level, trong TB)

- **Gắn vào:** `tb_accel_xsim.sv`, sample trong task ghi/đọc của TB. **Nguồn spec:** §6.3, §9.

| ID | Coverpoint / bin | Dự đoán |
| --- | --- | --- |
| HOST.WR | Host ghi bank `{0, 1, 2}` | Bank 0: HIT. Bank 1, 2: **HOLE** |
| HOST.RD | Host đọc bank `{0, 1, 2}` | Bank 1: HIT (logits). Bank 0, 2: **HOLE** |
| HOST.BE | `host_be ∈ {0xFF, một phần}` | 0xFF: HIT. Một phần: **HOLE** (TB nối cứng `8'hFF`) |
| HOST.ADDR | Địa chỉ `{0, giữa, 2047}` | 2047: **HOLE** (ảnh chỉ dùng 0..1023) |

---

## 5. Kế hoạch đóng hole

| Hole | Hành động | Đóng luôn |
| --- | --- | --- |
| CTRL.T7, HOST.RD bank 0/2 | **Test "dump từng op"**: với mỗi ảnh, chạy với `stop_after_op = k` (k = 0..9), đọc bank output của op k, so với `golden_<i>_<op>.hex`, ví dụ `golden_0_s2b.hex` (đã có sẵn trong `model/vectors`, L4 cocotb đang dùng) | Một test đóng nhiều hole: dừng sớm, và đọc cả ba bank vì out_bank đổi theo op |
| CTRL.T8 | Trong cùng test: chạy tiếp op k+1 với `first_op = k+1`, từ trạng thái bộ nhớ op k để lại | |
| CTRL.T9 | Directed: phát `start` giữa lúc RUN, kiểm tra logits vẫn khớp golden và `cycles` không đổi | Kết hợp được với scoreboard có sẵn |
| HOST.WR bank 1/2, HOST.BE, HOST.ADDR 2047 | Directed: ghi rồi đọc lại pattern ở cả 3 bank, có byte-enable một phần, ở biên địa chỉ | Thực chất là `test_act_mem` (cocotb) chạy lại trên XSim, ở quy mô nhỏ |
| LANE.TIE, LANE.N ngoài 17..35, LANE.NR, LANE.RES clamp | **Không đóng ở network.** Đánh dấu "closed ở L1, `tb/unit/test_lane.py`". Phase 2 đo chúng bằng Python trong cocotb (§7) | |
| LANE.T ≥ 2^24, LANE.CLAMP16, LANE.SAT8 nếu không hit | Đo trước. Nếu không hit: tăng số ảnh (chỉ phần này phụ thuộc dữ liệu). Nếu vẫn không hit: ghi IGN kèm phân tích chặn trên | |

**Quy tắc closure:** mỗi bin cuối cùng phải ở đúng một trong bốn trạng thái: **hit**, **ignore có lý do**, **closed ở tầng khác có trỏ tới test**, hoặc **hole được chấp nhận có lý do** (ví dụ P = 4/16 để phase 2). Không được có hole "không ai biết".

---

## 6. Những gì cố ý không đưa vào coverage

| Thứ | Vì sao | Dùng gì thay |
| --- | --- | --- |
| Bank in == out, R < ceil(P/8), weight vượt D_W | Đây là *vi phạm*, không phải tình huống cần thấy | SVA có sẵn, `controller.sv:74-77` |
| \|acc\| ≥ 2^30 | Vi phạm chặn trên của Spec §4.3 | SVA có sẵn, `lane.sv:59` |
| `first && last` cùng tick | Không thể xảy ra (R ≥ 2) | Nên thêm thành assertion |
| `y_valid` lệch với tag | Vi phạm timing contract | SVA có sẵn, `pe_array.sv` |
| Host ghi khi `busy` | Vi phạm giao thức | Nên thêm assertion ở TB |

**Quy tắc chung:** *muốn thấy nó xảy ra* thì dùng coverage. *Không được phép xảy ra* thì dùng assertion, vì assertion báo đúng cycle và có thông điệp rõ hơn.

**Ngoại lệ duy nhất là `illegal_bins` ở cross padding của CG_AGU.** Ô `stride2 × bottom/right` không thể xảy ra về mặt hình học. Nếu dùng `ignore_bins`, một AGU bị bug đọc padding cạnh dưới sẽ bị *giấu đi*: bin đó không được đếm và không có gì báo lỗi. Dùng `illegal_bins` thì quy tắc nằm ngay cạnh cross mà nó giới hạn, và vẫn báo lỗi nếu bị vi phạm. Hai điều đã kiểm bằng mutation (§8): XSim thực sự báo lỗi, nhưng **chỉ in `ERROR` ra log, không làm simulation fail**. Vì vậy `make cov` phải tự grep chữ `Illegal`.

---

## 7. Mục tiêu và các phase

| Phase | Nội dung | Tiêu chí xong |
| --- | --- | --- |
| **1** | `accel_cov.sv` (CG_CTRL, CG_OP, CG_AGU, CG_LANE) + CG_HOST trong TB + `make cov` + báo cáo `xcrg`. Chạy TB hiện tại, 3 ảnh | Có báo cáo HTML. So từng dòng "Dự đoán" ở §4 với kết quả thật và ghi chỗ đoán sai vào §8 |
| **2** | Đóng hole theo §5 (test dump từng op, start lúc bận, host directed) | Mọi bin ở một trong bốn trạng thái của §5. Ghi con số coverage trước và sau |
| **3** (tùy chọn) | Code coverage XSim (`xelab -cc_type`, cần kiểm tra cú pháp với 2024.1). Coverage L1 bằng Python trong `test_lane.py`. Chạy TB với P = 4 và 16 | Đọc được báo cáo code coverage, giải thích được các nhánh chưa chạy |

**Mục tiêu số:** 100% bin *không bị ignore* của CG_CTRL, CG_OP, CG_AGU, CG_HOST sau phase 2. CG_LANE: 100% sau khi trừ các bin được đánh dấu L1 và IGN. Con số thật ghi ở §8, **không viết vào CV trước khi có số đo**.

---

## 8. Kết quả

Đã làm: CG_CTRL, CG_OP, CG_AGU (padding), CG_LANE (SAT8, RELU). Tổng cộng **64 bin**. Chạy bằng `make cov` (khoảng 5 phút, 3 test, rồi `xcrg` merge). Một test fail nếu lệch golden hoặc nếu có illegal bin bị hit. Báo cáo nằm ở `results/cov/base/` (trước khi đóng hole) và `results/cov/merged/` (sau). Đo ngày 2026-11-16.

| Test | Stimulus | Đóng bin |
| --- | --- | --- |
| `base` | Ảnh 0–2, chạy liền 10 op, giống `make xsim` | (baseline) |
| `step` | `+STEP`: ảnh 0, từng op với `first_op = stop_after_op = k`, so bank output của từng op với `golden_0_<op>.hex`, rồi chạy ảnh 0–2 | CTRL.T7, CTRL.T8 |
| `sat` | `+IMG0=81 +N_IMG=1`: ảnh 81 | LANE.SAT8 |

| Covergroup | Bin | base | merged | Chỗ dự đoán sai |
| --- | --- | --- | --- | --- |
| cg_ctrl (CG_CTRL) | 11 (5 state + 6 transition) | 100% | 100% | — |
| cg_run_end (CTRL.T6/T7) | 2 | 50% | 100% | — (T7 là HOLE như dự đoán) |
| cg_run_start (CTRL.T8) | 2 | 50% | 100% | — (T8 là HOLE như dự đoán) |
| cg_op (CG_OP) | 21 (10 op + 4 kind + 2 res + 5 cross) | 100% | 100% | — |
| cg_agu (CG_AGU) | 21 (2 stride + 3 row + 3 col + 13 cross; 5 ô illegal) | 100% | 100% | — (không phụ thuộc dữ liệu, 1 ảnh đã hit hết) |
| cg_lane (CG_LANE) | 7 (3 sat + 4 relu) | 66.7% | 100% | **SAT8 dự đoán HIT?, thực tế là HOLE** |
| **Tổng** | **64** | **77.8%** | **100%** | |
| CG_HOST, các bin LANE còn lại | | chưa làm | | |

Điểm tổng mà `xcrg` báo là trung bình điểm của các covergroup, không phải tỷ lệ bin: base = (66.7 + 100 + 50 + 50 + 100 + 100) / 6 = 77.8%.

**Kiểm chứng chính môi trường verify** (mutation test: cố tình làm sai rồi xem có bị bắt không):

| Mutation | Kỳ vọng | Kết quả |
| --- | --- | --- |
| Trong bản sao `agu_cov`: Hin − 1 (stride 2 bị xếp vào ô "bottom") | Illegal bin `s2_bottom_right` báo lỗi | Báo 2,264 lần. Nhưng simulation vẫn in `XSIM PASS`, nên đã sửa `make cov` để fail khi có `Illegal` |
| Trong bản sao TB: chế độ step so với golden của ảnh 1 thay vì ảnh 0 | Cả 10 op báo mismatch | 10/10 op báo `MISMATCH`, `XSIM FAIL` |

Regression cocotb (`make test`) sau khi sửa TB: 59/59 pass.

**Hole quan trọng nhất: saturation int8 không xảy ra trên ảnh 0–2.**

- Coverage báo `sat_pos = sat_neg = 0` trên 32,262 output của mỗi lane. Không tin ngay con số này: kiểm chéo bằng golden model Python, và golden cũng cho 0 lần saturation trên 3 ảnh này. Vậy coverage đúng, dự đoán sai.
- Nguyên nhân: calibration dùng phương pháp `max` trên 1,000 ảnh train (`model/checkpoints/qparams.json`). Scale được chọn để giá trị lớn nhất ánh xạ tới 127, nên chỉ ảnh test vượt max của tập calibration mới saturate.
- Đếm bằng golden trên toàn bộ 10,000 ảnh test: khoảng 1,000 sự kiện saturation, không có trong 50 ảnh đầu. Ảnh đầu tiên saturate cả hai phía là **ảnh 81** (+2, −3).
- Đóng hole: export thêm vector (`model/export.py --images 82`), thêm test `sat`. Coverage đếm được đúng `sat_pos = 2`, `sat_neg = 3`, khớp golden. Đây là bằng chứng độc lập rằng covergroup sample đúng tầng pipeline.

**Năm bài học khi triển khai** (đều là câu chuyện phỏng vấn tốt):

1. **Kiểm chéo con số coverage bằng nguồn độc lập.** Số sample (10,754 pixel × số lượt ảnh) và số saturation đều được đối chiếu với golden model. Không chấp nhận một con số chưa giải thích được.
2. **Type coverage mặc định là trung bình, không phải hợp.** Lần chạy đầu cho `cg_lane` 75%, dù xét cả 8 lane thì hai bin saturation đều đã hit. Sửa bằng `type_option.merge_instances = 1`.
3. **Kết quả đúng vì lý do sai.** Ở một phiên bản trung gian, 8 instance cùng tên `cg`, và `xcrg` gộp chúng làm một khi merge DB. Điểm ra 100% nhưng số sample của từng lane sai (462,417 thay vì 86,032). Phát hiện được nhờ bài học 1. Sửa bằng `set_inst_name("%m")`.
4. **Bug của testbench, không phải của DUT.** Lần chạy `step` đầu tiên báo 10 mismatch. Nguyên nhân: XSim 2024.1 đọc `localparam string` dạng mảng thành rác, nên tên file golden sai và golden toàn `x`. Trước khi nghi RTL, hãy xem checker đang so với cái gì.
5. **Verify chính môi trường verify.** Một checker chưa từng fail thì chưa chứng minh được gì. Mutation test cho thấy checker của step bắt được lỗi. Nó cũng cho thấy illegal bin bị hit mà test vẫn pass. Nếu không thử, flow sẽ âm thầm bỏ lọt một AGU bị bug.

---

## 9. Câu hỏi phỏng vấn DV và cách trả lời bằng project này

**Code coverage và functional coverage khác nhau thế nào? Cái nào quan trọng hơn?**
Code coverage do tool đo, cho biết RTL đã *chạy* chỗ nào. Functional coverage do người viết, cho biết *tình huống theo spec* đã xảy ra chưa. Cần cả hai: code coverage tìm code chết hoặc stimulus thiếu, functional coverage tìm tính năng chưa thử. Ví dụ: dòng saturation trong `lane` được code coverage tính 100% dù chưa có giá trị nào saturate.

**Bạn xây coverage plan từ đâu?**
Từ spec, theo từng mục: §4.4 cho số học, §5.1 và §6.5 cho AGU, §7.2 và §8 cho descriptor, §9 cho host. Mỗi bin trỏ về một mục spec. Sau đó dùng dữ liệu thật (10 descriptor) để phân loại trước: bin nào chắc chắn hit, bin nào không thể đạt, bin nào sẽ thành hole.

**`ignore_bins` và `illegal_bins` khác nhau thế nào?**
Cả hai đều bị loại khỏi mẫu số. Ignore là "ngoài scope, không quan tâm", ví dụ các loại op mà ROM không dùng. Illegal là "nếu xảy ra thì báo lỗi". `stride2 × padding cạnh dưới` không thể xảy ra về mặt hình học, nên tôi để nó là illegal: nếu để ignore, một AGU bị bug sẽ bị giấu đi. Tôi kiểm bằng mutation và thấy XSim chỉ in `ERROR` mà không làm test fail, nên Makefile phải tự kiểm log.

**Chọn sampling event thế nào? Sample sai thì sao?**
`lane` có pipeline hậu xử lý 6 tầng. Nếu sample mọi thứ ở `y_valid`, giá trị ở các tầng đầu đã thuộc về pixel khác, và coverage trở thành số vô nghĩa. Tôi sample mỗi coverpoint bằng đúng bit valid của tầng đó (`v[k]`).

**Vì sao dùng `bind`?**
Không đụng vào RTL: synthesis không thấy covergroup, người design không phải review code DV, và có thể bật hoặc tắt coverage mà không sửa design.

**Coverage 100% có nghĩa là không còn bug?**
Không. Coverage chỉ nói stimulus đã đi tới đâu. Phải có checker mạnh. Ở đây checker là golden model bit-exact cho từng byte của mọi bank.

**Hole thú vị nhất bạn tìm được là gì?**
(Điền bằng kết quả thật.) Ứng viên theo dự đoán: tính năng `stop_after_op` dùng để debug trên board nhưng chưa từng được chạy trong XSim; và trường hợp tie âm khi làm tròn, gần như không thể xảy ra ở mức network, nên chứng minh được vì sao cần unit test directed.

**Vì sao không đo coverage bằng Verilator?**
Verilator 5.049 bỏ qua covergroup (cảnh báo `COVERIGN`). Tôi đã thử và xác nhận. Vì vậy coverage SV chạy trên XSim, còn regression nhanh vẫn ở Verilator.

**Chạy thêm random có tăng coverage không?**
Chỉ tăng ở phần phụ thuộc dữ liệu (`lane`). Phần control (FSM, AGU, descriptor) giống hệt nhau với mọi ảnh, nên muốn đóng hole ở đó phải viết directed test. Biết phần nào phụ thuộc dữ liệu giúp không lãng phí thời gian chạy simulation.

**Type coverage và instance coverage?**
8 lane dùng chung một covergroup type. Tôi gộp theo type, vì câu hỏi là "có lane nào saturate chưa". Nếu các lane khác nhau về cấu trúc thì mới cần per-instance.
