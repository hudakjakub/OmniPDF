"""Check and securely download published Omni PDF updates."""
import hashlib
import ctypes
import json
import ntpath
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time
from contextlib import suppress
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .app_info import VERSION, RELEASE_REPOSITORY

API_URL = f"https://api.github.com/repos/{RELEASE_REPOSITORY}/releases/latest"
MAX_JSON = 1024 * 1024
MAX_EXECUTABLE = 512 * 1024 * 1024
TIMEOUT = 30
_HOSTS = {"github.com", "release-assets.githubusercontent.com", "objects.githubusercontent.com"}
_VERSION = re.compile(r"v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\Z")
_HASH = re.compile(r"[0-9a-fA-F]{64}\Z")
PORTABLE_NAME = 'OmniPDF-windows-x64.exe'


class UpdateError(Exception):
    """An update could not be checked or downloaded safely."""


@dataclass(frozen=True)
class Release:
    version: str
    asset_url: str
    checksum: str
    size: int


def _version(value):
    match = _VERSION.fullmatch(value if isinstance(value, str) else "")
    if not match:
        raise UpdateError("Invalid release version.")
    return tuple(map(int, match.groups()))


def _asset_url(url, tag, name):
    parsed = urlsplit(url if isinstance(url, str) else "")
    if (parsed.scheme != "https" or parsed.netloc != "github.com" or parsed.query or parsed.fragment
            or parsed.path != f"/{RELEASE_REPOSITORY}/releases/download/{tag}/{name}"):
        raise UpdateError("Invalid release download URL.")
    return url


def _trusted_url(url):
    parsed = urlsplit(url)
    return parsed.scheme == "https" and parsed.netloc in _HOSTS and not parsed.fragment


def _release_url(release):
    tag = 'v' + release.version
    _version(tag)
    return _asset_url(release.asset_url, tag, PORTABLE_NAME)


class _Redirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not _trusted_url(newurl):
            raise UpdateError("Untrusted update download redirect.")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _open(url):
    try:
        return build_opener(_Redirects()).open(Request(url, headers={"User-Agent": "OmniPDF-Updater", "Accept": "application/vnd.github+json"}), timeout=TIMEOUT)
    except HTTPError:
        raise
    except (OSError, URLError, ValueError) as exc:
        raise UpdateError("Could not connect to the update service.") from exc


def _read_bounded(response, limit):
    data = response.read(limit + 1)
    if len(data) > limit:
        raise UpdateError("Update response is too large.")
    return data


def check_for_update(current_version=VERSION):
    current = _version("v" + current_version.removeprefix("v"))
    try:
        with _open(API_URL) as response:
            data = json.loads(_read_bounded(response, MAX_JSON))
    except HTTPError as exc:
        exc.close()
        if exc.code == 404:
            return None
        raise UpdateError("Could not check for updates.") from exc
    except (ValueError, OSError) as exc:
        raise UpdateError("Invalid update response.") from exc
    if not isinstance(data, dict):
        raise UpdateError("Invalid update response.")
    if data.get("draft") is not False or data.get("prerelease") is not False:
        return None
    tag = data.get("tag_name")
    if _version(tag) <= current:
        return None
    version = tag[1:]
    assets = data.get("assets")
    if not isinstance(assets, list):
        raise UpdateError("Release assets are missing.")
    matches = [item for item in assets if isinstance(item, dict) and item.get("name") == PORTABLE_NAME]
    if len(matches) != 1:
        raise UpdateError("The portable release asset is missing or duplicated.")
    executable = matches[0]
    url = _asset_url(executable.get("browser_download_url"), tag, PORTABLE_NAME)
    size = executable.get("size")
    if type(size) is not int or not 0 < size <= MAX_EXECUTABLE:
        raise UpdateError("Invalid update size.")
    digest = executable.get("digest")
    if not isinstance(digest, str) or not digest.startswith("sha256:") or not _HASH.fullmatch(digest[7:]):
        raise UpdateError("Invalid update checksum.")
    return Release(version, url, digest[7:].lower(), size)


def download_update(release, destination_dir, *, cancelled=None, progress=None):
    url = _release_url(release)
    if not isinstance(release.checksum, str) or not _HASH.fullmatch(release.checksum) or type(release.size) is not int or not 0 < release.size <= MAX_EXECUTABLE:
        raise UpdateError("Invalid release metadata.")
    if cancelled and cancelled():
        raise UpdateError("Update cancelled.")
    directory = Path(destination_dir)
    temporary = None
    try:
        directory.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=directory, prefix=".update-", suffix=".tmp", delete=False) as output:
            temporary = Path(output.name)
            digest = hashlib.sha256()
            total = 0
            with _open(url) as response:
                while True:
                    if cancelled and cancelled():
                        raise UpdateError("Update cancelled.")
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > release.size or total > MAX_EXECUTABLE:
                        raise UpdateError("Update download is too large.")
                    digest.update(chunk)
                    output.write(chunk)
                    if progress:
                        progress(total, release.size)
        if cancelled and cancelled():
            raise UpdateError("Update cancelled.")
        if total != release.size or digest.hexdigest() != release.checksum.lower():
            raise UpdateError("Update download failed verification.")
        final = directory / PORTABLE_NAME
        os.replace(temporary, final)
        temporary = None
        return final
    except (HTTPError, OSError) as exc:
        raise UpdateError("Could not download the update.") from exc
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def verify_update(path, release):
    _release_url(release)
    if (Path(path).name != PORTABLE_NAME or type(release.size) is not int
            or not 0 < release.size <= MAX_EXECUTABLE
            or not isinstance(release.checksum, str) or not _HASH.fullmatch(release.checksum)):
        raise UpdateError("Invalid update metadata.")
    digest = hashlib.sha256()
    total = 0
    try:
        with open(path, "rb") as executable:
            while chunk := executable.read(1024 * 1024):
                total += len(chunk)
                if total > release.size:
                    raise UpdateError("Update failed verification.")
                digest.update(chunk)
    except OSError as exc:
        raise UpdateError("Could not read the update executable.") from exc
    if total != release.size or digest.hexdigest() != release.checksum.lower():
        raise UpdateError("Update failed verification.")


