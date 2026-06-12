#!/usr/bin/env python3
"""Task Bar Hero - Overlay Widget
ゲーム左横にリアルタイム情報を表示
"""
import tkinter as tk
from tkinter import font as tkfont
import threading
import time
from datetime import datetime
from PIL import ImageGrab, Image
import win32gui
import hashlib
import re
import csv
from pathlib import Path

# ========================
# 設定
# ========================
UPDATE_SEC = 3

LOG_DIR = Path(__file__).parent / "logs"
LOG_DIR.mkdir(exist_ok=True)
LOG_CSV = LOG_DIR / "monitor_log.csv"
IMG_DIR = LOG_DIR / "captures"
IMG_DIR.mkdir(exist_ok=True)

# ガイド画像からの推奨ローテーション
RECOMMENDED_ROTATION = [
    ("1-4",  "Lv.1+",   "Normal"),
    ("1-9",  "Lv.1+",   "Normal"),
    ("2-5",  "Lv.20+",  "Normal"),
    ("L49",  "Lv.49+",  "Normal"),
    ("L80",  "Lv.80+",  "Nightmare"),
]

# キャプチャ領域
NOTIF_REGION   = (1548, 1185, 2360, 1230)  # 通知バー
STAGE_REGION   = (1640, 1340, 1720, 1370)  # ステージ番号バッジ周辺


# ========================
# ゲーム情報取得
# ========================
def get_game_rect():
    hwnd = win32gui.FindWindow("UnityWndClass", "TaskBarHero")
    if not hwnd:
        return None
    return win32gui.GetWindowRect(hwnd)  # (L, T, R, B)


def img_hash(img):
    return hashlib.md5(img.tobytes()).hexdigest()


def detect_elite(img):
    arr = img.load()
    w, h = img.size
    total = w * h
    # 暗いバナー検知
    dark = sum(1 for x in range(w) for y in range(h)
               if arr[x, y][0] < 80 and arr[x, y][1] < 80 and arr[x, y][2] < 80)
    if dark < total * 0.1:
        return None  # 通知なし
    # Elite=橙色チェック
    orange = sum(1 for x in range(w) for y in range(h)
                 if arr[x, y][0] > 200 and arr[x, y][1] > 100 and arr[x, y][2] < 80)
    return "elite" if orange > total * 0.05 else "normal"


def read_stage_badge(rect):
    """バトルストリップのステージバッジ読み取り (色ベース近似)"""
    if not rect:
        return "---"
    L, T, R, B = rect
    # バッジ位置: ウィンドウ左端から少し右
    bx = L + 220
    by = T + 995
    badge = ImageGrab.grab(bbox=(bx, by, bx+55, by+25))
    arr = badge.load()
    # ほぼ暗い背景=バッジあり
    dark = sum(1 for x in range(55) for y in range(25)
               if arr[x, y][0] < 100 and arr[x, y][1] < 100 and arr[x, y][2] < 100)
    if dark > 55 * 25 * 0.3:
        return "取得中"
    return "---"


