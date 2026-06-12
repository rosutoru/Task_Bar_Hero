#!/usr/bin/env python3
"""Task Bar Hero - Overlay Widget
ゲーム左横にリアルタイム情報を表示
"""
import tkinter as tk
from tkinter import font as tkfont
import threading
import time
import re
import csv
import hashlib
from datetime import datetime
from PIL import ImageGrab
import win32gui
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

COOLDOWN_SEC = 15 * 60  # 15分

RECOMMENDED_ROTATION = [
    ("1-1", "Lv 1",  "Normal"),
    ("1-4", "Lv 2",  "Normal"),
    ("1-8", "Lv 3",  "Normal"),
    ("2-3", "Lv 15", "Normal"),
    ("2-8", "Lv 20", "Normal"),
    ("3-8", "Lv 30", "Normal"),
    ("1-9", "Lv 40", "Nightmare"),
    ("3-5", "Lv 50", "Nightmare"),
    ("2-5", "Lv 65", "Hell"),
    ("1-3", "Lv 80", "Torment"),
]

NOTIF_REGION = (1548, 1185, 2360, 1230)


# ========================
# OCR
# ========================
_ocr_reader = None
_ocr_ready = False

def _init_ocr():
    global _ocr_reader, _ocr_ready
    try:
        import easyocr
        _ocr_reader = easyocr.Reader(['ja', 'en'], gpu=False, verbose=False)
        _ocr_ready = True
    except Exception:
        _ocr_ready = False

threading.Thread(target=_init_ocr, daemon=True).start()


def ocr_text(img):
    if not _ocr_ready or _ocr_reader is None:
        return ""
    try:
        result = _ocr_reader.readtext(img, detail=0)
        return " ".join(result)
    except Exception:
        return ""


def parse_stage(text):
    """OCRテキストからステージ名を正規化して返す"""
    # ハイフン付き: ステージ 3-5
    m = re.search(r'ステージ\s*([A-Z]?\d+[-]\d+)', text)
    if m:
        return m.group(1)
    # Lxx形式: ステージ L49
    m = re.search(r'ステージ\s*(L\d+)', text)
    if m:
        return m.group(1)
    # 2桁数字（ハイフン消え）: ステージ35 → 3-5
    m = re.search(r'ステージ\s*(\d)(\d)(?:\D|$)', text)
    if m:
        return f"{m.group(1)}-{m.group(2)}"
    return None


# ========================
# ゲーム情報取得
# ========================
def get_game_rect():
    hwnd = win32gui.FindWindow("UnityWndClass", "TaskBarHero")
    if not hwnd:
        return None
    return win32gui.GetWindowRect(hwnd)


def img_hash(img):
    return hashlib.md5(img.tobytes()).hexdigest()


def detect_chest(img):
    arr = img.load()
    w, h = img.size
    total = w * h
    dark = sum(1 for x in range(w) for y in range(h)
               if arr[x, y][0] < 80 and arr[x, y][1] < 80 and arr[x, y][2] < 80)
    if dark < total * 0.1:
        return None
    orange = sum(1 for x in range(w) for y in range(h)
                 if arr[x, y][0] > 200 and arr[x, y][1] > 100 and arr[x, y][2] < 80)
    return "elite" if orange > total * 0.05 else "normal"


