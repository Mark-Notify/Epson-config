# -*- coding: utf-8 -*-
"""
Epson Ink Pad Reset - ส่วนติดต่อเครื่องพิมพ์ (ไม่มี UI)

ทำได้:
- เช็กสถานะ ระดับหมึก ตัวนับซับหมึก และสถิติเครื่อง (อ่านอย่างเดียว)
- รีเซ็ตตัวนับซับหมึก (สำรอง EEPROM ก่อนทุกครั้ง) และรีเซ็ตชั่วคราว
- กู้คืน EEPROM จากไฟล์สำรอง
- ตั้งเวลาปิดเครื่องอัตโนมัติ
- เชื่อมต่อผ่าน USB หรือ Wi-Fi/LAN (SNMP) และค้นหาเครื่องในวงแลน
- พิมพ์หน้าเช็กหัวพิมพ์และสั่งล้างหัวพิมพ์
- บันทึกประวัติการทำงานไว้ที่ Documents\\EpsonResetBackups\\history.json

ใช้ไลบรารี epson_print_conf (Ircama, EUPL-1.2) และค่าคอนฟิกรุ่นจาก
epson.toml ของ ReInkPy (แปลงเป็น printers.pickle ตอน build)

โหมดทดสอบโดยไม่มีเครื่องพิมพ์:  set EPSON_RESET_MOCK=1
"""

import concurrent.futures
import copy
import datetime
import ipaddress
import json
import logging
import os
import pickle
import re
import socket
import sys
import threading
import time
from pathlib import Path

APP_TITLE = "Epson Ink Pad Reset"
APP_VERSION = "3.0.1"


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
NetworkPrinter = getattr(epc, "NetworkEpsonPrinter", epc.EpsonPrinter)


# ---------------------------------------------------------------- logging
class ListHandler(logging.Handler):
    """Keep library warnings/errors so the GUI can show them."""

    def __init__(self):
        super().__init__(level=logging.WARNING)
        self.lines = []

    def emit(self, record):
        try:
            self.lines.append(self.format(record))
            del self.lines[:-200]
        except Exception:
            pass


LOG = ListHandler()
LOG.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
logging.getLogger().addHandler(LOG)
logging.getLogger().setLevel(logging.WARNING)

#: One printer conversation at a time: USB allows a single open handle and
#: overlapping SNMP writes to the same EEPROM must never interleave.
PRINTER_LOCK = threading.RLock()


# ---------------------------------------------------------------- config
def load_config() -> dict:
    path = app_dir() / "printers.pickle"
    if not path.is_file():
        return {}
    with open(path, "rb") as fp:
        return pickle.load(fp)


CONF = load_config()
MOCK = os.environ.get("EPSON_RESET_MOCK") == "1"
_mock_cfg = None

if MOCK and "L4260" not in CONF:
    # Developer machines without printers.pickle: borrow the built-in L4160
    # entry so the fake L4260 still has stats, timer and reset data.
    CONF = dict(CONF)
    _base = copy.deepcopy(epc.EpsonPrinter.PRINTER_CONFIG.get("L4160", {}))
    _base.pop("alias", None)
    _base.setdefault("stats", {})["Power off timer"] = [359, 358]
    CONF["L4260"] = _base


def mock_config():
    """Fake L4260 with a full waste counter (EPSON_RESET_MOCK=1)."""
    global _mock_cfg
    if _mock_cfg is None:
        from epson_usb.backends.mock import MockConfig

        eeprom = {i: 0 for i in range(256)}
        eeprom.update({54: 104, 55: 94, 255: 104, 28: 7, 47: 0x00, 48: 0xA1,
                       49: 0x2A, 50: 0xD3, 51: 0x03, 9: 0x31, 8: 0x4E,
                       133: 0x00, 132: 0x00, 131: 0x2F, 130: 0x1A})
        for addr, val in {776: 0, 775: 0, 774: 0x12, 773: 0x9C,
                          1843: 0, 1842: 0, 1841: 0, 1840: 0xD7,
                          554: 6, 555: 4, 556: 3, 557: 4,
                          359: 0, 358: 30}.items():
            eeprom[addr] = val
        _mock_cfg = MockConfig(
            device_id=(
                b"MFG:EPSON;CMD:ESCPL2,BDC,D4;MDL:L4260 Series;"
                b"CLS:PRINTER;DES:EPSON L4260 Series;"
            ),
            eeprom=eeprom,
        )
    return _mock_cfg