def init_log():
    if not LOG_CSV.exists():
        with open(LOG_CSV, "w", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow(["timestamp", "type", "stage", "extra", "image"])


def log_event(ts, event_type, img):
    fname = f"{ts.strftime('%Y%m%d_%H%M%S')}_{event_type}.png"
    img.save(str(IMG_DIR / fname))
    with open(LOG_CSV, "a", newline="", encoding="utf-8") as f:
        csv.writer(f).writerow([ts.strftime("%Y-%m-%d %H:%M:%S"), event_type, "", "", fname])
    return fname


# ========================
# オーバーレイUI
# ========================
class Overlay:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("TBH Monitor")
        self.root.resizable(False, False)
        self.root.attributes("-topmost", True)
        self.root.attributes("-alpha", 0.88)
        self.root.overrideredirect(True)  # タイトルバー非表示
        self.root.configure(bg="#1a1a2e")

        # ゲーム窓の左に配置
        rect = get_game_rect()
        if rect:
            L, T, R, B = rect
            wx = max(0, L - 260)
            wy = T + 40
        else:
            wx, wy = 1080, 380
        self.root.geometry(f"250x520+{wx}+{wy}")

        self._build_ui()

        # 状態
        self.prev_hash = ""
        self.elite_count = 0
        self.normal_count = 0
        self.last_elite = None
        self.last_notify = None
        self.running = True

        init_log()
        self._start_monitor()

        # ドラッグ移動
        self.root.bind("<ButtonPress-1>", self._drag_start)
        self.root.bind("<B1-Motion>", self._drag_move)

    def _build_ui(self):
        BG = "#1a1a2e"
        HEADER = "#e94560"
        TEXT = "#eaeaea"
        DIM = "#888"
        GOLD = "#f4c430"
        GREEN = "#4ade80"
        BLUE = "#60a5fa"

        f = tkfont.Font(family="Segoe UI", size=9)
        fb = tkfont.Font(family="Segoe UI", size=9, weight="bold")
        ft = tkfont.Font(family="Segoe UI", size=11, weight="bold")
        fs = tkfont.Font(family="Segoe UI", size=8)

        # --- ヘッダー ---
        hdr = tk.Frame(self.root, bg=HEADER, padx=6, pady=4)
        hdr.pack(fill="x")
        tk.Label(hdr, text="⚔ Task Bar Hero Monitor",
                 fg="white", bg=HEADER, font=fb).pack(side="left")
        tk.Button(hdr, text="×", fg="white", bg=HEADER, bd=0,
                  font=fb, cursor="hand2",
                  command=self.root.destroy).pack(side="right")

        pad = dict(bg=BG, padx=8)

        # --- ゲーム状態 ---
        tk.Label(self.root, text="[+] GAME STATUS", fg=HEADER, bg=BG,
                 font=fb, anchor="w", padx=8).pack(fill="x", pady=(8, 2))

        row1 = tk.Frame(self.root, **pad)
        row1.pack(fill="x")
        tk.Label(row1, text="現在ステージ:", fg=DIM, bg=BG, font=f).pack(side="left")
        self.lbl_stage = tk.Label(row1, text="読取中...", fg=GREEN, bg=BG, font=fb)
        self.lbl_stage.pack(side="left", padx=(4, 0))

        self.lbl_notif = tk.Label(self.root, text="", fg=GOLD, bg=BG,
                                  font=fs, anchor="w", padx=8, wraplength=230)
        self.lbl_notif.pack(fill="x")

        tk.Frame(self.root, bg="#333", height=1).pack(fill="x", pady=4)

        # --- Elite Chest カウンター ---
        tk.Label(self.root, text="[*] ELITE CHEST", fg=GOLD, bg=BG,
                 font=fb, anchor="w", padx=8).pack(fill="x", pady=(2, 2))

        row2 = tk.Frame(self.root, **pad)
        row2.pack(fill="x")
        tk.Label(row2, text="今セッション:", fg=DIM, bg=BG, font=f).pack(side="left")
        self.lbl_elite_count = tk.Label(row2, text="0 回", fg=GOLD, bg=BG, font=ft)
        self.lbl_elite_count.pack(side="left", padx=4)

        row3 = tk.Frame(self.root, **pad)
        row3.pack(fill="x")
        tk.Label(row3, text="前回取得:", fg=DIM, bg=BG, font=f).pack(side="left")
        self.lbl_last_elite = tk.Label(row3, text="---", fg=TEXT, bg=BG, font=f)
        self.lbl_last_elite.pack(side="left", padx=4)

        row4 = tk.Frame(self.root, **pad)
        row4.pack(fill="x")
        tk.Label(row4, text="通常宝箱:", fg=DIM, bg=BG, font=f).pack(side="left")
        self.lbl_normal_count = tk.Label(row4, text="0 回", fg=BLUE, bg=BG, font=f)
        self.lbl_normal_count.pack(side="left", padx=4)

        tk.Frame(self.root, bg="#333", height=1).pack(fill="x", pady=4)

        # --- 推奨ローテーション ---
        tk.Label(self.root, text="[R] 推奨ローテーション", fg=BLUE, bg=BG,
                 font=fb, anchor="w", padx=8).pack(fill="x", pady=(2, 4))

        self.rot_frames = []
        for stage, lv, diff in RECOMMENDED_ROTATION:
            row = tk.Frame(self.root, bg=BG, padx=8)
            row.pack(fill="x", pady=1)
            color = "#ff6b6b" if diff == "Nightmare" else "#4ade80"
            tk.Label(row, text=f"  {stage}", fg=GOLD, bg=BG,
                     font=fb, width=6, anchor="w").pack(side="left")
            tk.Label(row, text=lv, fg=DIM, bg=BG,
                     font=fs, width=8, anchor="w").pack(side="left")
            tk.Label(row, text=diff, fg=color, bg=BG,
                     font=fs, anchor="w").pack(side="left")
            self.rot_frames.append(row)

        tk.Frame(self.root, bg="#333", height=1).pack(fill="x", pady=4)

        # --- 更新時刻 ---
        self.lbl_update = tk.Label(self.root, text="更新: ---",
                                   fg=DIM, bg=BG, font=fs, anchor="w", padx=8)
        self.lbl_update.pack(fill="x", pady=(0, 4))

    def _drag_start(self, e):
        self._dx = e.x
        self._dy = e.y

    def _drag_move(self, e):
        x = self.root.winfo_x() + e.x - self._dx
        y = self.root.winfo_y() + e.y - self._dy
        self.root.geometry(f"+{x}+{y}")

    def _start_monitor(self):
        t = threading.Thread(target=self._monitor_loop, daemon=True)
        t.start()

    def _monitor_loop(self):
        while self.running:
            try:
                self._update()
            except Exception:
                pass
            time.sleep(UPDATE_SEC)

    def _update(self):
        ts = datetime.now()
        rect = get_game_rect()

        # ステージ読み取り
        stage_txt = read_stage_badge(rect) if rect else "ゲーム未起動"

        # 通知エリア
        notif_img = ImageGrab.grab(bbox=NOTIF_REGION)
        h = img_hash(notif_img)
        notif_result = None
        notif_txt = ""

        if h != self.prev_hash:
            result = detect_elite(notif_img)
            if result == "elite":
                self.elite_count += 1
                self.last_elite = ts
                notif_txt = f"★ Elite Chest! ({ts.strftime('%H:%M:%S')})"
                log_event(ts, "elite_chest", notif_img)
            elif result == "normal":
                self.normal_count += 1
                notif_txt = f"宝箱取得 ({ts.strftime('%H:%M:%S')})"
                log_event(ts, "notification", notif_img)
            self.prev_hash = h

        # UI更新（メインスレッドで）
        def _ui():
            self.lbl_stage.config(text=stage_txt)
            self.lbl_elite_count.config(text=f"{self.elite_count} 回")
            self.lbl_normal_count.config(text=f"{self.normal_count} 回")
            if self.last_elite:
                delta = int((ts - self.last_elite).total_seconds())
                self.lbl_last_elite.config(
                    text=f"{self.last_elite.strftime('%H:%M:%S')} ({delta}秒前)")
            if notif_txt:
                self.lbl_notif.config(text=notif_txt)
            self.lbl_update.config(text=f"更新: {ts.strftime('%H:%M:%S')}")
        self.root.after(0, _ui)

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    Overlay().run()
