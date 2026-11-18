# Báo cáo Day 09 — Trần Anh Tùng, 2A202603280

## 1. Kết luận trước

Pipeline kết luận **HOLD**. Intake nhận 193/224 ảnh, loại 31 ảnh (2 hỏng, 3 dưới kích thước tối thiểu, 8 trùng exact, 7 trùng gần, 11 rò rỉ test/val). Sau mô phỏng duyệt 80 ảnh, không còn lỗi bắt buộc nhưng vẫn có cảnh báo trên 53/193 ảnh (27,46%), cao hơn ngưỡng Hold 10%. Có 193 ảnh trong bản export nháp; đây chưa phải bản phát hành.

## 2. Lỗi và phân việc

Số liệu trước sửa lấy từ `02_error_list_v1.csv`; lỗi cửa vào có mẫu số 224 ảnh, lỗi QC trên 193 ảnh được nhận. Với cảnh báo model, ghi số issue và số ảnh bị ảnh hưởng vì một ảnh có thể có nhiều dự đoán.

| Mã lỗi | Số liệu trước sửa | Xử lý |
|---|---:|---|
| CORRUPT_IMAGE / BAD_SIZE | 2/224; 3/224 | Máy loại ảnh |
| DUP_IMAGE_EXACT / DUP_IMAGE_NEAR / LEAK_TEST | 8/224; 7/224; 11/224 | Máy loại ảnh; near duplicate chọn `phash_dist=16` |
| BAD_CLASS_ID / BAD_FORMAT / BOX_ZERO / DUP_BOX | 6; 3; 4; 7 issue trên 193 ảnh | Máy xoá dòng lỗi |
| BOX_OUT_OF_IMAGE / BAD_CLASS_NAME | 8 dòng; 2 issue ở data.yaml | Máy clip 8 box và chuẩn hoá tên lớp |
| MISSING_LABEL_FILE | 6/193 | Chuyển người gán; máy không tạo nhãn rỗng |
| EMPTY_LABEL / BOX_TINY / BOX_HUGE / CLASS_RARE | 11; 6; 3; 4 issue | Cảnh báo cho người; CLASS_RARE là cảnh báo cấp dataset |
| POSSIBLE_MISSING / POSSIBLE_LOOSE_BOX | 148 issue trên 84 ảnh / 43 issue trên 35 ảnh | Người kiểm ngữ nghĩa và độ khít box |
| POSSIBLE_WRONG_CLASS / POSSIBLE_FALSE_POS | 20 issue trên 19 ảnh / 28 issue trên 26 ảnh | Người đối chiếu ảnh, nhãn và dự đoán model |

`03_fixes.csv` ghi 35 thay đổi: 20 `drop_line`, 8 `clip_box`, 6 `needs_label`, 1 `rename_classes`. Hàng đợi có 138 ảnh nhưng bộ mô phỏng chỉ duyệt 80. Ảnh `img_0160` đứng đầu (priority 35.692; cảnh báo thiếu nhãn và bất đồng lớp); ảnh có nhiều dự đoán thiếu nhãn hoặc sai lớp được ưu tiên. Mô phỏng dùng nhãn tham chiếu, không phải một người đã kiểm thực tế. Sau mô phỏng, `07_error_list_v3.csv` còn 90 POSSIBLE_MISSING issue trên 60 ảnh, 32 POSSIBLE_LOOSE_BOX trên 26 ảnh, 10 POSSIBLE_WRONG_CLASS trên 9 ảnh, 24 POSSIBLE_FALSE_POS trên 23 ảnh và các cảnh báo box/nhãn khác.

## 3. Calibration (2 ngưỡng)

| Tham số | Khởi đầu → chọn | Precision / recall trên calib | Lý do |
|---|---|---|---|
| `duplicates.phash_dist` | 2 → **16** | near duplicate: 1.00/0.50 → 1.00/0.83; exact: 1.00/1.00 → 1.00/1.00 | Bắt 5/6 ảnh gần trùng trong khi không có FP; ở 20 recall exact giảm còn 0.33. |
| `second_opinion.conf` | 0.25 → **0.25** | wrong class 0.56/0.83; missing 0.50/1.00; loose box 0.29/0.40; false positive 0.31/1.00 | Giữ ngưỡng khởi đầu để ưu tiên recall cho cảnh báo người xử lý; precision thấp tạo thêm việc xem lại. |

Calibration có thể đánh lừa vì chỉ có 39 ảnh và số lỗi mỗi nhóm nhỏ; ở conf 0.25 chỉ có 5 lỗi loose-box chèn, bắt được 2. Bộ calib cũng không có lỗi LEAK_TEST và khác phân bố raw. Kết quả calib không đảm bảo hiệu năng tương tự trên raw.

## 4. Cửa chặn và điểm mù

Gate thử với `python -m pipeline.run --budget 0 --reports work/rep_nb --export-dir work/exp_nb`: kết luận **Rework**, mã thoát **20**, còn 6 lỗi bắt buộc do 6 ảnh thiếu file nhãn và **không** tạo `work/exp_nb/clean_v1`. Ở lần chạy chính, sau mô phỏng duyệt không còn lỗi bắt buộc; 53/193 ảnh còn cảnh báo nên kết luận Hold. Cần xử lý ít nhất 34 ảnh cảnh báo trong số 53 ảnh còn lại để xuống dưới 10% (tối đa 19/193), rồi chạy lại gate theo quy trình duyệt được phép.

Điểm mù đã thấy: (1) `img_0001` còn thiếu box một người chỉ thấy nửa thân; (2) `img_0007` bỏ sót nhiều xe ở xa và không nhất quán; (3) `img_0002` có hai box person bị nghi gán cho vật giống kiện hàng; (4) `img_0004` nhãn rỗng dù người xem thấy xe hơi, còn train nằm ngoài bốn lớp car/person/truck/bus. Second opinion chỉ đưa cảnh báo, model cũng có thể bỏ sót hoặc nhầm lớp; bộ lớp cố định không thể biểu diễn các lớp ngoài danh sách.

## 5. Train: raw vs clean

**Chưa chạy.** Phần train Colab là tùy chọn và mất thêm thời gian; vì vậy không có kết quả mAP để kết luận clean tốt hơn raw.

## 6. Quyết định và ghi chú AI

Quyết định cuối là **HOLD**; cần xử lý đủ cảnh báo còn tồn theo quy trình duyệt được phép rồi chạy lại pipeline. AI được dùng hỗ trợ triển khai bốn module từ docstring và test có sẵn. Prompt chính: “Triển khai các stub theo hợp đồng đầu vào/đầu ra trong docstring và các ca kiểm tra của repo.” Cách kiểm: 79 test đạt, chạy calibration, pipeline chính và phép thử gate ngân sách 0. Một lỗi AI phát hiện trong lúc rà lại bản đầu: `needs_label` vẫn có thể được ghi cho ảnh đã bị loại; đã sửa để bỏ bản ghi đó.
