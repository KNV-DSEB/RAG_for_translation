# Khởi động Trợ lý phiên dịch.
#
# Từ khi bỏ Streamlit, backend FastAPI phục vụ luôn giao diện ở CÙNG cổng 8000 —
# một tiến trình, một cổng, không còn phải chạy song song hai thứ.
#
# Dùng:  .\run.ps1            -> chạy và mở trình duyệt
#        .\run.ps1 -NoBrowser -> chạy, không tự mở trình duyệt
#        .\run.ps1 -Stop      -> dừng
#        .\run.ps1 -Check     -> chỉ kiểm môi trường rồi thoát

param(
    [switch]$NoBrowser,
    [switch]$Stop,
    [switch]$Check
)

$ErrorActionPreference = 'Stop'
$Root = $PSScriptRoot
$Python = Join-Path $Root '.venv\Scripts\python.exe'
$Port = 8000

function Write-Step($m) { Write-Host "==> $m" -ForegroundColor Cyan }
function Write-Good($m) { Write-Host "OK  $m" -ForegroundColor Green }
function Write-Bad($m)  { Write-Host "!!  $m" -ForegroundColor Red }
function Write-Warn($m) { Write-Host "!!  $m" -ForegroundColor Yellow }

# ---------------------------------------------------------------- Dừng
if ($Stop) {
    Write-Step 'Dừng máy chủ...'
    $conns = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
    if (-not $conns) {
        Write-Good "Cổng $Port vốn đã trống."
        return
    }
    foreach ($c in $conns) {
        Write-Host "    dừng PID $($c.OwningProcess)"
        Stop-Process -Id $c.OwningProcess -Force -ErrorAction SilentlyContinue
    }
    Start-Sleep -Seconds 1
    Write-Good 'Đã dừng.'
    return
}

# ------------------------------------------------------- Kiểm môi trường
$problems = @()

if (-not (Test-Path $Python)) {
    $problems += "Chưa có môi trường ảo. Chạy:  uv sync --python D:\Python\python.exe"
}

$envFile = Join-Path $Root '.env'
if (-not (Test-Path $envFile)) {
    $problems += "Chưa có tệp .env. Chạy:  Copy-Item .env.example .env"
} else {
    $envText = Get-Content $envFile -Raw
    if ($envText -notmatch '(?m)^\s*GOOGLE_API_KEY\s*=\s*\S') {
        Write-Warn '.env chưa có GOOGLE_API_KEY.'
        Write-Host '    App vẫn chạy được, nhưng nghiên cứu / sinh kịch bản / chấm điểm sẽ báo lỗi.'
        Write-Host '    Lấy key miễn phí: https://aistudio.google.com/apikey'
        Write-Host ''
    }
}

if (-not (Test-Path (Join-Path $Root 'web\index.html'))) {
    $problems += 'Không tìm thấy web\index.html — thiếu phần giao diện.'
}

if ($problems.Count -gt 0) {
    foreach ($p in $problems) { Write-Bad $p }
    exit 1
}

if ($Check) {
    Write-Good 'Môi trường đủ để chạy.'
    & $Python -c "import sys; print('    Python', sys.version.split()[0])"
    return
}

# ------------------------------------------------------------ Cổng bận?
$busy = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
if ($busy) {
    Write-Bad "Cổng $Port đang bị PID $($busy[0].OwningProcess) chiếm."
    Write-Host '    Chạy  .\run.ps1 -Stop  rồi thử lại.'
    exit 1
}

# ------------------------------------------------------------ Khởi động
Write-Step "Khởi động máy chủ trên http://127.0.0.1:$Port ..."
$server = Start-Process -FilePath $Python `
    -ArgumentList '-m', 'uvicorn', 'backend.main:app', '--host', '127.0.0.1', '--port', "$Port" `
    -WorkingDirectory $Root -PassThru -WindowStyle Minimized

# Chờ sẵn sàng thay vì đoán mò bằng sleep cố định
$ready = $false
foreach ($i in 1..60) {
    Start-Sleep -Milliseconds 500
    try {
        $r = Invoke-WebRequest -Uri "http://127.0.0.1:$Port/health" -UseBasicParsing -TimeoutSec 2
        if ($r.StatusCode -eq 200) { $ready = $true; break }
    } catch { }
}

if (-not $ready) {
    Write-Bad 'Máy chủ không phản hồi sau 30 giây. Xem cửa sổ máy chủ để biết lỗi.'
    exit 1
}

Write-Good "Đang chạy (PID $($server.Id))"

try {
    $health = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/health" -TimeoutSec 5
    Write-Host "    Python $($health.python_version) · $($health.n_tables)/18 bảng · $([math]::Round($health.rss_mb)) MB RAM"
    foreach ($w in $health.warnings) { Write-Warn $w }
} catch { }

Write-Host ''
Write-Host "  Giao diện : http://127.0.0.1:$Port" -ForegroundColor Cyan
Write-Host "  Mẫu thiết kế: http://127.0.0.1:$Port/gallery.html" -ForegroundColor DarkGray
Write-Host "  Tài liệu API: http://127.0.0.1:$Port/docs" -ForegroundColor DarkGray
Write-Host ''
Write-Host '  Dừng: .\run.ps1 -Stop' -ForegroundColor DarkGray

if (-not $NoBrowser) {
    Start-Process "http://127.0.0.1:$Port"
}
