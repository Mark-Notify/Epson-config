# -*- coding: utf-8 -*-
"""
Epson Ink Pad Reset - หน้าต่างกดใช้งานง่าย (customtkinter)

โหมดทดสอบโดยไม่มีเครื่องพิมพ์:  set EPSON_RESET_MOCK=1
"""

import os
import queue
import sys
import threading
import traceback
import webbrowser

import customtkinter as ctk

import epson_reset_core as core
import updater

# ---------------------------------------------------------------- theme
FONT = "Leelawadee UI"

BG = ("#EEF2F7", "#111318")
CARD = ("#FFFFFF", "#1B1E25")
BORDER = ("#E3E8EF", "#2A2E37")
TEXT = ("#111827", "#E8EAED")
MUTED = ("#6B7280", "#9AA0A6")
SOFT = ("#F5F7FA", "#22262E")

BLUE = ("#2563EB", "#3B82F6")
BLUE_H = ("#1D4ED8", "#2563EB")
RED = ("#DC2626", "#EF4444")
RED_H = ("#B91C1C", "#DC2626")
GREEN = ("#16A34A", "#22C55E")
AMBER = ("#D97706", "#F59E0B")
GREY = ("#9CA3AF", "#6B7280")

INK_COLORS = {
    "Black": ("#1F2937", "#D1D5DB"),
    "Cyan": ("#06B6D4", "#22D3EE"),
    "Magenta": ("#DB2777", "#F472B6"),
    "Yellow": ("#EAB308", "#FACC15"),
}

HERO = {
    "idle": ("?", GREY, "พร้อมเริ่มใช้งาน",
             "เสียบสาย USB และเปิดเครื่องพิมพ์ แล้วกด \"ตรวจสอบเครื่องพิมพ์\""),
    "busy": ("…", BLUE, "กำลังทำงาน", ""),
    "error": ("!", RED, "ติดต่อเครื่องพิมพ์ไม่ได้",
              "เช็กว่าเสียบสาย USB และเปิดเครื่องแล้ว ปิดโปรแกรมอื่นที่ใช้เครื่องพิมพ์ "
              "(เช่น WIC Reset) แล้วลองใหม่"),
    "ok": ("✓", GREEN, "เครื่องพิมพ์ปกติ", "ซับหมึกยังไม่เต็ม ใช้งานต่อได้เลย"),
    "full": ("!", RED, "ซับหมึกเต็ม",
             "เครื่องพิมพ์หยุดทำงานเพราะตัวนับซับหมึกเต็ม กด \"รีเซ็ตซับหมึก\" เพื่อแก้"),
    "unsupported": ("?", AMBER, "ยังไม่รองรับรุ่นนี้",
                    "อ่านข้อมูลเครื่องได้ แต่ไม่มีข้อมูลสำหรับรีเซ็ตรุ่นนี้"),
    "done": ("✓", GREEN, "รีเซ็ตสำเร็จ",
             "ปิดเครื่องพิมพ์ด้วยปุ่ม Power รอไฟดับ เปิดใหม่ แล้วกด \"ตรวจสอบอีกครั้ง\""),
    "failed": ("!", RED, "รีเซ็ตไม่สำเร็จ",
               "เครื่องพิมพ์ไม่รับคำสั่ง ลองปิด-เปิดเครื่องพิมพ์แล้วทำใหม่"),
    "backup_failed": ("!", RED, "สำรองข้อมูลไม่สำเร็จ",
                      "จึงยังไม่ได้รีเซ็ต เพื่อความปลอดภัย ลองกดตรวจสอบแล้วทำใหม่"),
}


def font(size, weight="normal"):
    return ctk.CTkFont(family=FONT, size=size, weight=weight)


# ---------------------------------------------------------------- widgets
class Card(ctk.CTkFrame):
    def __init__(self, master, **kw):
        super().__init__(master, fg_color=CARD, corner_radius=16,
                         border_width=1, border_color=BORDER, **kw)