# ---------------------------------------------------------------- connection
class Target:
    """Where the printer is: USB cable (host=None) or an IP address."""

    def __init__(self, host=None):
        host = (host or "").strip()
        self.host = host or None

    @property
    def is_network(self):
        return self.host is not None

    def label(self):
        return f"Wi-Fi {self.host}" if self.host else "USB"


def make_printer(model=None, target=None):
    target = target or Target()
    conf = copy.deepcopy(CONF)
    if target.is_network and not MOCK:
        return NetworkPrinter(conf_dict=conf, model=model, hostname=target.host,
                              timeout=3, retries=1)
    kwargs = {}
    if MOCK:
        kwargs["backend"] = "mock"
        kwargs["usb_options"] = {"config": mock_config()}
    elif os.environ.get("EPSON_RESET_BACKEND"):
        kwargs["backend"] = os.environ["EPSON_RESET_BACKEND"]
    return epc.EpsonPrinter(conf_dict=conf, model=model, **kwargs)


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


def validate_host(host: str) -> str:
    host = (host or "").strip()
    if not host:
        raise ValueError("empty-host")
    try:
        ipaddress.ip_address(host)
        return host
    except ValueError:
        pass
    if not re.fullmatch(r"[A-Za-z0-9.-]{1,253}", host):
        raise ValueError("bad-host")
    return host


def detect_model(target=None):
    """Return (model_name, supported, device_id_dict)."""
    target = target or Target()
    printer = make_printer(target=target)
    try:
        if target.is_network and not MOCK:
            info = printer.get_snmp_info("Model") or {}
            raw = info.get("Model", "")
            if not raw:
                raise ConnectionError("no-identification")
            ident = {"Model": [raw]}
        else:
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


# ---------------------------------------------------------------- status
INK_TH = {"Black": "ดำ", "Cyan": "ฟ้า", "Magenta": "ชมพู", "Yellow": "เหลือง",
          "Photo Black": "ดำ (ภาพถ่าย)", "Matte Black": "ดำด้าน", "Gray": "เทา",
          "Light Cyan": "ฟ้าอ่อน", "Light Magenta": "ชมพูอ่อน", "Red": "แดง",
          "Orange": "ส้ม", "Light Gray": "เทาอ่อน", "Gloss Optimizer": "เคลือบเงา"}

STATUS_TH = {"Idle (ready to print)": "พร้อมพิมพ์", "Error": "มีข้อผิดพลาด",
             "Printing": "กำลังพิมพ์", "Busy": "ไม่ว่าง",
             "Self Printing": "กำลังพิมพ์ทดสอบ", "Cleaning": "กำลังล้างหัวพิมพ์",
             "Waiting": "รอ", "Power OFF": "ปิดเครื่อง"}

#: (english key prefix, thai label, unit, group)
STAT_LABELS = [
    ("Total print page counter", "หน้าที่พิมพ์ทั้งหมด", "หน้า", "usage"),
    ("Total print pass counter", "รอบหัวพิมพ์วิ่ง", "รอบ", "usage"),
    ("Total scan counter", "จำนวนครั้งที่สแกน", "ครั้ง", "usage"),
    ("Total print CD-R counter", "พิมพ์แผ่น CD", "แผ่น", "usage"),
    ("Manual cleaning counter", "ล้างหัวพิมพ์ (สั่งเอง)", "ครั้ง", "clean"),
    ("Timer cleaning counter", "ล้างหัวพิมพ์อัตโนมัติ", "ครั้ง", "clean"),
    ("Power cleaning counter", "ล้างหัวพิมพ์แบบเข้ม", "ครั้ง", "clean"),
    ("Ink replacement cleaning counter", "ล้างหลังเปลี่ยนหมึก", "ครั้ง", "clean"),
    ("Ink replacement counter", "เติม/เปลี่ยนหมึก", "ครั้ง", "ink"),
    ("First TI received time", "เริ่มใช้งานครั้งแรก", "", "info"),
    ("Power off timer", "ปิดเครื่องอัตโนมัติ", "นาที", "info"),
]


