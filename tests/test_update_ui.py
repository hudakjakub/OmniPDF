import hashlib
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import pymupdf
from PySide6.QtCore import QSettings, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox, QPushButton

from omnipdf.main import Editor
from omnipdf import updates
from omnipdf.updates import Release


class UpdateUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.settings = QSettings(str(self.root / 'settings.ini'), QSettings.Format.IniFormat)
        with patch('omnipdf.main.QSettings', return_value=self.settings):
            self.window = Editor()
        self.window._auto_ocr = lambda *args: None
        self.window._error = lambda error: self.fail(str(error))
        self.window.show()
        self.app.processEvents()
        self.installer = self.root / 'OmniPDF-Setup-0.2.0-windows-x64.exe'
        self.installer.write_bytes(b'fake installer for tests only')
        self.release = Release('0.2.0', 'https://github.com/hudakjakub/OmniPDF/releases/download/v0.2.0/' + self.installer.name,
                               hashlib.sha256(self.installer.read_bytes()).hexdigest(), self.installer.stat().st_size)

    def tearDown(self):
        self.wait_for_worker()
        if self.window.pdf:
            self.window.pdf.close()
            self.window.pdf = None
        self.window.pending = False
        self.window.close()
        self.app.processEvents()
        self.temp.cleanup()

    def wait_for_worker(self):
        deadline = time.monotonic() + 3
        while self.window.update_worker is not None and time.monotonic() < deadline:
            QTest.qWait(10)
        self.assertIsNone(self.window.update_worker)

    def test_manual_check_reports_latest_and_resets_action(self):
        with patch('omnipdf.main.updates.check_for_update', return_value=None), patch.object(QMessageBox, 'information') as message:
            self.window.check_updates()
            self.wait_for_worker()
            message.assert_called_once()
        self.assertTrue(self.window.check_updates_action.isEnabled())

    def test_background_download_can_be_deferred_and_draft_cancel_blocks_install(self):
        source = self.root / 'source.pdf'
        with pymupdf.open() as document:
            document.new_page().insert_text((50, 80), 'Original text', fontsize=12)
            document.save(source)
        original = source.read_bytes()
        self.window.open_file(path=source)
        self.window.select_text(self.window.pdf.spans(0)[0])
        self.window.text.setPlainText('Changed text')
        with patch('omnipdf.main.sys.frozen', True, create=True), \
             patch('omnipdf.main.updates.check_for_update', return_value=self.release), \
             patch('omnipdf.main.updates.download_update', return_value=self.installer) as download, \
             patch.object(QMessageBox, 'question', return_value=QMessageBox.StandardButton.No):
            self.window.check_updates()
            self.wait_for_worker()
        self.assertEqual(self.window.ready_update, (self.release, None))
        download.assert_not_called()
        with patch.object(QMessageBox, 'question', side_effect=[QMessageBox.StandardButton.Yes, QMessageBox.StandardButton.Cancel]), \
             patch('omnipdf.main.updates.launch_installer') as launch:
            self.window._offer_update()
            launch.assert_not_called()
        self.assertTrue(self.window.pending)
        self.assertTrue(self.window.isVisible())
        output = self.root / 'copy.pdf'
        with patch.object(QMessageBox, 'question', side_effect=[QMessageBox.StandardButton.Yes, QMessageBox.StandardButton.Save]), \
             patch.object(QFileDialog, 'getSaveFileName', return_value=(str(output), 'PDF')), \
             patch('omnipdf.main.updates.download_update', return_value=self.installer) as download, \
             patch('omnipdf.main.updates.launch_installer') as launch:
            self.window._offer_update()
            self.wait_for_worker()
            launch.assert_called_once()
            self.assertTrue(callable(download.call_args.kwargs['cancelled']))
            self.assertTrue(self.window._close_approved)
            self.assertFalse(self.window.isVisible())
        with pymupdf.open(output) as saved:
            self.assertIn('Changed text', saved[0].get_text())
        self.assertEqual(source.read_bytes(), original)

    def test_tampered_cached_installer_is_never_launched(self):
        self.window.ready_update = (self.release, self.installer)
        self.installer.write_bytes(b'tampered')
        with patch.object(QMessageBox, 'question', return_value=QMessageBox.StandardButton.Yes), \
             patch.object(QMessageBox, 'warning') as warning, patch('omnipdf.main.updates.launch_installer') as launch:
            self.window._offer_update()
            self.wait_for_worker()
            launch.assert_not_called()
            warning.assert_called_once()
        self.assertIsNone(self.window.ready_update)
        self.assertTrue(self.window.isVisible())

    def test_download_progress_can_be_cancelled_without_installing(self):
        self.window.ready_update = (self.release, None)
        started = threading.Event()
        def download(release, folder, *, cancelled, progress):
            progress(25, 100)
            started.set()
            while not cancelled():
                time.sleep(0.01)
            raise RuntimeError('cancelled')
        with patch('omnipdf.main.updates.download_update', side_effect=download), \
             patch.object(QMessageBox, 'question', return_value=QMessageBox.StandardButton.Yes), \
             patch('omnipdf.main.updates.launch_installer') as launch, patch.object(QMessageBox, 'warning') as warning:
            self.window._offer_update()
            self.assertTrue(started.wait(1))
            QTest.qWait(50)
            self.assertEqual(self.window.update_progress.value(), 25)
            QTest.mouseClick(self.window.update_progress.findChild(QPushButton), Qt.MouseButton.LeftButton)
            self.wait_for_worker()
            launch.assert_not_called()
            warning.assert_not_called()
        self.assertIsNone(self.window.update_progress)
        self.assertFalse(self.window._install_pending)
        self.assertTrue(self.window.isVisible())

    def test_downloaded_installer_is_verified_before_launch(self):
        self.window.ready_update = (self.release, None)
        self.installer.write_bytes(b'tampered')
        with patch('omnipdf.main.updates.download_update', return_value=self.installer), \
             patch.object(QMessageBox, 'question', return_value=QMessageBox.StandardButton.Yes), \
             patch('omnipdf.main.updates.launch_installer') as launch, patch.object(QMessageBox, 'warning') as warning:
            self.window._offer_update()
            self.wait_for_worker()
            launch.assert_not_called()
            warning.assert_called_once()
        self.assertIsNone(self.window.ready_update)
        self.assertTrue(self.window.isVisible())

    def test_windows_policy_block_explains_why_installer_could_not_start(self):
        self.window._verified_update = (self.release, self.installer)
        error = updates.UpdateError('Could not start the installer.')
        error.__cause__ = OSError(22, 'blocked', None, 4551)
        with patch('omnipdf.i18n.language', return_value='en'), \
             patch('omnipdf.main.updates.launch_installer', side_effect=error), \
             patch.object(QMessageBox, 'warning') as warning:
            self.window._launch_update()
        self.assertIn('Windows security policy', warning.call_args.args[2])
        self.assertTrue(self.window.isVisible())
        self.assertFalse(self.window._close_approved)

    def test_discarded_draft_does_not_block_update_after_verification(self):
        source = self.root / 'draft.pdf'
        with pymupdf.open() as document:
            document.new_page().insert_text((50, 80), 'Original text', fontsize=12)
            document.save(source)
        original = source.read_bytes()
        self.window.open_file(path=source)
        self.window.select_text(self.window.pdf.spans(0)[0])
        self.window.text.setPlainText('Draft text')
        self.window.ready_update = (self.release, self.installer)
        with patch.object(QMessageBox, 'question', side_effect=[QMessageBox.StandardButton.Yes, QMessageBox.StandardButton.Discard]), \
             patch('omnipdf.main.updates.launch_installer') as launch:
            self.window._offer_update()
            self.wait_for_worker()
            launch.assert_called_once()
        self.assertEqual(source.read_bytes(), original)

    def test_queued_ocr_is_deferred_during_update_prompt(self):
        source = self.root / 'source.pdf'
        with pymupdf.open() as document:
            document.new_page().insert_text((50, 80), 'Original text', fontsize=12)
            document.save(source)
        self.window.open_file(path=source)
        self.window.ready_update = (self.release, self.installer)
        def answer(*args):
            self.window._auto_ocr(self.window.pdf, self.window.page_index)
            return QMessageBox.StandardButton.No
        with patch.object(self.window, 'start_ocr') as ocr, patch.object(QMessageBox, 'question', side_effect=answer):
            self.window._offer_update()
            ocr.assert_not_called()
        self.assertFalse(self.window._close_approved)
        self.assertFalse(self.window._install_pending)

    def test_close_during_check_cancels_without_destroying_running_thread(self):
        gate = threading.Event()
        started = threading.Event()
        def check():
            started.set()
            gate.wait(2)
            return None
        with patch('omnipdf.main.updates.check_for_update', side_effect=check), patch.object(QMessageBox, 'information') as message:
            self.window.check_updates()
            try:
                self.assertTrue(started.wait(1))
                self.window.close()
                self.assertTrue(self.window._closing_after_update)
                self.assertTrue(self.window.update_worker.isInterruptionRequested())
            finally:
                gate.set()
                self.wait_for_worker()
            message.assert_not_called()
        self.assertFalse(self.window.isVisible())

    def test_cancel_close_during_verification_also_cancels_installation(self):
        source = self.root / 'draft.pdf'
        with pymupdf.open() as document:
            document.new_page().insert_text((50, 80), 'Original text', fontsize=12)
            document.save(source)
        self.window.open_file(path=source)
        self.window.select_text(self.window.pdf.spans(0)[0])
        self.window.text.setPlainText('Draft text')
        self.window.auto_apply_timer.stop()
        self.window.ready_update = (self.release, self.installer)
        gate = threading.Event()
        started = threading.Event()
        def verify(*args):
            started.set()
            gate.wait(2)
        answers = [QMessageBox.StandardButton.Yes, QMessageBox.StandardButton.Discard, QMessageBox.StandardButton.Cancel]
        with patch('omnipdf.main.updates.verify_installer', side_effect=verify), \
             patch('omnipdf.main.updates.launch_installer') as launch, patch.object(QMessageBox, 'question', side_effect=answers):
            self.window._offer_update()
            try:
                self.assertTrue(started.wait(1))
                self.window.close()
                self.assertTrue(self.window.isVisible())
            finally:
                gate.set()
                self.wait_for_worker()
            launch.assert_not_called()
        self.assertFalse(self.window._close_approved)
        self.assertTrue(self.window.pending)

    def test_automatic_update_setting_can_disable_background_requests(self):
        self.window.auto_update_action.setChecked(False)
        with patch('omnipdf.main.updates.check_for_update') as check:
            self.window.check_updates(automatic=True)
            check.assert_not_called()
        self.assertFalse(self.settings.value('updates/automatic', True, type=bool))


if __name__ == '__main__':
    unittest.main()