class Circle(ctk.CTkFrame):
    """Fixed-size round badge: the frame keeps its size, the text sits inside,
    so a wide glyph or Windows display scaling never stretches it into an oval."""

    def __init__(self, master, size, text="", color=GREY, text_color="#FFFFFF",
                 text_font=None):
        super().__init__(master, width=size, height=size, corner_radius=size // 2,
                         fg_color=color)
        self.pack_propagate(False)
        self.grid_propagate(False)
        self.label = ctk.CTkLabel(self, text=text, fg_color="transparent",
                                  text_color=text_color, font=text_font,
                                  width=1, height=1)
        self.label.place(relx=0.5, rely=0.5, anchor="center")

    def set(self, text=None, color=None, text_color=None):
        if color is not None:
            self.configure(fg_color=color)
        kw = {}
        if text is not None:
            kw["text"] = text
        if text_color is not None:
            kw["text_color"] = text_color
        if kw:
            self.label.configure(**kw)


class Pill(ctk.CTkLabel):
    def __init__(self, master, **kw):
        super().__init__(master, text="—", font=font(12, "bold"), corner_radius=10,
                         fg_color=SOFT, text_color=MUTED, height=26, width=96, **kw)

    def set(self, text, color=None):
        if color is None:
            self.configure(text=text, fg_color=SOFT, text_color=MUTED)
        else:
            self.configure(text=text, fg_color=color, text_color="#FFFFFF")


class InkBar(ctk.CTkFrame):
    def __init__(self, master, name):
        super().__init__(master, fg_color="transparent")
        self.color = color = INK_COLORS.get(name, BLUE)
        self.value = ctk.CTkLabel(self, text="—", font=font(13, "bold"),
                                  text_color=TEXT)
        self.value.pack()
        self.bar = ctk.CTkProgressBar(self, orientation="vertical", width=22,
                                      height=86, corner_radius=8,
                                      progress_color=color, fg_color=SOFT)
        self.bar.set(0)
        self.bar.configure(progress_color=SOFT)
        self.bar.pack(pady=4)
        ctk.CTkLabel(self, text=core.INK_TH.get(name, name), font=font(12),
                     text_color=MUTED).pack()

    def set(self, level):
        if level is None:
            self.value.configure(text="—")
            self.bar.set(0)
            self.bar.configure(progress_color=SOFT)
        else:
            self.value.configure(text=f"{level}%")
            self.bar.configure(progress_color=self.color)
            self.bar.set(max(0, min(100, level)) / 100)


class Steps(ctk.CTkFrame):
    LABELS = ("เชื่อมต่อ", "ตรวจสอบ", "รีเซ็ต", "ปิด-เปิดเครื่อง")

    def __init__(self, master):
        super().__init__(master, fg_color="transparent")
        self.dots = []
        for i, label in enumerate(self.LABELS):
            col = ctk.CTkFrame(self, fg_color="transparent")
            col.grid(row=0, column=i * 2)
            dot = Circle(col, 26, str(i + 1), SOFT, MUTED, font(12, "bold"))
            dot.pack()
            ctk.CTkLabel(col, text=label, font=font(11), text_color=MUTED).pack()
            self.dots.append(dot)
            if i < len(self.LABELS) - 1:
                ctk.CTkFrame(self, height=2, width=46, fg_color=BORDER).grid(
                    row=0, column=i * 2 + 1, padx=4, pady=(0, 18))

    def set(self, done_upto, current):
        for i, dot in enumerate(self.dots):
            if i < done_upto:
                dot.set("✓", GREEN, "#FFFFFF")
            elif i == current:
                dot.set(str(i + 1), BLUE, "#FFFFFF")
            else:
                dot.set(str(i + 1), SOFT, MUTED)