def describe_stats(stats: dict):
    """Turn library stats into Thai rows the UI can show directly."""
    rows = []
    for key, value in (stats or {}).items():
        for prefix, label, unit, group in STAT_LABELS:
            if key.startswith(prefix):
                break
        else:
            continue
        if key.startswith("Ink replacement counter - "):
            color = key.split(" - ", 1)[1]
            label = f"{label} {INK_TH.get(color, color)}"
            rows.append({"key": key, "label": label, "value": value,
                         "unit": unit, "group": group, "color": color})
            continue
        rows.append({"key": key, "label": label, "value": value, "unit": unit,
                     "group": group})
    order = {p[0]: i for i, p in enumerate(STAT_LABELS)}
    rows.sort(key=lambda r: (next((v for k, v in order.items()
                                   if r["key"].startswith(k)), 99), r["key"]))
    return rows


def is_waste_full(status: dict) -> bool:
    err = str(status.get("errcode", ""))
    if "waste" in err.lower() or "overflow" in err.lower():
        return True
    for key in ("maintenance_box_1", "maintenance_box_2"):
        val = str(status.get(key, "")).lower()
        if val.startswith("full") or val.startswith("near"):
            return True
    return False


def pad_state(value) -> str:
    val = str(value or "").lower()
    if val.startswith("full"):
        return "full"
    if val.startswith("near"):
        return "near"
    if val.startswith("not full"):
        return "ok"
    return "unknown"


def ink_levels(status: dict):
    inks = []
    for ink in status.get("ink_level") or []:
        try:
            name, level = ink[2], int(ink[4])
        except Exception:
            continue
        inks.append({"name": name, "th": INK_TH.get(name, name), "level": level})
    return inks


def low_inks(inks, threshold: int):
    return [i for i in inks if i["level"] <= threshold]


def _mock_status_extras(status):
    if MOCK and "ink_level" not in status:
        status["ink_level"] = [(1, 0, "Black", "", 64), (3, 0, "Cyan", "", 41),
                               (4, 0, "Magenta", "", 12), (5, 0, "Yellow", "", 77)]
        status["maintenance_box_1"] = "full (1)"
    return status


def check_printer(host=None):
    """Read-only: identify the printer and read everything we can."""
    target = Target(host)
    with PRINTER_LOCK:
        model, supported, ident = detect_model(target)
        result = {"model": model, "supported": supported, "ident": ident,
                  "connection": target.label(), "host": target.host}
        printer = make_printer(model if supported else None, target)
        try:
            result["status"] = _mock_status_extras(printer.get_printer_status() or {})
            if supported:
                for key, func in (("stats", printer.get_stats),
                                  ("waste", printer.get_waste_ink_levels)):
                    try:
                        result[key] = func() or {}
                    except Exception as exc:
                        logging.warning("%s: %s", key, exc)
                        result[key] = {}
        finally:
            close_printer(printer)
    result["serial"] = str(result["status"].get("serial_number_info", "") or "")
    return result


# ---------------------------------------------------------------- backups
BACKUP_LINE = re.compile(
    r"EEPROM_ADDR 0x([0-9A-Fa-f]+)\s*=\s*\d+:\s*(--|0x[0-9A-Fa-f]{1,2})")
BACKUP_META = re.compile(r"#\s*model=(\S*)\s+serial=(\S*)\s+time=(\S*)")


def safe_serial(serial):
    return re.sub(r"[^A-Za-z0-9]", "", serial or "") or "unknown"


def backup_eeprom(printer, model: str, serial: str, reason="reset") -> Path:
    data = printer.dump_eeprom(0, 255)
    values = [v for v in data.values() if v is not None]
    if len(values) < len(data) // 2:
        raise IOError("backup-failed")
    for addr in (printer.parm or {}).get("raw_waste_reset", {}):
        if addr <= 255 and data.get(addr) is None:
            raise IOError("backup-failed")
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    path = backup_dir() / f"{model}_{safe_serial(serial)}_{stamp}.txt"
    n = 1
    while path.exists():
        n += 1
        path = backup_dir() / f"{model}_{safe_serial(serial)}_{stamp}-{n}.txt"
    with open(path, "w", encoding="utf-8") as fp:
        fp.write(f"# {APP_TITLE} {APP_VERSION} EEPROM backup ({reason})\n")
        fp.write(f"# model={model} serial={serial or 'unknown'} time={stamp}\n")
        for addr, val in data.items():
            disp = "  --" if val is None else f"{val:#04x}"
            fp.write(f"EEPROM_ADDR 0x{addr:02X} = {addr:3d}: {disp}\n")
    return path