def launch_portable_update(path, target, parent_pid, release):
    _release_url(release)
    if Path(path).name != PORTABLE_NAME:
        raise UpdateError('The portable update executable was not found.')
    return _start_executable([str(path), '--apply-portable-update', str(target), str(parent_pid),
                              release.version, release.checksum, str(release.size)])


def _start_executable(arguments):
    env = {**os.environ, 'PYINSTALLER_RESET_ENVIRONMENT': '1'}
    kernel = None
    try:
        if sys.platform == 'win32' and getattr(sys, 'frozen', False):
            meipass = sys._MEIPASS
            root = ntpath.normcase(ntpath.abspath(meipass))
            def outside_bundle(entry):
                try:
                    return ntpath.commonpath((root, ntpath.normcase(ntpath.abspath(entry)))) != root
                except ValueError:
                    return True
            env['PATH'] = ';'.join(entry for entry in env.get('PATH', '').split(';') if outside_bundle(entry))
            api = ctypes.windll.kernel32
            reset = api.SetDllDirectoryW
            kernel = api
            if not reset(None):
                raise UpdateError("Could not prepare the update environment.")
        return subprocess.Popen(arguments, env=env, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, AttributeError) as exc:
        raise UpdateError("Could not start the update executable.") from exc
    finally:
        if kernel is not None:
            kernel.SetDllDirectoryW(sys._MEIPASS)


def _wait_for_parent(pid):
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_bool, ctypes.c_uint32]
    kernel.OpenProcess.restype = ctypes.c_void_p
    kernel.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    kernel.WaitForSingleObject.restype = ctypes.c_uint32
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    handle = kernel.OpenProcess(0x00100000, False, pid)
    if not handle:
        error = ctypes.get_last_error()
        if error == 87:  # The previous application process has already exited.
            return
        raise ctypes.WinError(error)
    try:
        if kernel.WaitForSingleObject(handle, 30000) != 0:
            raise UpdateError('Omni PDF did not close in time to update.')
    finally:
        kernel.CloseHandle(handle)


def apply_portable_update(source, target, parent_pid, version, checksum, size, *, restart_arguments=()):
    directory = None
    keep_backup = False
    try:
        source = Path(source).resolve(strict=True)
        target = Path(target).resolve(strict=True)
        pid = int(parent_pid)
        if (version != VERSION or source.name != PORTABLE_NAME or target.suffix.lower() != '.exe'
                or not target.is_file() or source.samefile(target) or not 0 < pid <= 0xffffffff):
            raise UpdateError('Invalid portable update request.')
        release = Release(version, f'https://github.com/{RELEASE_REPOSITORY}/releases/download/v{version}/{PORTABLE_NAME}',
                          checksum, int(size))
        original = target.stat()
        directory = Path(tempfile.mkdtemp(prefix='.omnipdf-update-', dir=target.parent))
        staged = directory / PORTABLE_NAME
        backup = directory / 'previous.exe'
        shutil.copyfile(source, staged)
        verify_update(staged, release)
        _wait_for_parent(pid)
        shutil.copyfile(target, backup)
        # The PyInstaller bootloader can hold the executable briefly after its child exits.
        deadline = time.monotonic() + 10
        while True:
            current = target.stat()
            if not os.path.samestat(original, current) or (original.st_size, original.st_mtime_ns) != (current.st_size, current.st_mtime_ns):
                raise UpdateError('The portable app changed while the update was being prepared.')
            try:
                os.replace(staged, target)
                break
            except PermissionError:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(0.25)
        try:
            _start_executable([str(target), *restart_arguments])
        except UpdateError:
            try:
                os.replace(backup, target)
            except OSError as exc:
                keep_backup = True
                raise UpdateError(f'The portable app could not restart. The previous executable is at:\n{backup}') from exc
            raise
    except (OSError, ValueError) as exc:
        raise UpdateError('Could not replace the portable app in its current folder.') from exc
    finally:
        if directory is not None and not keep_backup:
            for filename in (PORTABLE_NAME, 'previous.exe'):
                with suppress(OSError):
                    (directory / filename).unlink(missing_ok=True)
            with suppress(OSError):
                directory.rmdir()