# ---------------------------------------------------------------- confirm dialog
class ConfirmDialog(ctk.CTkToplevel):
    def __init__(self, master, model):
        super().__init__(master)
        self.result = False
        self.title("ยืนยันการรีเซ็ต")
        self.configure(fg_color=BG)
        self.resizable(False, False)
        self.transient(master)

        card = Card(self)
        card.pack(padx=18, pady=18, fill="both", expand=True)

        Circle(card, 56, "!", AMBER, "#FFFFFF", font(28, "bold")).pack(pady=(22, 8))
        ctk.CTkLabel(card, text=f"รีเซ็ตซับหมึก {model}?", font=font(20, "bold"),
                     text_color=TEXT).pack()

        points = (
            ("💾", "โปรแกรมจะสำรองข้อมูลเครื่องพิมพ์ไว้ก่อนอัตโนมัติ"),
            ("🔌", "ห้ามปิดเครื่องพิมพ์หรือถอดสาย USB ระหว่างรีเซ็ต"),
            ("💧", "แผ่นซับหมึกจริงยังเต็ม ควรล้าง/เปลี่ยน หรือต่อถังหมึกทิ้ง"),
            ("🛡", "การรีเซ็ตเองอาจทำให้เสียสิทธิ์ประกันจาก Epson"),
        )
        box = ctk.CTkFrame(card, fg_color=SOFT, corner_radius=12)
        box.pack(padx=22, pady=16, fill="x")
        for icon, text in points:
            row = ctk.CTkFrame(box, fg_color="transparent")
            row.pack(fill="x", padx=14, pady=5)
            ctk.CTkLabel(row, text=icon, width=26, font=font(15)).pack(side="left")
            ctk.CTkLabel(row, text=text, font=font(13), text_color=TEXT,
                         anchor="w", justify="left", wraplength=360).pack(
                side="left", fill="x", padx=(6, 0))

        self.agree = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(card, text="ฉันเข้าใจและต้องการรีเซ็ต", variable=self.agree,
                        font=font(13), text_color=TEXT, fg_color=RED,
                        hover_color=RED_H, command=self._toggle).pack(
            padx=22, anchor="w")

        btns = ctk.CTkFrame(card, fg_color="transparent")
        btns.pack(fill="x", padx=22, pady=(16, 22))
        ctk.CTkButton(btns, text="ยกเลิก", height=44, corner_radius=12,
                      font=font(14), fg_color=SOFT, hover_color=BORDER,
                      text_color=TEXT, command=self.destroy).pack(
            side="left", expand=True, fill="x", padx=(0, 6))
        self.ok_btn = ctk.CTkButton(btns, text="รีเซ็ตเลย", height=44,
                                    corner_radius=12, font=font(14, "bold"),
                                    fg_color=RED, hover_color=RED_H,
                                    state="disabled", command=self._ok)
        self.ok_btn.pack(side="left", expand=True, fill="x", padx=(6, 0))

        self.update_idletasks()
        x = master.winfo_rootx() + (master.winfo_width() - self.winfo_width()) // 2
        y = master.winfo_rooty() + 60
        self.geometry(f"+{max(x, 0)}+{max(y, 0)}")
        self.after(50, self._grab)

    def _grab(self):
        try:
            self.grab_set()
            self.focus_force()
        except Exception:
            pass

    def _toggle(self):
        self.ok_btn.configure(state="normal" if self.agree.get() else "disabled")

    def _ok(self):
        self.result = True
        self.destroy()


