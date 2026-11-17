"""Check and securely download published Omni PDF updates."""
import hashlib
import ctypes
import json
import ntpath
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from app_info import VERSION, RELEASE_REPOSITORY

API_URL = f"https://api.github.com/repos/{RELEASE_REPOSITORY}/releases/latest"
MAX_JSON = 1024 * 1024
MAX_CHECKSUMS = 1024 * 1024
MAX_INSTALLER = 512 * 1024 * 1024
TIMEOUT = 30
_HOSTS = {"github.com", "release-assets.githubusercontent.com", "objects.githubusercontent.com"}
_VERSION = re.compile(r"v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\Z")
_HASH = re.compile(r"[0-9a-fA-F]{64}\Z")


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
    filename = f"OmniPDF-Setup-{version}-windows-x64.exe"
    assets = data.get("assets")
    if not isinstance(assets, list):
        raise UpdateError("Release assets are missing.")
    def asset(name):
        matches = [item for item in assets if isinstance(item, dict) and item.get("name") == name]
        if len(matches) != 1:
            raise UpdateError("Release assets are missing or duplicated.")
        return matches[0]
    installer = asset(filename)
    url = _asset_url(installer.get("browser_download_url"), tag, filename)
    size = installer.get("size")
    if type(size) is not int or not 0 < size <= MAX_INSTALLER:
        raise UpdateError("Invalid installer size.")
    digest = installer.get("digest")
    if digest is not None:
        if not isinstance(digest, str) or not digest.startswith("sha256:") or not _HASH.fullmatch(digest[7:]):
            raise UpdateError("Invalid installer checksum.")
        checksum = digest[7:].lower()
    else:
        sums = asset("SHA256SUMS.txt")
        sums_url = _asset_url(sums.get("browser_download_url"), tag, "SHA256SUMS.txt")
        try:
            with _open(sums_url) as response:
                content = _read_bounded(response, MAX_CHECKSUMS).decode("utf-8")
        except (HTTPError, OSError, UnicodeError) as exc:
            raise UpdateError("Could not read release checksums.") from exc
        matches = []
        for line in content.splitlines():
            match = re.fullmatch(r"([0-9a-fA-F]{64}) [ *](.+)", line)
            if match and match.group(2) == filename:
                matches.append(match.group(1).lower())
        if len(matches) != 1:
            raise UpdateError("Installer checksum is missing or duplicated.")
        checksum = matches[0]
    return Release(version, url, checksum, size)


def download_update(release, destination_dir, *, cancelled=None):
    tag = "v" + release.version
    _version(tag)
    filename = f"OmniPDF-Setup-{release.version}-windows-x64.exe"
    _asset_url(release.asset_url, tag, filename)
    if not isinstance(release.checksum, str) or not _HASH.fullmatch(release.checksum) or type(release.size) is not int or not 0 < release.size <= MAX_INSTALLER:
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
            with _open(release.asset_url) as response:
                while True:
                    if cancelled and cancelled():
                        raise UpdateError("Update cancelled.")
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > release.size or total > MAX_INSTALLER:
                        raise UpdateError("Installer download is too large.")
                    digest.update(chunk)
                    output.write(chunk)
        if cancelled and cancelled():
            raise UpdateError("Update cancelled.")
        if total != release.size or digest.hexdigest() != release.checksum.lower():
            raise UpdateError("Installer download failed verification.")
        final = directory / filename
        os.replace(temporary, final)
        temporary = None
        return final
    except (HTTPError, OSError) as exc:
        raise UpdateError("Could not download the update.") from exc
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def verify_installer(path, release):
    tag = "v" + release.version
    _version(tag)
    filename = f"OmniPDF-Setup-{release.version}-windows-x64.exe"
    _asset_url(release.asset_url, tag, filename)
    if (Path(path).name != filename or type(release.size) is not int
            or not 0 < release.size <= MAX_INSTALLER
            or not isinstance(release.checksum, str) or not _HASH.fullmatch(release.checksum)):
        raise UpdateError("Invalid installer metadata.")
    digest = hashlib.sha256()
    total = 0
    try:
        with open(path, "rb") as installer:
            while chunk := installer.read(1024 * 1024):
                total += len(chunk)
                if total > release.size:
                    raise UpdateError("Installer failed verification.")
                digest.update(chunk)
    except OSError as exc:
        raise UpdateError("Could not read the installer.") from exc
    if total != release.size or digest.hexdigest() != release.checksum.lower():
        raise UpdateError("Installer failed verification.")


def launch_installer(path, installation_dir, parent_pid):
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
                raise UpdateError("Could not prepare the installer environment.")
        return subprocess.Popen([str(path), "/SILENT", "/NORESTART", "/SP-", "/OMNIPDFUPDATE=1", f"/OMNIPDFWAITPID={parent_pid}", f"/DIR={installation_dir}"],
                                env=env,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, AttributeError) as exc:
        raise UpdateError("Could not start the installer.") from exc
    finally:
        if kernel is not None:
            kernel.SetDllDirectoryW(sys._MEIPASS)
