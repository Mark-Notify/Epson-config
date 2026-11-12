# -*- coding: utf-8 -*-
"""
Epson Ink Pad Reset - หน้าต่างกดใช้งานง่ายสำหรับเช็กสถานะและรีเซ็ตตัวนับซับหมึก
ของเครื่องพิมพ์ Epson ผ่านสาย USB

ใช้ไลบรารี epson_print_conf (Ircama, EUPL-1.2) และค่าคอนฟิกรุ่นจาก
epson.toml ของ ReInkPy (แปลงเป็น printers.pickle ตอน build)

โหมดทดสอบโดยไม่มีเครื่องพิมพ์:  set EPSON_RESET_MOCK=1
"""

import copy
import datetime
import logging
import os
import pickle
import queue
import re
import sys
import threading
import traceback
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

APP_TITLE = "Epson Ink Pad Reset"
APP_VERSION = "1.0.0"


# ---------------------------------------------------------------- paths
def app_dir() -> Path:
    """Folder holding bundled files (PyInstaller) or this script."""
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parent


def backup_dir() -> Path:
    base = Path(os.environ.get("USERPROFILE") or Path.home()) / "Documents"
    folder = base / "EpsonResetBackups"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


if not getattr(sys, "frozen", False):
    vendor = app_dir() / "vendor" / "epson_print_conf"
    if vendor.is_dir():
        sys.path.insert(0, str(vendor))

import epson_print_conf as epc  # noqa: E402

epc.enable_usb_transport()


# ---------------------------------------------------------------- logging
class ListHandler(logging.Handler):
    """Keep library warnings/errors so the GUI can show them."""

    def __init__(self):
        super().__init__(level=logging.WARNING)
        self.lines = []

    def emit(self, record):
        try:
            self.lines.append(self.format(record))
        except Exception:
            pass


LOG = ListHandler()
LOG.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
logging.getLogger().addHandler(LOG)
logging.getLogger().setLevel(logging.WARNING)


# ---------------------------------------------------------------- printer access
def load_config() -> dict:
    path = app_dir() / "printers.pickle"
    if not path.is_file():
        return {}
    with open(path, "rb") as fp:
        return pickle.load(fp)


CONF = load_config()
MOCK = os.environ.get("EPSON_RESET_MOCK") == "1"
_mock_cfg = None


def mock_config():
    """Fake L4260 with a full waste counter (EPSON_RESET_MOCK=1)."""
    global _mock_cfg
    if _mock_cfg is None:
        from epson_usb.backends.mock import MockConfig

        _mock_cfg = MockConfig(
            device_id=(
                b"MFG:EPSON;CMD:ESCPL2,BDC,D4;MDL:L4260 Series;"
                b"CLS:PRINTER;DES:EPSON L4260 Series;"
            ),
            eeprom={i: 0 for i in range(256)} | {54: 104, 55: 94, 255: 104,
                                                  28: 7, 47: 0x80, 48: 0x3B},
        )
    return _mock_cfg


def make_printer(model=None):
    kwargs = {}
    if MOCK:
        kwargs["backend"] = "mock"
        kwargs["usb_options"] = {"config": mock_config()}
    elif os.environ.get("EPSON_RESET_BACKEND"):
        kwargs["backend"] = os.environ["EPSON_RESET_BACKEND"]
    return epc.EpsonPrinter(conf_dict=copy.deepcopy(CONF), model=model, **kwargs)


def close_printer(printer):
    try:
        printer.close()
    except Exception:
        pass


def normalize_model(raw: str) -> str:
    name = (raw or "").strip()
    name = re.sub(r"^(EPSON|Epson)\s+", "", name)
    name = re.sub(r"\s+Series$", "", name, flags=re.IGNORECASE)
    return name.strip()


def first(value):
    if isinstance(value, (list, tuple)):
        return value[0] if value else ""
    return value or ""


def detect_model():
    """Return (model_name, supported, device_id_dict)."""
    printer = make_printer()
    try:
        ident = printer.get_device_identification()
    finally:
        close_printer(printer)
    if not ident:
        raise ConnectionError("no-identification")
    raw = first(ident.get("Model")) or first(ident.get("MDL")) \
        or first(ident.get("Description"))
    model = normalize_model(raw)
    supported = model in make_printer().valid_printers
    return model, supported, ident