def parse_backup(path) -> dict:
    """Read one of our backup files: {"model", "serial", "time", "cells"}."""
    path = Path(path)
    info = {"path": str(path), "name": path.name, "model": "", "serial": "",
            "time": "", "cells": {}}
    with open(path, encoding="utf-8", errors="replace") as fp:
        for line in fp:
            meta = BACKUP_META.search(line)
            if meta:
                info["model"], info["serial"], info["time"] = meta.groups()
                continue
            cell = BACKUP_LINE.search(line)
            if cell and cell.group(2) != "--":
                info["cells"][int(cell.group(1), 16)] = int(cell.group(2), 16)
    if not info["model"]:
        parts = path.stem.split("_")
        if len(parts) >= 3:
            info["model"], info["serial"], info["time"] = parts[0], parts[1], parts[2]
    return info


def list_backups():
    items = []
    for path in sorted(backup_dir().glob("*.txt"), key=lambda p: p.stat().st_mtime,
                       reverse=True):
        try:
            info = parse_backup(path)
        except Exception:
            continue
        if not info["cells"]:
            continue
        items.append({k: info[k] for k in ("path", "name", "model", "serial", "time")}
                     | {"cells": len(info["cells"]),
                        "when": _pretty_stamp(info["time"]),
                        "size": path.stat().st_size})
    return items


def _pretty_stamp(stamp):
    try:
        dt = datetime.datetime.strptime(stamp[:15], "%Y%m%d-%H%M%S")
        return dt.isoformat(timespec="seconds")
    except Exception:
        return stamp


def restore_plan(path, model, serial, host=None):
    """Compare a backup with the printer now. Read-only."""
    info = parse_backup(path)
    if not info["cells"]:
        raise ValueError("empty-backup")
    if info["model"] and model and info["model"] != model:
        raise ValueError(f"model-mismatch:{info['model']}")
    if safe_serial(info["serial"]) not in ("unknown", safe_serial(serial)) \
            and safe_serial(serial) != "unknown":
        raise ValueError(f"serial-mismatch:{info['serial']}")
    with PRINTER_LOCK:
        printer = make_printer(model, Target(host))
        try:
            if not printer.parm:
                raise ValueError("unsupported")
            now = printer.dump_eeprom(0, 255)
        finally:
            close_printer(printer)
    diff = [{"addr": a, "now": now.get(a), "backup": v}
            for a, v in sorted(info["cells"].items())
            if now.get(a) is not None and now.get(a) != v]
    return {"backup": info["name"], "time": _pretty_stamp(info["time"]),
            "diff": diff, "unreadable": sum(1 for v in now.values() if v is None)}


def restore_backup(path, model, serial, host=None):
    """Write back every cell that differs from the backup.

    A fresh backup of the current state is taken first, so a restore can
    itself be undone."""
    plan = restore_plan(path, model, serial, host)
    with PRINTER_LOCK:
        printer = make_printer(model, Target(host))
        try:
            undo = backup_eeprom(printer, model, serial, reason="before-restore")
            written, failed = 0, []
            for cell in plan["diff"]:
                ok = printer.write_eeprom(cell["addr"], cell["backup"],
                                          label="restore_backup")
                if ok:
                    written += 1
                else:
                    failed.append(cell["addr"])
        finally:
            close_printer(printer)
    ok = not failed
    add_history("restore", model, serial, ok, backup=str(undo),
                detail={"source": plan["backup"], "written": written,
                        "failed": failed}, host=host)
    return {"ok": ok, "written": written, "failed": failed, "undo": str(undo)}


# ---------------------------------------------------------------- history
def history_path() -> Path:
    return backup_dir() / "history.json"


_history_lock = threading.Lock()


def load_history():
    try:
        with open(history_path(), encoding="utf-8") as fp:
            data = json.load(fp)
        return data if isinstance(data, list) else []
    except Exception:
        return []


def add_history(kind, model, serial, ok, backup=None, detail=None, host=None):
    entry = {"time": datetime.datetime.now().isoformat(timespec="seconds"),
             "kind": kind, "model": model or "", "serial": serial or "",
             "ok": bool(ok), "connection": Target(host).label()}
    if backup:
        entry["backup"] = str(backup)
    if detail:
        entry["detail"] = detail
    with _history_lock:
        items = load_history()
        items.append(entry)
        tmp = history_path().with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as fp:
            json.dump(items[-1000:], fp, ensure_ascii=False, indent=1)
        os.replace(tmp, history_path())
    return entry


