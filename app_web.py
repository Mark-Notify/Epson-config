# -*- coding: utf-8 -*-
"""
Epson Ink Pad Reset - หน้าต่างหลัก (HTML/CSS ผ่าน pywebview + WebView2)

หน้าตาอยู่ใน ui/ (index.html, style.css, app.js) ส่วนนี้เป็นแค่สะพาน:
JavaScript เรียก window.pywebview.api.<method>() แล้วได้ dict กลับไป
งานทุกอย่างทำใน epson_reset_core

ถ้าเครื่องไม่มี Microsoft Edge WebView2 Runtime จะเปิดหน้าต่างแบบเดิม
(epson_reset_gui, customtkinter) ให้แทน

โหมดทดสอบโดยไม่มีเครื่องพิมพ์:  set EPSON_RESET_MOCK=1
"""

import os
import sys
import threading
import traceback
import webbrowser

import epson_reset_core as core
import updater


def _err(exc):
    text = str(exc) or exc.__class__.__name__
    return {"ok": False, "error": text, "kind": exc.__class__.__name__}


def _guard(func):
    """Every API call returns a dict; exceptions become {"ok": False, ...}."""

    def wrapper(self, *args):
        core.LOG.lines.clear()
        try:
            result = func(self, *args)
            if isinstance(result, dict):
                result.setdefault("ok", True)
            else:
                result = {"ok": True, "data": result}
        except Exception as exc:  # noqa: BLE001 - reported to the UI
            self._trace(traceback.format_exc())
            result = _err(exc)
        if core.LOG.lines:
            result["log"] = list(core.LOG.lines)
            self._trace("\n".join(core.LOG.lines))
        return result

    wrapper.__name__ = func.__name__
    wrapper.__doc__ = func.__doc__
    return wrapper


class Api:
    """Methods exposed to JavaScript. Names without a leading underscore only."""

    def __init__(self):
        self._window = None
        self._release = None
        self._dl = {"state": "idle", "progress": 0.0, "error": ""}
        self._scan = {"state": "idle", "progress": 0.0, "results": []}
        self._tech = []

    # -- helpers (not exposed: pywebview skips names starting with "_")
    def _trace(self, text):
        self._tech.append(text.rstrip())
        del self._tech[:-300]

    # -- app info
    @_guard
    def info(self):
        return {"version": core.APP_VERSION, "title": core.APP_TITLE,
                "mock": core.MOCK, "has_db": bool(core.CONF),
                "backup_dir": str(core.backup_dir()),
                "settings": core.load_settings(),
                "platform": sys.platform}

    @_guard
    def tech_log(self):
        return {"lines": self._tech[-200:]}

    @_guard
    def save_settings(self, changes):
        return {"settings": core.save_settings(changes or {})}

    # -- printer
    @_guard
    def check(self, host=None):
        host = core.validate_host(host) if host else None
        r = core.check_printer(host)
        st = r.get("status") or {}
        raw = st.get("status")
        st_text = raw[1] if isinstance(raw, (list, tuple)) and len(raw) > 1 else ""
        settings = core.load_settings()
        inks = core.ink_levels(st)
        waste = r.get("waste") or {}
        out = {
            "model": r["model"], "supported": r["supported"],
            "serial": r["serial"], "connection": r["connection"],
            "host": r["host"],
            "status_text": core.STATUS_TH.get(st_text, st_text or "—"),
            "error_code": str(st.get("errcode") or ""),
            "pads": [core.pad_state(st.get(k)) for k in
                     ("maintenance_box_1", "maintenance_box_2")],
            "waste_full": core.is_waste_full(st),
            "waste": [{"key": k, "percent": v} for k, v in waste.items()],
            "inks": inks,
            "low_inks": core.low_inks(inks, settings["ink_threshold"]),
            "ink_threshold": settings["ink_threshold"],
            "stats": core.describe_stats(r.get("stats")),
            "advice": core.pad_advice(r["serial"], r["model"]),
        }
        self._trace(f"check {r['connection']}: {r['model']} {st}")
        if host:
            core.save_settings({"connection": "wifi", "host": host})
        return out

    @_guard
    def reset(self, model, serial, host=None):
        ok, path = core.reset_printer(model, serial, host or None)
        return {"ok": ok, "backup": str(path)}

    @_guard
    def advice(self, serial, model):
        return core.pad_advice(serial, model)

    @_guard
    def temp_reset(self, model, serial, host=None):
        return {"ok": core.temporary_reset(model, serial, host or None)}

    @_guard
    def power_timer(self, model, host=None):
        return core.read_power_off_timer(model, host or None)

    @_guard
    def set_power_timer(self, model, serial, minutes, host=None):
        return {"ok": core.write_power_off_timer(model, serial, minutes, host or None)}

    @_guard
    def maintenance(self, action, model, serial="", host=None, queue=None):
        if queue and queue not in core.windows_printer_queues():
            raise ValueError("no-queue")
        return core.run_maintenance(action, model, serial, host or None, queue or None)

    @_guard
    def queues(self):
        return {"queues": core.windows_printer_queues()}

    # -- backups & history
    @_guard
    def backups(self):
        return {"items": core.list_backups(), "dir": str(core.backup_dir())}

    @_guard
    def restore_plan(self, path, model, serial, host=None):
        self._check_backup_path(path)
        return core.restore_plan(path, model, serial, host or None)

    @_guard
    def restore(self, path, model, serial, host=None):
        self._check_backup_path(path)
        return core.restore_backup(path, model, serial, host or None)

    def _check_backup_path(self, path):
        folder = core.backup_dir().resolve()
        if os.path.dirname(os.path.realpath(path)) != str(folder):
            raise ValueError("backup-outside-folder")

    @_guard
    def history(self):
        items = core.load_history()
        items.reverse()
        return {"items": items[:300]}

    @_guard
    def open_backups(self):
        path = str(core.backup_dir())
        if sys.platform == "win32":
            os.startfile(path)
        else:
            webbrowser.open("file://" + path)
        return {}

    # -- models
    @_guard
    def models(self):
        return {"items": core.list_models()}

    # -- network scan (runs in the background, UI polls scan_status)
    @_guard
    def scan_start(self):
        if self._scan["state"] == "running":
            return dict(self._scan)
        self._scan = {"state": "running", "progress": 0.0, "results": []}

        def progress(v):
            self._scan["progress"] = v

        def worker():
            try:
                self._scan["results"] = core.scan_network(progress)
                self._scan["state"] = "done"
            except Exception as exc:  # noqa: BLE001
                self._trace(traceback.format_exc())
                self._scan["state"] = "error"
                self._scan["error"] = str(exc)
            self._scan["progress"] = 1.0

        threading.Thread(target=worker, daemon=True).start()
        return dict(self._scan)

    @_guard
    def scan_status(self):
        return dict(self._scan)

    # -- updates
    @_guard
    def update_check(self):
        rel = updater.check(core.APP_VERSION)
        self._release = rel
        if rel is None:
            return {"available": False, "current": core.APP_VERSION}
        return {"available": True, "current": core.APP_VERSION,
                "version": rel.version, "notes": rel.notes[:1500], "page": rel.page,
                "can_install": updater.is_frozen()}

    @_guard
    def update_start(self):
        rel = self._release
        if rel is None:
            raise RuntimeError("no-release")
        if not updater.is_frozen():
            webbrowser.open(rel.page)
            return {"state": "browser"}
        if self._dl["state"] == "running":
            return dict(self._dl)
        self._dl = {"state": "running", "progress": 0.0, "error": ""}

        def progress(v):
            self._dl["progress"] = v

        def worker():
            try:
                path = updater.download(rel, core.APP_VERSION, progress)
            except Exception as exc:  # noqa: BLE001
                self._trace(f"update failed: {exc}")
                self._dl.update(state="error",
                                error="checksum" if "checksum" in str(exc) else "download")
                return
            if updater.can_install_in_place(path):
                self._dl.update(state="installing", progress=1.0)
                updater.install(path)
                threading.Timer(0.6, self._close).start()
            else:
                self._dl.update(state="manual", progress=1.0, path=str(path))

        threading.Thread(target=worker, daemon=True).start()
        return dict(self._dl)

    @_guard
    def update_status(self):
        return dict(self._dl)

    @_guard
    def open_url(self, url):
        if not str(url).startswith("https://github.com/"):
            raise ValueError("blocked-url")
        webbrowser.open(url)
        return {}

    def _close(self):
        try:
            self._window.destroy()
        except Exception:
            os._exit(0)


