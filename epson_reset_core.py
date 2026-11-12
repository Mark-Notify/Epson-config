# -*- coding: utf-8 -*-
"""
Epson Ink Pad Reset - ส่วนติดต่อเครื่องพิมพ์ (ไม่มี UI)
เช็กสถานะและรีเซ็ตตัวนับซับหมึกของเครื่องพิมพ์ Epson ผ่านสาย USB

ใช้ไลบรารี epson_print_conf (Ircama, EUPL-1.2) และค่าคอนฟิกรุ่นจาก
epson.toml ของ ReInkPy (แปลงเป็น printers.pickle ตอน build)

โหมดทดสอบโดยไม่มีเครื่องพิมพ์:  set EPSON_RESET_MOCK=1
"""

import copy
import datetime
import logging
import os
import pickle
import re
import sys
from pathlib import Path

APP_TITLE = "Epson Ink Pad Reset"
APP_VERSION = "2.1.0"


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