def pad_advice(serial, model=""):
    """How many successful resets this printer has had, and what to do."""
    key = safe_serial(serial)
    resets = [h for h in load_history()
              if h.get("kind") in ("reset", "temp_reset") and h.get("ok")
              and (safe_serial(h.get("serial")) == key if key != "unknown"
                   else h.get("model") == model)]
    count = len(resets)
    last = resets[-1]["time"] if resets else None
    if count == 0:
        level, text = "ok", "ยังไม่เคยรีเซ็ตเครื่องนี้ด้วยโปรแกรมนี้"
    elif count == 1:
        level, text = "info", ("รีเซ็ตไปแล้ว 1 ครั้ง แผ่นซับจริงอิ่มหมึกแล้ว "
                               "ควรล้างหรือเปลี่ยนแผ่นซับในโอกาสแรก")
    else:
        level, text = "warn", (f"รีเซ็ตไปแล้ว {count} ครั้ง แผ่นซับน่าจะเต็มจริง "
                               "ควรเปลี่ยนแผ่นซับหรือต่อถังหมึกทิ้งภายนอกก่อนหมึกล้น")
    return {"count": count, "last": last, "level": level, "text": text}


# ---------------------------------------------------------------- settings
def settings_path() -> Path:
    return backup_dir() / "settings.json"


DEFAULT_SETTINGS = {"ink_threshold": 20, "connection": "usb", "host": "",
                    "recent_hosts": []}


def load_settings():
    data = dict(DEFAULT_SETTINGS)
    try:
        with open(settings_path(), encoding="utf-8") as fp:
            stored = json.load(fp)
        if isinstance(stored, dict):
            data.update({k: v for k, v in stored.items() if k in DEFAULT_SETTINGS})
    except Exception:
        pass
    try:
        data["ink_threshold"] = max(1, min(90, int(data["ink_threshold"])))
    except Exception:
        data["ink_threshold"] = DEFAULT_SETTINGS["ink_threshold"]
    return data


def save_settings(changes: dict):
    data = load_settings()
    data.update({k: v for k, v in (changes or {}).items() if k in DEFAULT_SETTINGS})
    host = data.get("host") or ""
    if host:
        recent = [h for h in data.get("recent_hosts", []) if h != host]
        data["recent_hosts"] = ([host] + recent)[:6]
    with open(settings_path(), "w", encoding="utf-8") as fp:
        json.dump(data, fp, ensure_ascii=False, indent=1)
    return load_settings()


# ---------------------------------------------------------------- reset
def reset_printer(model: str, serial: str, host=None):
    """Back up the EEPROM, then reset the waste ink counters."""
    with PRINTER_LOCK:
        printer = make_printer(model, Target(host))
        try:
            if not printer.parm:
                raise ValueError("unsupported")
            try:
                before = printer.get_waste_ink_levels() or {}
            except Exception:
                before = {}
            path = backup_eeprom(printer, model, serial)
            report = []
            ok = bool(printer.reset_waste_ink_levels(report=report))
        finally:
            close_printer(printer)
    add_history("reset", model, serial, ok, backup=path,
                detail={"waste_before": before}, host=host)
    return ok, path


def temporary_reset(model: str, serial: str, host=None):
    """'rw' service command: lets a locked printer print again for a while.

    Writes nothing to the EEPROM (no backup needed); the counter keeps
    counting and the printer will stop again later."""
    with PRINTER_LOCK:
        printer = make_printer(model if model in make_printer().valid_printers
                               else None, Target(host))
        try:
            ok = MOCK or bool(printer.temporary_reset_waste())
        finally:
            close_printer(printer)
    add_history("temp_reset", model, serial, ok, host=host)
    return ok


# ---------------------------------------------------------------- power off timer
POWER_OFF_CHOICES = [30, 60, 120, 240, 480, 720]


def read_power_off_timer(model, host=None):
    with PRINTER_LOCK:
        printer = make_printer(model, Target(host))
        try:
            if not printer.parm or "Power off timer" not in printer.parm.get("stats", {}):
                return {"supported": False, "minutes": None,
                        "choices": POWER_OFF_CHOICES}
            stats = printer.get_stats("Power off timer") or {}
        finally:
            close_printer(printer)
    return {"supported": True, "minutes": stats.get("Power off timer"),
            "choices": POWER_OFF_CHOICES}


