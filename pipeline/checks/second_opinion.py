"""CHECK 6 — Ý kiến thứ hai: so nhãn với một model LỚN HƠN (yolo26l).   ★★★ (khó nhất, đáng điểm nhất)

Test:  pytest tests/test_second_opinion.py -q

Máy kiểm quy tắc, người kiểm ý nghĩa (slide). Các lỗi như thiếu nhãn / gán nhầm lớp hợp lệ / box lỏng
KHÔNG bắt được bằng quy tắc cú pháp. Ta nhờ một model mạnh hơn "nhìn lại" và CHỈ CẢNH BÁO (model cũng có thể sai):
những ảnh bị cờ sẽ vào hàng đợi cho NGƯỜI duyệt.

`preds[stem]` = list `[id_lớp, conf, cx, cy, w, h]` của model (lấy qua `get_preds(ds, cfg, "checker")` nếu preds=None).
`L = ds.valid_boxes(stem)` = list `(id_lớp, cx, cy, w, h)` của nhãn (đã bỏ dòng hỏng).
Ngưỡng ở `cfg["second_opinion"]`: conf, min_area_px, fp_conf, iou_missing, iou_match, iou_loose.

Thuật toán gợi ý, với từng ảnh (bỏ qua ảnh không có trong preds hoặc không có file nhãn):
  P = dự đoán có conf >= conf  VÀ diện tích px (w*W * h*H) >= min_area_px
  Với mỗi dự đoán r trong P: lấy các nhãn có IoU(r, nhãn) >= iou_missing  (cands)
   - không có cands                            -> POSSIBLE_MISSING     (model thấy vật mà nhãn không có box)
   - có cands cùng lớp, tốt nhất IoU < iou_loose -> POSSIBLE_LOOSE_BOX  (đúng vật, box lỏng/lệch)
   - không có cands cùng lớp, nhưng cands tốt nhất IoU >= iou_match (khác lớp) -> POSSIBLE_WRONG_CLASS
  Với mỗi dòng nhãn hợp lệ: nếu IoU với MỌI dự đoán (conf >= fp_conf, không lọc diện tích) đều < iou_missing
                                             -> POSSIBLE_FALSE_POS  (box nhãn không khớp vật nào model thấy; Issue.line = số dòng)

Chi tiết các ca biên (test kiểm đúng các ca này)
- `cands` gồm nhãn MỌI lớp có IoU >= iou_missing; "tốt nhất cùng lớp" = cands cùng lớp có IoU lớn nhất; "tốt nhất khác lớp" tương tự với cands khác lớp.
- Thứ tự quyết định cho mỗi dự đoán: (1) cands rỗng -> MISSING. (2) có cands cùng lớp: IoU tốt nhất < iou_loose -> LOOSE_BOX, ngược lại KHÔNG cờ
  (nhãn đúng lớp đã phủ vật này, kể cả khi còn nhãn khác lớp chồng lên). (3) không có cands cùng lớp: nếu IoU tốt nhất khác lớp >= iou_match -> WRONG_CLASS;
  nếu chỉ có khác lớp với IoU trong [iou_missing, iou_match) -> không cờ gì (mơ hồ: để cho FALSE_POS / lần duyệt khác).
- Một dự đoán sinh tối đa MỘT issue (MISSING / LOOSE_BOX / WRONG_CLASS); một ảnh có thể có nhiều issue.
- Thứ tự issue: theo `ds.image_files()` rồi theo thứ tự dự đoán trong `preds[stem]`, cuối cùng là các FALSE_POS theo số dòng; `Issue.image` = stem, `Issue.line` chỉ đặt cho FALSE_POS.

Lưu ý số dòng: dùng `ds.read_label_lines(stem)` (giữ số dòng gốc, kể cả dòng hỏng/trống) để lấy `Issue.line`; `valid_boxes` KHÔNG giữ số dòng.

Tất cả severity WARN; `Issue.extra` nên có {"conf": ...} hoặc {"iou": ...} (hàng đợi duyệt dùng conf để xếp ưu tiên).

Gợi ý
- `iou_xywh` có sẵn. Dòng nhãn hỏng không được làm script chết (dùng `ds.valid_boxes` và `parse_yolo_line` trong try).
- Kết quả phụ thuộc mạnh vào ngưỡng: calibrate chúng ở Bước 3 thay vì đoán.
"""
from ..common import WARN, Issue, iou_xywh, parse_yolo_line  # noqa: F401
from ..model_cache import get_preds  # noqa: F401


def run(ds, cfg, preds=None):
    if preds is None:
        preds = get_preds(ds, cfg, "checker")
    rules = cfg["second_opinion"]
    issues = []
    for image in ds.image_files():
        stem = image.stem
        raw_lines = ds.read_label_lines(stem)
        if raw_lines is None or stem not in preds:
            continue

        labels = []
        for line_no, text in raw_lines:
            try:
                box = parse_yolo_line(text)
            except (TypeError, ValueError):
                continue
            if 0 <= box[0] < len(ds.classes):
                labels.append((line_no, box[0], box[1:]))

        size = ds.image_size(stem)
        if size:
            image_w, image_h = size
        else:
            image_w = image_h = 0
        image_preds = list(preds.get(stem) or [])
        strong = []
        for pred in image_preds:
            cls, conf, cx, cy, w, h = pred
            box = (cx, cy, w, h)
            if conf >= rules["conf"] and w * image_w * h * image_h >= rules["min_area_px"]:
                strong.append((int(cls), float(conf), box))

        for pred_cls, confidence, pred_box in strong:
            candidates = [(label_cls, iou_xywh(pred_box, label_box))
                          for _, label_cls, label_box in labels
                          if iou_xywh(pred_box, label_box) >= rules["iou_missing"]]
            if not candidates:
                issues.append(Issue("second_opinion", WARN, "POSSIBLE_MISSING", stem,
                                    "model thấy vật chưa có box nhãn tương ứng",
                                    extra={"conf": confidence}))
                continue
            same = [iou for label_cls, iou in candidates if label_cls == pred_cls]
            other = [iou for label_cls, iou in candidates if label_cls != pred_cls]
            if same:
                best = max(same)
                if best < rules["iou_loose"]:
                    issues.append(Issue("second_opinion", WARN, "POSSIBLE_LOOSE_BOX", stem,
                                        "box nhãn cùng lớp có thể bị lỏng hoặc lệch",
                                        extra={"conf": confidence, "iou": best}))
            elif other and max(other) >= rules["iou_match"]:
                issues.append(Issue("second_opinion", WARN, "POSSIBLE_WRONG_CLASS", stem,
                                    "model và nhãn có thể bất đồng về lớp",
                                    extra={"conf": confidence, "iou": max(other)}))

        fp_preds = [(int(p[0]), float(p[1]), (p[2], p[3], p[4], p[5]))
                    for p in image_preds if p[1] >= rules["fp_conf"]]
        for line_no, _, label_box in labels:
            best_iou = max((iou_xywh(label_box, pred_box) for _, _, pred_box in fp_preds), default=0.0)
            if best_iou < rules["iou_missing"]:
                issues.append(Issue("second_opinion", WARN, "POSSIBLE_FALSE_POS", stem,
                                    "box nhãn không khớp dự đoán model đủ tin cậy", line_no,
                                    extra={"iou": best_iou}))
    return issues
