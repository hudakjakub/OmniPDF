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
    content = b"portable executable"
    digest = hashlib.sha256(content).hexdigest()
    tag = "v0.10.0"
    filename = updates.PORTABLE_NAME
    url = f"https://github.com/{updates.RELEASE_REPOSITORY}/releases/download/{tag}/{filename}"

    def metadata(self):
        return {"tag_name": self.tag, "draft": False, "prerelease": False, "assets": [{"name": self.filename, "browser_download_url": self.url, "size": len(self.content), "digest": "sha256:" + self.digest}]}

    def check(self, data, current="0.9.0"):
        with patch.object(updates, "_open", return_value=io.BytesIO(json.dumps(data).encode())):
            return updates.check_for_update(current)

    def test_numeric_version_and_no_downgrade(self):
        self.assertEqual(self.check(self.metadata()).version, "0.10.0")
        self.assertIsNone(self.check(self.metadata(), "0.11.0"))

    def test_only_the_portable_asset_is_used(self):
        previous_asset = 'OmniPDF-Setup-windows-x64.exe'
        url = self.url.rsplit('/', 1)[0] + '/' + previous_asset
        data = self.metadata()
        data['assets'].insert(0, {'name': previous_asset, 'browser_download_url': url,
                               'size': len(self.content), 'digest': 'sha256:' + self.digest})
        self.assertEqual(self.check(data).asset_url, self.url)
        portable = data['assets'].pop()
        with self.assertRaises(updates.UpdateError):
            self.check(data)
        data['assets'].extend((portable, portable))
        with self.assertRaises(updates.UpdateError):
            self.check(data)

    def test_portable_replaces_the_existing_executable_and_rolls_back_a_failed_restart(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / updates.PORTABLE_NAME
            source.write_bytes(self.content)
            portable = root / 'My renamed copy.exe'
            portable.write_bytes(b'original')
            def wait(pid):
                self.assertEqual(pid, 42)
                self.assertEqual(portable.read_bytes(), b'original')
            def fail_start(arguments):
                self.assertEqual(arguments, [str(portable.resolve())])
                self.assertEqual(portable.read_bytes(), self.content)
                raise updates.UpdateError('Could not start')
            arguments = (source, portable, '42', updates.VERSION, self.digest, str(len(self.content)))
            with patch.object(updates, '_wait_for_parent', side_effect=wait), \
                 patch.object(updates, '_start_executable', side_effect=fail_start):
                with self.assertRaisesRegex(updates.UpdateError, 'Could not start'):
                    updates.apply_portable_update(*arguments)
            self.assertEqual(portable.read_bytes(), b'original')
            with patch.object(updates, '_wait_for_parent', side_effect=wait), \
                 patch.object(updates, '_start_executable') as start:
                updates.apply_portable_update(*arguments)
                start.assert_called_once_with([str(portable.resolve())])
            self.assertEqual(portable.read_bytes(), self.content)
            self.assertEqual(set(root.iterdir()), {source, portable})

    def test_download_revalidates_the_url(self):
        release = self.check(self.metadata())
        for bad_url in (self.url.replace('github.com', 'evil.test'), self.url.replace(self.tag, 'v0.9.0'),
                        self.url + '?x=1', self.url.replace(self.filename, 'other.exe')):
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

    def test_missing_or_invalid_github_digest_is_rejected(self):
        data = self.metadata()
        del data["assets"][0]["digest"]
        with self.assertRaisesRegex(updates.UpdateError, 'checksum'):
            self.check(data)
        data["assets"][0]["digest"] = 'sha256:invalid'
        with self.assertRaisesRegex(updates.UpdateError, 'checksum'):
            self.check(data)

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
        release = self.check(self.metadata())
        path = f'C:/temp/{self.filename}'
        target = 'C:/Apps/Renamed Omni PDF.exe'
        with patch.object(updates.subprocess, "Popen") as popen:
            updates.launch_portable_update(path, target, 42, release)
        self.assertEqual(popen.call_args.args[0], [path, '--apply-portable-update', target, '42',
                                                  release.version, self.digest, str(len(self.content))])

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
            updates.launch_portable_update(self.filename, 'app.exe', 42, self.check(self.metadata()))
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

    def test_cached_executable_verification(self):
        release = updates.Release("0.10.0", self.url, self.digest, len(self.content))
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / self.filename
            path.write_bytes(self.content)
            updates.verify_update(path, release)
            path.write_bytes(b"tampered!")
            with self.assertRaises(updates.UpdateError):
                updates.verify_update(path, release)
            path.rename(Path(folder) / "other.exe")
            with self.assertRaises(updates.UpdateError):
                updates.verify_update(Path(folder) / "other.exe", release)


if __name__ == "__main__":
    unittest.main()