# ---------------------------------------------------------------- main window
class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        ctk.set_appearance_mode("system")
        self.title(core.APP_TITLE + (" · โหมดทดสอบ" if core.MOCK else ""))
        self.configure(fg_color=BG)
        try:
            self.iconbitmap(str(core.app_dir() / "assets" / "app.ico"))
        except Exception:
            pass
        self._fit_to_screen(640, 820)

        self.jobs = queue.Queue()
        self.model = None
        self.serial = ""
        self.supported = False
        self.ui_state = "idle"
        self.log_visible = False
        self.last_backup = None
        self.release = None
        self.dl_progress = None

        self._build()
        self._set_state("idle")
        self.after(100, self._poll)
        self.after(1500, lambda: self.check_update(silent=True))
        if not core.CONF:
            self._set_state("error")
            self.hero_sub.configure(text="ไม่พบไฟล์ข้อมูลรุ่นเครื่องพิมพ์ (printers.pickle)")

    def _fit_to_screen(self, width, height):
        """Never open taller than the screen (small laptops, 125-150% scaling)."""
        try:
            scale = ctk.ScalingTracker.get_window_scaling(self)
        except Exception:
            scale = 1.0
        screen_h = self.winfo_screenheight() / scale
        screen_w = self.winfo_screenwidth() / scale
        h = int(min(height, screen_h - 90))
        w = int(min(width, screen_w - 40))
        self.minsize(min(520, w), min(480, h))
        self.geometry(f"{w}x{h}+{int((screen_w - w) / 2)}+{max(int((screen_h - h) / 2) - 30, 0)}")

    # -- layout
    def _build(self):
        wrap = ctk.CTkFrame(self, fg_color="transparent")
        wrap.pack(fill="both", expand=True, padx=22, pady=(18, 10))

        # update banner (shown only when a newer release exists)
        self.update_bar = ctk.CTkFrame(wrap, fg_color=BLUE, corner_radius=14)
        ub = ctk.CTkFrame(self.update_bar, fg_color="transparent")
        ub.pack(fill="x", padx=14, pady=10)
        ctk.CTkLabel(ub, text="⬆", font=font(18, "bold"),
                     text_color="#FFFFFF").pack(side="left", padx=(0, 8))
        self.update_text = ctk.CTkLabel(ub, text="", font=font(13, "bold"),
                                        text_color="#FFFFFF", anchor="w",
                                        justify="left", wraplength=330)
        self.update_text.pack(side="left", fill="x", expand=True)
        self.update_later = ctk.CTkButton(
            ub, text="ภายหลัง", width=70, height=32, corner_radius=10,
            font=font(12), fg_color="transparent", hover_color=BLUE_H,
            text_color="#FFFFFF", command=lambda: self.update_bar.pack_forget())
        self.update_later.pack(side="right", padx=(6, 0))
        self.update_btn = ctk.CTkButton(
            ub, text="อัปเดตเลย", width=100, height=32, corner_radius=10,
            font=font(13, "bold"), fg_color="#FFFFFF", hover_color="#DBEAFE",
            text_color=BLUE, command=self.on_update)
        self.update_btn.pack(side="right")
        self.update_progress = ctk.CTkProgressBar(
            self.update_bar, height=6, progress_color="#FFFFFF",
            fg_color=BLUE_H)

        # header
        head = ctk.CTkFrame(wrap, fg_color="transparent")
        head.pack(fill="x")
        self.head = head
        ctk.CTkLabel(head, text="🖨", font=font(30)).pack(side="left", padx=(0, 10))
        titles = ctk.CTkFrame(head, fg_color="transparent")
        titles.pack(side="left")
        ctk.CTkLabel(titles, text="รีเซ็ตซับหมึก Epson", font=font(22, "bold"),
                     text_color=TEXT).pack(anchor="w")
        ctk.CTkLabel(titles, text="เช็กสถานะและรีเซ็ตตัวนับซับหมึกผ่านสาย USB",
                     font=font(13), text_color=MUTED).pack(anchor="w")
        badge = "โหมดทดสอบ" if core.MOCK else "USB"
        ctk.CTkLabel(head, text=badge, font=font(12, "bold"), corner_radius=10,
                     fg_color=AMBER if core.MOCK else BLUE, text_color="#FFFFFF",
                     height=26, width=80).pack(side="right")

        self.steps = Steps(wrap)
        self.steps.pack(pady=(18, 10))

        # bottom area is packed BEFORE the cards, so on a short screen the
        # cards scroll instead of the buttons and links being cut off
        bottom = ctk.CTkFrame(wrap, fg_color="transparent")
        bottom.pack(side="bottom", fill="x", pady=(8, 0))

        self.btn_primary = ctk.CTkButton(bottom, text="", height=52,
                                         corner_radius=14, font=font(16, "bold"),
                                         command=self._primary)
        self.btn_primary.pack(fill="x")
        self.btn_secondary = ctk.CTkButton(bottom, text="", height=40,
                                           corner_radius=12, font=font(14),
                                           fg_color="transparent", border_width=1,
                                           border_color=BORDER, text_color=TEXT,
                                           hover_color=SOFT,
                                           command=self._secondary)
        self.secondary_slot = ctk.CTkFrame(bottom, fg_color="transparent", height=0)
        self.secondary_slot.pack(fill="x")

        self.log_box = ctk.CTkTextbox(bottom, height=110, font=("Consolas", 11),
                                      fg_color=CARD, text_color=MUTED,
                                      border_width=1, border_color=BORDER,
                                      corner_radius=12, wrap="word")
        self.log_box.configure(state="disabled")

        foot = ctk.CTkFrame(bottom, fg_color="transparent")
        foot.pack(fill="x", side="bottom", pady=(6, 0))
        link = dict(fg_color="transparent", hover_color=SOFT, text_color=BLUE,
                    font=font(12), height=28, width=10)
        ctk.CTkButton(foot, text="📁 เปิดโฟลเดอร์ไฟล์สำรอง",
                      command=self._open_backups, **link).pack(side="left")
        self.btn_log = ctk.CTkButton(foot, text="รายละเอียดทางเทคนิค ▾",
                                     command=self._toggle_log, **link)
        self.btn_log.pack(side="left", padx=4)
        self.btn_upd = ctk.CTkButton(foot, text="ตรวจหาอัปเดต",
                                     command=lambda: self.check_update(silent=False),
                                     **link)
        self.btn_upd.pack(side="left", padx=4)
        self.version_label = ctk.CTkLabel(
            foot, text=f"v{core.APP_VERSION} · EUPL-1.2", font=font(11),
            text_color=MUTED)
        self.version_label.pack(side="right")

        # middle: cards, scrollable when the window is short
        mid = ctk.CTkScrollableFrame(wrap, fg_color="transparent",
                                     scrollbar_button_color=BORDER,
                                     scrollbar_button_hover_color=MUTED)
        mid.pack(fill="both", expand=True)
        self.mid = mid
        mid.bind("<Configure>", lambda e: self.after_idle(self._update_scrollbar))
        mid._parent_canvas.bind("<Configure>",
                                lambda e: self.after_idle(self._update_scrollbar),
                                add="+")

        # hero
        hero = Card(mid)
        hero.pack(fill="x", pady=(4, 10))
        inner = ctk.CTkFrame(hero, fg_color="transparent")
        inner.pack(fill="x", padx=20, pady=18)
        self.hero_icon = Circle(inner, 64, "?", GREY, "#FFFFFF", font(30, "bold"))
        self.hero_icon.pack(side="left", padx=(0, 16))
        texts = ctk.CTkFrame(inner, fg_color="transparent")
        texts.pack(side="left", fill="x", expand=True)
        self.hero_title = ctk.CTkLabel(texts, text="", font=font(20, "bold"),
                                       text_color=TEXT, anchor="w")
        self.hero_title.pack(fill="x")
        self.hero_sub = ctk.CTkLabel(texts, text="", font=font(13),
                                     text_color=MUTED, anchor="w", justify="left",
                                     wraplength=440)
        self.hero_sub.pack(fill="x")
        self.progress = ctk.CTkProgressBar(texts, mode="indeterminate", height=6,
                                           progress_color=BLUE, fg_color=SOFT)

        # info row: printer + waste pads
        row = ctk.CTkFrame(mid, fg_color="transparent")
        row.pack(fill="x", pady=(0, 10))
        row.grid_columnconfigure((0, 1), weight=1, uniform="c")

        info = Card(row)
        info.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        ctk.CTkLabel(info, text="เครื่องพิมพ์", font=font(13, "bold"),
                     text_color=MUTED).pack(anchor="w", padx=16, pady=(14, 4))
        self.info_rows = {}
        for key, label in (("model", "รุ่น"), ("status", "สถานะ"),
                           ("serial", "ซีเรียล")):
            r = ctk.CTkFrame(info, fg_color="transparent")
            r.pack(fill="x", padx=16, pady=2)
            ctk.CTkLabel(r, text=label, font=font(13), text_color=MUTED,
                         width=60, anchor="w").pack(side="left")
            v = ctk.CTkLabel(r, text="—", font=font(13, "bold"), text_color=TEXT,
                             anchor="w")
            v.pack(side="left", fill="x", expand=True)
            self.info_rows[key] = v
        ctk.CTkFrame(info, fg_color="transparent", height=10).pack()

        pads = Card(row)
        pads.grid(row=0, column=1, sticky="nsew", padx=(6, 0))
        ctk.CTkLabel(pads, text="แผ่นซับหมึก", font=font(13, "bold"),
                     text_color=MUTED).pack(anchor="w", padx=16, pady=(14, 4))
        self.pad_pills = []
        for i in (1, 2):
            r = ctk.CTkFrame(pads, fg_color="transparent")
            r.pack(fill="x", padx=16, pady=4)
            ctk.CTkLabel(r, text=f"ซับหมึก {i}", font=font(13),
                         text_color=TEXT).pack(side="left")
            pill = Pill(r)
            pill.pack(side="right")
            self.pad_pills.append(pill)

        # inks
        inks = Card(mid)
        inks.pack(fill="x", pady=(0, 12))
        ctk.CTkLabel(inks, text="ระดับหมึก", font=font(13, "bold"),
                     text_color=MUTED).pack(anchor="w", padx=16, pady=(14, 0))
        bars = ctk.CTkFrame(inks, fg_color="transparent")
        bars.pack(pady=(4, 14))
        self.ink_bars = {}
        for name in ("Black", "Cyan", "Magenta", "Yellow"):
            bar = InkBar(bars, name)
            bar.pack(side="left", padx=26)
            self.ink_bars[name] = bar

        self.after(200, self._update_scrollbar)

    # -- state
    def _set_state(self, state, sub=None):
        self.ui_state = state
        icon, color, title, text = HERO[state]
        self.hero_icon.set(icon, color)
        self.hero_title.configure(text=title)
        self.hero_sub.configure(text=sub if sub is not None else text)

        busy = state == "busy"
        if busy:
            self.progress.pack(fill="x", pady=(10, 0))
            self.progress.start()
        else:
            self.progress.stop()
            self.progress.pack_forget()

        steps = {"idle": (0, 0), "busy": (None, None), "error": (0, 0),
                 "ok": (2, 2), "full": (2, 2), "unsupported": (1, 1),
                 "done": (3, 3), "failed": (2, 2), "backup_failed": (2, 2)}
        done, cur = steps[state]
        if done is not None:
            self.steps.set(done, cur)

        primary = {
            "idle": ("ตรวจสอบเครื่องพิมพ์", BLUE, BLUE_H),
            "busy": ("กรุณารอสักครู่...", BLUE, BLUE_H),
            "error": ("ลองอีกครั้ง", BLUE, BLUE_H),
            "ok": ("ตรวจสอบอีกครั้ง", BLUE, BLUE_H),
            "full": ("รีเซ็ตซับหมึก", RED, RED_H),
            "unsupported": ("ตรวจสอบอีกครั้ง", BLUE, BLUE_H),
            "done": ("ตรวจสอบอีกครั้ง", BLUE, BLUE_H),
            "failed": ("ตรวจสอบอีกครั้ง", BLUE, BLUE_H),
            "backup_failed": ("ตรวจสอบอีกครั้ง", BLUE, BLUE_H),
        }[state]
        if hasattr(self, "update_btn") and self.release is not None \
                and self.dl_progress is None:
            self.update_btn.configure(state="disabled" if busy else "normal")
        self.btn_primary.configure(text=primary[0], fg_color=primary[1],
                                   hover_color=primary[2],
                                   state="disabled" if busy else "normal")

        secondary = {"full": "ตรวจสอบอีกครั้ง", "ok": "รีเซ็ตซับหมึกอยู่ดี"}.get(state)
        if secondary:
            self.btn_secondary.configure(text=secondary, state="normal")
            self.btn_secondary.pack(fill="x", pady=(8, 0), in_=self.secondary_slot)
        else:
            self.btn_secondary.pack_forget()

    def _primary(self):
        if self.ui_state == "full":
            self.on_reset()
        else:
            self.on_check()

    def _secondary(self):
        if self.ui_state == "full":
            self.on_check()
        else:
            self.on_reset()

    # -- footer helpers
    def _toggle_log(self):
        self.log_visible = not self.log_visible
        if self.log_visible:
            self.log_box.pack(fill="x", pady=(8, 0), after=self.secondary_slot)
            self.btn_log.configure(text="ซ่อนรายละเอียด ▴")
        else:
            self.log_box.pack_forget()
            self.btn_log.configure(text="รายละเอียดทางเทคนิค ▾")
        self.after(50, self._update_scrollbar)

    def _update_scrollbar(self):
        """Show the scrollbar only when the cards don't fit."""
        try:
            canvas = self.mid._parent_canvas
            bar = self.mid._scrollbar
            need = self.mid.winfo_reqheight() > canvas.winfo_height() + 2
            if need and not bar.winfo_ismapped():
                bar.grid()
            elif not need and bar.winfo_ismapped():
                bar.grid_remove()
                canvas.yview_moveto(0)
        except Exception:
            pass

    def _open_backups(self):
        try:
            os.startfile(str(core.backup_dir()))
        except Exception as exc:
            self._log(f"เปิดโฟลเดอร์ไม่ได้: {exc}")

    def _log(self, text):
        self.log_box.configure(state="normal")
        self.log_box.insert("end", text.rstrip() + "\n")
        self.log_box.see("end")
        self.log_box.configure(state="disabled")

    # -- background jobs
    def _run(self, func, done, *args):
        core.LOG.lines.clear()

        def worker():
            try:
                self.jobs.put((done, func(*args), None))
            except Exception as exc:
                self.jobs.put((done, None, exc))

        threading.Thread(target=worker, daemon=True).start()

    def _poll(self):
        if self.dl_progress is not None:
            self.update_progress.set(self.dl_progress)
        try:
            while True:
                done, result, exc = self.jobs.get_nowait()
                for line in core.LOG.lines:
                    self._log(line)
                if exc is not None:
                    self._log("".join(traceback.format_exception_only(exc)))
                done(result, exc)
        except queue.Empty:
            pass
        self.after(100, self._poll)

    # -- check
    def on_check(self):
        self._set_state("busy", "กำลังอ่านข้อมูลจากเครื่องพิมพ์...")
        self.steps.set(1, 1)
        self._run(core.check_printer, self.after_check)

    def _clear_info(self):
        for v in self.info_rows.values():
            v.configure(text="—")
        for p in self.pad_pills:
            p.set("—")
        for bar in self.ink_bars.values():
            bar.set(None)

    def after_check(self, result, exc):
        if exc is not None:
            self.supported = False
            self._clear_info()
            self._set_state("error")
            return

        self.model = result["model"]
        self.supported = result["supported"]
        status = result.get("status") or {}
        self.serial = str(status.get("serial_number_info", "") or "")
        self._log(f"รุ่น {self.model} | {status}")

        self.info_rows["model"].configure(text=self.model or "ไม่ทราบ")
        st = status.get("status")
        st_text = st[1] if isinstance(st, (list, tuple)) and len(st) > 1 else "—"
        st_th = {"Idle (ready to print)": "พร้อมพิมพ์", "Error": "มีข้อผิดพลาด",
                 "Printing": "กำลังพิมพ์", "Busy": "ไม่ว่าง"}.get(st_text, st_text)
        self.info_rows["status"].configure(text=st_th)
        self.info_rows["serial"].configure(text=self.serial or "—")

        for pill, key in zip(self.pad_pills, ("maintenance_box_1", "maintenance_box_2")):
            val = str(status.get(key, ""))
            if val.startswith("full"):
                pill.set("เต็ม", RED)
            elif val.startswith("near"):
                pill.set("ใกล้เต็ม", AMBER)
            elif val.startswith("not full"):
                pill.set("ปกติ", GREEN)
            else:
                pill.set("—")

        for bar in self.ink_bars.values():
            bar.set(None)
        for ink in status.get("ink_level") or []:
            try:
                if ink[2] in self.ink_bars:
                    self.ink_bars[ink[2]].set(int(ink[4]))
            except Exception:
                pass

        if not self.supported:
            self._set_state("unsupported",
                            f"อ่านข้อมูล {self.model or 'เครื่องนี้'} ได้ "
                            "แต่ยังไม่มีข้อมูลสำหรับรีเซ็ตรุ่นนี้")
        elif core.is_waste_full(status):
            err = status.get("errcode")
            self._set_state("full", None if not err else
                            "เครื่องพิมพ์แจ้งว่าตัวนับซับหมึกเต็ม "
                            "กด \"รีเซ็ตซับหมึก\" เพื่อแก้")
        else:
            self._set_state("ok")

    # -- reset
    def on_reset(self):
        if not self.supported:
            return
        dialog = ConfirmDialog(self, self.model)
        self.wait_window(dialog)
        if not dialog.result:
            return
        self._set_state("busy", "กำลังสำรองข้อมูลและรีเซ็ต... ห้ามปิดเครื่องพิมพ์")
        self.steps.set(2, 2)
        self._run(core.reset_printer, self.after_reset, self.model, self.serial)

    def after_reset(self, result, exc):
        if exc is not None:
            if isinstance(exc, IOError) and "backup-failed" in str(exc):
                self._set_state("backup_failed")
            else:
                self._set_state("failed")
            return
        ok, path = result
        self.last_backup = path
        self._log(f"สำรองไว้ที่: {path}")
        if ok:
            for p in self.pad_pills:
                p.set("—")
            self.info_rows["status"].configure(text="รอปิด-เปิดเครื่อง")
            self._set_state("done")
        else:
            self._set_state("failed")


