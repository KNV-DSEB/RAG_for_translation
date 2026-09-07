"""C11 — mọi điểm vào phải dựng được, và danh sách điểm vào lấy từ ĐĨA.

Vì sao có tệp này
-----------------
`web/gallery.html` là một trang tĩnh riêng, không nằm trong SPA. Nó hỏng suốt một vòng
sửa mà không ai biết, vì hai chỗ cùng bỏ sót:

1. **Kiểm cú pháp sai chế độ.** `node --check` đọc tệp `.js` như *script* CommonJS, không
   như *ES module*. Đo trên chính máy này: một tệp có chuỗi bị xuống dòng thật giữa dấu
   nháy — lỗi cú pháp chắc chắn — cho `exit=0` khi chạy `node --check x.js`, nhưng `exit=1`
   khi chạy `node --check x.mjs` hoặc `node --input-type=module --check`.

2. **Đếm điểm vào bằng cách lần theo import.** Tìm từ `index.html` trở đi thì không bao
   giờ thấy `gallery.html` — nó là gốc riêng. Danh sách điểm vào phải quét TỆP TRÊN ĐĨA,
   không suy ra từ đồ thị phụ thuộc của một gốc đã biết.

Bài học chung: một phép kiểm chỉ đáng tin khi biết rõ nó KHÔNG bao phủ cái gì.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"

# Bỏ qua thư mục sinh ra / tải về, không phải mã nguồn của dự án.
SKIP_DIRS = {"node_modules", ".venv", "__pycache__", "vendor", ".qa"}


def _clean(paths):
    return [p for p in paths if not any(part in SKIP_DIRS for part in p.parts)]


def _html_entrypoints() -> list[Path]:
    """Mọi trang HTML trên đĩa — ĐÂY là danh sách điểm vào, không phải đồ thị import."""
    return sorted(_clean(WEB.rglob("*.html")))


def _js_modules() -> list[Path]:
    return sorted(_clean((WEB / "js").rglob("*.js")))


def test_c11a_moi_module_js_parse_duoc_o_che_do_module():
    """Mọi `.js` trong web/js phải parse ĐÚNG CHẾ ĐỘ MODULE.

    Không dùng `node --check <file>.js`: nó đọc như script và bỏ lọt lỗi thật.
    """
    if not _js_modules():
        pytest.skip("không có tệp js nào")

    broken: list[str] = []
    for path in _js_modules():
        proc = subprocess.run(
            ["node", "--input-type=module", "--check"],
            input=path.read_bytes(),
            capture_output=True,
        )
        if proc.returncode != 0:
            first = proc.stderr.decode("utf-8", "replace").strip().splitlines()
            broken.append(f"{path.relative_to(ROOT).as_posix()}: " + " | ".join(first[:3]))

    assert not broken, "Module JS không parse được ở chế độ module:\n  " + "\n  ".join(broken)


def test_c11b_moi_trang_html_tro_toi_tep_co_that():
    """Mọi `src`/`href` cục bộ trong mọi trang HTML phải tồn tại trên đĩa.

    Bắt được cả trang mồ côi lẫn đường dẫn gõ sai — kể cả trang không SPA nào nạp tới.
    """
    pages = _html_entrypoints()
    assert pages, "không tìm thấy trang HTML nào — danh sách điểm vào không thể rỗng"

    missing: list[str] = []
    for page in pages:
        html = page.read_text(encoding="utf-8", errors="replace")
        refs = re.findall(r'(?:src|href)\s*=\s*["\']([^"\']+)["\']', html)
        for ref in refs:
            if ref.startswith(("http://", "https://", "//", "data:", "#", "mailto:")):
                continue
            target = (WEB / ref.lstrip("/")) if ref.startswith("/") else (page.parent / ref)
            if not target.exists():
                missing.append(f"{page.relative_to(ROOT).as_posix()} → {ref}")

    assert not missing, "Trang HTML trỏ tới tệp không có thật:\n  " + "\n  ".join(missing)


def test_c11c_moi_script_module_cua_trang_html_deu_parse_duoc():
    """Nối hai phép trên: script mà TRANG thật sự nạp phải parse được ở chế độ module.

    `gallery.html` hỏng vì `gallery.js` hỏng. Không có phép này thì một trang mồ côi
    vẫn nằm ngoài mọi vòng kiểm.
    """
    checked = 0
    broken: list[str] = []
    for page in _html_entrypoints():
        html = page.read_text(encoding="utf-8", errors="replace")
        for m in re.finditer(
            r'<script[^>]*type\s*=\s*["\']module["\'][^>]*src\s*=\s*["\']([^"\']+)["\']', html
        ):
            ref = m.group(1)
            if ref.startswith(("http://", "https://", "//")):
                continue
            target = (WEB / ref.lstrip("/")) if ref.startswith("/") else (page.parent / ref)
            if not target.exists():
                continue          # đã do C11b bắt
            checked += 1
            proc = subprocess.run(
                ["node", "--input-type=module", "--check"],
                input=target.read_bytes(),
                capture_output=True,
            )
            if proc.returncode != 0:
                broken.append(
                    f"{page.name} nạp {ref}: "
                    + proc.stderr.decode("utf-8", "replace").strip().splitlines()[0]
                )

    assert checked, "không trang nào nạp script module — nghi phép kiểm này đã mù"
    assert not broken, "Trang HTML nạp script hỏng:\n  " + "\n  ".join(broken)


def test_c11d_moi_module_python_backend_bien_dich_duoc():
    """Đối xứng phía Python: sửa tệp bằng script cũng làm vỡ chuỗi y hệt."""
    proc = subprocess.run(
        [sys.executable, "-m", "compileall", "-q", "-x", r"__pycache__", str(ROOT / "backend")],
        capture_output=True,
    )
    assert proc.returncode == 0, (
        "backend không biên dịch được:\n"
        + proc.stdout.decode("utf-8", "replace")
        + proc.stderr.decode("utf-8", "replace")
    )
