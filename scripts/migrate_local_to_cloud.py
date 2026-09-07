"""Chuyển dữ liệu từ bản chạy trên máy sang PostgreSQL + pgvector.

    python scripts/migrate_local_to_cloud.py plan
    python scripts/migrate_local_to_cloud.py migrate --owner-user-id <UUID> [--dry-run]
    python scripts/migrate_local_to_cloud.py verify  --owner-user-id <UUID>
    python scripts/migrate_local_to_cloud.py history

Đích đến lấy từ `DATABASE_URL`. Không có biến đó thì `migrate` từ chối chạy — đích sẽ
là chính SQLite trên máy, và chuyển dữ liệu vào chính nó thì không có nghĩa gì.

`plan` KHÔNG BAO GIỜ ghi gì, ở bất kỳ đâu, kể cả sổ cái. Nó chạy được cả khi chưa có
UUID thật, để xem trước sẽ chuyển những gì.

TỆP TÀI LIỆU KHÔNG ĐƯỢC TẢI LÊN Ở GIAI ĐOẠN NÀY. Chúng chỉ được kiểm kê kèm SHA256 và
đánh dấu `pending_upload`. Kho lưu trữ riêng là việc của Phase 7.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from backend.migration import inventory, ledger, runner, verify   # noqa: E402
from backend.migration.spec import DURABLE, RUNTIME_SKIPPED       # noqa: E402

UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)

# UUID có dạng đúng nhưng rõ ràng là chỗ điền tạm. Chặn ở đây vì một lần chuyển thật mà
# gắn nhầm chủ sở hữu thì mọi hồ sơ thuộc về một tài khoản không tồn tại — và không ai
# đọc được chúng nữa.
PLACEHOLDER_OWNERS = {
    "00000000-0000-0000-0000-000000000000",
    "11111111-1111-1111-1111-111111111111",
}


def _require_owner(value: str | None, *, dry_run: bool) -> str:
    if not value:
        if dry_run:
            return "(chưa có — chạy thử)"
        raise SystemExit(
            "Thiếu --owner-user-id. Đây phải là UUID THẬT của tài khoản Supabase Auth "
            "(trường `sub` trong JWT). Không tự bịa: gắn nhầm chủ thì mọi hồ sơ thuộc về "
            "một tài khoản không tồn tại, và không ai mở được chúng nữa."
        )
    if not UUID_RE.match(value):
        raise SystemExit(f"`{value}` không phải UUID. Lấy từ Supabase Auth, đừng tự đặt.")
    if value.lower() in PLACEHOLDER_OWNERS:
        raise SystemExit(f"`{value}` là UUID điền tạm, không phải tài khoản thật.")
    return value


def _print_inventory(inv: inventory.Inventory) -> None:
    print("=" * 74)
    print("KIỂM KÊ NGUỒN — không ghi gì, ở bất kỳ đâu")
    print("=" * 74)
    print(f"  git                  {inv.git_commit}")
    print(f"  SQLite               {inv.sqlite_path}")
    print(f"  SQLite SHA256        {inv.sqlite_sha256}")
    print(f"  manifest SHA256      {inv.document_manifest_sha256}")
    print(f"  vân tay nguồn        {inv.fingerprint}")
    print()
    print(f"  hồ sơ khách hàng     {inv.n_workspaces}")
    print(f"  tài liệu             {len(inv.documents)}  ({inv.total_document_bytes:,} byte)")
    print(f"  chunk                {inv.n_chunks}  ({inv.chunk_text_chars:,} ký tự)")
    print(f"  model embedding      {inv.embedding_model}")
    print(f"  số chiều             {inv.embedding_dim}")
    print()
    print("  DỮ LIỆU BỀN sẽ chuyển:")
    for ent in DURABLE:
        n = inv.row_counts.get(ent.table)
        print(f"    {ent.table:22} {n if n is not None else '(không có)':>6}")
    print()
    print("  TRẠNG THÁI CHẠY — cố ý KHÔNG chuyển:")
    for table, why in RUNTIME_SKIPPED.items():
        n = inv.skipped_counts.get(table, 0)
        print(f"    {table:22} {n:>6}   {why[:74]}")
    print()
    print("  TỆP TÀI LIỆU — chỉ kiểm kê, CHƯA tải lên:")
    for d in inv.documents:
        mark = "ok " if d.exists else "MẤT"
        sha = (d.sha256 or "-")[:16]
        print(f"    [{mark}] #{d.document_id} ws={d.workspace_id} {d.size_bytes:>8,}B "
              f"{sha}…  {d.cloud_status}  {d.filename[:34]}")
    print(f"    → đã tải lên cloud: 0  (kho lưu trữ riêng là việc của Phase 7)")
    if inv.warnings:
        print()
        print("  CẢNH BÁO:")
        for w in inv.warnings:
            print(f"    - {w}")


def cmd_plan(args: argparse.Namespace) -> int:
    inv = inventory.collect()
    _print_inventory(inv)
    print()
    print("  Chưa ghi gì. Chạy `migrate --owner-user-id <UUID>` để thực hiện.")
    if args.json:
        pathlib.Path(args.json).write_text(
            json.dumps(inv.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"  Đã ghi kiểm kê ra {args.json}")
    return 0


def cmd_migrate(args: argparse.Namespace) -> int:
    owner = _require_owner(args.owner_user_id, dry_run=args.dry_run)

    if args.dry_run:
        inv = inventory.collect()
        _print_inventory(inv)
        print()
        print("  CHẠY THỬ — số lệnh ghi đã thực hiện: 0")
        print(f"  chủ sở hữu sẽ gắn: {owner}")
        return 0

    before = inventory.collect(measure_embedding=False).sqlite_sha256
    print(f"  chủ sở hữu: {owner}")
    print("  đang chuyển:")
    try:
        result = runner.migrate(owner_user_id=owner, progress=print)
    except runner.MigrationError as exc:
        print(f"\n  DỪNG: {exc}")
        return 2

    print()
    print("=" * 74)
    print(f"ĐÃ CHUYỂN  (lần chạy #{result.run_id}, vân tay {result.fingerprint[:16]}…)")
    print("=" * 74)
    print(f"  {'bảng':24} {'nguồn':>7} {'đích':>7}")
    for t in result.tables:
        print(f"  {t.table:24} {t.source_rows:>7} {t.written:>7}   {t.note}")
    print(f"  {'vector (dựng lại)':24} {result.chunks_embedded:>7} {result.chunks_embedded:>7}")
    print()
    print(f"  tài liệu đã kiểm kê:      {result.documents_inventoried}")
    print(f"  tài liệu đã tải lên cloud: 0   (Phase 7)")
    print(f"  trạng thái chạy bỏ qua:   {result.runtime_skipped}")

    after = inventory.collect(measure_embedding=False).sqlite_sha256
    print(f"  nguồn SQLite: {'KHÔNG ĐỔI' if before == after else 'ĐÃ BỊ ĐỔI — LỖI NGHIÊM TRỌNG'}")
    return 0 if before == after else 3


def cmd_verify(args: argparse.Namespace) -> int:
    owner = _require_owner(args.owner_user_id, dry_run=False)
    res = verify.run(owner_user_id=owner, source_sqlite_sha256=args.expect_sqlite_sha256)

    print("=" * 74)
    print("KIỂM CHỨNG ĐỘC LẬP — đọc lại từ cả nguồn lẫn đích")
    print("=" * 74)
    print(f"  {'thực thể':24} {'nguồn':>7} {'đích':>7}")
    for name, (a, b) in res.counts.items():
        mark = " " if a <= b else " <-- THIẾU"
        print(f"  {name:24} {a:>7} {b:>7}{mark}")
    for n in res.notes:
        print(f"  ghi chú: {n}")
    if res.findings:
        print()
        for f in res.findings:
            print(f"  {f.level} [{f.area}] {f.detail}")
    print()
    print("  KẾT QUẢ:", "ĐẠT" if res.ok else "KHÔNG ĐẠT")
    return 0 if res.ok else 1


def cmd_history(_args: argparse.Namespace) -> int:
    rows = ledger.history()
    if not rows:
        print("  Chưa có lần chuyển nào.")
        return 0
    print(f"  {'#':>4} {'trạng thái':11} {'vân tay':18} {'git':10} {'bắt đầu':20}")
    for r in rows:
        print(f"  {r['id']:>4} {str(r['status']):11} {str(r['source_fingerprint'])[:16]:18} "
              f"{str(r['source_git_commit'])[:8]:10} {str(r['started_at'])[:19]:20} "
              f"{r['error_class'] or ''}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="migrate_local_to_cloud",
        description="Chuyển dữ liệu bền từ bản chạy trên máy sang PostgreSQL + pgvector.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("plan", help="kiểm kê nguồn, không ghi gì")
    p.add_argument("--json", help="ghi kiểm kê ra tệp JSON")
    p.set_defaults(func=cmd_plan)

    p = sub.add_parser("migrate", help="chuyển dữ liệu bền lên PostgreSQL")
    p.add_argument("--owner-user-id", help="UUID thật của tài khoản Supabase Auth")
    p.add_argument("--dry-run", action="store_true", help="không ghi gì, chỉ báo cáo")
    p.set_defaults(func=cmd_migrate)

    p = sub.add_parser("verify", help="kiểm chứng độc lập, đọc lại từ hai phía")
    p.add_argument("--owner-user-id", required=True)
    p.add_argument("--expect-sqlite-sha256", help="SHA256 của nguồn trước khi chuyển")
    p.set_defaults(func=cmd_verify)

    p = sub.add_parser("history", help="các lần chuyển đã ghi trong sổ cái")
    p.set_defaults(func=cmd_history)

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