# ---------------------------------------------------------------- updates
def _bg(app, func, done, *args):
    def worker():
        try:
            app.jobs.put((done, func(*args), None))
        except Exception as exc:
            app.jobs.put((done, None, exc))

    threading.Thread(target=worker, daemon=True).start()


class UpdateMixin:
    def check_update(self, silent=True):
        if not silent:
            self.btn_upd.configure(text="กำลังตรวจ...", state="disabled")
        _bg(self, updater.check,
            lambda r, e: self.after_check_update(r, e, silent), core.APP_VERSION)

    def after_check_update(self, release, exc, silent):
        self.btn_upd.configure(text="ตรวจหาอัปเดต", state="normal")
        if exc is not None:
            if not silent:
                self._log(f"ตรวจหาอัปเดตไม่ได้: {exc}")
                self._flash_version("ตรวจหาอัปเดตไม่ได้ (เช็กอินเทอร์เน็ต)", RED)
            return
        if release is None:
            if not silent:
                self._flash_version(f"v{core.APP_VERSION} เป็นเวอร์ชันล่าสุดแล้ว ✓", GREEN)
            return
        self.release = release
        self.update_text.configure(
            text=f"มีเวอร์ชันใหม่ v{release.version} (ตอนนี้ v{core.APP_VERSION})")
        self.update_btn.configure(text="อัปเดตเลย", command=self.on_update,
                                  state="disabled" if self.ui_state == "busy" else "normal")
        self.update_later.pack(side="right", padx=(6, 0))
        if not self.update_bar.winfo_ismapped():
            self.update_bar.pack(fill="x", pady=(0, 12), before=self.head)

    def _flash_version(self, text, color):
        self.version_label.configure(text=text, text_color=color)
        self.after(4000, lambda: self.version_label.configure(
            text=f"v{core.APP_VERSION} · EUPL-1.2", text_color=MUTED))

    def on_update(self):
        if not self.release or self.ui_state == "busy":
            return
        if not updater.is_frozen():
            webbrowser.open(self.release.page)
            return
        self.update_btn.configure(text="กำลังโหลด...", state="disabled")
        self.update_later.pack_forget()
        self.update_text.configure(text=f"กำลังดาวน์โหลด v{self.release.version}...")
        self.dl_progress = 0.0
        self.update_progress.set(0)
        self.update_progress.pack(fill="x", padx=14, pady=(0, 10))

        def progress(value):
            self.dl_progress = value

        _bg(self, updater.download, self.after_download, self.release,
            core.APP_VERSION, progress)

    def after_download(self, path, exc):
        self.dl_progress = None
        self.update_progress.pack_forget()
        if exc is not None:
            self._log(f"อัปเดตไม่สำเร็จ: {exc}")
            msg = ("ไฟล์ที่โหลดมาไม่ตรงกับต้นฉบับ จึงไม่ได้ติดตั้ง"
                   if "checksum" in str(exc) else "ดาวน์โหลดไม่สำเร็จ ลองใหม่อีกครั้ง")
            self.update_text.configure(text=msg)
            self.update_btn.configure(text="ลองอีกครั้ง", state="normal")
            self.update_later.pack(side="right", padx=(6, 0))
            return
        if updater.can_install_in_place(path):
            self.update_text.configure(text="กำลังติดตั้ง โปรแกรมจะปิดแล้วเปิดใหม่เองในไม่กี่วินาที")
            self.update_btn.configure(state="disabled")
            updater.install(path)
            self.after(400, self.destroy)
        else:
            self.update_text.configure(
                text=f"โหลดไว้ที่ {path}\nโฟลเดอร์โปรแกรมเขียนไม่ได้ ปิดโปรแกรมแล้วใช้ไฟล์นี้แทน")
            self.update_btn.configure(text="เปิดโฟลเดอร์", state="normal",
                                      command=lambda: os.startfile(str(path.parent)))


for _name, _func in vars(UpdateMixin).items():
    if callable(_func) and not _name.startswith("__"):
        setattr(App, _name, _func)


def main():
    if updater.handle_command_line(sys.argv):
        return
    App().mainloop()


if __name__ == "__main__":
    main()
