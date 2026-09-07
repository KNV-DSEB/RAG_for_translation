"""Dịch SQL giữa SQLite và PostgreSQL — MỘT bản schema, hai dialect.

Vì sao có tệp này
-----------------
Toàn bộ mã nghiệp vụ đi qua đúng một cửa `db.get_conn()` và viết SQL bằng phương ngữ
SQLite. Nhân đôi nghiệp vụ thành `sqlite_version()` / `postgres_version()` ở 22 tệp là
cách chắc chắn để hai bản lệch nhau rồi không ai biết bản nào đúng. Thay vào đó, chữ SQL
giữ nguyên một bản, và tệp này dịch đúng những chỗ hai phương ngữ thật sự khác.

Đo trên mã hiện tại trước khi viết (xem `docs/cloud-migration.md` §2.2), khác biệt chỉ có:

  ? → %s                 159 lệnh execute
  lastrowid              18 chỗ  → Postgres phải dùng `RETURNING id`
  AUTOINCREMENT          18 chỗ  → chỉ nằm trong `_SCHEMA`
  datetime('now')        16 chỗ trong truy vấn, 20 chỗ trong DEFAULT
  INSERT OR REPLACE      1 chỗ

Không có `json_*()`, `group_concat`, `strftime`. Nên một lớp dịch mỏng là đủ.

Quyết định: GIỮ mốc thời gian dạng TEXT `'YYYY-MM-DD HH:MM:SS'` trên cả hai
------------------------------------------------------------------------
Đổi sang `TIMESTAMPTZ` thì đúng kiểu hơn, nhưng giao diện đang cắt chuỗi (`str(x)[:16]`)
và các truy vấn đang so sánh trực tiếp `expires_at > datetime('now')`. Đổi kiểu là đổi
định dạng chuỗi trả về, làm hỏng cả hai chỗ đó mà không thêm được bảo đảm nào cho đợt
này. Giữ TEXT là thay đổi nhỏ nhất còn giữ nguyên hành vi — và ghi lại ở đây để lần sau
đổi thì biết vì sao nó từng như vậy.
"""

from __future__ import annotations

import re

# Biểu thức "bây giờ" ở dạng chuỗi giống hệt SQLite sinh ra, để so sánh chuỗi vẫn đúng.
PG_NOW = "to_char(now() AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS')"


def _now_plus(placeholder: str) -> str:
    """`datetime('now', ?)` với modifier kiểu `'+8 hours'`.

    Chuỗi modifier của SQLite (`+8 hours`, `+15 minutes`) tình cờ cũng là interval hợp lệ
    của Postgres, nên truyền thẳng được, không phải chuyển đổi ở phía Python.
    """
    return (
        "to_char(now() AT TIME ZONE 'UTC' + ("
        + placeholder
        + ")::interval, 'YYYY-MM-DD HH24:MI:SS')"
    )


def qmark_to_percent(sql: str) -> str:
    """Đổi `?` thành `%s`, BỎ QUA dấu ? nằm trong chuỗi hoặc chú thích.

    Đi từng ký tự thay vì `str.replace`: một câu SQL có `'... ? ...'` trong literal sẽ bị
    thay nhầm, và lỗi đó chỉ lộ ra lúc chạy thật với đúng dữ liệu đó.

    `%` có sẵn trong SQL (ví dụ `LIKE 'sqlite_%'`) phải nhân đôi thành `%%`, vì psycopg
    dùng `%` làm ký tự định dạng.
    """
    out: list[str] = []
    i = 0
    n = len(sql)
    while i < n:
        ch = sql[i]

        if ch == "'":                                  # chuỗi SQL: '' là dấu nháy thoát
            j = i + 1
            while j < n:
                if sql[j] == "'":
                    if j + 1 < n and sql[j + 1] == "'":
                        j += 2
                        continue
                    break
                j += 1
            out.append(sql[i : j + 1].replace("%", "%%"))
            i = j + 1
            continue

        if ch == '"':                                  # định danh có dấu nháy kép
            j = sql.find('"', i + 1)
            j = n - 1 if j == -1 else j
            out.append(sql[i : j + 1])
            i = j + 1
            continue

        if sql.startswith("--", i):                    # chú thích tới hết dòng
            j = sql.find("\n", i)
            j = n if j == -1 else j
            out.append(sql[i:j].replace("%", "%%"))
            i = j
            continue

        if ch == "?":
            out.append("%s")
        elif ch == "%":
            out.append("%%")
        else:
            out.append(ch)
        i += 1
    return "".join(out)


def _translate_datetime(sql: str) -> str:
    """`datetime('now')` và `datetime('now', %s)` → biểu thức tương đương của Postgres."""
    sql = re.sub(
        r"datetime\(\s*'now'\s*,\s*%s\s*\)",
        lambda _: _now_plus("%s"),
        sql,
        flags=re.IGNORECASE,
    )
    return re.sub(r"datetime\(\s*'now'\s*\)", PG_NOW, sql, flags=re.IGNORECASE)


def to_postgres(sql: str) -> str:
    """Dịch một câu SQL viết theo phương ngữ SQLite sang PostgreSQL."""
    sql = qmark_to_percent(sql)
    sql = _translate_datetime(sql)
    sql = re.sub(r"\bINSERT\s+OR\s+IGNORE\s+INTO\b", "INSERT INTO", sql, flags=re.I)
    return sql


# ============================== Schema ==============================


def ddl_to_postgres(ddl: str) -> str:
    """Dịch một câu CREATE viết cho SQLite sang PostgreSQL.

    Chỉ xử lý đúng những gì `_SCHEMA` thật sự dùng. Cố ý KHÔNG viết trình dịch DDL tổng
    quát: nó sẽ im lặng dịch sai một cấu trúc mà schema này không có, và không ai biết.
    """
    ddl = re.sub(
        r"\bINTEGER\s+PRIMARY\s+KEY\s+AUTOINCREMENT\b", "BIGSERIAL PRIMARY KEY", ddl, flags=re.I
    )
    # Khoá ngoại trỏ tới cột BIGSERIAL phải là BIGINT, nếu không Postgres từ chối tạo.
    ddl = re.sub(
        r"\b(\w+_id)(\s+)INTEGER\b",
        lambda m: f"{m.group(1)}{m.group(2)}BIGINT",
        ddl,
        flags=re.I,
    )
    ddl = re.sub(r"DEFAULT\s*\(\s*datetime\(\s*'now'\s*\)\s*\)", f"DEFAULT {PG_NOW}", ddl, flags=re.I)
    return _translate_datetime(ddl)