def write_power_off_timer(model, serial, minutes, host=None):
    minutes = int(minutes)
    if minutes not in POWER_OFF_CHOICES:
        raise ValueError("bad-minutes")
    with PRINTER_LOCK:
        printer = make_printer(model, Target(host))
        try:
            if not printer.parm or "Power off timer" not in printer.parm.get("stats", {}):
                raise ValueError("unsupported")
            path = backup_eeprom(printer, model, serial, reason="power-off-timer")
            ok = bool(printer.write_poweroff_timer(minutes))
        finally:
            close_printer(printer)
    add_history("power_timer", model, serial, ok, backup=path,
                detail={"minutes": minutes}, host=host)
    return ok


# ---------------------------------------------------------------- models
def list_models():
    printer = make_printer()
    conf = printer.PRINTER_CONFIG
    out = []
    for name in sorted(printer.valid_printers, key=_model_sort_key):
        parm = conf[name]
        stats = parm.get("stats", {})
        out.append({
            "name": name,
            "aliases": sorted(a for a in parm.get("alias", []) if a != name),
            "reset": "raw_waste_reset" in parm or "main_waste" in parm,
            "stats": bool(stats),
            "timer": "Power off timer" in stats,
        })
    return out


def _model_sort_key(name):
    m = re.match(r"([A-Za-z-]+)(\d+)?(.*)", name)
    if not m:
        return (name, 0, "")
    return (m.group(1).upper(), int(m.group(2) or 0), m.group(3))


# ---------------------------------------------------------------- network discovery
PRINTER_PORTS = (9100, 515, 631, 80)


def local_ipv4s():
    ips = []
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("192.0.2.1", 1))
            ips.append(sock.getsockname()[0])
    except OSError:
        pass
    try:
        for ip in socket.gethostbyname_ex(socket.gethostname())[2]:
            if ip not in ips:
                ips.append(ip)
    except OSError:
        pass
    return [ip for ip in ips if not ip.startswith(("127.", "169.254."))]


def _port_open(ip, port, timeout=0.6):
    try:
        with socket.create_connection((ip, port), timeout=timeout):
            return True
    except OSError:
        return False


def _snmp_model(ip):
    try:
        printer = NetworkPrinter(hostname=ip, timeout=1.5, retries=0)
        info = printer.get_snmp_info("Model") or {}
        return info.get("Model") or ""
    except Exception:
        return ""


def scan_network(progress=None):
    """Find printers on the local /24 networks.

    A TCP connect to the usual print ports finds candidates; SNMP then asks
    each one for its model so only Epson printers are kept on top."""
    if MOCK:
        time.sleep(1.2)
        return [{"ip": "192.168.1.50", "name": "EPSON L4260 Series",
                 "model": "L4260", "epson": True, "supported": True},
                {"ip": "192.168.1.77", "name": "HP LaserJet", "model": "",
                 "epson": False, "supported": False}]
    nets = []
    for ip in local_ipv4s():
        net = ipaddress.ip_network(ip + "/24", strict=False)
        if net not in nets:
            nets.append(net)
    hosts = [str(h) for net in nets for h in net.hosts()]
    found, done = [], 0
    lock = threading.Lock()

    def probe(ip):
        nonlocal done
        hit = any(_port_open(ip, p) for p in PRINTER_PORTS[:3])
        with lock:
            done += 1
            if progress:
                progress(done / max(len(hosts), 1))
        return ip if hit else None

    with concurrent.futures.ThreadPoolExecutor(max_workers=96) as pool:
        candidates = [ip for ip in pool.map(probe, hosts) if ip]
    valid = make_printer().valid_printers
    with concurrent.futures.ThreadPoolExecutor(max_workers=16) as pool:
        names = list(pool.map(_snmp_model, candidates))
    for ip, name in zip(candidates, names):
        model = normalize_model(name)
        epson = "epson" in name.lower()
        found.append({"ip": ip, "name": name or "ไม่ทราบชื่อ", "model": model,
                      "epson": epson, "supported": model in valid})
    found.sort(key=lambda p: (not p["epson"], tuple(int(x) for x in p["ip"].split("."))))
    return found


# ---------------------------------------------------------------- maintenance
def _escp2():
    from epson_escp2.epson_encode import EpsonEscp2
    return EpsonEscp2()


def nozzle_check_data():
    return _escp2().check_nozzles(type=0)


