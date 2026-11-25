import os
import tempfile
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication, QFileDialog, QLineEdit, QMessageBox

from main import Editor, apply_light_theme


class LightThemeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.palette = self.app.palette()
        self.stylesheet = self.app.styleSheet()
        self.scheme = self.app.styleHints().colorScheme()
        self.dialog_attribute = self.app.testAttribute(Qt.ApplicationAttribute.AA_DontUseNativeDialogs)
        self.app.setStyleSheet('')
        self.app.styleHints().setColorScheme(Qt.ColorScheme.Dark)
        dark = QPalette()
        for role in (QPalette.ColorRole.Window, QPalette.ColorRole.Base, QPalette.ColorRole.Button,
                     QPalette.ColorRole.ToolTipBase):
            dark.setColor(role, QColor('#222222'))
        self.app.setPalette(dark)
        apply_light_theme(self.app)
        self.window = Editor()

    def tearDown(self):
        self.window.close()
        self.app.styleHints().setColorScheme(self.scheme)
        self.app.setPalette(self.palette)
        self.app.setStyleSheet(self.stylesheet)
        self.app.setAttribute(Qt.ApplicationAttribute.AA_DontUseNativeDialogs, self.dialog_attribute)

    def assert_light(self, widget):
        for role in (QPalette.ColorRole.Window, QPalette.ColorRole.Base, QPalette.ColorRole.Button,
                     QPalette.ColorRole.ToolTipBase):
            self.assertGreater(widget.palette().color(role).lightness(), 230, (type(widget).__name__, role))
        for role in (QPalette.ColorRole.Text, QPalette.ColorRole.WindowText, QPalette.ColorRole.ButtonText):
            self.assertLess(widget.palette().color(QPalette.ColorGroup.Active, role).lightness(), 100)

    def test_light_palette_reaches_popups_inputs_and_dialogs_after_dark_startup(self):
        self.assertNotEqual(self.app.styleHints().colorScheme(), Qt.ColorScheme.Dark)
        self.assertTrue(self.app.testAttribute(Qt.ApplicationAttribute.AA_DontUseNativeDialogs))
        with tempfile.TemporaryDirectory() as directory:
            file_dialog = QFileDialog(self.window, 'Otvoriť PDF', directory, 'PDF (*.pdf)')
            message = QMessageBox(QMessageBox.Icon.Warning, 'Upozornenie', 'Skúšobná správa',
                                 QMessageBox.StandardButton.Ok, self.window)
            context_menu = self.window.text.createStandardContextMenu()
            for widget in (self.window, self.window.pages_menu, context_menu, self.window.font_size,
                           self.window.font_size.view(), self.window.white_background,
                           self.window.text, QLineEdit(self.window), file_dialog, message):
                self.assert_light(widget)
            self.assertEqual(file_dialog.palette().color(QPalette.ColorRole.Highlight).name(), '#dcefee')
            context_menu.close()
            file_dialog.close()
            message.close()

    def test_actual_menu_background_and_selected_row_are_light(self):
        menu = self.window.pages_menu
        self.window.duplicate_page_action.setEnabled(True)
        menu.popup(QPoint(20, 20))
        menu.setActiveAction(self.window.duplicate_page_action)
        self.app.processEvents()
        image = menu.grab().toImage()
        self.assertGreater(image.pixelColor(image.width() - 8, image.height() - 8).lightness(), 235)
        row = menu.actionGeometry(self.window.duplicate_page_action)
        selected = image.pixelColor(row.left() + 2, row.center().y())
        self.assertGreater(selected.lightness(), 190)
        self.assertGreater(selected.green(), selected.red())
        menu.close()


if __name__ == '__main__':
    unittest.main()
