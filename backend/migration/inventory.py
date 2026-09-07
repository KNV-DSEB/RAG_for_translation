"""Kiểm kê trạng thái nguồn và tính vân tay — CHỈ ĐỌC, không bao giờ ghi.

Vào:  cơ sở dữ liệu SQLite trên máy + thư mục `data/documents/`.
Ra:   số liệu kiểm kê, manifest tài liệu kèm SHA256, và một vân tay xác định.

Vân tay dùng để trả lời một câu duy nhất: **trạng thái trên cloud này được dựng từ ảnh
chụp local nào?** Không có nó thì sau vài tháng không ai biết dữ liệu cloud tương ứng
với lần chạy nào, và một lần chuyển lặp lại sẽ không phân biệt được với lần đầu.

CHỈ ĐỌC là điều kiện bắt buộc, không phải mong muốn: mọi hàm ở đây mở SQLite ở chế độ
`mode=ro`. Bản chạy local phải nguyên vẹn để còn quay lui được.
"""

from __future__ import annotations

import hashlib
import json
import pathlib
import sqlite3
import subprocess
from dataclasses import dataclass, field
from typing import Any

from backend.config import settings
from backend.migration.spec import DURABLE, RUNTIME_SKIPPED

CHUNK_READ = 1024 * 1024


def _sha256_file(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        while block := fh.read(CHUNK_READ):
            h.update(block)
    return h.hexdigest()


def open_source_readonly(db_path: pathlib.Path | None = None) -> sqlite3.Connection:
    """Mở SQLite nguồn ở chế độ CHỈ ĐỌC.

    `mode=ro` là cách để hệ điều hành tự chặn, thay vì dựa vào việc mã không viết lệnh
    ghi nào. Một lệnh ghi lọt vào đây sẽ ném lỗi ngay thay vì âm thầm sửa bản gốc.
    """
    path = db_path or pathlib.Path(settings.db_path)
    conn = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def git_commit() -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=settings.base_dir, capture_output=True, text=True, timeout=20,
        )
        return out.stdout.strip() or "(không xác định)"
    except (OSError, subprocess.SubprocessError):
        return "(không xác định)"


@dataclass
class DocumentEntry:
    """Một tài liệu trong manifest.

    `cloud_status` LUÔN là `pending_upload` ở giai đoạn này. Việc tải tệp lên kho riêng
    là Phase 7; ghi bất cứ trạng thái nào khác ở đây là tuyên bố một việc chưa xảy ra.
    """

    document_id: int
    workspace_id: int
    filename: str
    local_path: str
    exists: bool
    size_bytes: int
    size_matches_db: bool
    sha256: str | None
    cloud_status: str = "pending_upload"

    def to_dict(self) -> dict[str, Any]:
        return {
            "document_id": self.document_id,
            "workspace_id": self.workspace_id,
            "filename": self.filename,
            "local_path": self.local_path,
            "exists": self.exists,
            "size_bytes": self.size_bytes,
            "size_matches_db": self.size_matches_db,
            "sha256": self.sha256,
            "cloud_status": self.cloud_status,
        }


