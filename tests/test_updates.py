import hashlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request

from omnipdf import updates


class UpdateTests(unittest.TestCase):
    content = b"installer"
    digest = hashlib.sha256(content).hexdigest()
    tag = "v0.10.0"
    filename = "OmniPDF-Setup-0.10.0-windows-x64.exe"
    url = f"https://github.com/{updates.RELEASE_REPOSITORY}/releases/download/{tag}/{filename}"

    def metadata(self):
        return {"tag_name": self.tag, "draft": False, "prerelease": False, "assets": [{"name": self.filename, "browser_download_url": self.url, "size": len(self.content), "digest": "sha256:" + self.digest}]}

    def check(self, data, current="0.9.0"):
        with patch.object(updates, "_open", return_value=io.BytesIO(json.dumps(data).encode())):
            return updates.check_for_update(current)

    def test_numeric_version_and_no_downgrade(self):
        self.assertEqual(self.check(self.metadata()).version, "0.10.0")
        self.assertIsNone(self.check(self.metadata(), "0.11.0"))

    def test_unversioned_installer_and_legacy_compatibility(self):
        filename = 'OmniPDF-Setup-windows-x64.exe'
        url = self.url.rsplit('/', 1)[0] + '/' + filename
        data = self.metadata()
        data['assets'].append({'name': filename, 'browser_download_url': url,
                               'size': len(self.content), 'digest': 'sha256:' + self.digest})
        release = self.check(data)
        self.assertEqual(release.asset_url, url)
        with tempfile.TemporaryDirectory() as folder:
            with patch.object(updates, '_open', return_value=io.BytesIO(self.content)):
                path = updates.download_update(release, folder)
            self.assertEqual(path.name, filename)
            updates.verify_installer(path, release)
            path.write_bytes(b'tampered')
            with self.assertRaises(updates.UpdateError):
                updates.verify_installer(path, release)
        self.assertEqual(self.check(self.metadata()).asset_url, self.url)
        data['assets'].append(data['assets'][-1])
        with self.assertRaises(updates.UpdateError):
            self.check(data)

    def test_unversioned_installer_checksum_file_and_url_validation(self):
        filename = 'OmniPDF-Setup-windows-x64.exe'
        url = self.url.rsplit('/', 1)[0] + '/' + filename
        data = self.metadata()
        data['assets'] = [
            {'name': filename, 'browser_download_url': url, 'size': len(self.content)},
            {'name': 'SHA256SUMS.txt', 'browser_download_url': self.url.rsplit('/', 1)[0] + '/SHA256SUMS.txt'},
        ]
        with patch.object(updates, '_open', side_effect=[io.BytesIO(json.dumps(data).encode()), io.BytesIO(f'{self.digest}  {filename}\n'.encode())]):
            release = updates.check_for_update('0.9.0')
        self.assertEqual(release.checksum, self.digest)
        for bad_url in (url.replace('github.com', 'evil.test'), url.replace(self.tag, 'v0.9.0'), url + '?x=1', url.replace(filename, 'other.exe')):
            bad = updates.Release(release.version, bad_url, self.digest, len(self.content))
            with tempfile.TemporaryDirectory() as folder, self.assertRaises(updates.UpdateError):
                updates.download_update(bad, folder)

    def test_no_release_and_unpublished(self):
        with patch.object(updates, "_open", side_effect=HTTPError(updates.API_URL, 404, "missing", {}, None)):
            self.assertIsNone(updates.check_for_update())
        for field in ("draft", "prerelease"):
            data = self.metadata()
            data[field] = True
            self.assertIsNone(self.check(data))

    def test_bad_tag_and_url(self):
        for field, value in (("tag_name", "v1.0.0-rc1"),):
            data = self.metadata()
            data[field] = value
            with self.assertRaises(updates.UpdateError):
                self.check(data)
        for url in (self.url.replace("github.com", "evil.test"), self.url.replace("https:", "http:"), self.url.replace(updates.RELEASE_REPOSITORY, "other/repo")):
            data = self.metadata()
            data["assets"][0]["browser_download_url"] = url
            with self.assertRaises(updates.UpdateError):
                self.check(data)

    def test_redirects(self):
        handler = updates._Redirects()
        req = Request(self.url)
        for url in ("http://github.com/a", "https://evil.test/a"):
            with self.assertRaises(updates.UpdateError):
                handler.redirect_request(req, None, 302, "", {}, url)
        self.assertIsNotNone(handler.redirect_request(req, None, 302, "", {}, "https://release-assets.githubusercontent.com/a"))

    def test_checksum_file(self):
        data = self.metadata()
        del data["assets"][0]["digest"]
        data["assets"].append({"name": "SHA256SUMS.txt", "browser_download_url": self.url.rsplit("/", 1)[0] + "/SHA256SUMS.txt"})
        with patch.object(updates, "_open", side_effect=[io.BytesIO(json.dumps(data).encode()), io.BytesIO(f"{self.digest}  {self.filename}\n".encode())]):
            self.assertEqual(updates.check_for_update("0.9.0").checksum, self.digest)

    def test_download_verifies_and_rolls_back(self):
        release = updates.Release("0.10.0", self.url, self.digest, len(self.content))
        with tempfile.TemporaryDirectory() as folder:
            with patch.object(updates, "_open", return_value=io.BytesIO(self.content)):
                path = updates.download_update(release, folder)
            self.assertEqual(path.read_bytes(), self.content)
            path.unlink()
            for payload in (b"bad", self.content + b"extra"):
                with patch.object(updates, "_open", return_value=io.BytesIO(payload)), self.assertRaises(updates.UpdateError):
                    updates.download_update(release, folder)
                self.assertEqual(list(Path(folder).iterdir()), [])
            with patch.object(updates, "_open", side_effect=TimeoutError()), self.assertRaises(updates.UpdateError):
                updates.download_update(release, folder)
            self.assertEqual(list(Path(folder).iterdir()), [])

    def test_download_reports_verified_size_progress(self):
        release = updates.Release('0.10.0', self.url, self.digest, len(self.content))
        progress = []
        with tempfile.TemporaryDirectory() as folder:
            with patch.object(updates, '_open', return_value=io.BytesIO(self.content)):
                path = updates.download_update(release, folder, progress=lambda total, size: progress.append((total, size)))
            self.assertEqual(path.read_bytes(), self.content)
            self.assertEqual(progress[-1], (len(self.content), len(self.content)))

    def test_launch_args(self):
        with patch.object(updates.subprocess, "Popen") as popen:
            updates.launch_installer("C:/temp/setup.exe", "C:/Program Files/Omni PDF", 42)
        self.assertEqual(popen.call_args.args[0], ["C:/temp/setup.exe", "/SILENT", "/NORESTART", "/SP-", "/OMNIPDFUPDATE=1", "/OMNIPDFWAITPID=42", "/DIR=C:/Program Files/Omni PDF"])

    def test_frozen_windows_launch_sanitizes_dll_search(self):
        from unittest.mock import Mock, call
        kernel = Mock()
        kernel.SetDllDirectoryW.return_value = True
        with patch.object(updates.sys, 'platform', 'win32'), \
             patch.object(updates.sys, 'frozen', True, create=True), \
             patch.object(updates.sys, '_MEIPASS', r'C:\Temp\bundle', create=True), \
             patch.object(updates.ctypes, 'windll', Mock(kernel32=kernel), create=True), \
             patch.dict(updates.os.environ, {'PATH': r'C:\Temp\bundle;C:\Temp\bundle\lib;C:\Windows'}, clear=True), \
             patch.object(updates.subprocess, 'Popen') as popen:
            updates.launch_installer('setup.exe', 'app', 42)
        self.assertEqual(kernel.SetDllDirectoryW.call_args_list, [call(None), call(r'C:\Temp\bundle')])
        self.assertEqual(popen.call_args.kwargs['env']['PATH'], r'C:\Windows')
        self.assertEqual(popen.call_args.kwargs['env']['PYINSTALLER_RESET_ENVIRONMENT'], '1')
        self.assertEqual(popen.call_args.kwargs['env']['PYINSTALLER_RESET_ENVIRONMENT'], '1')

    def test_cancellation_cleans_temporary_file(self):
        release = updates.Release("0.10.0", self.url, self.digest, len(self.content))
        with tempfile.TemporaryDirectory() as folder:
            with patch.object(updates, "_open", return_value=io.BytesIO(self.content)):
                with self.assertRaisesRegex(updates.UpdateError, "Update cancelled"):
                    updates.download_update(release, folder, cancelled=iter([False, False, True]).__next__)
            self.assertEqual(list(Path(folder).iterdir()), [])
            with patch.object(updates, "_open") as opener:
                with self.assertRaisesRegex(updates.UpdateError, "Update cancelled"):
                    updates.download_update(release, folder, cancelled=lambda: True)
                opener.assert_not_called()

    def test_cached_installer_verification(self):
        release = updates.Release("0.10.0", self.url, self.digest, len(self.content))
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / self.filename
            path.write_bytes(self.content)
            updates.verify_installer(path, release)
            path.write_bytes(b"tampered!")
            with self.assertRaises(updates.UpdateError):
                updates.verify_installer(path, release)
            path.rename(Path(folder) / "other.exe")
            with self.assertRaises(updates.UpdateError):
                updates.verify_installer(Path(folder) / "other.exe", release)


if __name__ == "__main__":
    unittest.main()
