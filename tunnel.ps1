# Mở Trợ lý phiên dịch ra ngoài Internet qua Cloudflare Tunnel.
#
# Dùng khi chuyên gia phiên dịch ngồi ở máy khác. Tunnel cho một địa chỉ HTTPS thật,
# nên trình duyệt của họ mở được bình thường.
#
# Dùng:  .\tunnel.ps1        -> chạy máy chủ + mở tunnel, in ra địa chỉ để gửi cho họ
#        .\tunnel.ps1 -Stop  -> đóng tunnel và dừng máy chủ
#
# ĐỌC KỸ TRƯỚC KHI DÙNG
#   1. Địa chỉ tạo ra là CÔNG KHAI. Ai có link đều vào được toàn bộ dữ liệu, không có
#      mật khẩu. Chỉ gửi cho đúng người, và đóng tunnel ngay khi dùng xong.
#   2. Dữ liệu đi qua máy chủ Cloudflare. Với tài liệu có ràng buộc bảo mật thì KHÔNG
#      nên dùng cách này — hãy cài thẳng trên máy họ.
#   3. Máy này phải bật và giữ cửa sổ chạy suốt thời gian họ dùng.

param([switch]$Stop)

$ErrorActionPreference = 'Stop'
$Root = $PSScriptRoot
$Cloudflared = Join-Path $Root 'tools\cloudflared.exe'
$Port = 8000

function Write-Step($m) { Write-Host "==> $m" -ForegroundColor Cyan }
function Write-Good($m) { Write-Host "OK  $m" -ForegroundColor Green }
function Write-Bad($m)  { Write-Host "!!  $m" -ForegroundColor Red }

if ($Stop) {
    Write-Step 'Đóng tunnel và dừng máy chủ...'
    Get-Process cloudflared -ErrorAction SilentlyContinue | Stop-Process -Force
    & (Join-Path $Root 'run.ps1') -Stop
    Write-Good 'Đã đóng. Địa chỉ cũ không còn dùng được nữa.'
    return
}

if (-not (Test-Path $Cloudflared)) {
    Write-Bad 'Thiếu tools\cloudflared.exe'
    Write-Host '    Tải tại: https://github.com/cloudflare/cloudflared/releases/latest'
    Write-Host '    Lấy bản cloudflared-windows-amd64.exe, đổi tên thành cloudflared.exe, bỏ vào thư mục tools\'
    exit 1
}

# ---- Bảo đảm máy chủ đang chạy ----
$running = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
if (-not $running) {
    Write-Step 'Máy chủ chưa chạy — khởi động trước...'
    & (Join-Path $Root 'run.ps1') -NoBrowser
    if ($LASTEXITCODE -ne 0) { exit 1 }
} else {
    Write-Good "Máy chủ đã chạy trên cổng $Port"
}

Write-Host ''
Write-Host '  ┌─────────────────────────────────────────────────────────────┐' -ForegroundColor Yellow
Write-Host '  │  Địa chỉ sắp tạo ra là CÔNG KHAI — không có mật khẩu.       │' -ForegroundColor Yellow
Write-Host '  │  Chỉ gửi cho đúng người. Đóng ngay khi dùng xong.           │' -ForegroundColor Yellow
Write-Host '  │  Đừng dùng với tài liệu có ràng buộc bảo mật.               │' -ForegroundColor Yellow
Write-Host '  └─────────────────────────────────────────────────────────────┘' -ForegroundColor Yellow
Write-Host ''

Write-Step 'Đang mở tunnel...'

# cloudflared in địa chỉ ra stderr; gom lại để bắt lấy rồi in cho dễ thấy
$logFile = Join-Path $env:TEMP 'cloudflared-tunnel.log'
if (Test-Path $logFile) { Remove-Item $logFile -Force }

$proc = Start-Process -FilePath $Cloudflared `
    -ArgumentList 'tunnel', '--url', "http://127.0.0.1:$Port", '--no-autoupdate' `
    -RedirectStandardError $logFile -RedirectStandardOutput "$logFile.out" `
    -PassThru -WindowStyle Hidden

$url = $null
foreach ($i in 1..60) {
    Start-Sleep -Milliseconds 500
    if (Test-Path $logFile) {
        $m = Select-String -Path $logFile -Pattern 'https://[a-z0-9-]+\.trycloudflare\.com' -ErrorAction SilentlyContinue
        if ($m) { $url = $m.Matches[0].Value; break }
    }
}

if (-not $url) {
    Write-Bad 'Không lấy được địa chỉ tunnel sau 30 giây.'
    Write-Host "    Xem chi tiết trong: $logFile"
    Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
    exit 1
}

Write-Host ''
Write-Good 'Tunnel đã mở.'
Write-Host ''
Write-Host '  Gửi địa chỉ này cho chuyên gia:' -ForegroundColor Cyan
Write-Host ''
Write-Host "      $url" -ForegroundColor White -BackgroundColor DarkBlue
Write-Host ''
Set-Clipboard -Value $url -ErrorAction SilentlyContinue
Write-Host '  (đã chép vào clipboard)' -ForegroundColor DarkGray
Write-Host ''
Write-Host '  Giữ cửa sổ này mở suốt thời gian họ dùng.' -ForegroundColor DarkGray
Write-Host '  Đóng tunnel: .\tunnel.ps1 -Stop' -ForegroundColor DarkGray
Write-Host ''
Write-Host 'Nhấn Ctrl+C để đóng tunnel...' -ForegroundColor DarkGray

try {
    Wait-Process -Id $proc.Id
} finally {
    Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
    Write-Host ''
    Write-Good 'Tunnel đã đóng. Địa chỉ cũ không còn dùng được.'
}