INK_TH = {"Black": "ดำ", "Cyan": "ฟ้า", "Magenta": "ชมพู", "Yellow": "เหลือง",
          "Photo Black": "ดำ (ภาพถ่าย)", "Gray": "เทา", "Light Cyan": "ฟ้าอ่อน",
          "Light Magenta": "ชมพูอ่อน"}


def is_waste_full(status: dict) -> bool:
    err = str(status.get("errcode", ""))
    if "waste" in err.lower() or "overflow" in err.lower():
        return True
    for key in ("maintenance_box_1", "maintenance_box_2"):
        val = str(status.get(key, "")).lower()
        if val.startswith("full") or val.startswith("near"):
            return True
    return False


def check_printer():
    """Read-only: identify the printer and read its status."""
    model, supported, ident = detect_model()
    result = {"model": model, "supported": supported, "ident": ident}
    printer = make_printer(model if supported else None)
    try:
        result["status"] = printer.get_printer_status() or {}
        if supported:
            try:
                result["stats"] = printer.get_stats() or {}
            except Exception:
                result["stats"] = {}
    finally:
        close_printer(printer)
    return result


def backup_eeprom(printer, model: str, serial: str) -> Path:
    data = printer.dump_eeprom(0, 255)
    values = [v for v in data.values() if v is not None]
    if len(values) < len(data) // 2:
        raise IOError("backup-failed")
    for addr in printer.parm.get("raw_waste_reset", {}):
        if addr <= 255 and data.get(addr) is None:
            raise IOError("backup-failed")
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    safe_serial = re.sub(r"[^A-Za-z0-9]", "", serial or "") or "unknown"
    path = backup_dir() / f"{model}_{safe_serial}_{stamp}.txt"
    with open(path, "w", encoding="utf-8") as fp:
        fp.write(f"# {APP_TITLE} {APP_VERSION} EEPROM backup\n")
        fp.write(f"# model={model} serial={serial} time={stamp}\n")
        for addr, val in data.items():
            disp = "  --" if val is None else f"{val:#04x}"
            fp.write(f"EEPROM_ADDR 0x{addr:02X} = {addr:3d}: {disp}\n")
    return path


def reset_printer(model: str, serial: str):
    """Back up the EEPROM, then reset the waste ink counters."""
    printer = make_printer(model)
    try:
        if not printer.parm:
            raise ValueError("unsupported")
        path = backup_eeprom(printer, model, serial)
        report = []
        ok = printer.reset_waste_ink_levels(report=report)
        return bool(ok), path
    finally:
        close_printer(printer)