def head_clean_data(power=False):
    # group 0 = every colour group. The library's own print_clean_nozzles()
    # drops power_clean, so the ESC/P2 sequence is built here directly.
    return _escp2().clean_nozzles(0, power_clean=bool(power))


def windows_printer_queues():
    """Names of the Windows print queues (no pywin32 needed)."""
    if sys.platform != "win32":
        return []
    import ctypes
    from ctypes import wintypes

    winspool = ctypes.WinDLL("winspool.drv")

    class PRINTER_INFO_4(ctypes.Structure):
        _fields_ = [("pPrinterName", wintypes.LPWSTR),
                    ("pServerName", wintypes.LPWSTR),
                    ("Attributes", wintypes.DWORD)]

    flags = 0x2 | 0x4  # PRINTER_ENUM_LOCAL | PRINTER_ENUM_CONNECTIONS
    needed, count = wintypes.DWORD(), wintypes.DWORD()
    winspool.EnumPrintersW(flags, None, 4, None, 0, ctypes.byref(needed),
                           ctypes.byref(count))
    if not needed.value:
        return []
    buf = ctypes.create_string_buffer(needed.value)
    if not winspool.EnumPrintersW(flags, None, 4, buf, needed, ctypes.byref(needed),
                                  ctypes.byref(count)):
        return []
    arr = ctypes.cast(buf, ctypes.POINTER(PRINTER_INFO_4 * count.value)).contents
    return [p.pPrinterName for p in arr if p.pPrinterName]


def find_queue(model):
    model = (model or "").lower()
    queues = windows_printer_queues()
    epson = [q for q in queues if "epson" in q.lower()]
    for q in epson:
        if model and model in q.lower().replace(" ", ""):
            return q
    for q in epson:
        if model and model.split("-")[0] in q.lower():
            return q
    return epson[0] if len(epson) == 1 else None


def send_raw_to_queue(queue_name, data: bytes, title="Epson maintenance"):
    """Send raw ESC/P2 bytes through the Windows spooler (USB printers)."""
    import ctypes
    from ctypes import wintypes

    winspool = ctypes.WinDLL("winspool.drv")

    class DOC_INFO_1(ctypes.Structure):
        _fields_ = [("pDocName", wintypes.LPWSTR),
                    ("pOutputFile", wintypes.LPWSTR),
                    ("pDatatype", wintypes.LPWSTR)]

    handle = wintypes.HANDLE()
    if not winspool.OpenPrinterW(queue_name, ctypes.byref(handle), None):
        raise OSError(f"open-queue:{queue_name}")
    try:
        doc = DOC_INFO_1(title, None, "RAW")
        if not winspool.StartDocPrinterW(handle, 1, ctypes.byref(doc)):
            raise OSError("start-doc")
        try:
            winspool.StartPagePrinter(handle)
            written = wintypes.DWORD()
            buf = ctypes.create_string_buffer(data, len(data))
            ok = winspool.WritePrinter(handle, buf, len(data), ctypes.byref(written))
            winspool.EndPagePrinter(handle)
            if not ok or written.value != len(data):
                raise OSError("write")
        finally:
            winspool.EndDocPrinter(handle)
    finally:
        winspool.ClosePrinter(handle)
    return True


def _lpr_send(host, data, label):
    from pyprintlpr import LprClient
    with LprClient(host, port="LPR", label=label, timeout=60) as lpr:
        lpr.send(data)
    return True


def run_maintenance(action, model, serial="", host=None, queue_name=None):
    """action: 'nozzle_check' | 'clean' | 'power_clean'."""
    if action == "nozzle_check":
        data, label = nozzle_check_data(), "Nozzle check"
    elif action in ("clean", "power_clean"):
        data, label = head_clean_data(action == "power_clean"), "Head cleaning"
    else:
        raise ValueError("bad-action")
    if not data:
        raise ValueError("no-data")
    if MOCK:
        time.sleep(1.0)
        via = "mock"
    elif host:
        _lpr_send(validate_host(host), data, label)
        via = f"Wi-Fi {host}"
    else:
        queue_name = queue_name or find_queue(model)
        if not queue_name:
            raise LookupError("no-queue")
        send_raw_to_queue(queue_name, data, label)
        via = queue_name
    add_history(action, model, serial, True, detail={"via": via}, host=host)
    return {"ok": True, "via": via}