def init_log():
    if not LOG_CSV.exists():
        with open(LOG_CSV, "w", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow(["timestamp", "type", "stage", "extra", "image"])


def log_event(ts, event_type, stage, img):
    fname = f"{ts.strftime('%Y%m%d_%H%M%S')}_{event_type}.png"
    img.save(str(IMG_DIR / fname))
    with open(LOG_CSV, "a", newline="", encoding="utf-8") as f:
        csv.writer(f).writerow([ts.strftime("%Y-%m-%d %H:%M:%S"), event_type, stage or "", "", fname])
    return fname


def fmt_elapsed(ts, now):
    secs = int((now - ts).total_seconds())
    if secs < 60:
        return f"{secs}秒前"
    return f"{secs // 60}分{secs % 60:02d}秒前"


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
        self.root.overrideredirect(True)
        self.root.configure(bg="#1a1a2e")

        rect = get_game_rect()
        if rect:
            L, T, R, B = rect
            wx = max(0, L - 270)
            wy = T + 40
        else:
            wx, wy = 1080, 380
        self.root.geometry(f"270x680+{wx}+{wy}")

        # 状態
        self.prev_hash = ""
        self.elite_count = 0
        self.normal_count = 0
        self.last_elite = None
        self.stage_last = {}   # stage_name -> datetime

        self._build_ui()
        init_log()
        self._start_monitor()

        self.root.bind("<ButtonPress-1>", self._drag_start)
        self.root.bind("<B1-Motion>", self._drag_move)

    def _build_ui(self):
        BG    = "#1a1a2e"
        HDR   = "#e94560"
        TEXT  = "#eaeaea"
        DIM   = "#888"
        GOLD  = "#f4c430"
        GREEN = "#4ade80"
        BLUE  = "#60a5fa"

        f  = tkfont.Font(family="Segoe UI", size=9)
        fb = tkfont.Font(family="Segoe UI", size=9, weight="bold")
        ft = tkfont.Font(family="Segoe UI", size=11, weight="bold")
        fs = tkfont.Font(family="Segoe UI", size=8)

        # ヘッダー
        hdr = tk.Frame(self.root, bg=HDR, padx=6, pady=4)
        hdr.pack(fill="x")
        tk.Label(hdr, text="Task Bar Hero Monitor",
                 fg="white", bg=HDR, font=fb).pack(side="left")
        tk.Button(hdr, text="x", fg="white", bg=HDR, bd=0,
                  font=fb, cursor="hand2",
                  command=self.root.destroy).pack(side="right")

        # OCRステータス
        self.lbl_ocr = tk.Label(self.root, text="OCR: 初期化中...",
                                fg=DIM, bg=BG, font=fs, anchor="w", padx=8)
        self.lbl_ocr.pack(fill="x")

        tk.Frame(self.root, bg="#333", height=1).pack(fill="x")

        # Elite Chest カウンター
        tk.Label(self.root, text="[*] ELITE CHEST", fg=GOLD, bg=BG,
                 font=fb, anchor="w", padx=8).pack(fill="x", pady=(6, 2))

        row2 = tk.Frame(self.root, bg=BG, padx=8)
        row2.pack(fill="x")
        tk.Label(row2, text="今セッション:", fg=DIM, bg=BG, font=f).pack(side="left")
        self.lbl_elite_count = tk.Label(row2, text="0 回", fg=GOLD, bg=BG, font=ft)
        self.lbl_elite_count.pack(side="left", padx=4)

        row3 = tk.Frame(self.root, bg=BG, padx=8)
        row3.pack(fill="x")
        tk.Label(row3, text="前回取得:", fg=DIM, bg=BG, font=f).pack(side="left")
        self.lbl_last_elite = tk.Label(row3, text="---", fg=TEXT, bg=BG, font=f)
        self.lbl_last_elite.pack(side="left", padx=4)

        self.lbl_notif = tk.Label(self.root, text="", fg=GOLD, bg=BG,
                                  font=fs, anchor="w", padx=8, wraplength=240)
        self.lbl_notif.pack(fill="x")

        tk.Frame(self.root, bg="#333", height=1).pack(fill="x", pady=4)

        # 推奨ローテーション（各行に経過時間追加）
        tk.Label(self.root, text="[R] 推奨ローテーション", fg=BLUE, bg=BG,
                 font=fb, anchor="w", padx=8).pack(fill="x", pady=(0, 4))

        # ヘッダー行
        hrow = tk.Frame(self.root, bg=BG, padx=8)
        hrow.pack(fill="x")
        tk.Label(hrow, text="Stage", fg=DIM, bg=BG, font=fs, width=6, anchor="w").pack(side="left")
        tk.Label(hrow, text="Lv",    fg=DIM, bg=BG, font=fs, width=7, anchor="w").pack(side="left")
        tk.Label(hrow, text="Diff",  fg=DIM, bg=BG, font=fs, width=5, anchor="w").pack(side="left")
        tk.Label(hrow, text="残り",  fg=DIM, bg=BG, font=fs, anchor="w").pack(side="left")

        DIFF_COLOR = {
            "Normal":    GREEN,
            "Nightmare": "#fb923c",
            "Hell":      "#f87171",
            "Torment":   "#c084fc",
        }

        self.rot_time_labels = {}  # stage -> Label
        for stage, lv, diff in RECOMMENDED_ROTATION:
            row = tk.Frame(self.root, bg=BG, padx=8)
            row.pack(fill="x", pady=1)
            dc = DIFF_COLOR.get(diff, DIM)
            tk.Label(row, text=stage, fg=GOLD, bg=BG,
                     font=fb, width=6, anchor="w").pack(side="left")
            tk.Label(row, text=lv, fg=DIM, bg=BG,
                     font=fs, width=7, anchor="w").pack(side="left")
            tk.Label(row, text=diff[:4], fg=dc, bg=BG,
                     font=fs, width=5, anchor="w").pack(side="left")
            lbl = tk.Label(row, text="---", fg=DIM, bg=BG, font=fs, anchor="w")
            lbl.pack(side="left")
            self.rot_time_labels[stage] = lbl

        tk.Frame(self.root, bg="#333", height=1).pack(fill="x", pady=4)

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
        threading.Thread(target=self._monitor_loop, daemon=True).start()
        threading.Thread(target=self._ocr_status_loop, daemon=True).start()

    def _ocr_status_loop(self):
        while True:
            if _ocr_ready:
                self.root.after(0, lambda: self.lbl_ocr.config(text="OCR: 準備完了", fg="#4ade80"))
                break
            time.sleep(1)

    def _monitor_loop(self):
        while True:
            try:
                self._update()
            except Exception:
                pass
            time.sleep(UPDATE_SEC)

    def _update(self):
        ts = datetime.now()

        notif_img = ImageGrab.grab(bbox=NOTIF_REGION)
        h = img_hash(notif_img)
        notif_txt = ""
        detected_stage = None

        if h != self.prev_hash:
            result = detect_chest(notif_img)
            if result in ("elite", "normal"):
                # OCRでステージ名取得
                if _ocr_ready:
                    ocr = ocr_text(notif_img)
                    detected_stage = parse_stage(ocr)
                    if detected_stage:
                        self.stage_last[detected_stage] = ts

                if result == "elite":
                    self.elite_count += 1
                    self.last_elite = ts
                    stage_str = detected_stage or "?"
                    notif_txt = f"Elite! [{stage_str}] {ts.strftime('%H:%M:%S')}"
                else:
                    stage_str = detected_stage or "?"
                    notif_txt = f"宝箱 [{stage_str}] {ts.strftime('%H:%M:%S')}"

                log_event(ts, f"{result}_chest", detected_stage, notif_img)
            self.prev_hash = h

        def _ui():
            self.lbl_elite_count.config(text=f"{self.elite_count} 回")
            if self.last_elite:
                delta = fmt_elapsed(self.last_elite, ts)
                self.lbl_last_elite.config(text=f"{self.last_elite.strftime('%H:%M:%S')} ({delta})")
            if notif_txt:
                self.lbl_notif.config(text=notif_txt)

            # ローテ行の残り時間更新
            for stage, lv, diff in RECOMMENDED_ROTATION:
                lbl = self.rot_time_labels[stage]
                if stage in self.stage_last:
                    elapsed_sec = int((ts - self.stage_last[stage]).total_seconds())
                    remain = COOLDOWN_SEC - elapsed_sec
                    if remain <= 0:
                        lbl.config(text="OK!", fg="#4ade80")
                    else:
                        m, s = divmod(remain, 60)
                        lbl.config(text=f"{m}:{s:02d}", fg="#facc15")
                else:
                    lbl.config(text="---", fg="#888")

            self.lbl_update.config(text=f"更新: {ts.strftime('%H:%M:%S')}")

        self.root.after(0, _ui)

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    Overlay().run()