def ui_path():
    return str(core.app_dir() / "ui" / "index.html")


def run_web():
    import webview

    api = Api()
    title = core.APP_TITLE + (" · โหมดทดสอบ" if core.MOCK else "")
    window = webview.create_window(
        title, ui_path(), js_api=api, width=1180, height=780,
        min_size=(760, 600), background_color="#0E1220", text_select=False)
    api._window = window
    gui = "edgechromium" if sys.platform == "win32" else None
    webview.start(gui=gui, debug=os.environ.get("EPSON_RESET_DEBUG") == "1",
                  private_mode=False,
                  storage_path=str(core.backup_dir() / ".webview"))


def run_classic():
    import epson_reset_gui
    epson_reset_gui.App().mainloop()


def selftest(out_path):
    """Packaging check for CI: can the frozen exe load everything it needs?"""
    import json
    report = {"version": core.APP_VERSION, "models": len(core.make_printer().valid_printers),
              "ui": os.path.isfile(ui_path())}
    try:
        import webview  # noqa: F401
        report["webview"] = True
    except Exception as exc:  # noqa: BLE001
        report["webview"] = repr(exc)
    try:
        import customtkinter  # noqa: F401
        import epson_reset_gui  # noqa: F401
        report["classic"] = True
    except Exception as exc:  # noqa: BLE001
        report["classic"] = repr(exc)
    try:
        report["escp2"] = len(core.nozzle_check_data()) > 0
    except Exception as exc:  # noqa: BLE001
        report["escp2"] = repr(exc)
    report["ok"] = all(v is True for k, v in report.items()
                       if k in ("ui", "webview", "classic", "escp2")) and report["models"] > 0
    with open(out_path, "w", encoding="utf-8") as fp:
        json.dump(report, fp)
    return report["ok"]


def main():
    if updater.handle_command_line(sys.argv):
        return
    if "--selftest" in sys.argv:
        idx = sys.argv.index("--selftest")
        out = sys.argv[idx + 1] if len(sys.argv) > idx + 1 else "selftest.json"
        sys.exit(0 if selftest(out) else 1)
    if "--classic" in sys.argv or os.environ.get("EPSON_RESET_CLASSIC") == "1":
        run_classic()
        return
    try:
        run_web()
    except Exception:  # noqa: BLE001 - e.g. no WebView2 runtime installed
        traceback.print_exc()
        run_classic()


if __name__ == "__main__":
    main()
