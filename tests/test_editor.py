import os
from pathlib import Path
import tempfile
from threading import Event
import time
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import pymupdf
from PySide6.QtCore import QPoint, QPointF, Qt, QTimer
from PySide6.QtGui import QWheelEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox

from omnipdf.main import Editor, STYLE
from omnipdf.i18n import _


class EditorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setStyle('Fusion')
        cls.app.setStyleSheet(STYLE)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.source = self.root / 'invoice.pdf'
        with pymupdf.open() as doc:
            page = doc.new_page(width=500, height=700)
            page.insert_text((50, 80), 'INVOICE 12345', fontsize=20)
            page.insert_text((50, 140), 'TOTAL 120.00 EUR', fontsize=14)
            doc.new_page().insert_text((50, 80), 'Second page')
            doc.save(self.source)
            page = doc[0]
            page.get_pixmap(matrix=pymupdf.Matrix(2, 2)).save(self.root / 'scan.png')
        self.window = Editor()
        self.auto_ocr_patch = patch.object(self.window, '_auto_ocr')
        self.auto_ocr_patch.start()
        self.addCleanup(self.auto_ocr_patch.stop)
        self.window._error = lambda error: self.fail(str(error))
        self.window.show()
        self.app.processEvents()
        self.window.open_file(path=self.source)
        self.app.processEvents()

    def tearDown(self):
        self.window.auto_apply_timer.stop()
        self.window.view.raster_timer.stop()
        if self.window.ocr_worker:
            self.window.ocr_worker.wait(125000)
            self.app.processEvents()
        if self.window.pdf:
            self.window.pdf.close()
            self.window.pdf = None
        self.window.pending = False
        self.window.close()
        self.temp.cleanup()

    def test_editor_panel_slides_only_for_editable_text(self):
        window = self.window
        panel = window.editor_panel
        slide = window._editor_slide
        full_width = window.view.width()
        self.assertTrue(panel.isHidden())
        window.select_range(window.pdf.characters(0)[:3])
        self.assertTrue(panel.isHidden())
        window.cover_button.click()
        window.select_region((45, 55, 120, 95))
        self.assertTrue(panel.isHidden())
        window.cover_button.click()

        window.select_text(window.pdf.spans(0)[0])
        self.assertTrue(panel.isVisible())
        slide.setCurrentTime(slide.duration() // 2)
        midway = panel.width()
        self.assertGreater(midway, 0)
        self.assertLess(midway, 320)
        self.assertLess(window.view.width(), full_width)
        self.assertLessEqual(window.selection_preview.pixmap().width(), 320 - 48)
        window.cancel_button.click()
        self.assertEqual(panel.width(), midway)
        slide.setCurrentTime(0)
        self.assertTrue(panel.isHidden())
        self.assertEqual(window.view.width(), full_width)

        window.region_button.click()
        window.select_region((45, 55, 120, 95))
        slide.setCurrentTime(slide.duration())
        self.assertEqual(panel.width(), 320)
        self.assertTrue(window.text.hasFocus())
        QTest.keyClick(window.text, Qt.Key.Key_Escape)
        slide.setCurrentTime(0)
        self.assertTrue(panel.isHidden())
        self.assertTrue(window.view.hasFocus())

    def test_click_creates_text_box_ready_for_typing(self):
        window = self.window
        view = window.view
        window.region_button.click()
        point = view.mapFromScene(view.display_rect((200, 200, 200, 200)).topLeft())
        QTest.mouseClick(view.viewport(), Qt.MouseButton.LeftButton, pos=point)
        self.assertTrue(window.selection['insert_only'])
        rect = pymupdf.Rect(window.selection['bbox'])
        self.assertGreaterEqual(rect.width, 100)
        self.assertGreaterEqual(rect.height, 20)
        self.assertTrue(window.text.hasFocus())
        QTest.keyClicks(window.text, 'Hello')
        self.assertTrue(window.apply_change())
        self.assertIn('Hello', window.pdf.document[0].get_text())
        window.undo()
        window.cover_button.click()
        QTest.mouseClick(view.viewport(), Qt.MouseButton.LeftButton, pos=point)
        self.assertIsNone(window.selection)
        self.assertFalse(window.pdf.dirty)

    def test_click_text_box_fits_page_edges_including_rotated_page(self):
        window = self.window
        path = self.root / 'rotated-text-box.pdf'
        with pymupdf.open() as doc:
            page = doc.new_page(width=500, height=700)
            page.insert_text((50, 80), 'Text')
            page.set_rotation(90)
            doc.save(path)
        for source in (self.source, path):
            window.open_file(path=source)
            window.region_button.setChecked(True)
            view = window.view
            point = view.page_rect.bottomRight() - QPointF(5, 5)
            view.centerOn(point)
            self.app.processEvents()
            QTest.mouseClick(view.viewport(), Qt.MouseButton.LeftButton, pos=view.mapFromScene(point))
            box = pymupdf.Rect(window.selection['bbox'])
            page = window.pdf.document[0]
            self.assertTrue((page.rect * page.derotation_matrix).contains(box))
            self.assertGreaterEqual(box.get_area(), 100 * 20)
            self.assertTrue(window.text.hasFocus())
            QTest.keyClicks(window.text, 'Hi')
            self.assertTrue(window.apply_change())
            self.assertIn('Hi', window.pdf.document[0].get_text())
            window.undo()
            window.cancel_selection()

    def test_drag_still_sets_custom_text_box_size(self):
        window = self.window
        view = window.view
        window.region_button.click()
        start = view.mapFromScene(view.display_rect((100, 200, 100, 200)).topLeft())
        end = view.mapFromScene(view.display_rect((180, 240, 180, 240)).topLeft())
        QTest.mousePress(view.viewport(), Qt.MouseButton.LeftButton, pos=start)
        QTest.mouseMove(view.viewport(), end)
        QTest.mouseRelease(view.viewport(), Qt.MouseButton.LeftButton, pos=end)
        box = pymupdf.Rect(window.selection['bbox'])
        self.assertAlmostEqual(box.width, 80, delta=3)
        self.assertAlmostEqual(box.height, 40, delta=3)

    def test_standard_save_and_zoom_shortcuts(self):
        window = self.window
        view = window.view
        view.setFocus()
        with patch.object(QFileDialog, 'getSaveFileName', return_value=('', '')) as dialog:
            QTest.keyClick(view, Qt.Key.Key_S, Qt.KeyboardModifier.ControlModifier)
            self.assertEqual(dialog.call_count, 1)
            QTest.keyClick(view, Qt.Key.Key_S, Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier)
            self.assertEqual(dialog.call_count, 2)
        original = view.transform().m11()
        QTest.keyClick(view, Qt.Key.Key_Plus, Qt.KeyboardModifier.ControlModifier)
        self.assertGreater(view.transform().m11(), original)
        QTest.keyClick(view, Qt.Key.Key_Minus, Qt.KeyboardModifier.ControlModifier)
        self.assertAlmostEqual(view.transform().m11(), original)
        QTest.keyClick(view, Qt.Key.Key_Equal, Qt.KeyboardModifier.ControlModifier)
        self.assertGreater(view.transform().m11(), original)
        QTest.keyClick(view, Qt.Key.Key_0, Qt.KeyboardModifier.ControlModifier)
        self.assertTrue(view.fit_to_width)
        window.select_text(window.pdf.spans(0)[0])
        window.text.setFocus()
        with patch.object(QFileDialog, 'getSaveFileName', return_value=('', '')) as dialog:
            QTest.keyClick(window.text, Qt.Key.Key_S, Qt.KeyboardModifier.ControlModifier)
            self.assertEqual(dialog.call_count, 1)
        original_text = window.text.toPlainText()
        original = view.transform().m11()
        QTest.keyClick(window.text, Qt.Key.Key_Plus, Qt.KeyboardModifier.ControlModifier)
        self.assertGreater(view.transform().m11(), original)
        self.assertEqual(window.text.toPlainText(), original_text)
        window.cancel_selection()
        window.delete_page()
        window.delete_page()
        original = view.transform().m11()
        with patch.object(QFileDialog, 'getSaveFileName') as dialog:
            QTest.keyClick(window, Qt.Key.Key_S, Qt.KeyboardModifier.ControlModifier)
            QTest.keyClick(window, Qt.Key.Key_Plus, Qt.KeyboardModifier.ControlModifier)
            dialog.assert_not_called()
        self.assertEqual(view.transform().m11(), original)

    def test_signed_pdf_requires_confirmation_to_open_or_insert(self):
        window = self.window
        path = self.root / 'signed.pdf'
        with pymupdf.open() as doc:
            page = doc.new_page()
            page.insert_text((50, 80), 'Signed content')
            widget = pymupdf.Widget()
            widget.field_name = 'Signature'
            widget.field_type = pymupdf.PDF_WIDGET_TYPE_SIGNATURE
            widget.rect = pymupdf.Rect(50, 100, 200, 140)
            page.add_widget(widget)
            xref = doc.get_new_xref()
            doc.update_object(xref, '<< /Type /Sig /ByteRange [0 1 2 3] /Contents <00> >>')
            doc.xref_set_key(next(page.widgets()).xref, 'V', f'{xref} 0 R')
            doc.save(path)
        source_bytes = path.read_bytes()
        with patch.object(QMessageBox, 'question') as question:
            window.open_file(path=self.source)
            question.assert_not_called()
        original = window.pdf
        with patch.object(QMessageBox, 'question', return_value=QMessageBox.StandardButton.No) as question:
            window.open_file(path=path)
            self.assertIs(window.pdf, original)
            self.assertEqual(question.call_count, 1)
            self.assertEqual(question.call_args.args[-1], QMessageBox.StandardButton.No)
            window.insert_pdf(path=path)
            self.assertEqual(window.pdf.page_count, 2)
            self.assertEqual(question.call_count, 2)
        with patch.object(QMessageBox, 'question', return_value=QMessageBox.StandardButton.Yes) as question:
            window.insert_pdf(path=path)
            self.assertEqual(window.pdf.page_count, 3)
            self.assertEqual(question.call_count, 1)
            window.undo()
            window.open_file(path=path)
            self.assertEqual(window.pdf.source, path.resolve())
            self.assertIn('Signed content', window.pdf.document[0].get_text())
            self.assertEqual(question.call_count, 2)
        self.assertEqual(path.read_bytes(), source_bytes)
        output = self.root / 'signed-copy.pdf'
        window.pdf.save_copy(output)
        self.assertTrue(output.exists())
        self.assertEqual(path.read_bytes(), source_bytes)

    def test_select_edit_save_and_undo(self):
        window = self.window
        self.assertEqual(window.page_label.text(), '1 / 2')
        span = window.pdf.spans(0)[0]
        point = window.view.mapFromScene(window.view.display_rect(span['bbox']).center())
        QTest.mouseClick(window.view.viewport(), Qt.MouseButton.LeftButton, pos=point)
        self.assertEqual(window.text.toPlainText(), 'INVOICE 12345')
        window.text.setPlainText('INVOICE 12346')
        self.assertTrue(window.apply_change())
        self.assertIn('INVOICE 12346', window.pdf.document[0].get_text())
        output = self.root / 'edited.pdf'
        with patch.object(QFileDialog, 'getSaveFileName', return_value=(str(output), 'PDF')):
            self.assertTrue(window.save_copy())
        with pymupdf.open(output) as saved:
            self.assertIn('INVOICE 12346', saved[0].get_text())
            self.assertIn('Second page', saved[1].get_text())
        window.undo()
        self.assertIn('INVOICE 12345', window.pdf.document[0].get_text())
        with pymupdf.open(self.source) as original:
            self.assertNotIn('INVOICE 12346', original[0].get_text())

    def test_ocr_region_edit_and_page_change(self):
        window = self.window
        window.open_file(path=self.root / 'scan.png')
        lines = [{'text': text, 'bbox': (49, y, 210, y + 30), 'size': 12, 'color': 0}
                 for y, text in [(59, 'INVOICE 12345'), (120, 'TOTAL 120.00 EUR'), (180, 'Another line')]]
        window.pdf.page_versions[0].ocr = lines
        window.select_text(lines[0])
        window.text.setPlainText('INVOICE 54321')
        self.assertTrue(window.apply_change())
        self.assertIn('INVOICE 54321', window.pdf.document[0].get_text())
        self.assertEqual(window.pdf.page_versions[0].ocr, lines[1:])
        window.select_text(lines[1])
        window.text.setPlainText('TOTAL 42.00 EUR')
        self.assertTrue(window.apply_change())
        self.assertEqual(window.pdf.page_versions[0].ocr, lines[2:])
        window.undo()
        self.assertEqual(window.pdf.page_versions[0].ocr, lines[1:])
        self.assertEqual({area['text'] for area in window.view.areas},
                         {'INVOICE 54321', 'TOTAL 120.00 EUR', 'Another line'})
        window.redo()
        self.assertEqual(window.pdf.page_versions[0].ocr, lines[2:])
        window.undo()
        window.undo()
        self.assertEqual(window.pdf.document[0].get_text(), '')
        self.assertEqual(window.pdf.page_versions[0].ocr, lines)

    def test_unsaved_prompt_has_primary_save_and_close_keeps_the_draft(self):
        window = self.window
        window.select_text(window.pdf.spans(0)[0])
        window.text.setPlainText('Unfinished edit')
        window.auto_apply_timer.stop()
        visible = {}
        save_colors = []
        close_results = []

        def close_prompt():
            prompt = self.app.activeModalWidget()
            try:
                for button in prompt.buttons():
                    if button.isVisible():
                        visible[prompt.standardButton(button)] = button.objectName()
                save = prompt.button(QMessageBox.StandardButton.Save).grab().toImage()
                save_colors.append(save.pixelColor(save.width() // 2, round(4 * save.devicePixelRatio())).name())
            finally:
                close_results.append(prompt.close())

        QTimer.singleShot(0, close_prompt)
        self.assertFalse(window.close())
        buttons = QMessageBox.StandardButton
        self.assertEqual(set(visible), {buttons.Save, buttons.Discard})
        self.assertEqual(visible[buttons.Save], 'primary')
        self.assertEqual(len(save_colors), 1)
        self.assertIn(save_colors[0], ('#087f83', '#07676b'))
        self.assertEqual(close_results, [True])
        self.assertTrue(window.isVisible())
        self.assertTrue(window.pending)
        self.assertEqual(window.text.toPlainText(), 'Unfinished edit')

    def test_save_dialog_requires_confirmation_before_replacing_source(self):
        window = self.window
        window.select_text(window.pdf.spans(0)[0])
        window.text.setPlainText('INVOICE 54321')
        before = self.source.read_bytes()
        with patch.object(QFileDialog, 'getSaveFileName', return_value=(str(self.source), 'PDF (*.pdf)')):
            with patch.object(QMessageBox, 'question', return_value=QMessageBox.StandardButton.No):
                self.assertFalse(window.save_copy())
            self.assertEqual(self.source.read_bytes(), before)
            with patch.object(QMessageBox, 'question', return_value=QMessageBox.StandardButton.Yes):
                self.assertTrue(window.save_copy())
        with pymupdf.open(self.source) as saved:
            self.assertIn('INVOICE 54321', saved[0].get_text())

    def test_searchable_save_ocr_visits_unopened_scan_pages(self):
        window = self.window
        source = self.root / 'searchable-source.pdf'
        target = self.root / 'searchable.pdf'
        with pymupdf.open() as pdf:
            pdf.new_page(width=500, height=700).insert_text((50, 70), 'Introduction')
            page = pdf.new_page(width=500, height=700)
            page.insert_image(page.rect, filename=self.root / 'scan.png')
            pdf.save(source)
        window.open_file(path=source)
        self.auto_ocr_patch.stop()
        sample = [{'text': 'INVOICE 12345', 'bbox': (105, 160, 450, 205)}]
        with patch('omnipdf.main.recognize', return_value=sample) as recognize, \
                patch.object(QFileDialog, 'getSaveFileName', return_value=(str(target), 'PDF (*.pdf)')):
            self.assertTrue(window.save_copy(searchable=True))
            recognize.assert_called_once()
        self.assertEqual(window.page_index, 0)
        with pymupdf.open(target) as saved:
            self.assertIn('INVOICE 12345', saved[1].get_text())
            self.assertTrue(saved[1].get_images())

    def test_thumbnail_modifier_selection_and_batch_editing(self):
        window = self.window
        window.insert_pdf(path=self.source, append=True)
        thumbnails = window.thumbnails
        def click(row, modifier=Qt.KeyboardModifier.NoModifier):
            item = thumbnails.item(row)
            thumbnails.scrollToItem(item)
            QTest.mouseClick(thumbnails.viewport(), Qt.MouseButton.LeftButton, modifier,
                             thumbnails.visualItemRect(item).center())
            self.app.processEvents()
        click(0)
        click(2, Qt.KeyboardModifier.ControlModifier)
        self.assertEqual(thumbnails.selected_pages(), [0, 2])
        window.rotate_right_action.trigger()
        self.assertEqual([page.rotation for page in window.pdf.document], [90, 0, 90, 0])
        self.assertEqual(thumbnails.selected_pages(), [0, 2])
        click(0)
        click(2, Qt.KeyboardModifier.ShiftModifier)
        self.assertEqual(thumbnails.selected_pages(), [0, 1, 2])
        window.delete_page_action.trigger()
        self.assertEqual(window.pdf.page_count, 1)
        window.undo()
        self.assertEqual(window.pdf.page_count, 4)

    def test_navigation_flushes_pending_text_and_blocks_invalid_edit(self):
        window = self.window
        self.assertFalse(window.previous_button.isEnabled())
        self.assertTrue(window.next_button.isEnabled())
        window.select_text(window.pdf.spans(0)[0])
        window.text.setPlainText('EDITED 12345')
        window.next_button.click()
        self.assertEqual(window.page_index, 1)
        self.assertEqual(window.page_label.text(), '2 / 2')
        self.assertTrue(window.previous_button.isEnabled())
        self.assertFalse(window.next_button.isEnabled())
        self.assertIn('EDITED 12345', window.pdf.document[0].get_text())
        window.previous_button.click()
        window.select_text(window.pdf.spans(0)[0])
        window.text.setPlainText('X' * 2000)
        with patch.object(window, '_error'):
            window.next_button.click()
        self.assertEqual(window.page_index, 0)
        self.assertTrue(window.pending)
        self.assertFalse(window.edit_error.isHidden())

    def test_drag_partial_text_delete_and_undo(self):
        window = self.window
        chars = window.pdf.characters(0)
        first, last = (window.view.display_rect(chars[i]['bbox']) for i in (0, 2))
        start = window.view.mapFromScene(QPointF(first.left() + 1, first.center().y()))
        end = window.view.mapFromScene(QPointF(last.right() - 1, last.center().y()))
        viewport = window.view.viewport()
        QTest.mousePress(viewport, Qt.MouseButton.LeftButton, pos=start)
        QTest.mouseMove(viewport, end)
        QTest.mouseRelease(viewport, Qt.MouseButton.LeftButton, pos=end)
        self.assertEqual(window.text.toPlainText(), 'INV')
        self.assertTrue(window.text.isReadOnly())
        QTest.keyClick(window.view, Qt.Key.Key_Delete)
        self.assertNotIn('INV', window.pdf.document[0].get_text())
        self.assertIn('OICE 12345', window.pdf.document[0].get_text())
        window.undo()
        self.assertIn('INVOICE 12345', window.pdf.document[0].get_text())

    def test_delete_in_text_field_waits_for_auto_apply(self):
        window = self.window
        window.select_text(window.pdf.spans(0)[0])
        window.text.setFocus()
        cursor = window.text.textCursor()
        cursor.setPosition(0)
        window.text.setTextCursor(cursor)
        QTest.keyClick(window.text, Qt.Key.Key_Delete)
        self.assertEqual(window.text.toPlainText(), 'NVOICE 12345')
        self.assertIn('INVOICE 12345', window.pdf.document[0].get_text())
        QTest.qWait(750)
        self.assertIn('NVOICE 12345', window.pdf.document[0].get_text())

    def test_text_replacement_preserves_background_unless_white_is_selected(self):
        path = self.root / 'yellow.pdf'
        with pymupdf.open() as doc:
            page = doc.new_page(width=250, height=120)
            page.draw_rect(page.rect, color=None, fill=(1, 0.8, 0))
            page.insert_text((20, 60), '17 500,00', fontname='hebo', fontsize=22)
            doc.save(path)
        window = self.window
        window.open_file(path=path)
        before = window.pdf.render(0, scale=1).samples
        span = window.pdf.spans(0)[0]
        rect = pymupdf.Rect(span['bbox'])
        x, y = int(rect.x1 - 4), int(rect.y0 + rect.height * 0.4)
        self.assertFalse(window.white_background.isChecked())

        window.select_text(span)
        window.text.setPlainText('7')
        self.assertTrue(window.apply_change())
        self.assertEqual(window.pdf.document[0].get_text().strip(), '7')
        self.assertEqual(window.pdf.render(0, scale=1).pixel(x, y), (255, 204, 0))

        window.white_background.setChecked(True)
        self.assertTrue(window.apply_change())
        self.assertEqual(window.pdf.render(0, scale=1).pixel(x, y), (255, 255, 255))
        window.undo()
        self.assertEqual(window.pdf.render(0, scale=1).samples, before)

    def test_auto_apply_coalesces_and_keeps_last_valid_result(self):
        window = self.window
        window.select_text(window.pdf.spans(0)[0])
        window.text.setFocus()
        window.text.setPlainText('INVOICE 11111')
        QTest.qWait(750)
        self.assertIn('INVOICE 11111', window.pdf.document[0].get_text())
        self.assertTrue(window.text.hasFocus())
        window.text.setPlainText('INVOICE 22222')
        QTest.qWait(750)
        self.assertIn('INVOICE 22222', window.pdf.document[0].get_text())
        window.text.setPlainText('X' * 2000)
        QTest.qWait(750)
        self.assertTrue(window.pending)
        self.assertFalse(window.edit_error.isHidden())
        self.assertIn('INVOICE 22222', window.pdf.document[0].get_text())
        window.pending = False
        window.undo()
        self.assertIn('INVOICE 12345', window.pdf.document[0].get_text())
        self.assertFalse(window.pdf.can_undo)

    def test_cancel_invalid_draft_keeps_last_valid_preview(self):
        window = self.window
        window.select_text(window.pdf.spans(0)[0])
        window.text.setPlainText('INVOICE 33333')
        self.assertTrue(window.apply_change())
        window.text.setPlainText('X' * 2000)
        window.cancel_button.click()
        self.assertIsNone(window.selection)
        self.assertFalse(window.pending)
        self.assertIn('INVOICE 33333', window.pdf.document[0].get_text())
        window.undo()
        self.assertIn('INVOICE 12345', window.pdf.document[0].get_text())

    def test_delete_entire_selected_span_and_manual_area(self):
        window = self.window
        window.select_text(window.pdf.spans(0)[0])
        QTest.keyClick(window.view, Qt.Key.Key_Delete)
        self.assertNotIn('INVOICE 12345', window.pdf.document[0].get_text())
        self.assertIn('TOTAL 120.00 EUR', window.pdf.document[0].get_text())
        window.undo()
        window.region_button.click()
        self.assertTrue(window.view.region_mode)
        window.select_region((45, 50, 210, 90))
        QTest.keyClick(window.view, Qt.Key.Key_Delete)
        self.assertIn('INVOICE 12345', window.pdf.document[0].get_text())
        window.select_region((45, 50, 210, 90))
        window.text.setPlainText('New text')
        QTest.qWait(750)
        self.assertIn('New text', window.pdf.document[0].get_text())
        self.assertIn('INVOICE 12345', window.pdf.document[0].get_text())
        QTest.keyClick(window.view, Qt.Key.Key_Delete)
        self.assertNotIn('New text', window.pdf.document[0].get_text())
        self.assertIn('INVOICE 12345', window.pdf.document[0].get_text())

    def test_history_buttons_shortcuts_and_tool_icons(self):
        window = self.window
        def icon_lightness(button):
            image = button.grab().toImage()
            pixels = [image.pixelColor(x, y) for x in range(3, image.width() - 3) for y in range(3, image.height() - 3)]
            return min(color.lightness() for color in pixels if color.alpha() > 200)

        for button in (window.undo_button, window.redo_button, window.cover_button, window.region_button):
            self.assertEqual(button.text(), '')
            self.assertFalse(button.icon().isNull())
            self.assertTrue(button.toolTip())
        self.assertFalse(window.redo_button.isEnabled())
        self.assertGreater(icon_lightness(window.undo_button), 150)
        self.assertGreater(icon_lightness(window.redo_button), 150)
        window.select_text(window.pdf.spans(0)[0])
        window.text.setPlainText('Edited')
        self.assertTrue(window.apply_change())
        self.assertLess(icon_lightness(window.undo_button), 100)
        window.undo_button.click()
        self.assertGreater(icon_lightness(window.undo_button), 150)
        self.assertTrue(window.redo_button.isEnabled())
        self.assertLess(icon_lightness(window.redo_button), 100)
        window.redo_button.click()
        self.assertGreater(icon_lightness(window.redo_button), 150)
        self.assertIn('Edited', window.pdf.document[0].get_text())
        for modifier, key in ((Qt.KeyboardModifier.ControlModifier, Qt.Key.Key_Y),
                              (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier, Qt.Key.Key_Z)):
            window.undo()
            window.view.setFocus()
            QTest.keyClick(window.view, key, modifier)
            self.assertIn('Edited', window.pdf.document[0].get_text())

    def test_compact_font_picker_keeps_custom_size(self):
        window = self.window
        self.assertFalse(window.font_size.isEditable())
        self.assertLessEqual(window.font_size.width(), 80)
        self.assertLessEqual(window.font_size.height(), 28)
        span = dict(window.pdf.spans(0)[0], size=8.6)
        window.select_text(span)
        self.assertEqual(window.font_size.currentData(), 8.6)
        self.assertFalse(window.pending)
        window.font_size.setCurrentIndex(window.font_size.findData(12))
        window.text.setPlainText('Edited')
        self.assertTrue(window.apply_change())
        self.assertIn('Edited', window.pdf.document[0].get_text())

    def test_classic_toolbar_actions_and_zoom(self):
        window = self.window
        buttons = (window.open_button, window.save_button, window.print_button, window.undo_button,
                   window.redo_button, window.previous_button, window.next_button,
                   window.region_button, window.cover_button, window.minus_button,
                   window.plus_button, window.fit_button, window.pages_button)
        toolbar = window.file_label.parentWidget()
        self.assertEqual(toolbar.height(), 46)
        self.assertTrue(all(button.parentWidget() is toolbar for button in buttons))
        self.assertTrue(all(button.text() == '' for button in buttons))
        self.assertEqual(len({button.geometry().center().y() for button in buttons}), 1)
        original = self.source.read_bytes()
        with patch.object(QFileDialog, 'getOpenFileName', return_value=(str(self.source), 'PDF')):
            window.open_button.click()
        self.assertEqual(window.pdf.source, self.source)
        before = window.zoom_label.text()
        window.plus_button.click()
        self.assertNotEqual(before, window.zoom_label.text())
        output = self.root / 'toolbar-copy.pdf'
        with patch.object(QFileDialog, 'getSaveFileName', return_value=(str(output), 'PDF')):
            window.save_button.click()
        self.assertTrue(output.is_file())
        self.assertEqual(self.source.read_bytes(), original)

    def test_page_menu_operations_update_navigation_thumbnails_and_history(self):
        window = self.window
        original = self.source.read_bytes()
        window.resize(1600, 900)
        self.app.processEvents()
        window.select_text(window.pdf.spans(0)[0])
        window.text.setPlainText('EDITED 12345')
        window.duplicate_page_action.trigger()
        self.assertEqual(window.page_index, 1)
        self.assertEqual(window.page_label.text(), '2 / 3')
        self.assertEqual(window.thumbnails.count(), 4)
        self.assertIn('EDITED 12345', window.pdf.document[1].get_text())
        self.assertIsNone(window.selection)
        window.undo()
        self.assertEqual(window.pdf.page_count, 2)
        self.assertEqual(window.thumbnails.count(), 3)
        window.redo()
        self.assertEqual(window.pdf.page_count, 3)
        window.change_page(2)
        window.pdf.page_versions[2].ocr = [{'text': 'Stale'}]
        window.delete_page_action.trigger()
        self.assertEqual(window.page_index, 1)
        self.assertEqual(window.thumbnails.count(), 3)
        self.assertTrue(all(version.ocr is None for version in window.pdf.page_versions))
        window.delete_page_action.trigger()
        self.assertEqual(window.page_label.text(), '1 / 1')
        self.assertTrue(window.delete_page_action.isEnabled())
        with patch.object(QFileDialog, 'getOpenFileName', return_value=(str(self.source), 'PDF')):
            window.insert_pdf_action.trigger()
        self.assertEqual(window.page_label.text(), '2 / 3')
        self.assertEqual(window.thumbnails.count(), 4)
        self.assertTrue(window.delete_page_action.isEnabled())
        window.change_page(2)
        window.undo()
        self.assertEqual(window.page_index, 0)
        self.assertEqual(window.page_label.text(), '1 / 1')
        window.redo()
        self.assertEqual(window.pdf.page_count, 3)
        self.assertEqual(self.source.read_bytes(), original)

    def test_page_operations_block_invalid_pending_edit_and_cancel_insert(self):
        window = self.window
        window.select_text(window.pdf.spans(0)[0])
        window.text.setPlainText('X' * 2000)
        with patch.object(window, '_error'):
            window.duplicate_page_action.trigger()
            window.delete_page_action.trigger()
            window.insert_pdf(path=self.source)
            window.add_pdf_card.button.click()
        self.assertEqual(window.pdf.page_count, 2)
        self.assertFalse(window.pdf.can_undo)
        self.assertTrue(window.pending)
        window.clear_selection()
        with patch.object(QFileDialog, 'getOpenFileName', return_value=('', '')):
            window.insert_pdf_action.trigger()
        self.assertEqual(window.pdf.page_count, 2)
        self.assertFalse(window.pdf.dirty)

    def test_delete_last_page_add_pdf_and_history(self):
        window = self.window
        original = self.source.read_bytes()
        window.delete_page()
        window.delete_page()
        self.assertEqual(window.pdf.page_count, 0)
        self.assertEqual(window.page_label.text(), '0 / 0')
        self.assertEqual(window.thumbnails.count(), 1)
        self.assertIs(window.thumbnails.item(0), window.add_pdf_item)
        self.assertTrue(window.add_pdf_card.button.isEnabled())
        self.assertFalse(window.save_button.isEnabled())
        window.undo()
        self.assertEqual(window.pdf.page_count, 1)
        window.redo()
        self.assertEqual(window.pdf.page_count, 0)
        with patch.object(QFileDialog, 'getOpenFileName', return_value=(str(self.source), 'PDF')):
            window.add_pdf_card.button.click()
        self.assertEqual(window.pdf.page_count, 2)
        window.undo()
        self.assertEqual(window.pdf.page_count, 0)
        window.redo()
        self.assertEqual(window.pdf.page_count, 2)
        self.assertEqual(self.source.read_bytes(), original)

    def test_append_card_click_adds_pdf_after_last_page_and_supports_history(self):
        window = self.window
        original = self.source.read_bytes()
        self.assertEqual(window.thumbnails.row(window.add_pdf_item), 2)
        with patch.object(QFileDialog, 'getOpenFileName', return_value=('', '')):
            window.add_pdf_card.button.click()
        self.assertEqual(window.pdf.page_count, 2)
        self.assertFalse(window.pdf.dirty)
        window.select_text(window.pdf.spans(0)[0])
        window.text.setPlainText('EDITED 12345')
        with patch.object(QFileDialog, 'getOpenFileName', return_value=(str(self.source), 'PDF')):
            window.add_pdf_card.button.click()
        self.assertEqual(window.pdf.page_count, 4)
        self.assertEqual(window.page_index, 2)
        self.assertIn('EDITED 12345', window.pdf.document[0].get_text())
        self.assertIn('Second page', window.pdf.document[1].get_text())
        self.assertIn('INVOICE 12345', window.pdf.document[2].get_text())
        self.assertEqual(window.thumbnails.row(window.add_pdf_item), 4)
        window.undo()
        self.assertEqual(window.pdf.page_count, 2)
        self.assertEqual(window.thumbnails.row(window.add_pdf_item), 2)
        window.redo()
        self.assertEqual(window.pdf.page_count, 4)
        self.assertEqual(self.source.read_bytes(), original)

    def test_automatic_ocr_runs_once_for_image_and_not_native_text(self):
        window = self.window
        self.auto_ocr_patch.stop()
        with patch('omnipdf.main.recognize', return_value=[{'text': 'Scan text', 'bbox': (100, 120, 300, 170)}]) as recognize:
            window.render_page()
            self.app.processEvents()
            recognize.assert_not_called()
            window.open_file(path=self.root / 'scan.png')
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                self.app.processEvents()
                if recognize.called and window.ocr_worker is None:
                    break
                QTest.qWait(20)
            self.assertEqual(recognize.call_count, 1)
            self.assertEqual(window.pdf.page_versions[0].ocr[0]['text'], 'Scan text')
            self.assertTrue(window.open_button.isEnabled())
            window.render_page()
            self.app.processEvents()
            self.assertEqual(recognize.call_count, 1)

    def test_thumbnail_drop_and_undo_keep_page_content_and_versions(self):
        window = self.window
        thumbnails = window.thumbnails
        versions = window.pdf.page_versions.copy()
        icons = dict(window._thumbnail_icons)
        thumbnails.setCurrentRow(0)
        drop = Mock()
        drop.source.return_value = thumbnails
        drop.position.return_value = QPointF(thumbnails.visualItemRect(thumbnails.item(1)).bottomLeft()) + QPointF(15, -5)
        with patch('omnipdf.main.QDrag') as drag:
            drag.return_value.exec.side_effect = lambda _: thumbnails.dropEvent(drop)
            thumbnails.startDrag(Qt.DropAction.MoveAction)
            drag.return_value.setMimeData.assert_called_once()
        drop.accept.assert_called_once()
        self.assertEqual(window.pdf.page_versions, versions[::-1])
        self.assertIn('INVOICE', window.pdf.document[1].get_text())
        self.assertEqual(window._thumbnail_icons, icons)
        self.assertIs(thumbnails.item(2), window.add_pdf_item)
        self.assertEqual(window.page_index, 1)
        overlay = thumbnails._reorder_overlay
        animation = thumbnails._reorder_animation
        self.assertTrue(overlay.isVisible())
        first_frame = overlay.pixmap().toImage()
        animation.setCurrentTime(animation.duration() // 3)
        self.assertNotEqual(overlay.pixmap().toImage(), first_frame)
        animation.setCurrentTime(animation.duration())
        self.assertFalse(overlay.isVisible())
        window.undo()
        self.assertEqual(window.pdf.page_versions, versions)
        self.assertEqual(window.page_index, 0)
        self.assertTrue(overlay.isVisible())
        window.redo()
        self.assertEqual(window.pdf.page_versions, versions[::-1])
        self.assertTrue(overlay.isVisible())
        output = self.root / 'reordered.pdf'
        window.pdf.save_copy(output)
        with pymupdf.open(output) as saved:
            self.assertIn('INVOICE', saved[1].get_text())

    def test_thumbnail_gap_and_its_adjacent_halves_share_one_drop_boundary(self):
        window = self.window
        window.pdf.insert_pdf(self.source, 1)
        window.render_page()
        thumbnails = window.thumbnails
        self.app.processEvents()
        self.assertFalse(thumbnails.showDropIndicator())
        above = thumbnails.visualItemRect(thumbnails.item(1))
        below = thumbnails.visualItemRect(thumbnails.item(2))
        gap_y = (above.bottom() + below.top()) // 2
        for y in (above.bottom() - 4, gap_y, below.top() + 4):
            with self.subTest(y=y):
                self.assertEqual(thumbnails._drop_boundary(y), 2)
        x = above.center().x()
        thumbnails._set_drop_y(gap_y)
        image = thumbnails.viewport().grab().toImage().scaled(thumbnails.viewport().size())
        marker_y = [y for y in range(above.bottom() + 1, below.top())
                    if image.pixelColor(x, y).name() == '#087f83']
        self.assertIn(len(marker_y), (2, 3))
        self.assertEqual(marker_y[-1] - marker_y[0], len(marker_y) - 1)

        thumbnails.setCurrentRow(0)
        drop = Mock()
        drop.source.return_value = thumbnails
        drop.position.return_value = QPointF(x, gap_y)
        before = window.pdf.page_versions.copy()
        with patch('omnipdf.main.QDrag') as drag:
            drag.return_value.exec.side_effect = lambda _: thumbnails.dropEvent(drop)
            thumbnails.startDrag(Qt.DropAction.MoveAction)
        self.assertEqual(window.pdf.page_versions, [before[1], before[0], *before[2:]])
        self.assertIsNone(thumbnails._drop_y)

    def test_only_edited_page_is_rendered_again(self):
        window = self.window
        path = self.root / 'many-pages.pdf'
        with pymupdf.open() as pdf:
            for index in range(20):
                pdf.new_page(width=400, height=400).insert_text((50, 70), f'Page {index + 1}')
            pdf.save(path)
        window.open_file(path=path)
        self.app.processEvents()
        unchanged = window.thumbnails.item(1).icon().cacheKey()
        window.select_text(window.pdf.spans(0)[0])
        window.text.setPlainText('Page A')
        with patch.object(window.pdf, 'render', wraps=window.pdf.render) as render:
            self.assertTrue(window.apply_change())
        self.assertGreater(render.call_count, 0)
        self.assertEqual({call.args[0] for call in render.call_args_list}, {0})
        self.assertEqual(window.thumbnails.item(1).icon().cacheKey(), unchanged)

    def test_find_popup_follows_top_right_without_resizing_document(self):
        window = self.window
        document_bounds = window.splitter.geometry()
        QTest.keyClick(window, Qt.Key.Key_F, Qt.KeyboardModifier.ControlModifier)
        self.app.processEvents()
        popup = window.find_bar
        self.assertTrue(popup.isVisible())
        self.assertTrue(window.find_input.hasFocus())
        self.assertEqual(window.splitter.geometry(), document_bounds)

        for width in (1100, 950):
            window.resize(width, window.height())
            self.app.processEvents()
            parent = window.centralWidget()
            self.assertTrue(parent.rect().contains(popup.geometry()))
            self.assertLess(popup.width(), parent.width() // 2)
            self.assertLess(parent.rect().right() - popup.geometry().right(), 24)
            self.assertLess(popup.y() - window.splitter.y(), 24)

        QTest.keyClick(window.find_input, Qt.Key.Key_Escape)
        self.assertTrue(popup.isHidden())

    def test_find_searches_unvisited_scans_without_blocking_navigation(self):
        window = self.window
        path = self.root / 'search.pdf'
        with pymupdf.open() as pdf:
            pdf.new_page(width=500, height=700).insert_text((50, 70), 'Invoice document')
            page = pdf.new_page(width=500, height=700)
            page.insert_image(page.rect, filename=self.root / 'scan.png')
            pdf.new_page(width=500, height=700).insert_text((50, 70), 'Third page')
            pdf.save(path)
        self.auto_ocr_patch.stop()
        release = Event()

        def recognize(path, *, cancelled):
            release.wait(10)
            return [{'text': 'INVOICE scan', 'bbox': (90, 90, 345, 135)}]

        with patch('omnipdf.main.recognize', side_effect=recognize):
            try:
                window.open_file(path=path)
                QTest.keyClick(window, Qt.Key.Key_F, Qt.KeyboardModifier.ControlModifier)
                self.assertTrue(window.find_bar.isVisible())
                window.find_input.setText('invoice')
                deadline = time.monotonic() + 5
                while window.ocr_worker is None and time.monotonic() < deadline:
                    QTest.qWait(20)
                self.assertIsNotNone(window.ocr_worker)
                self.assertIs(window.ocr_worker.version, window.pdf.page_versions[1])
                self.assertTrue(window.next_button.isEnabled())
                window.change_page(2)
                self.assertEqual(window.page_index, 2)
                release.set()
                while window.ocr_worker and time.monotonic() < deadline:
                    QTest.qWait(20)
                self.assertIsNone(window.ocr_worker)
                self.assertEqual([index for index, _ in window._find_hits()], [0, 1])
                self.assertEqual(window.page_index, 2)
                self.assertEqual(window.pdf.page_versions[1].ocr[0]['text'], 'INVOICE scan')
                window.find_next.click()
                self.assertEqual(window.page_index, 1)
                self.assertTrue(window.view.find_items)
                QTest.keyClick(window.find_input, Qt.Key.Key_Escape)
                self.assertTrue(window.find_bar.isHidden())
                self.assertFalse(window.view.find_items)
            finally:
                release.set()

    def test_find_grouping_and_failed_offscreen_scan(self):
        window = self.window
        path = self.root / 'wrapped.pdf'
        with pymupdf.open() as pdf:
            page = pdf.new_page(width=500, height=700)
            page.insert_text((30, 70), 'Find this\nphrase here', fontsize=14)
            page = pdf.new_page(width=500, height=700)
            page.insert_image(page.rect, filename=self.root / 'scan.png')
            pdf.save(path)
        self.auto_ocr_patch.stop()
        with patch('omnipdf.main.recognize', side_effect=RuntimeError('OCR language pack unavailable')) as recognize:
            window.open_file(path=path)
            window._open_find()
            window.find_input.setText('this phrase')
            deadline = time.monotonic() + 5
            while (not recognize.called or window.ocr_worker) and time.monotonic() < deadline:
                QTest.qWait(20)
            recognize.assert_called_once()
            self.assertEqual(len(window._find_hits()), 1)
            self.assertEqual(len(window._find_hit[1]), 2)
            self.assertEqual(len(window.view.find_items), 2)
            incomplete = _('Niektoré strany sa nepodarilo prehľadať')
            self.assertEqual(window.find_status.text(), f'1 / 1 · {incomplete}')
            window.find_next.click()
            self.assertEqual(window.find_status.text(), f'1 / 1 · {incomplete}')
            window.find_input.setText('no native results')
            QTest.qWait(180)
            self.assertEqual(window.find_status.text(), incomplete)
            self.assertFalse(window.find_next.isEnabled())
            recognize.assert_called_once()

    def test_zoom_refresh_preserves_selection_and_transform(self):
        window = self.window
        window.select_text(window.pdf.spans(0)[0])
        highlight = window.view.selection_item
        scale = window.view.raster_scale
        window.view.zoom(1.25)
        window.view.zoom(1.25)
        transform = window.view.transform()
        QTest.qWait(250)
        self.assertGreater(window.view.raster_scale, scale)
        self.assertEqual(window.view.transform(), transform)
        self.assertIs(window.view.selection_item, highlight)
        self.assertEqual(window.view.pixmap_item.transformationMode(), Qt.TransformationMode.SmoothTransformation)

    def test_continuous_wheel_scroll_syncs_navigation_and_edits_second_page(self):
        window = self.window
        view = window.view
        zoom = view.transform().m22()
        view.verticalScrollBar().setValue(round((view.page_rects[1].top() - 160) * zoom))
        self.app.processEvents()
        before = view.verticalScrollBar().value()
        position = view.viewport().rect().center()
        wheel = QWheelEvent(QPointF(position), QPointF(view.viewport().mapToGlobal(position)),
                            QPoint(), QPoint(0, -120), Qt.MouseButton.NoButton,
                            Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase, False)
        self.app.sendEvent(view.viewport(), wheel)
        self.app.processEvents()
        self.assertGreater(view.verticalScrollBar().value(), before)
        self.assertEqual(window.page_index, 1)
        self.assertEqual(window.page_label.text(), '2 / 2')
        self.assertEqual(window.thumbnails.currentRow(), 1)
        self.assertFalse(view.page_items[1].pixmap().isNull())
        span = window.pdf.spans(1)[0]
        point = view.mapFromScene(view.display_rect(span['bbox']).center())
        QTest.mouseClick(view.viewport(), Qt.MouseButton.LeftButton, pos=point)
        self.assertEqual(window.text.toPlainText(), 'Second page')
        window.text.setPlainText('Changed page')
        scroll = view.verticalScrollBar().value()
        self.assertTrue(window.apply_change())
        self.assertIn('Changed page', window.pdf.document[1].get_text())
        self.assertIn('INVOICE 12345', window.pdf.document[0].get_text())
        self.assertEqual(view.verticalScrollBar().value(), scroll)
        window.undo()
        self.assertIn('Second page', window.pdf.document[1].get_text())
        self.assertEqual(view.verticalScrollBar().value(), scroll)
        window.redo()
        self.assertIn('Changed page', window.pdf.document[1].get_text())
        window.previous_button.click()
        self.assertEqual(window.page_index, 0)
        self.assertIn(0, view.visible_page_indices())

    def test_continuous_click_on_adjacent_page_and_invalid_pending_edit(self):
        window = self.window
        view = window.view
        # Most of page 1 remains visible, with the first text of page 2 below it.
        value = round((view.page_rects[1].top() + 140) * view.transform().m22() - view.viewport().height())
        view.verticalScrollBar().setValue(value)
        self.app.processEvents()
        self.assertEqual(window.page_index, 0)
        self.assertIn(1, view.visible_page_indices())
        span = window.pdf.spans(1)[0]
        rect = pymupdf.Rect(span['bbox'])
        offset = view.page_rects[1].topLeft()
        point = view.mapFromScene(offset.x() + (rect.x0 + rect.x1) / 2, offset.y() + (rect.y0 + rect.y1) / 2)
        self.assertTrue(view.viewport().rect().contains(point))
        scroll = view.verticalScrollBar().value()
        QTest.mouseClick(view.viewport(), Qt.MouseButton.LeftButton, pos=point)
        self.assertEqual(window.page_index, 1)
        self.assertEqual(window.text.toPlainText(), 'Second page')
        self.assertEqual(view.verticalScrollBar().value(), scroll)
        window.text.setPlainText('X' * 2000)
        self.assertFalse(window.apply_change(automatic=True))
        view.scroll_to_page(0)
        self.app.processEvents()
        self.assertEqual(window.page_index, 0)
        self.assertEqual(window.selection['page_index'], 1)
        self.assertTrue(window.pending)
        self.assertFalse(window.edit_error.isHidden())
        self.assertIn('Second page', window.pdf.document[1].get_text())

    def test_continuous_raster_cache_evicts_distant_pages(self):
        window = self.window
        path = self.root / 'long.pdf'
        with pymupdf.open() as doc:
            for index in range(12):
                doc.new_page(width=500, height=700).insert_text((50, 80), f'Page {index + 1}')
            doc.save(path)
        original = path.read_bytes()
        window.open_file(path=path)
        self.app.processEvents()
        view = window.view
        self.assertEqual(len(view.page_rects), 12)
        self.assertLessEqual(len(view.page_scales), 3)
        view.scroll_to_page(11)
        self.app.processEvents()
        self.assertEqual(window.page_index, 11)
        self.assertEqual(window.page_label.text(), '12 / 12')
        self.assertLessEqual(len(view.page_scales), 3)
        self.assertTrue(view.page_items[0].pixmap().isNull())
        self.assertFalse(view.page_items[11].pixmap().isNull())
        self.assertEqual(path.read_bytes(), original)

    def test_selected_text_survives_scroll_and_delete_targets_original_page(self):
        window = self.window
        window.select_text(window.pdf.spans(0)[0])
        self.app.processEvents()
        window.update_selection_preview()
        preview = window.selection_preview.pixmap().toImage()
        window.view.scroll_to_page(1)
        self.app.processEvents()
        self.assertEqual(window.page_index, 1)
        self.assertEqual(window.selection['page_index'], 0)
        self.assertEqual(window.text.toPlainText(), 'INVOICE 12345')
        self.assertEqual(window.selection_preview.pixmap().toImage(), preview)
        self.assertTrue(window.view.page_rects[0].contains(window.view.selection_item.boundingRect().center()))
        QTest.keyClick(window.view, Qt.Key.Key_Delete)
        self.assertNotIn('INVOICE 12345', window.pdf.document[0].get_text())
        self.assertIn('Second page', window.pdf.document[1].get_text())
        window.undo()
        self.assertIn('INVOICE 12345', window.pdf.document[0].get_text())

    def test_selected_characters_and_pending_edits_survive_scroll(self):
        window = self.window
        window.select_range(window.pdf.characters(0)[:3])
        window.view.scroll_to_page(1)
        self.app.processEvents()
        self.assertEqual(window.text.toPlainText(), 'INV')
        self.assertEqual(window.selection['page_index'], 0)
        QTest.keyClick(window.view, Qt.Key.Key_Delete)
        self.assertIn('OICE 12345', window.pdf.document[0].get_text())
        self.assertIn('Second page', window.pdf.document[1].get_text())
        window.undo()
        window.change_page(0)
        window.select_text(window.pdf.spans(0)[0])
        window.text.setPlainText('EDITED 12345')
        window.view.scroll_to_page(1)
        self.app.processEvents()
        self.assertTrue(window.pending)
        self.assertTrue(window.apply_change())
        self.assertEqual(window.page_index, 1)
        self.assertIn('EDITED 12345', window.pdf.document[0].get_text())
        self.assertIn('Second page', window.pdf.document[1].get_text())
        QTest.keyClick(window.view, Qt.Key.Key_Escape)
        self.assertIsNone(window.selection)

    def test_rotated_selection_stays_on_source_page_after_scrolling(self):
        window = self.window
        path = self.root / 'rotated-selection.pdf'
        with pymupdf.open() as doc:
            page = doc.new_page(width=700, height=500)
            page.insert_text((40, 80), 'Original', fontsize=12)
            page.set_rotation(90)
            doc.new_page(width=500, height=900).insert_text((40, 80), 'Next page', fontsize=12)
            doc.save(path)
        original = path.read_bytes()
        window.open_file(path=path)
        window.select_text(window.pdf.spans(0)[0])
        before = window.view.selection_item.boundingRect()
        window.view.scroll_to_page(1)
        self.app.processEvents()
        self.assertEqual(window.page_index, 1)
        self.assertEqual(window.view.selection_item.boundingRect(), before)
        window.text.setPlainText('Changed')
        self.assertTrue(window.apply_change())
        self.assertIn('Changed', window.pdf.document[0].get_text())
        self.assertIn('Next page', window.pdf.document[1].get_text())
        self.assertEqual(path.read_bytes(), original)

    def test_cover_region_removes_text_and_undo_restores_it(self):
        window = self.window
        window.cover_button.click()
        rect = pymupdf.Rect(window.pdf.spans(0)[0]['bbox']) + (-2, -2, 2, 2)
        display = window.view.display_rect(rect)
        start = window.view.mapFromScene(display.topLeft())
        end = window.view.mapFromScene(display.bottomRight())
        viewport = window.view.viewport()
        QTest.mousePress(viewport, Qt.MouseButton.LeftButton, pos=start)
        QTest.mouseMove(viewport, end)
        QTest.mouseRelease(viewport, Qt.MouseButton.LeftButton, pos=end)
        self.assertIn('INVOICE 12345', window.pdf.document[0].get_text())
        self.assertEqual(window.selection['kind'], 'area')
        QTest.keyClick(window.view, Qt.Key.Key_Delete)
        self.assertNotIn('INVOICE 12345', window.pdf.document[0].get_text())
        pixmap = window.pdf.document[0].get_pixmap()
        self.assertEqual(pixmap.pixel(int(rect.x0 + 2), int(rect.y0 + 2)), (255, 255, 255))
        window.undo()
        self.assertIn('INVOICE 12345', window.pdf.document[0].get_text())

    def test_area_move_resize_and_undo(self):
        window = self.window
        view = window.view
        window.cover_button.click()
        bbox = tuple(pymupdf.Rect(window.pdf.spans(0)[0]['bbox']) + (-2, -2, 2, 2))
        window.select_region(bbox)
        rect = view.display_rect(bbox)
        start = view.mapFromScene(rect.center())
        end = start + QPoint(60, 50)
        QTest.mousePress(view.viewport(), Qt.MouseButton.LeftButton, pos=start)
        QTest.mouseMove(view.viewport(), end)
        QTest.mouseRelease(view.viewport(), Qt.MouseButton.LeftButton, pos=end)
        moved = pymupdf.Rect(window.selection['bbox'])
        self.assertGreater(moved.x0, bbox[0] + 10)
        self.assertNotIn('INVOICE', window.pdf.document[0].get_text())
        image_rect = window.pdf.document[0].get_image_rects(window.pdf.document[0].get_images()[0][0])[0]
        self.assertAlmostEqual(image_rect.x0, moved.x0, delta=1)
        rect = view.display_rect(moved)
        start = view.mapFromScene(rect.bottomRight())
        end = start + QPoint(30, 25)
        QTest.mousePress(view.viewport(), Qt.MouseButton.LeftButton, pos=start)
        QTest.mouseMove(view.viewport(), end)
        QTest.mouseRelease(view.viewport(), Qt.MouseButton.LeftButton, pos=end)
        self.assertGreater(pymupdf.Rect(window.selection['bbox']).width, moved.width)
        window.undo()
        window.undo()
        self.assertAlmostEqual(window.pdf.spans(0)[0]['bbox'][0], 50, delta=1)

    def test_area_cursor_matches_move_and_resize_handles(self):
        window = self.window
        view = window.view
        window.cover_button.click()
        window.select_region((60, 160, 240, 280))
        for zoom in (1, 1.5):
            if zoom != 1:
                view.zoom(zoom)
            rect = view.display_rect(window.selection['bbox'])
            cases = [
                (rect.center(), Qt.CursorShape.SizeAllCursor),
                (rect.topLeft(), Qt.CursorShape.SizeFDiagCursor),
                (rect.bottomRight(), Qt.CursorShape.SizeFDiagCursor),
                (rect.topRight(), Qt.CursorShape.SizeBDiagCursor),
                (rect.bottomLeft(), Qt.CursorShape.SizeBDiagCursor),
                (QPointF(rect.left(), rect.center().y()), Qt.CursorShape.SizeHorCursor),
                (QPointF(rect.right(), rect.center().y()), Qt.CursorShape.SizeHorCursor),
                (QPointF(rect.center().x(), rect.top()), Qt.CursorShape.SizeVerCursor),
                (QPointF(rect.center().x(), rect.bottom()), Qt.CursorShape.SizeVerCursor),
                (rect.topLeft() - QPointF(20, 20), Qt.CursorShape.CrossCursor),
            ]
            for point, expected in cases:
                QTest.mouseMove(view.viewport(), view.mapFromScene(point))
                self.assertEqual(view.viewport().cursor().shape(), expected)
        point = view.mapFromScene(rect.topLeft())
        QTest.mouseMove(view.viewport(), point)
        QTest.mousePress(view.viewport(), Qt.MouseButton.LeftButton, pos=point)
        QTest.mouseMove(view.viewport(), point + QPoint(12, 12))
        self.assertEqual(view.viewport().cursor().shape(), Qt.CursorShape.SizeFDiagCursor)
        QTest.mouseRelease(view.viewport(), Qt.MouseButton.LeftButton, pos=point + QPoint(12, 12))
        window.cancel_selection()
        self.assertEqual(view.viewport().cursor().shape(), Qt.CursorShape.ArrowCursor)

    def test_area_move_back_preserves_covered_content_and_shows_drag_preview(self):
        window = self.window
        view = window.view
        window.cover_button.click()
        source = pymupdf.Rect(window.pdf.spans(0)[0]['bbox']) + (-2, -2, 2, 2)
        destination = source + (0, 60, 0, 60)
        ocr = {'text': 'TOTAL', 'bbox': (50, 125, 165, 145)}
        window.pdf.page_versions[0].ocr = [ocr]
        window.select_region(tuple(source))
        original = window.pdf.document[0].get_pixmap().samples
        start = view.mapFromScene(view.display_rect(source).center())
        end = view.mapFromScene(view.display_rect(destination).center())
        QTest.mousePress(view.viewport(), Qt.MouseButton.LeftButton, pos=start)
        QTest.mouseMove(view.viewport(), end)
        self.assertIsNotNone(view.area_preview)
        self.assertFalse(view.area_preview.pixmap().isNull())
        self.assertAlmostEqual(view.area_preview.sceneBoundingRect().center().y(),
                               view.display_rect(destination).center().y(), delta=2)
        QTest.mouseRelease(view.viewport(), Qt.MouseButton.LeftButton, pos=end)
        self.assertIsNone(view.area_preview)
        window.transform_area(tuple(source))
        self.assertIn('TOTAL 120.00 EUR', window.pdf.document[0].get_text())
        self.assertEqual(window.pdf.document[0].get_pixmap().samples, original)
        self.assertEqual(window.pdf.page_versions[0].ocr, [ocr])
        window.undo()
        self.assertIn('TOTAL 120.00 EUR', window.pdf.document[0].get_text())

    def test_delete_moved_area_preserves_content_under_destination(self):
        window = self.window
        window.cover_button.click()
        source = pymupdf.Rect(window.pdf.spans(0)[0]['bbox']) + (-2, -2, 2, 2)
        window.select_region(tuple(source))
        window.transform_area(tuple(source + (0, 60, 0, 60)))
        window.delete_selection()
        text = window.pdf.document[0].get_text()
        self.assertIn('TOTAL 120.00 EUR', text)
        self.assertNotIn('INVOICE', text)

    def test_failed_area_move_restores_previous_document(self):
        window = self.window
        window.cover_button.click()
        source = pymupdf.Rect(window.pdf.spans(0)[0]['bbox']) + (-2, -2, 2, 2)
        window.select_region(tuple(source))
        window.transform_area(tuple(source + (0, 60, 0, 60)))
        with pymupdf.open('pdf', window.pdf.document.tobytes()) as snapshot:
            before = snapshot[0].get_pixmap().samples
        selected = window.selection['bbox']
        with patch.object(window.pdf, 'cover_region', side_effect=ValueError('failed')):
            with patch.object(window, '_error') as error:
                window.transform_area(tuple(source + (0, 100, 0, 100)))
        error.assert_called_once()
        self.assertEqual(window.pdf.document[0].get_pixmap().samples, before)
        self.assertEqual(window.selection['bbox'], selected)
        window.undo()
        self.assertIn('INVOICE 12345', window.pdf.document[0].get_text())

    def test_area_move_on_rotated_page(self):
        path = self.root / 'rotated-area.pdf'
        with pymupdf.open() as doc:
            page = doc.new_page(width=500, height=700)
            page.insert_text((50, 80), 'Rotated text', fontsize=20)
            page.set_rotation(90)
            doc.save(path)
        window = self.window
        window.open_file(path=path)
        window.cover_button.click()
        bbox = tuple(pymupdf.Rect(window.pdf.spans(0)[0]['bbox']) + (-2, -2, 2, 2))
        window.select_region(bbox)
        view = window.view
        start = view.mapFromScene(view.display_rect(bbox).center())
        end = start + QPoint(40, 40)
        QTest.mousePress(view.viewport(), Qt.MouseButton.LeftButton, pos=start)
        QTest.mouseMove(view.viewport(), end)
        QTest.mouseRelease(view.viewport(), Qt.MouseButton.LeftButton, pos=end)
        self.assertNotEqual(pymupdf.Rect(window.selection['bbox']), pymupdf.Rect(bbox))
        self.assertNotIn('Rotated text', window.pdf.document[0].get_text())
        self.assertTrue(window.pdf.document[0].get_images())
        window.undo()
        self.assertAlmostEqual(window.pdf.spans(0)[0]['bbox'][0], 50, delta=1)

    @unittest.skipUnless(os.getenv('RUN_WINDOWS_OCR') == '1', 'Opt-in integration with installed Windows OCR languages')
    def test_real_ocr_then_replace(self):
        window = self.window
        self.auto_ocr_patch.stop()
        scan = self.root / 'yellow-scan.png'
        with pymupdf.open(self.source) as source:
            page = source[0]
            page.draw_rect(page.rect, color=None, fill=(1, 0.8, 0), overlay=False)
            page.get_pixmap(matrix=pymupdf.Matrix(2, 2)).save(scan)
        window.open_file(path=scan)
        self.app.processEvents()
        deadline = time.monotonic() + 45
        while window.ocr_worker and time.monotonic() < deadline:
            self.app.processEvents()
            QTest.qWait(50)
        self.assertIsNone(window.ocr_worker)
        area = next(s for s in window.pdf.page_versions[0].ocr if '12345' in s['text'])
        window.select_text(area)
        window.text.setPlainText('INVOICE 54321')
        self.assertTrue(window.apply_change())
        self.assertIn('INVOICE 54321', window.pdf.document[0].get_text())
        rect = pymupdf.Rect(area['bbox'])
        edited_pixels = window.pdf.render(0, scale=2, clip=rect).samples
        self.assertIn(b'\xff\xcc\x00', edited_pixels)
        self.assertNotIn(b'\xff\xff\xff', edited_pixels)


if __name__ == '__main__':
    unittest.main()
