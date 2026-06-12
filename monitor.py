#!/usr/bin/env python3
"""Task Bar Hero - Background Monitor
通知エリアを監視してステージクリア/宝箱取得をログ記録
"""
import time
import os
import csv
import hashlib
from datetime import datetime
from pathlib import Path

try:
    import win32gui
    import win32api
    import win32con
    HAS_WIN32 = True
except ImportError:
    HAS_WIN32 = False

from PIL import ImageGrab, Image

# 設定
LOG_DIR = Path(__file__).parent / "logs"
LOG_DIR.mkdir(exist_ok=True)
LOG_CSV = LOG_DIR / "monitor_log.csv"
IMG_DIR = LOG_DIR / "captures"
IMG_DIR.mkdir(exist_ok=True)

INTERVAL = 3  # 秒
# 通知エリア (screen絶対座標)
NOTIF_REGION = (1548, 1185, 2360, 1230)
# バトルストリップ: ステージ名
STAGE_REGION = (1640, 1275, 2160, 1320)


def get_game_window():
    """TaskBarHeroウィンドウの矩形を取得"""
    if not HAS_WIN32:
        return None
    hwnd = win32gui.FindWindow("UnityWndClass", "TaskBarHero")
    if not hwnd:
        return None
    return win32gui.GetWindowRect(hwnd)


def capture_region(region):
    """指定領域をキャプチャ"""
    return ImageGrab.grab(bbox=region)


def img_hash(img):
    """画像のハッシュ(変化検知用)"""
    return hashlib.md5(img.tobytes()).hexdigest()


def detect_notification(img):
    """通知バナーが存在するか(暗い背景を検知)"""
    arr = img.load()
    w, h = img.size
    total = w * h
    dark = sum(1 for x in range(w) for y in range(h)
               if arr[x, y][0] < 80 and arr[x, y][1] < 80 and arr[x, y][2] < 80)
    return dark > total * 0.1


def is_elite_chest(img):
    """Elite宝箱の橙色検知"""
    arr = img.load()
    w, h = img.size
    total = w * h
    orange = sum(1 for x in range(w) for y in range(h)
                 if arr[x, y][0] > 200 and arr[x, y][1] > 100 and arr[x, y][2] < 80)
    return orange > total * 0.05


def log_event(ts, event_type, img, stage="", extra=""):
    """CSVログ + 画像保存"""
    fname = f"{ts.strftime('%Y%m%d_%H%M%S')}_{event_type}.png"
    img_path = IMG_DIR / fname
    img.save(str(img_path))

    with open(LOG_CSV, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([ts.strftime("%Y-%m-%d %H:%M:%S"), event_type, stage, extra, fname])


def init_log():
    if not LOG_CSV.exists():
        with open(LOG_CSV, "w", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow(["timestamp", "type", "stage", "extra", "image"])


def main():
    init_log()
    print(f"Task Bar Hero Monitor 起動")
    print(f"ログ: {LOG_CSV}")
    print(f"間隔: {INTERVAL}秒 | 停止: Ctrl+C")
    print("-" * 40)

    prev_hash = ""
    prev_stage_hash = ""
    consecutive_same = 0

    while True:
        try:
            ts = datetime.now()

            # ゲーム起動確認
            rect = get_game_window()
            if not rect:
                print(f"{ts.strftime('%H:%M:%S')} ゲーム未起動")
                time.sleep(INTERVAL)
                continue

            # 通知エリアキャプチャ
            notif_img = capture_region(NOTIF_REGION)
            h = img_hash(notif_img)

            if h != prev_hash:
                consecutive_same = 0
                has_notif = detect_notification(notif_img)

                if has_notif:
                    is_elite = is_elite_chest(notif_img)
                    event_type = "elite_chest" if is_elite else "notification"
                    log_event(ts, event_type, notif_img)

                    if is_elite:
                        print(f"{ts.strftime('%H:%M:%S')} ★ ELITE CHEST!")
                    else:
                        print(f"{ts.strftime('%H:%M:%S')} 通知変化 → {IMG_DIR.name}/{ts.strftime('%Y%m%d_%H%M%S')}_notification.png")

                prev_hash = h
            else:
                consecutive_same += 1
                if consecutive_same % 20 == 0:  # 1分ごとにalive表示
                    print(f"{ts.strftime('%H:%M:%S')} 監視中...")

        except KeyboardInterrupt:
            print("\n停止")
            break
        except Exception as e:
            print(f"エラー: {e}")

        time.sleep(INTERVAL)


if __name__ == "__main__":
    main()
