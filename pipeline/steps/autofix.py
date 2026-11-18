"""BƯỚC 2/4 — Sửa tự động những lỗi bắt buộc mà máy sửa được AN TOÀN.   ★★

Test:  pytest tests/test_autofix.py -q

`fix(ds, issues, cfg) -> list[dict]`: duyệt `issues` (chỉ lỗi severity ERROR), sửa thẳng vào thư mục `ds`,
và trả về danh sách thay đổi; mỗi phần tử có khoá: image, line, action, before, after
(đây chính là file `03_fixes.csv` — bằng chứng pipeline đã làm gì, người có thể kiểm lại).

| code lỗi                                       | cách sửa                                    | action           |
|------------------------------------------------|---------------------------------------------|------------------|
| BAD_FORMAT, BAD_CLASS_ID, BOX_ZERO, DUP_BOX    | xoá dòng đó khỏi file nhãn                  | "drop_line"      |
| BOX_OUT_OF_IMAGE                               | cắt box về trong [0,1] (giữ nguyên lớp)     | "clip_box"       |
| MISSING_LABEL_FILE                             | KHÔNG sửa file (máy không thể bịa nhãn): ghi 1 dòng fix, before="(không có file)", after="chuyển người gán" | "needs_label" |
| BAD_CLASS_NAME                                 | ghi lại `names` trong data.yaml đúng `cfg["classes"]` | "rename_classes" |
| DUP_IMAGE_*, LEAK_TEST, CORRUPT_IMAGE, BAD_SIZE| xoá ảnh + nhãn khỏi `ds`                    | "remove_image"   |

Bẫy cần nghĩ tới (có test cho từng cái)
- Một file có NHIỀU dòng lỗi: số dòng trong `issues` là số dòng GỐC. Nếu xoá từng dòng một thì số dòng lệch.
  Gom theo file, rồi ghi lại MỘT lần.
- Sau khi cắt, box có thể không còn diện tích (nằm hẳn ngoài ảnh): lúc đó xoá dòng thay vì ghi box rỗng.
- Một dòng có 2 lỗi (vd. BOX_OUT_OF_IMAGE + DUP_BOX): xoá dòng thắng, chỉ ghi 1 fix `drop_line`, không ghi thêm `clip_box`. Dòng trống ở giữa file vẫn đếm vào số dòng gốc.
- Ảnh vừa bị xoá (DUP_IMAGE_*...) mà còn issue dòng của chính nó: bỏ qua êm, không được báo lỗi/chết.
- Không động tới lỗi WARN (cảnh báo là việc của người). Không sửa file ở `data/raw/` — chỉ sửa `ds`.
- Chạy lần 2 trên dữ liệu đã sửa phải không làm gì thêm (idempotent) — NGOẠI LỆ duy nhất: `needs_label` được ghi lại mỗi lần còn lỗi `MISSING_LABEL_FILE` (vì ảnh vẫn chưa có nhãn).

- `needs_label` KHÔNG tạo file nhãn rỗng (rỗng = "ảnh nền", khác với "chưa gán"). `review_queue` sẽ đẩy ảnh này lên đầu hàng đợi cho người.

Gợi ý: `yaml.safe_load / safe_dump`.
"""
from collections import defaultdict  # noqa: F401

import yaml  # noqa: F401

from ..common import ERROR, parse_yolo_line  # noqa: F401


def fix(ds, issues, cfg):
    fixes = []
    drop_codes = {"BAD_FORMAT", "BAD_CLASS_ID", "BOX_ZERO", "DUP_BOX"}
    remove_codes = {"DUP_IMAGE_EXACT", "DUP_IMAGE_NEAR", "LEAK_TEST", "CORRUPT_IMAGE", "BAD_SIZE"}
    per_image = defaultdict(list)
    remove_images = set()
    rename = False
    for issue in issues:
        if issue.severity != ERROR:
            continue
        if issue.code in remove_codes:
            remove_images.add(issue.image)
        elif issue.code == "BAD_CLASS_NAME":
            rename = True
        elif issue.code == "MISSING_LABEL_FILE":
            fixes.append({"image": issue.image, "line": "", "action": "needs_label",
                          "before": "(không có file)", "after": "chuyển người gán"})
        elif issue.code in drop_codes | {"BOX_OUT_OF_IMAGE"} and issue.line is not None:
            per_image[issue.image].append(issue)

    for stem in sorted(remove_images):
        targets = [p for p in ds.image_files() if p.stem == stem]
        label = ds.label_path(stem)
        existed = bool(targets or label.exists())
        for path in targets:
            path.unlink(missing_ok=True)
        label.unlink(missing_ok=True)
        if existed:
            fixes.append({"image": stem, "line": "", "action": "remove_image",
                          "before": "ảnh và nhãn trong dataset", "after": "đã loại bỏ"})

    if remove_images:
        fixes = [f for f in fixes if f["action"] != "needs_label" or f["image"] not in remove_images]

    # Mọi số dòng trong issues là số dòng gốc; áp dụng gộp một lần cho mỗi file.
    for stem in sorted(per_image):
        if stem in remove_images:
            continue
        path = ds.label_path(stem)
        if not path.exists():
            continue
        original = path.read_text(encoding="utf-8", errors="replace").splitlines()
        by_line = defaultdict(list)
        for issue in per_image[stem]:
            by_line[issue.line].append(issue)
        output = []
        for line_no, before in enumerate(original, 1):
            line_issues = by_line.get(line_no, [])
            codes = {i.code for i in line_issues}
            if codes & drop_codes:
                fixes.append({"image": stem, "line": line_no, "action": "drop_line",
                              "before": before, "after": "(đã xoá)"})
                continue
            if "BOX_OUT_OF_IMAGE" in codes:
                try:
                    cls, cx, cy, w, h = parse_yolo_line(before)
                    x1, y1 = max(0.0, cx - w / 2), max(0.0, cy - h / 2)
                    x2, y2 = min(1.0, cx + w / 2), min(1.0, cy + h / 2)
                    nw, nh = x2 - x1, y2 - y1
                    if nw <= 0 or nh <= 0:
                        fixes.append({"image": stem, "line": line_no, "action": "drop_line",
                                      "before": before, "after": "(box nằm ngoài ảnh)"})
                        continue
                    after = " ".join(format(v, ".8g") for v in (cls, (x1 + x2) / 2,
                                                                    (y1 + y2) / 2, nw, nh))
                    output.append(after)
                    fixes.append({"image": stem, "line": line_no, "action": "clip_box",
                                  "before": before, "after": after})
                    continue
                except (TypeError, ValueError):
                    # Dữ liệu có thể đã đổi sau khi issue được tạo; không làm file hỏng thêm.
                    output.append(before)
                    continue
            output.append(before)
        path.write_text("\n".join(output) + ("\n" if original else ""), encoding="utf-8")

    if rename:
        path = ds.yaml_path
        before = path.read_text(encoding="utf-8") if path.exists() else "(không có file)"
        data = yaml.safe_load(before) if path.exists() else {}
        data = data or {}
        data["names"] = list(cfg["classes"])
        after = yaml.safe_dump(data, allow_unicode=True, sort_keys=False)
        path.write_text(after, encoding="utf-8")
        fixes.append({"image": "data.yaml", "line": "", "action": "rename_classes",
                      "before": before, "after": after})
    return fixes
