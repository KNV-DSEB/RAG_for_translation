"""Kiểm chứng ĐỘC LẬP: đọc lại từ cả nguồn lẫn đích, không tin kết quả của `migrate`.

Chạy được ở một tiến trình khác, sau khi tiến trình chuyển đã thoát. Đó là điều kiện
bắt buộc: kiểm bằng biến còn trong bộ nhớ của chính lần chuyển thì chỉ chứng minh mã
đã chạy, không chứng minh dữ liệu đã tới nơi.

Đếm bằng nhau CHƯA ĐỦ. Xoá một dòng rồi chèn một dòng khác vẫn cho cùng con số, nên
phải so cả id và nội dung. `verify` băm từng dòng theo các cột nghiệp vụ trong
`spec.DURABLE` và đối chiếu hai bên.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

from backend.database import driver
from backend.db import get_conn
from backend.migration import inventory
from backend.migration.spec import DURABLE, RUNTIME_SKIPPED, Entity


@dataclass
class Finding:
    level: str          # "FAIL" | "WARN"
    area: str
    detail: str


@dataclass
class VerifyResult:
    ok: bool = True
    findings: list[Finding] = field(default_factory=list)
    counts: dict[str, tuple[int, int]] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    def fail(self, area: str, detail: str) -> None:
        self.ok = False
        self.findings.append(Finding("FAIL", area, detail))

    def warn(self, area: str, detail: str) -> None:
        self.findings.append(Finding("WARN", area, detail))


def _row_digest(row: dict[str, Any], columns: tuple[str, ...]) -> str:
    """Băm một dòng theo các cột NGHIỆP VỤ.

    Không băm `created_at`: SQLite và PostgreSQL sinh mặc định theo định dạng khác nhau,
    nên nó sẽ luôn lệch mà chẳng nói lên điều gì. Cột nào mang ý nghĩa nghiệp vụ thì
    khai trong `spec.DURABLE` và được so ở đây.
    """
    payload = {}
    for c in columns:
        v = row.get(c)
        # SQLite lưu boolean là 0/1, PostgreSQL có thể trả về True/False. Chuẩn hoá về
        # số để hai bên so được với nhau — khác biểu diễn không phải khác dữ liệu.
        if isinstance(v, bool):
            v = int(v)
        elif v is not None and not isinstance(v, (int, float, str)):
            v = str(v)
        payload[c] = v
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()[:16]


def _assert_columns_exist(src, ent: Entity, res: VerifyResult) -> tuple[str, ...]:
    """Cột khai trong `spec` mà không tồn tại thật thì phải BÁO, không được lặng lẽ bỏ qua.

    Đây là lỗi đã xảy ra: `spec` khai `term_vi_normalized` trong khi cột thật tên
    `term_vi_norm`. Cả hai phía đều trả `None` cho tên không tồn tại, nên băm hai bên
    bằng nhau và verify báo ĐẠT — một phép kiểm không kiểm gì cả, mà lại tự tin.

    Bắt được nhờ dựng nguồn test bằng chính schema của ứng dụng. Nếu nguồn test cũng do
    tay viết theo trí nhớ thì hai cái sai sẽ khớp nhau và không ai thấy.
    """
    from backend.database import introspect

    src_cols = {str(r["name"]) for r in src.execute(f"PRAGMA table_info({ent.table})")}
    with get_conn() as conn:
        dst_cols = introspect.table_columns(conn, ent.table)

    ma = [c for c in ent.hash_columns if c not in src_cols and c not in dst_cols]
    if ma:
        res.fail(
            ent.table,
            f"spec khai cột không tồn tại ở cả hai phía: {ma}. So sánh những cột này là "
            "so None với None và luôn báo khớp — phép kiểm sẽ nói dối.",
        )
    return tuple(c for c in ent.hash_columns if c in src_cols and c in dst_cols)


def _compare_entity(src, ent: Entity, res: VerifyResult) -> None:
    cols = _assert_columns_exist(src, ent, res)
    src_rows = {
        int(r[ent.pk]): dict(r) for r in src.execute(f'SELECT * FROM "{ent.table}"')
    }
    with get_conn() as conn:
        dst_rows = {
            int(r[ent.pk]): dict(r) for r in conn.execute(f'SELECT * FROM "{ent.table}"')
        }

    res.counts[ent.table] = (len(src_rows), len(dst_rows))

    missing = sorted(set(src_rows) - set(dst_rows))
    if missing:
        res.fail(ent.table, f"thiếu {len(missing)} dòng ở đích, id: {missing[:8]}")

    # Dòng thừa ở đích KHÔNG phải lỗi: cloud có thể đã có dữ liệu tạo trực tiếp trên đó.
    extra = sorted(set(dst_rows) - set(src_rows))
    if extra:
        res.notes.append(
            f"{ent.table}: {len(extra)} dòng chỉ có ở đích (dữ liệu tạo trực tiếp trên cloud)"
        )

    if not cols:
        return
    lech = []
    for pk in sorted(set(src_rows) & set(dst_rows)):
        a = _row_digest(src_rows[pk], cols)
        b = _row_digest(dst_rows[pk], cols)
        if a != b:
            khac = [
                c for c in cols
                if _row_digest(src_rows[pk], (c,)) != _row_digest(dst_rows[pk], (c,))
            ]
            lech.append(f"id={pk} cột: {', '.join(khac)}")
    if lech:
        res.fail(ent.table, f"{len(lech)} dòng lệch nội dung — {'; '.join(lech[:4])}")


def _check_ownership(res: VerifyResult, owner_user_id: str) -> None:
    """Mọi hồ sơ đã chuyển phải có đúng chủ sở hữu.

    Hồ sơ chưa có chủ trên cloud là hồ sơ KHÔNG AI đọc được (xem `auth/ownership.py`) —
    nên bỏ sót bước này là chuyển xong rồi mà chuyên gia mở lên thấy trống trơn.
    """
    with get_conn() as conn:
        rows = conn.execute("SELECT id, name, owner_user_id FROM workspaces").fetchall()
    khong_chu = [int(r["id"]) for r in rows if not r["owner_user_id"]]
    sai_chu = [
        int(r["id"]) for r in rows
        if r["owner_user_id"] and str(r["owner_user_id"]) != owner_user_id
    ]
    if khong_chu:
        res.fail("ownership", f"{len(khong_chu)} hồ sơ chưa có chủ, id: {khong_chu[:8]}")
    if sai_chu:
        res.notes.append(f"{len(sai_chu)} hồ sơ thuộc về người dùng khác (không phải lỗi)")


def _check_runtime_not_migrated(src, res: VerifyResult) -> None:
    """Trạng thái bảo mật lúc chạy KHÔNG được mang từ máy cá nhân sang.

    Kiểm bằng cách đối chiếu id: đích có dòng nào TRÙNG id với nguồn nghĩa là đã bị
    nhập vào. Đích có dòng riêng thì bình thường — đó là hoạt động thật trên cloud.
    """
    from backend.database import introspect

    for table in RUNTIME_SKIPPED:
        try:
            src_cols = {str(r["name"]) for r in src.execute(f"PRAGMA table_info({table})")}
        except Exception:  # noqa: BLE001 — bảng có thể không tồn tại ở nguồn
            continue
        if not src_cols:
            continue

        # Không phải bảng nào cũng có cột `id`: `operation_calls` khoá theo
        # (operation_id, destination, provider). Dùng khoá thật của từng bảng, chứ không
        # giả định mọi bảng đều có khoá thay thế — giả định đó làm phép kiểm ném lỗi và
        # không kiểm được gì.
        key = ("id",) if "id" in src_cols else ("operation_id", "destination", "provider")
        key = tuple(c for c in key if c in src_cols)
        if not key:
            continue
        cols = ", ".join(f'"{c}"' for c in key)

        src_ids = {tuple(r[c] for c in key) for r in src.execute(f'SELECT {cols} FROM "{table}"')}
        if not src_ids:
            continue
        with get_conn() as conn:
            if table not in set(introspect.table_names(conn)):
                continue
            dst_ids = {
                tuple(r[c] for c in key)
                for r in conn.execute(f'SELECT {cols} FROM "{table}"')
            }
        trung = src_ids & dst_ids
        if trung:
            res.fail(
                "runtime-consent",
                f"`{table}`: {len(trung)} dòng trạng thái chạy đã bị mang từ máy sang. "
                "Đồng ý trên máy cá nhân KHÔNG phải đồng ý cho máy chủ ở nơi khác.",
            )


def _check_vectors(src, res: VerifyResult) -> None:
    from backend.rag import pgvector_store

    n_src = int(
        src.execute(
            "SELECT COUNT(*) AS n FROM document_chunks WHERE text IS NOT NULL AND text <> ''"
        ).fetchone()["n"]
    )
    n_dst = pgvector_store.count()
    res.counts["_vectors"] = (n_src, n_dst)
    if n_dst < n_src:
        res.fail("pgvector", f"chỉ có {n_dst}/{n_src} chunk mang vector")

    with get_conn() as conn:
        row = conn.execute(
            "SELECT vector_dims(embedding) AS d FROM document_chunks "
            "WHERE embedding IS NOT NULL LIMIT 1"
        ).fetchone()
    if row is not None and int(row["d"]) != pgvector_store.EMBEDDING_DIM:
        res.fail("pgvector", f"số chiều {row['d']} khác khai báo {pgvector_store.EMBEDDING_DIM}")


def _check_source_unchanged(res: VerifyResult, expected_fingerprint: str | None) -> None:
    """Bản chạy local phải nguyên vẹn — đó là điểm quay lui duy nhất."""
    if not expected_fingerprint:
        return
    now = inventory.collect(measure_embedding=False)
    # Vân tay bao gồm số chiều embedding; ở đây bỏ đo để khỏi nạp model, nên so hai
    # thành phần chứng minh được việc "nguồn không bị đụng tới": băm SQLite và băm manifest.
    if now.sqlite_sha256 != expected_fingerprint.split(":")[0]:
        res.fail("source", "SHA256 của SQLite nguồn đã đổi — migration đã ghi vào bản gốc")


def run(*, owner_user_id: str, source_sqlite_sha256: str | None = None) -> VerifyResult:
    """Kiểm chứng độc lập toàn bộ. Đọc lại từ nguồn và đích, không dùng lại gì của `migrate`."""
    res = VerifyResult()

    if not driver.is_postgres():
        res.warn("engine", "đích vẫn là SQLite — chưa đặt DATABASE_URL")

    src = inventory.open_source_readonly()
    try:
        for ent in DURABLE:
            _compare_entity(src, ent, res)
        _check_runtime_not_migrated(src, res)
        if driver.is_postgres():
            _check_vectors(src, res)
    finally:
        src.close()

    _check_ownership(res, owner_user_id)

    if source_sqlite_sha256:
        now = inventory.collect(measure_embedding=False)
        if now.sqlite_sha256 != source_sqlite_sha256:
            res.fail(
                "source",
                "SHA256 của SQLite nguồn đã đổi so với lúc bắt đầu — migration đã ghi vào "
                "bản gốc. Bản local là điểm quay lui duy nhất, không được đụng tới.",
            )
        else:
            res.notes.append("nguồn SQLite không đổi (SHA256 khớp)")

    return res
