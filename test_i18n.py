import os
from pathlib import Path
from string import Formatter
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtWidgets import QApplication, QMessageBox
import pymupdf

from i18n import EN, configure_language, language
from main import Editor


class LanguageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_system_languages_and_standard_buttons(self):
        for language, open_label, save_label, print_label in [('sk', 'Otvoriť súbor (Ctrl+O)', 'Uložiť', 'Tlačiť (Ctrl+P)'),
                                                               ('en', 'Open file (Ctrl+O)', 'Save', 'Print (Ctrl+P)')]:
            with self.subTest(language=language), patch('i18n.language', return_value=language):
                configure_language(self.app)
                window = Editor()
                box = QMessageBox()
                box.setStandardButtons(QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Cancel)
                self.assertEqual(window.open_button.toolTip(), open_label)
                self.assertEqual(window.print_button.toolTip(), print_label)
                self.assertEqual(box.button(QMessageBox.StandardButton.Save).text().replace('&', ''), save_label)
                window.close()
        configure_language(self.app)

    def test_first_system_ui_language_and_fallback(self):
        with patch('i18n.QLocale') as locale:
            for languages, expected in [(['sk-SK', 'en-US'], 'sk'), (['en-US', 'sk-SK'], 'en'), (['de-DE'], 'en'), ([], 'en')]:
                locale.system.return_value.uiLanguages.return_value = languages
                self.assertEqual(language(), expected)

    def test_translation_placeholders_match(self):
        formatter = Formatter()
        for source, translation in EN.items():
            with self.subTest(source=source):
                self.assertEqual({name for _, name, _, _ in formatter.parse(source) if name},
                                 {name for _, name, _, _ in formatter.parse(translation) if name})

    def test_document_status_and_errors_in_both_languages(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'test.pdf'
            with pymupdf.open() as pdf:
                pdf.new_page().insert_text((50, 80), 'Original text')
                pdf.save(path)
            for code, page_label, message, ocr in [('sk', 'Strana 1 z 1', 'Dokument nemá žiadnu stranu.', 'Automatické rozpoznanie'),
                                                    ('en', 'Page 1 of 1', 'The document has no pages.', 'Automatic text recognition')]:
                with self.subTest(language=code), patch('i18n.language', return_value=code):
                    window = Editor()
                    with patch.object(window, '_auto_ocr'):
                        window.show()
                        window.open_file(path=path)
                        self.assertEqual(window.page_label.accessibleName(), page_label)
                        with patch.object(QMessageBox, 'warning') as warning:
                            window._error(ValueError('The document has no pages.'))
                            self.assertEqual(warning.call_args.args[2], message)
                        window._ocr_failed('details')
                        self.assertIn(ocr, window.statusBar().currentMessage())
                        window.pdf.close()
                        window.pdf = None
                        window.close()

    def test_signed_document_confirmation_in_both_languages(self):
        for code, title, disclaimer in [('sk', 'Digitálne podpísané PDF', 'neoveruje jeho platnosť'),
                                         ('en', 'Digitally signed PDF', 'does not verify its validity')]:
            with self.subTest(language=code), patch('i18n.language', return_value=code):
                window = Editor()
                with patch.object(QMessageBox, 'question', return_value=QMessageBox.StandardButton.No) as question:
                    self.assertFalse(window._confirm_signed_pdf())
                    self.assertEqual(question.call_args.args[1], title)
                    self.assertIn(disclaimer, question.call_args.args[2])
                    self.assertEqual(question.call_args.args[-1], QMessageBox.StandardButton.No)
                window.close()


if __name__ == '__main__':
    unittest.main()
