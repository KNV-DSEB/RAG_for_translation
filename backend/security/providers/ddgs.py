"""Provider: DuckDuckGo qua thư viện `ddgs`. Đích `search`.

Vào:  một truy vấn.
Ra:   danh sách kết quả thô (dict) đúng như thư viện trả về.

Việc chuẩn hoá kết quả, đếm ngân sách truy vấn và thử lại nằm ở `research/search.py`.
"""

from __future__ import annotations

from typing import Any

PROVIDER = "ddgs"


def search(*, query: str, max_results: int, region: str = "wt-wt") -> list[dict[str, Any]]:
    from ddgs import DDGS

    with DDGS() as client:
        return list(client.text(query, max_results=max_results, region=region) or [])