@dataclass
class Inventory:
    git_commit: str
    sqlite_path: str
    sqlite_sha256: str
    row_counts: dict[str, int]
    skipped_counts: dict[str, int]
    documents: list[DocumentEntry]
    n_workspaces: int
    n_chunks: int
    chunk_text_chars: int
    embedding_model: str
    embedding_dim: int
    warnings: list[str] = field(default_factory=list)

    @property
    def document_manifest_sha256(self) -> str:
        """Băm của manifest, không phải của từng tệp.

        Đổi một byte trong bất kỳ tệp nào, hoặc thêm/bớt một tài liệu, đều làm giá trị
        này đổi — nên nó đủ để chứng minh bộ tài liệu nguồn không bị đụng tới.
        """
        payload = json.dumps(
            [d.to_dict() for d in sorted(self.documents, key=lambda d: d.document_id)],
            ensure_ascii=False, sort_keys=True,
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    @property
    def total_document_bytes(self) -> int:
        return sum(d.size_bytes for d in self.documents)

    @property
    def fingerprint(self) -> str:
        """Vân tay xác định của ảnh chụp nguồn."""
        payload = json.dumps(
            {
                "git_commit": self.git_commit,
                "sqlite_sha256": self.sqlite_sha256,
                "row_counts": self.row_counts,
                "document_manifest_sha256": self.document_manifest_sha256,
                "document_count": len(self.documents),
                "document_bytes": self.total_document_bytes,
                "chunk_count": self.n_chunks,
                "embedding_model": self.embedding_model,
                "embedding_dim": self.embedding_dim,
            },
            sort_keys=True,
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {
            "fingerprint": self.fingerprint,
            "git_commit": self.git_commit,
            "sqlite_sha256": self.sqlite_sha256,
            "document_manifest_sha256": self.document_manifest_sha256,
            "row_counts": self.row_counts,
            "skipped_counts": self.skipped_counts,
            "n_workspaces": self.n_workspaces,
            "n_documents": len(self.documents),
            "document_bytes": self.total_document_bytes,
            "n_chunks": self.n_chunks,
            "chunk_text_chars": self.chunk_text_chars,
            "embedding_model": self.embedding_model,
            "embedding_dim": self.embedding_dim,
            "documents": [d.to_dict() for d in self.documents],
            "warnings": self.warnings,
        }


def _embedding_facts() -> tuple[str, int]:
    """Model và số chiều — ĐO từ mã đang chạy, không lấy từ tài liệu.

    Đổi model mà quên đổi schema là hỏng im lặng: vector mới không nhét vừa cột cũ, và
    lỗi chỉ lộ ra ở lần nạp tài liệu tiếp theo. Nên số chiều phải đo, và
    `test_c13a` đối chiếu lại con số này mỗi lần chạy.
    """
    from backend.rag import store

    return settings.embedding_model, len(store.embed_texts(["đo số chiều"])[0])


def collect(db_path: pathlib.Path | None = None, *, measure_embedding: bool = True) -> Inventory:
    """Kiểm kê toàn bộ trạng thái nguồn. Không ghi gì, ở bất kỳ đâu."""
    path = db_path or pathlib.Path(settings.db_path)
    warnings: list[str] = []

    conn = open_source_readonly(path)
    try:
        existing = {
            str(r["name"])
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
        }

        row_counts: dict[str, int] = {}
        for ent in DURABLE:
            if ent.table not in existing:
                warnings.append(f"bảng `{ent.table}` không có trong nguồn — bỏ qua")
                continue
            row_counts[ent.table] = int(
                conn.execute(f'SELECT COUNT(*) AS n FROM "{ent.table}"').fetchone()["n"]
            )

        skipped_counts = {
            name: int(conn.execute(f'SELECT COUNT(*) AS n FROM "{name}"').fetchone()["n"])
            for name in RUNTIME_SKIPPED
            if name in existing
        }

        n_workspaces = row_counts.get("workspaces", 0)
        chunk_row = conn.execute(
            "SELECT COUNT(*) AS n, COALESCE(SUM(LENGTH(text)), 0) AS chars FROM document_chunks"
        ).fetchone()
        n_chunks, chunk_chars = int(chunk_row["n"]), int(chunk_row["chars"])

        empty = int(
            conn.execute(
                "SELECT COUNT(*) AS n FROM document_chunks WHERE text IS NULL OR text = ''"
            ).fetchone()["n"]
        )
        if empty:
            # Chiến lược chuyển vector là DỰNG LẠI từ văn bản chunk. Chunk rỗng nghĩa là
            # không dựng lại được, và im lặng bỏ qua nó là mất một mẩu ngữ cảnh mà chuyên
            # gia vẫn tưởng còn.
            warnings.append(
                f"{empty} chunk không có văn bản — không dựng lại được vector cho chúng"
            )

        documents: list[DocumentEntry] = []
        for row in conn.execute(
            "SELECT id, workspace_id, filename, stored_path, size_bytes FROM documents ORDER BY id"
        ):
            local = pathlib.Path(str(row["stored_path"]))
            exists = local.is_file()
            actual = local.stat().st_size if exists else 0
            documents.append(
                DocumentEntry(
                    document_id=int(row["id"]),
                    workspace_id=int(row["workspace_id"]),
                    filename=str(row["filename"]),
                    local_path=str(row["stored_path"]),
                    exists=exists,
                    size_bytes=actual,
                    size_matches_db=(actual == int(row["size_bytes"] or 0)),
                    sha256=_sha256_file(local) if exists else None,
                )
            )
            if not exists:
                warnings.append(
                    f"tài liệu #{row['id']} “{row['filename']}” không còn trên đĩa — "
                    "dữ liệu mô tả vẫn chuyển được, nhưng tệp thì không có gì để tải lên"
                )
            elif not documents[-1].size_matches_db:
                warnings.append(
                    f"tài liệu #{row['id']} có kích thước khác với con số trong cơ sở dữ liệu"
                )

        if any(pathlib.PurePath(d.local_path).is_absolute() for d in documents):
            warnings.append(
                "`documents.stored_path` là đường dẫn tuyệt đối trên máy này — không mang "
                "sang cloud được. Phase 7 phải dựng đường dẫn chuẩn theo (người dùng, hồ sơ)."
            )
    finally:
        conn.close()

    model, dim = _embedding_facts() if measure_embedding else (settings.embedding_model, 0)

    return Inventory(
        git_commit=git_commit(),
        sqlite_path=str(path),
        sqlite_sha256=_sha256_file(path),
        row_counts=row_counts,
        skipped_counts=skipped_counts,
        documents=documents,
        n_workspaces=n_workspaces,
        n_chunks=n_chunks,
        chunk_text_chars=chunk_chars,
        embedding_model=model,
        embedding_dim=dim,
        warnings=warnings,
    )
