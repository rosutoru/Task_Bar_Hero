# Task Bar Hero - Background Monitor
# 通知エリアを定期キャプチャ → OCRでテキスト読み取り → ログ記録

param(
    [int]$IntervalSec = 5,
    [string]$LogFile = "$PSScriptRoot\monitor_log.csv"
)

Add-Type -AssemblyName System.Drawing

# Windows OCR セットアップ
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$null = [Windows.Media.Ocr.OcrEngine, Windows, ContentType=WindowsRuntime]
$null = [Windows.Graphics.Imaging.BitmapDecoder, Windows, ContentType=WindowsRuntime]
$null = [Windows.Storage.Streams.InMemoryRandomAccessStream, Windows, ContentType=WindowsRuntime]

function Get-AsyncResult($task) {
    $task.GetAwaiter().GetResult()
}

function Invoke-Async($asyncOp) {
    $task = [System.WindowsRuntimeSystemExtensions]::AsTask($asyncOp)
    $task.Wait() | Out-Null
    $task.Result
}

function OCR-Screenshot($bmp) {
    try {
        $ms = New-Object System.IO.MemoryStream
        $bmp.Save($ms, [System.Drawing.Imaging.ImageFormat]::Png)
        $ms.Position = 0
        $bytes = $ms.ToArray()
        $ms.Dispose()

        $ras = [Windows.Storage.Streams.InMemoryRandomAccessStream]::new()
        $writer = [Windows.Storage.Streams.DataWriter]::new($ras)
        $writer.WriteBytes($bytes)
        Invoke-Async($writer.StoreAsync()) | Out-Null
        $ras.Seek(0)

        $decoder = Invoke-Async([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($ras))
        $softBmp = Invoke-Async($decoder.GetSoftwareBitmapAsync())

        $engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages()
        if (-not $engine) {
            $lang = [Windows.Globalization.Language]::new("ja")
            $engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromLanguage($lang)
        }
        $result = Invoke-Async($engine.RecognizeAsync($softBmp))
        return $result.Text
    } catch {
        return ""
    }
}

function Get-GameWindowRect {
    Add-Type @'
using System; using System.Runtime.InteropServices;
public class GWR {
    [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out R r);
    public struct R { public int L,T,Ri,B; }
}
'@ -ErrorAction SilentlyContinue
    $proc = Get-Process TaskBarHero -ErrorAction SilentlyContinue
    if (-not $proc) { return $null }
    $r = New-Object GWR+R
    [GWR]::GetWindowRect($proc.MainWindowHandle, [ref]$r) | Out-Null
    return $r
}

# ログファイル初期化
if (-not (Test-Path $LogFile)) {
    "timestamp,type,text,stage,seconds" | Out-File $LogFile -Encoding utf8
}

Write-Host "Task Bar Hero Monitor 起動" -ForegroundColor Green
Write-Host "ログ: $LogFile"
Write-Host "間隔: ${IntervalSec}秒 | 停止: Ctrl+C"
Write-Host "---"

$lastText = ""
$stagePattern = 'ステージ\s*([\d\-]+)\s*をクリア.*?(\d+)秒'
$chestPattern = '(Elite|一般|レア)宝箱.*?獲得.*?[（(](.+?)[）)]'

while ($true) {
    try {
        $rect = Get-GameWindowRect
        if (-not $rect) {
            Write-Host "$(Get-Date -f 'HH:mm:ss') ゲーム未起動"
            Start-Sleep -Seconds $IntervalSec
            continue
        }

        # 通知エリアキャプチャ (ゲーム下部の通知バー)
        # 通知はゲーム窓下部 y=1195-1225 付近
        $notifY = $rect.T + 855   # ウィンドウ相対 y=855
        $notifH = 35
        $notifX = $rect.L + 200
        $notifW = 800

        $bmp = New-Object System.Drawing.Bitmap($notifW, $notifH)
        $g = [System.Drawing.Graphics]::FromImage($bmp)
        $g.CopyFromScreen($notifX, $notifY, 0, 0, (New-Object System.Drawing.Size($notifW, $notifH)))
        $g.Dispose()

        $text = OCR-Screenshot $bmp
        $bmp.Dispose()

        $text = $text.Trim()

        if ($text -and $text -ne $lastText) {
            $ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"

            # ステージクリア検出
            if ($text -match $stagePattern) {
                $stage = $Matches[1]
                $secs = $Matches[2]
                $row = "$ts,stage_clear,$text,$stage,$secs"
                $row | Add-Content $LogFile -Encoding utf8
                Write-Host "$ts STAGE CLEAR: $stage ($secs秒)" -ForegroundColor Cyan
            }
            # 宝箱取得検出
            elseif ($text -match $chestPattern) {
                $chestType = $Matches[1]
                $source = $Matches[2]
                $row = "$ts,chest,$text,,"
                $row | Add-Content $LogFile -Encoding utf8
                $color = if ($chestType -eq "Elite") { "Yellow" } else { "Gray" }
                Write-Host "$ts CHEST ($chestType): $source" -ForegroundColor $color
            }
            # その他通知
            elseif ($text.Length -gt 3) {
                $row = "$ts,notify,$text,,"
                $row | Add-Content $LogFile -Encoding utf8
                Write-Host "$ts NOTIFY: $text"
            }

            $lastText = $text
        }
    } catch {
        # エラーは無視して継続
    }

    Start-Sleep -Seconds $IntervalSec
}