# ---------------------------------------------------------------- GUI
FONT = "Leelawadee UI"
GREEN, RED, AMBER, GREY = "#1e8e3e", "#c5221f", "#b06000", "#5f6368"


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"{APP_TITLE}{' (โหมดทดสอบ)' if MOCK else ''}")
        self.geometry("560x560")
        self.minsize(480, 480)
        self.configure(bg="white")
        self.jobs = queue.Queue()
        self.model = None
        self.serial = ""
        self.supported = False
        self._build()
        self.after(100, self._poll)
        if not CONF:
            self._set_headline("ไม่พบไฟล์ข้อมูลรุ่นเครื่องพิมพ์ (printers.pickle)", RED)

    # -- layout
    def _build(self):
        style = ttk.Style(self)
        style.configure("Big.TButton", font=(FONT, 13), padding=10)

        tk.Label(self, text="รีเซ็ตซับหมึกเครื่องพิมพ์ Epson", font=(FONT, 18, "bold"),
                 bg="white").pack(pady=(18, 2))
        tk.Label(self, text="เสียบสาย USB และเปิดเครื่องพิมพ์ก่อนกดปุ่ม",
                 font=(FONT, 11), fg=GREY, bg="white").pack()

        self.headline = tk.Label(self, text="กด \"ตรวจสอบเครื่องพิมพ์\" เพื่อเริ่ม",
                                 font=(FONT, 14, "bold"), fg=GREY, bg="white",
                                 wraplength=500, justify="center")
        self.headline.pack(pady=(18, 6))

        self.details = tk.Label(self, text="", font=(FONT, 11), bg="white",
                                justify="left", anchor="w", wraplength=500)
        self.details.pack(fill="x", padx=30)

        buttons = tk.Frame(self, bg="white")
        buttons.pack(pady=16)
        self.btn_check = ttk.Button(buttons, text="ตรวจสอบเครื่องพิมพ์",
                                    style="Big.TButton", command=self.on_check)
        self.btn_check.grid(row=0, column=0, padx=8)
        self.btn_reset = ttk.Button(buttons, text="รีเซ็ตซับหมึก",
                                    style="Big.TButton", command=self.on_reset,
                                    state="disabled")
        self.btn_reset.grid(row=0, column=1, padx=8)

        self.progress = ttk.Progressbar(self, mode="indeterminate", length=300)

        self.log = tk.Text(self, height=6, font=("Consolas", 9), fg=GREY,
                           relief="flat", bg="#f6f6f6", wrap="word")
        self.log.pack(fill="both", expand=True, padx=16, pady=(8, 4))
        self.log.configure(state="disabled")

        tk.Label(self, text=f"v{APP_VERSION} · ใช้ epson_print_conf (EUPL-1.2) · "
                            f"ไฟล์สำรอง: Documents\\EpsonResetBackups",
                 font=(FONT, 8), fg=GREY, bg="white").pack(pady=(0, 6))

    def _set_headline(self, text, color):
        self.headline.configure(text=text, fg=color)

    def _write_log(self, text):
        self.log.configure(state="normal")
        self.log.insert("end", text.rstrip() + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def _busy(self, busy: bool, text=""):
        state = "disabled" if busy else "normal"
        self.btn_check.configure(state=state)
        self.btn_reset.configure(
            state="normal" if (not busy and self.supported) else "disabled")
        if busy:
            self._set_headline(text, GREY)
            self.progress.pack(before=self.log, pady=4)
            self.progress.start(12)
        else:
            self.progress.stop()
            self.progress.pack_forget()

    # -- background jobs
    def _run(self, func, done, *args):
        LOG.lines.clear()

        def worker():
            try:
                result = func(*args)
                self.jobs.put((done, result, None))
            except Exception as exc:
                self.jobs.put((done, None, exc))

        threading.Thread(target=worker, daemon=True).start()

    def _poll(self):
        try:
            while True:
                done, result, exc = self.jobs.get_nowait()
                self._busy(False)
                for line in LOG.lines:
                    self._write_log(line)
                if exc is not None:
                    self._write_log("".join(traceback.format_exception_only(exc)))
                done(result, exc)
        except queue.Empty:
            pass
        self.after(100, self._poll)

    # -- check
    def on_check(self):
        self._busy(True, "กำลังอ่านข้อมูลจากเครื่องพิมพ์...")
        self._run(check_printer, self.after_check)

    def after_check(self, result, exc):
        if exc is not None:
            self.supported = False
            self.btn_reset.configure(state="disabled")
            self.details.configure(text="")
            self._set_headline(
                "ติดต่อเครื่องพิมพ์ไม่ได้\nเช็กว่าเสียบสาย USB เปิดเครื่อง "
                "และปิดโปรแกรมอื่นที่ใช้เครื่องพิมพ์อยู่ แล้วลองใหม่", RED)
            return

        self.model = result["model"]
        self.supported = result["supported"]
        status = result.get("status", {})
        self.serial = str(status.get("serial_number_info", "") or "")

        lines = [f"รุ่น: {self.model or 'ไม่ทราบ'}"]
        state = status.get("status")
        if isinstance(state, (list, tuple)) and len(state) > 1:
            lines.append(f"สถานะ: {state[1]}")
        if status.get("errcode"):
            lines.append(f"ข้อผิดพลาด: {status['errcode']}")
        for key, label in (("maintenance_box_1", "ซับหมึก 1"),
                           ("maintenance_box_2", "ซับหมึก 2")):
            if key in status:
                val = str(status[key])
                th = "เต็ม" if val.startswith("full") else \
                    "ใกล้เต็ม" if val.startswith("near") else \
                    "ยังไม่เต็ม" if val.startswith("not full") else val
                lines.append(f"{label}: {th}")
        inks = status.get("ink_level") or []
        if inks:
            parts = []
            for ink in inks:
                try:
                    parts.append(f"{INK_TH.get(ink[2], ink[2])} {ink[4]}%")
                except Exception:
                    pass
            if parts:
                lines.append("หมึก: " + ", ".join(parts))
        self.details.configure(text="\n".join(lines))
        self._write_log(f"รุ่น {self.model} | {status}")

        full = is_waste_full(status)
        if not self.supported:
            self._set_headline(
                f"ยังไม่รองรับรุ่น {self.model or 'นี้'}\nโปรแกรมนี้รีเซ็ตรุ่นนี้ไม่ได้", AMBER)
            self.btn_reset.configure(state="disabled")
        elif full:
            self._set_headline("ซับหมึกเต็ม · กด \"รีเซ็ตซับหมึก\" ได้เลย", RED)
            self.btn_reset.configure(state="normal")
        else:
            self._set_headline("เครื่องพิมพ์ปกติ ซับหมึกยังไม่เต็ม", GREEN)
            self.btn_reset.configure(state="normal")

    # -- reset
    def on_reset(self):
        if not self.supported:
            return
        ok = messagebox.askyesno(
            "ยืนยันการรีเซ็ต",
            f"จะรีเซ็ตตัวนับซับหมึกของ {self.model}\n\n"
            "• โปรแกรมจะสำรองข้อมูลเครื่องพิมพ์ไว้ก่อนอัตโนมัติ\n"
            "• ห้ามปิดเครื่องพิมพ์หรือถอดสายระหว่างรีเซ็ต\n"
            "• แผ่นซับหมึกจริงยังเต็มอยู่ ควรล้าง/เปลี่ยน หรือต่อถังหมึกทิ้ง\n"
            "• ทำแล้วอาจเสียสิทธิ์ประกันจาก Epson\n\n"
            "ต้องการรีเซ็ตเลยไหม?",
            icon="warning")
        if not ok:
            return
        self._busy(True, "กำลังสำรองข้อมูลและรีเซ็ต... ห้ามปิดเครื่องพิมพ์")
        self._run(reset_printer, self.after_reset, self.model, self.serial)

    def after_reset(self, result, exc):
        if exc is not None:
            if isinstance(exc, IOError) and "backup-failed" in str(exc):
                msg = "สำรองข้อมูลไม่สำเร็จ จึงยังไม่ได้รีเซ็ต\nลองกดตรวจสอบแล้วรีเซ็ตใหม่"
            else:
                msg = "รีเซ็ตไม่สำเร็จ ลองปิด-เปิดเครื่องพิมพ์แล้วทำใหม่"
            self._set_headline(msg, RED)
            return
        ok, path = result
        self._write_log(f"สำรองไว้ที่: {path}")
        if ok:
            self._set_headline(
                "รีเซ็ตสำเร็จ\nปิดเครื่องพิมพ์ แล้วเปิดใหม่ จากนั้นกด \"ตรวจสอบเครื่องพิมพ์\"",
                GREEN)
            messagebox.showinfo(
                "รีเซ็ตสำเร็จ",
                "รีเซ็ตตัวนับซับหมึกเรียบร้อย\n\n"
                "1. กดปุ่ม Power ปิดเครื่องพิมพ์ รอไฟดับ\n"
                "2. เปิดเครื่องใหม่\n"
                "3. กด \"ตรวจสอบเครื่องพิมพ์\" อีกครั้ง\n\n"
                f"ไฟล์สำรอง: {path}")
        else:
            self._set_headline(
                "เครื่องพิมพ์ไม่รับคำสั่งรีเซ็ต\nรุ่นหรือเฟิร์มแวร์นี้อาจไม่รองรับ", RED)


def main():
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
