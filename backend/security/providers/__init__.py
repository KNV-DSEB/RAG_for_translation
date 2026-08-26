"""Các client nói chuyện với dịch vụ bên ngoài.

⚠️ Gói này CHỈ được `backend/security/gateway.py` import. Invariant C1b canh điều đó
bằng cách quét AST — vì nếu module khác gọi thẳng provider thì nó đi vòng qua toàn bộ
kiểm tra đồng ý, ngân sách và nhật ký, và câu "egress có đúng một cửa" thành sai.

Mỗi module ở đây:
  • khai hằng `PROVIDER` — tên hiện trong nhật ký và trên hộp thoại đồng ý
  • import thư viện mạng BÊN TRONG hàm, không phải ở đầu tệp (máy chỉ có 7,8 GB RAM;
    nạp cả bốn thư viện lúc khởi động là phí)
  • chỉ làm đúng việc gọi mạng — không cache, không retry, không chọn giọng.
    Phần điều phối nằm ở `speech/`, `research/`, `security/llm.py`.
"""
