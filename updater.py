# -*- coding: utf-8 -*-
"""
ตัวอัปเดตอัตโนมัติจาก GitHub Releases

ขั้นตอน:
1. check()     อ่าน release ล่าสุดของ repo (public, ไม่ต้องล็อกอิน)
2. download()  โหลด exe ใหม่ไปไว้ข้างไฟล์เดิมเป็น EpsonInkPadReset.update.exe
               แล้วตรวจ SHA-256 กับไฟล์ .sha256 ที่แนบมากับ release
3. install()   เปิดตัวใหม่ด้วย --finish-update: รอตัวเก่าปิด คัดลอกตัวเองทับ
               แล้วเปิดตัวเก่า (ที่กลายเป็นเวอร์ชันใหม่) ซึ่งจะลบไฟล์ .update.exe ทิ้ง

ตัวแปรช่วยทดสอบ: EPSON_RESET_FAKE_VERSION=2.0.0 ทำเป็นว่าเวอร์ชันปัจจุบันเก่า
"""

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

GITHUB_REPO = "Mark-Notify/Epson-config"
ASSET_NAME = "EpsonInkPadReset.exe"
UPDATE_NAME = "EpsonInkPadReset.update.exe"
API_LATEST = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
RELEASES_PAGE = f"https://github.com/{GITHUB_REPO}/releases/latest"
TIMEOUT = 15
DOWNLOAD_TIMEOUT = 60


@dataclass
class Release:
    version: str
    tag: str
    notes: str
    page: str
    exe_url: str
    sha_url: Optional[str]
    size: int


def parse_version(text: str):
    nums = re.findall(r"\d+", text or "")
    return tuple(int(n) for n in nums[:3]) + (0,) * (3 - len(nums[:3]))


def current_version(app_version: str) -> str:
    return os.environ.get("EPSON_RESET_FAKE_VERSION") or app_version


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def _request(url: str, app_version: str, timeout: float = TIMEOUT):
    req = urllib.request.Request(url, headers={
        "User-Agent": f"EpsonInkPadReset/{app_version}",
        "Accept": "application/vnd.github+json",
    })
    return urllib.request.urlopen(req, timeout=timeout)


def check(app_version: str) -> Optional[Release]:
    """Return the latest release if it is newer than this one, else None."""
    with _request(API_LATEST, app_version) as resp:
        data = json.load(resp)
    tag = data.get("tag_name", "")
    if data.get("draft") or data.get("prerelease"):
        return None
    if parse_version(tag) <= parse_version(current_version(app_version)):
        return None
    exe = sha = None
    for asset in data.get("assets", []):
        if asset.get("name") == ASSET_NAME:
            exe = asset
        elif asset.get("name") == ASSET_NAME + ".sha256":
            sha = asset
    if exe is None:
        return None
    return Release(
        version=tag.lstrip("vV"),
        tag=tag,
        notes=(data.get("body") or "").strip(),
        page=data.get("html_url") or RELEASES_PAGE,
        exe_url=exe["browser_download_url"],
        sha_url=sha["browser_download_url"] if sha else None,
        size=int(exe.get("size") or 0),
    )


def target_path() -> Path:
    return Path(sys.executable).resolve()


def _writable_dir(folder: Path) -> bool:
    probe = folder / ".epson_reset_write_test"
    try:
        probe.write_bytes(b"")
        probe.unlink()
        return True
    except OSError:
        return False


def download(release: Release, app_version: str,
             progress: Optional[Callable[[float], None]] = None) -> Path:
    """Download and verify the new exe. Returns the downloaded file."""
    if not release.sha_url:
        raise IOError("no-checksum")
    with _request(release.sha_url, app_version) as resp:
        expected = resp.read().decode("ascii", "ignore").split()[0].lower()
    if not re.fullmatch(r"[0-9a-f]{64}", expected):
        raise IOError("bad-checksum-file")

    folder = target_path().parent if is_frozen() else Path.cwd()
    if not _writable_dir(folder):
        folder = Path(os.environ.get("USERPROFILE") or Path.home()) / "Downloads"
        folder.mkdir(parents=True, exist_ok=True)
    dest = folder / UPDATE_NAME

    attempts = 3
    for attempt in range(1, attempts + 1):
        try:
            _download_once(release, app_version, dest, expected, progress)
            return dest
        except (ConnectionError, TimeoutError, urllib.error.URLError) as exc:
            # dropped connection (flaky Wi-Fi, antivirus scanning the stream)
            if attempt == attempts:
                raise IOError(f"download-failed: {exc}") from exc
            time.sleep(2 * attempt)
    return dest


def _download_once(release, app_version, dest: Path, expected: str,
                   progress) -> None:
    digest = hashlib.sha256()
    done = 0
    try:
        with _request(release.exe_url, app_version, DOWNLOAD_TIMEOUT) as resp, \
                open(dest, "wb") as fp:
            total = int(resp.headers.get("Content-Length") or release.size or 0)
            while True:
                chunk = resp.read(256 * 1024)
                if not chunk:
                    break
                fp.write(chunk)
                digest.update(chunk)
                done += len(chunk)
                if progress and total:
                    progress(min(done / total, 1.0))
        if digest.hexdigest() != expected:
            raise IOError("checksum-mismatch")
    except BaseException:
        # never leave a partial or unverified file next to the program
        try:
            dest.unlink()
        except OSError:
            pass
        raise


def can_install_in_place(downloaded: Path) -> bool:
    return is_frozen() and downloaded.parent == target_path().parent


def _spawn(args) -> None:
    """Start a detached copy of a one-file exe with a clean environment."""
    env = {k: v for k, v in os.environ.items()
           if not k.startswith("_PYI") and k != "_MEIPASS2"}
    env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    flags = 0
    for name in ("DETACHED_PROCESS", "CREATE_NEW_PROCESS_GROUP"):
        flags |= getattr(subprocess, name, 0)
    subprocess.Popen([str(a) for a in args], env=env, creationflags=flags,
                     close_fds=True)


def install(downloaded: Path) -> None:
    """Hand over to the new exe; the caller quits right after this returns.

    No shell or script is involved: the downloaded (already verified) exe is
    started with --finish-update, waits until the old exe is no longer
    locked, copies itself over it and starts it. The restarted program then
    deletes the downloaded copy (see handle_command_line).
    """
    _spawn([downloaded, "--finish-update", target_path()])


def _retry(action, seconds: float) -> bool:
    deadline = time.time() + seconds
    while True:
        try:
            action()
            return True
        except OSError:
            if time.time() > deadline:
                return False
            time.sleep(0.5)


def handle_command_line(argv) -> bool:
    """Handle the updater's own arguments. True means: exit now, no window."""
    if len(argv) >= 3 and argv[1] == "--finish-update":
        target = Path(argv[2])
        me = Path(sys.executable)
        copied = _retry(lambda: shutil.copyfile(me, target), 60)
        _spawn([target, "--cleanup-update", me] if copied else [target])
        return True
    if len(argv) >= 3 and argv[1] == "--cleanup-update":
        leftover = Path(argv[2])
        if leftover.name.endswith(".update.exe") and leftover.exists():
            threading.Thread(target=_retry, args=(leftover.unlink, 30),
                             daemon=True).start()
        return False
    if is_frozen():
        stale = target_path().with_name(UPDATE_NAME)
        if stale.exists():
            threading.Thread(target=_retry, args=(stale.unlink, 5),
                             daemon=True).start()
    return False
