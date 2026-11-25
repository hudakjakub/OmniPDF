"""Local Windows editor for PDFs and scanned documents."""
import math
import argparse
import json
import os
import sys
import tempfile
from bisect import bisect_left
from collections import deque
from pathlib import Path

import pymupdf
from PySide6.QtCore import QEasingCurve, QEvent, QItemSelectionModel, QPoint, QPointF, QPropertyAnimation, QRect, QRectF, QSettings, QSize, Qt, QThread, QTimer, QUrl, QVariantAnimation, Signal
from PySide6.QtGui import QAction, QColor, QDesktopServices, QDrag, QIcon, QImage, QKeySequence, QPainter, QPainterPath, QPalette, QPen, QPixmap, QTransform
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QFileDialog, QFrame,
    QGraphicsDropShadowEffect, QGraphicsScene, QGraphicsView, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QMainWindow,
    QMenu, QMessageBox, QProgressDialog, QPushButton, QScrollArea, QSizePolicy, QSplitter, QStyledItemDelegate,
    QStyle, QStyleOptionToolButton, QStyleOptionViewItem, QStylePainter, QTextEdit, QToolButton, QVBoxLayout, QWidget,
)
from PySide6.QtWidgets import QListWidget, QListWidgetItem

from pdf_document import PdfDocument, SignedPdfError
from windows_ocr import recognize
from app_info import APP_NAME, VERSION, PROJECT_URL
from i18n import _, configure_language
import updates
from window_chrome import configure_title_bar, set_app_id, create_app_mutex, release_app_mutex


APP_ICON = Path(__file__).with_name('assets') / 'omni.svg'


ERRORS = {
    'The original PDF changed on disk. Save a copy or reopen the file.': 'Pôvodné PDF sa na disku zmenilo. Uložte kópiu alebo súbor znova otvorte.',
    'Some recognized text could not be saved as searchable text.': 'Niektorý rozpoznaný text sa nepodarilo uložiť ako prehľadávateľný text.',
    'Encrypted PDFs are not supported.': 'PDF je chránené heslom. Otvorte odomknutú kópiu.',
    'The PDF could not be recovered.': 'PDF je poškodené. Skúste ho znova exportovať.',
    'This PDF does not permit editing.': 'Toto PDF má zakázané úpravy.',
    'Digitally signed PDFs are not supported.': 'Digitálne podpísané PDF nie je možné upraviť bez zneplatnenia podpisu.',
    'PDFs with signature fields are not supported.': 'Toto PDF obsahuje digitálny podpis.',
    'Only PDF, JPG and PNG files are supported.': 'Vyberte PDF alebo obrázok vo formáte JPG či PNG.',
    'The document has no pages.': 'Dokument nemá žiadnu stranu.',
    'Select a valid page.': 'Vyberte platnú stranu.',
    'Only PDF files can be inserted.': 'Na vloženie ďalších strán vyberte PDF súbor.',
    'Select a valid area inside the page.': 'Označte oblasť vnútri strany.',
    'Enter valid text and font size.': 'Zadajte platný text a veľkosť písma.',
    'Text at this angle cannot be edited directly.': 'Text v tomto uhle nemožno upraviť priamo.',
    'Some characters in the replacement text cannot be rendered.': 'Niektoré znaky v náhradnom texte nemožno zobraziť.',
    'The original text could not be removed safely.': 'Pôvodný text sa nepodarilo bezpečne odstrániť.',
    'The selected area overlaps neighboring text.': 'Okraj oblasti zasahuje do susedného textu. Označte celý text alebo zmenšite oblasť.',
    'The replacement text does not fit in the selected area.': 'Text sa nezmestí do oblasti. Zmenšite písmo alebo označte väčšiu oblasť.',
    'The original file cannot be overwritten.': 'Originál sa neprepisuje. Vyberte nový názov PDF.',
    'Choose a new output file; existing files cannot be overwritten.': 'Tento súbor už existuje. Vyberte nový názov PDF.',
    'The saved PDF could not be verified.': 'Uložené PDF sa nepodarilo overiť.',
    'The selected text is no longer available.': 'Výber už nie je aktuálny. Označte text znova.',
    'Select text to delete.': 'Najprv označte text, ktorý chcete vymazať.',
    'There is no previous edit to update.': 'Predchádzajúcu úpravu už nemožno aktualizovať.',
}


class PageView(QGraphicsView):
    selected = Signal(object)
    region = Signal(object)
    text_range = Signal(object)
    delete_requested = Signal()
    selection_cleared = Signal()
    render_requested = Signal()
    zoom_changed = Signal(float)
    page_requested = Signal(int)
    area_changed = Signal(object)

    def __init__(self):
        super().__init__()
        self.setScene(QGraphicsScene(self))
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        self.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
        self.setBackgroundBrush(QColor('#e4e9ed'))
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAccessibleName(_('Strana PDF. Ťahaním označte text, klávesom Delete ho vymažte.'))
        self.areas = []
        self.characters = []
        self.page_rect = QRectF()
        self.rotation = pymupdf.Matrix(1, 1)
        self.derotation = pymupdf.Matrix(1, 1)
        self.selection_item = None
        self.find_items = []
        self.area_bbox = None
        self.area_page = None
        self.area_drag = None
        self.area_preview = None
        self.start_point = None
        self.region_mode = False
        self.click_to_insert = False
        self.anchor_cursor = None
        self.dragging_text = False
        self.pressed_span = None
        self.pixmap_item = None
        self.raster_scale = 0
        self.page_rects = []
        self.page_items = []
        self.page_scales = {}
        self.active_index = None
        self.fit_to_width = False
        self.raster_timer = QTimer(self)
        self.raster_timer.setSingleShot(True)
        self.raster_timer.setInterval(120)
        self.raster_timer.timeout.connect(self.render_requested.emit)

    def reset_document(self):
        self.scene().clear()
        self.find_items.clear()
        self.area_preview = None
        self.page_rects = []
        self.page_items = []
        self.page_scales = {}
        self.active_index = None
        self.page_rect = QRectF()
        self.pixmap_item = None
        self.raster_scale = 0
        self.selection_item = None
        self.start_point = None
        self.areas = []
        self.characters = []
        self.scene().setSceneRect(QRectF())

    def configure_pages(self, sizes):
        sizes = [(float(w), float(h)) for w, h in sizes]
        if sizes == [(r.width(), r.height()) for r in self.page_rects]:
            return False
        self.reset_document()
        if not sizes:
            return True
        width = max(w for w, _ in sizes)
        y = 24
        for w, h in sizes:
            rect = QRectF(24 + (width - w) / 2, y, w, h)
            self.page_rects.append(rect)
            background = self.scene().addRect(rect, QPen(Qt.PenStyle.NoPen), QColor('white'))
            background.setZValue(-1)
            item = self.scene().addPixmap(QPixmap())
            item.setTransformationMode(Qt.TransformationMode.SmoothTransformation)
            item.setPos(rect.topLeft())
            self.page_items.append(item)
            y += h + 24
        self.scene().setSceneRect(QRectF(0, 0, width + 48, y))
        return True

    def set_page(self, pixmap, scale, page, areas, characters=(), fit=False, page_index=None):
        if page_index is None:
            self.reset_document()
            self.pixmap_item = self.scene().addPixmap(QPixmap())
            self.pixmap_item.setTransformationMode(Qt.TransformationMode.SmoothTransformation)
            self.page_rect = QRectF(0, 0, page.rect.width, page.rect.height)
            self.scene().setSceneRect(self.page_rect.adjusted(-24, -24, 24, 24))
        else:
            self.highlight(None)
            self.start_point = None
            self.active_index = page_index
            self.page_rect = self.page_rects[page_index]
            self.pixmap_item = self.page_items[page_index]
            self.raster_scale = self.page_scales.get(page_index, 0)
        self.rotation = page.rotation_matrix
        self.derotation = page.derotation_matrix
        self.areas = areas
        self.characters = characters
        if pixmap is not None:
            self.update_raster(pixmap, scale)
        if fit:
            self.fit_width()

    def update_raster(self, pixmap, scale):
        if self.active_index is not None:
            self.update_page_raster(self.active_index, pixmap, scale)
            return
        image = QImage(pixmap.samples, pixmap.width, pixmap.height, pixmap.stride, QImage.Format.Format_RGB888).copy()
        self.pixmap_item.setPixmap(QPixmap.fromImage(image))
        self.pixmap_item.setScale(1 / scale)
        self.raster_scale = scale

    def update_page_raster(self, index, pixmap, scale):
        image = QImage(pixmap.samples, pixmap.width, pixmap.height, pixmap.stride, QImage.Format.Format_RGB888).copy()
        self.page_items[index].setPixmap(QPixmap.fromImage(image))
        self.page_items[index].setScale(1 / scale)
        self.page_scales[index] = scale
        if index == self.active_index:
            self.raster_scale = scale

    def evict_page_raster(self, index):
        self.page_items[index].setPixmap(QPixmap())
        self.page_scales.pop(index, None)
        if index == self.active_index:
            self.raster_scale = 0

    def visible_page_indices(self):
        visible = self.mapToScene(self.viewport().rect()).boundingRect()
        return [i for i, rect in enumerate(self.page_rects) if rect.intersects(visible)]

    def current_visible_page(self):
        if not self.page_rects:
            return None
        visible = self.mapToScene(self.viewport().rect()).boundingRect()
        def score(rect):
            overlap = rect.intersected(visible)
            area = overlap.width() * overlap.height()
            distance = max(rect.top() - visible.bottom(), visible.top() - rect.bottom(), 0)
            return (area, -distance)
        return max(range(len(self.page_rects)), key=lambda i: score(self.page_rects[i]))

    def scroll_to_page(self, index):
        self.verticalScrollBar().setValue(round((self.page_rects[index].top() - 24) * self.transform().m22()))

    def display_rect(self, bbox):
        rect = pymupdf.Rect(bbox) * self.rotation
        return QRectF(rect.x0 + self.page_rect.x(), rect.y0 + self.page_rect.y(), rect.width, rect.height)

    def show_find_hits(self, hits):
        for item in self.find_items:
            self.scene().removeItem(item)
        self.find_items.clear()
        for rect, current in hits:
            pen = QPen(QColor('#a66008'), 1) if current else QPen(Qt.PenStyle.NoPen)
            fill = QColor(255, 183, 43, 135) if current else QColor(255, 210, 77, 95)
            item = self.scene().addRect(rect, pen, fill)
            item.setZValue(0.5)
            self.find_items.append(item)

    def highlight(self, bbox, transform=None):
        self.highlight_boxes([bbox] if bbox is not None else [], transform)

    def highlight_boxes(self, boxes, transform=None):
        if self.selection_item is not None:
            self.scene().removeItem(self.selection_item)
            self.selection_item = None
        if boxes:
            path = QPainterPath()
            for bbox in boxes:
                rect = pymupdf.Rect(bbox)
                display = (transform.mapRect(QRectF(rect.x0, rect.y0, rect.width, rect.height))
                           if transform is not None else self.display_rect(bbox))
                path.addRect(display)
            pen = QPen(QColor('#087f83'), 1.4)
            pen.setCosmetic(True)
            self.selection_item = self.scene().addPath(path, pen, QColor(8, 127, 131, 40))
            self.selection_item.setZValue(1)

    def highlight_characters(self, characters, transform=None):
        boxes = {}
        for char in characters:
            rect = pymupdf.Rect(char['bbox'])
            boxes[char['line']] = boxes[char['line']] | rect if char['line'] in boxes else rect
        self.highlight_boxes(list(boxes.values()), transform)

    def fit_width(self):
        if self.page_rect.width():
            self.fit_to_width = True
            scene_rect = self.scene().sceneRect()
            scrollbar = self.verticalScrollBar().sizeHint().width()
            zoom = min(5, max(0.02, (self.viewport().width() - scrollbar - 2) / scene_rect.width()))
            self.resetTransform()
            self.scale(zoom, zoom)
            self.zoom_changed.emit(self.transform().m11())
            self.raster_timer.start()

    def zoom(self, factor):
        current = self.transform().m11()
        if 0.02 <= current * factor <= 5:
            self.fit_to_width = False
            self.scale(factor, factor)
            self.zoom_changed.emit(self.transform().m11())
            self.raster_timer.start()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.page_rect.width():
            if self.fit_to_width:
                self.fit_width()
            else:
                self.raster_timer.start()

    def event(self, event):
        if event.type() == QEvent.Type.DevicePixelRatioChange and hasattr(self, 'raster_timer'):
            self.raster_timer.start()
        return super().event(event)

    def _text_cursor(self, point, inside=False):
        point = pymupdf.Point(point.x() - self.page_rect.x(), point.y() - self.page_rect.y()) * self.derotation
        candidates = []
        for index, char in enumerate(self.characters):
            rect = pymupdf.Rect(char['bbox'])
            if rect.is_empty or (inside and not rect.contains(point)):
                continue
            dx = max(rect.x0 - point.x, 0, point.x - rect.x1)
            dy = max(rect.y0 - point.y, 0, point.y - rect.y1)
            candidates.append((dx * dx + dy * dy, abs((rect.y0 + rect.y1) / 2 - point.y), index))
        if not candidates:
            return None
        index = min(candidates)[2]
        rect = pymupdf.Rect(self.characters[index]['bbox'])
        return index + int(point.x > (rect.x0 + rect.x1) / 2)

    def _drag_characters(self, point):
        point.setX(min(max(point.x(), self.page_rect.left()), self.page_rect.right()))
        point.setY(min(max(point.y(), self.page_rect.top()), self.page_rect.bottom()))
        cursor = self._text_cursor(point)
        if cursor is None or self.anchor_cursor is None:
            return []
        first, last = sorted((self.anchor_cursor, cursor))
        return self.characters[first:last]

    def set_region_mode(self, enabled, *, click_to_insert=False):
        self.region_mode = enabled
        self.click_to_insert = click_to_insert
        self.setCursor(Qt.CursorShape.CrossCursor if enabled else Qt.CursorShape.ArrowCursor)

    def _area_hit(self, point):
        if not self.region_mode or self.area_bbox is None or self.area_page != self.active_index or not self.page_rect.contains(point):
            return None
        rect = self.display_rect(self.area_bbox)
        margin = 6 / self.transform().m11()
        if not rect.adjusted(-margin, -margin, margin, margin).contains(point):
            return None
        x = -1 if abs(point.x() - rect.left()) <= margin else 1 if abs(point.x() - rect.right()) <= margin else 0
        y = -1 if abs(point.y() - rect.top()) <= margin else 1 if abs(point.y() - rect.bottom()) <= margin else 0
        return x, y

    def _update_area_cursor(self, point):
        hit = self._area_hit(point)
        if hit is None:
            cursor = Qt.CursorShape.CrossCursor
        elif hit == (0, 0):
            cursor = Qt.CursorShape.SizeAllCursor
        elif not hit[0]:
            cursor = Qt.CursorShape.SizeVerCursor
        elif not hit[1]:
            cursor = Qt.CursorShape.SizeHorCursor
        else:
            cursor = Qt.CursorShape.SizeFDiagCursor if hit[0] == hit[1] else Qt.CursorShape.SizeBDiagCursor
        self.setCursor(cursor)

    def highlight_area(self, bbox, transform=None):
        self.area_bbox = bbox
        self.highlight(None)
        if bbox is None:
            return
        box = pymupdf.Rect(bbox)
        rect = transform.mapRect(QRectF(box.x0, box.y0, box.width, box.height)) if transform is not None else self.display_rect(bbox)
        path = QPainterPath()
        path.addRect(rect)
        size = 6 / self.transform().m11()
        for x in (rect.left(), rect.center().x(), rect.right()):
            for y in (rect.top(), rect.center().y(), rect.bottom()):
                if x != rect.center().x() or y != rect.center().y():
                    path.addRect(QRectF(x - size / 2, y - size / 2, size, size))
        pen = QPen(QColor('#202020'), 1, Qt.PenStyle.DashLine)
        pen.setCosmetic(True)
        self.selection_item = self.scene().addPath(path, pen)
        self.selection_item.setZValue(2)

    def mousePressEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton or not self.page_rect.width():
            return super().mousePressEvent(event)
        point = self.mapToScene(event.position().toPoint())
        if self.page_rects:
            clicked = next((i for i, rect in enumerate(self.page_rects) if rect.contains(point)), None)
            if clicked is None:
                return
            if clicked != self.active_index:
                self.page_requested.emit(clicked)
                if clicked != self.active_index:
                    return
        if not self.page_rect.contains(point):
            return
        self.setFocus()
        hit = self._area_hit(point)
        if hit is not None:
            rect = self.display_rect(self.area_bbox)
            x, y = hit
            self.area_drag = (QRectF(rect), x, y)
            pixels = QRectF((rect.left() - self.page_rect.left()) * self.raster_scale,
                                (rect.top() - self.page_rect.top()) * self.raster_scale,
                                rect.width() * self.raster_scale, rect.height() * self.raster_scale).toAlignedRect()
            pixmap = self.pixmap_item.pixmap().copy(pixels)
            if not pixmap.isNull():
                self.area_preview = self.scene().addPixmap(pixmap)
                self.area_preview.setTransformationMode(Qt.TransformationMode.SmoothTransformation)
                self.area_preview.setZValue(1.5)
                self.area_preview.setPos(rect.topLeft())
                self.area_preview.setTransform(QTransform.fromScale(rect.width() / pixmap.width(), rect.height() / pixmap.height()))
            self.start_point = point
            return
        self.start_point = point
        self.anchor_cursor = None
        self.dragging_text = False
        self.pressed_span = None
        if self.region_mode:
            return
        else:
            matches = [s for s in self.areas if self.display_rect(s['bbox']).contains(point)]
            if matches:
                self.pressed_span = min(matches, key=lambda s: pymupdf.Rect(s['bbox']).get_area())
            self.anchor_cursor = self._text_cursor(point, inside=True)

    def mouseMoveEvent(self, event):
        if self.start_point is not None and self.region_mode:
            point = self.mapToScene(event.position().toPoint())
            if self.area_drag:
                rect, x, y = self.area_drag
                rect = QRectF(rect)
                delta = point - self.start_point
                if not x and not y:
                    rect.translate(delta)
                    rect.moveLeft(min(max(rect.left(), self.page_rect.left()), self.page_rect.right() - rect.width()))
                    rect.moveTop(min(max(rect.top(), self.page_rect.top()), self.page_rect.bottom() - rect.height()))
                else:
                    if x == -1: rect.setLeft(min(rect.right() - 6, max(self.page_rect.left(), rect.left() + delta.x())))
                    if x == 1: rect.setRight(max(rect.left() + 6, min(self.page_rect.right(), rect.right() + delta.x())))
                    if y == -1: rect.setTop(min(rect.bottom() - 6, max(self.page_rect.top(), rect.top() + delta.y())))
                    if y == 1: rect.setBottom(max(rect.top() + 6, min(self.page_rect.bottom(), rect.bottom() + delta.y())))
            else:
                rect = QRectF(self.start_point, point).normalized().intersected(self.page_rect)
            bbox = pymupdf.Rect(rect.x() - self.page_rect.x(), rect.y() - self.page_rect.y(), rect.right() - self.page_rect.x(), rect.bottom() - self.page_rect.y()) * self.derotation
            if self.area_drag:
                if self.area_preview is not None:
                    pixmap = self.area_preview.pixmap()
                    self.area_preview.setPos(rect.topLeft())
                    self.area_preview.setTransform(QTransform.fromScale(rect.width() / pixmap.width(), rect.height() / pixmap.height()))
                self.highlight_area(tuple(bbox))
            else: self.highlight(tuple(bbox))
        elif self.start_point is not None and self.anchor_cursor is not None:
            point = self.mapToScene(event.position().toPoint())
            if self.dragging_text or (point - self.start_point).manhattanLength() * self.transform().m11() >= QApplication.startDragDistance():
                self.dragging_text = True
                self.highlight_characters(self._drag_characters(point))
        elif not self.region_mode:
            point = self.mapToScene(event.position().toPoint())
            over_text = any(self.display_rect(s['bbox']).contains(point) for s in self.areas)
            self.setCursor(Qt.CursorShape.IBeamCursor if over_text else Qt.CursorShape.ArrowCursor)
        elif self.start_point is None:
            self._update_area_cursor(self.mapToScene(event.position().toPoint()))
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.start_point is not None:
            point = self.mapToScene(event.position().toPoint())
            if self.area_drag:
                self.area_drag = None
                self.start_point = None
                if self.area_preview is not None:
                    self.scene().removeItem(self.area_preview)
                    self.area_preview = None
                self.area_changed.emit(self.area_bbox)
                self._update_area_cursor(point)
                return
            if not self.region_mode:
                if self.dragging_text:
                    self.text_range.emit(self._drag_characters(point))
                elif self.pressed_span is not None:
                    self.selected.emit(self.pressed_span)
                else:
                    self.selection_cleared.emit()
                self.start_point = None
                return
            rect = QRectF(self.start_point, point).normalized().intersected(self.page_rect)
            if self.click_to_insert and (point - self.start_point).manhattanLength() * self.transform().m11() < QApplication.startDragDistance():
                width = min(160, self.page_rect.width())
                height = min(24, self.page_rect.height())
                x = min(max(self.start_point.x(), self.page_rect.left()), self.page_rect.right() - width)
                y = min(max(self.start_point.y(), self.page_rect.top()), self.page_rect.bottom() - height)
                rect = QRectF(x, y, width, height)
            self.start_point = None
            if rect.width() >= 6 and rect.height() >= 6:
                bbox = pymupdf.Rect(rect.x() - self.page_rect.x(), rect.y() - self.page_rect.y(), rect.right() - self.page_rect.x(), rect.bottom() - self.page_rect.y()) * self.derotation
                self.region.emit(tuple(bbox))
                self._update_area_cursor(point)
            else:
                self.selection_cleared.emit()
            return
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Delete and event.modifiers() == Qt.KeyboardModifier.NoModifier:
            self.delete_requested.emit()
            event.accept()
            return
        super().keyPressEvent(event)


class OcrWorker(QThread):
    completed = Signal(object)
    failed = Signal(str)

    def __init__(self, document, index, parent):
        super().__init__(parent)
        self.document = document
        self.version = document.page_versions[index]
        page = document.document[index]
        self.scale = min(3.0, 3500 / max(page.rect.width, page.rect.height))
        self.rotation = page.rotation
        self.derotation = page.derotation_matrix
        self.bounds = page.rect * self.derotation
        self.native = [pymupdf.Rect(s['bbox']) for s in document.spans(index)]
        self.temp = tempfile.TemporaryDirectory(prefix='omnipdf-ocr-')
        self.image_path = Path(self.temp.name) / 'page.png'
        try:
            document.render(index, self.scale).save(self.image_path)
        except Exception:
            self.temp.cleanup()
            raise

    def run(self):
        try:
            lines = recognize(self.image_path, cancelled=self.isInterruptionRequested)
            if not self.isInterruptionRequested():
                self.completed.emit(lines)
        except Exception as exc:
            if not self.isInterruptionRequested():
                self.failed.emit(str(exc))


class UpdateWorker(QThread):
    completed = Signal(object)
    failed = Signal(str)
    downloading = Signal()

    def __init__(self, parent, verification=None):
        super().__init__(parent)
        self.verification = verification

    def run(self):
        try:
            if self.verification is not None:
                release, installer = self.verification
                updates.verify_installer(installer, release)
                if not self.isInterruptionRequested():
                    self.completed.emit(self.verification)
                return
            release = updates.check_for_update()
            if self.isInterruptionRequested():
                return
            installer = None
            if release is not None and getattr(sys, 'frozen', False):
                self.downloading.emit()
                cache = Path(os.environ.get('LOCALAPPDATA', str(Path.home() / 'AppData' / 'Local'))) / 'OmniPDF' / 'updates'
                installer = updates.download_update(release, cache, cancelled=self.isInterruptionRequested)
            if not self.isInterruptionRequested():
                self.completed.emit((release, installer))
        except Exception as exc:
            if not self.isInterruptionRequested():
                self.failed.emit(str(exc))


class ThumbnailDelegate(QStyledItemDelegate):
    def updateEditorGeometry(self, editor, option, index):
        editor.setGeometry(option.rect)

    def paint(self, painter, option, index):
        option = QStyleOptionViewItem(option)
        super().initStyleOption(option, index)
        pixmap = option.icon.pixmap(option.decorationSize, QIcon.Mode.Normal)
        text = option.text
        option.icon, option.text = QIcon(), ''
        option.state &= ~QStyle.StateFlag.State_HasFocus
        painter.save()
        option.widget.style().drawControl(QStyle.ControlElement.CE_ItemViewItem, option, painter, option.widget)
        painter.restore()
        if pixmap.isNull():
            return
        size = pixmap.deviceIndependentSize()
        margin = (option.rect.width() - size.width()) / 2
        target = QRectF(option.rect.x() + margin, option.rect.y() + margin, size.width(), size.height())
        painter.save()
        painter.drawPixmap(target, pixmap, QRectF(pixmap.rect()))
        painter.setPen(QColor('#243642'))
        painter.drawText(option.rect.adjusted(0, option.rect.height() - 24, 0, -2), Qt.AlignmentFlag.AlignCenter, text)
        painter.restore()


class ThumbnailList(QListWidget):
    pages_moved = Signal(object, int)

    def __init__(self):
        super().__init__()
        self.setDragDropMode(QListWidget.DragDropMode.InternalMove)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.setDropIndicatorShown(False)
        self.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        self._drag_item = None
        self._drag_pages = []
        self._drop_y = None
        self._moving_thumbnails = []
        self._reorder_overlay = QLabel(self.viewport())
        self._reorder_overlay.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._reorder_overlay.hide()
        self._reorder_animation = QVariantAnimation(self)
        self._reorder_animation.setStartValue(0.0)
        self._reorder_animation.setEndValue(1.0)
        self._reorder_animation.setDuration(210)
        self._reorder_animation.setEasingCurve(QEasingCurve.Type.InOutQuad)
        self._reorder_animation.valueChanged.connect(self._paint_reorder)
        self._reorder_animation.finished.connect(self.stop_reorder)
        self.verticalScrollBar().valueChanged.connect(self.stop_reorder)

    def selected_pages(self):
        return sorted(self.row(item) for item in self.selectedItems() if item.flags() & Qt.ItemFlag.ItemIsDragEnabled)

    def startDrag(self, supported_actions):
        item = self.currentItem()
        if item is None or not item.flags() & Qt.ItemFlag.ItemIsDragEnabled:
            return
        self.stop_reorder()
        self._drag_item = item
        self._drag_pages = self.selected_pages() if item.isSelected() else [self.row(item)]
        drag = QDrag(self)
        drag.setMimeData(self.mimeData([self.item(index) for index in self._drag_pages]))
        drag.setPixmap(item.icon().pixmap(self.iconSize()))
        try:
            drag.exec(Qt.DropAction.MoveAction)
        finally:
            self._drag_item = None
            self._drag_pages = []
            self._set_drop_y(None)

    def _drop_boundary(self, y):
        return bisect_left(range(self.count() - 1), y,
                           key=lambda row: self.visualItemRect(self.item(row)).center().y())

    def _set_drop_y(self, y):
        if self._drop_y != y:
            self._drop_y = y
            self.viewport().update()

    def dragMoveEvent(self, event):
        super().dragMoveEvent(event)
        if event.source() is self and self._drag_item is not None:
            self._set_drop_y(event.position().y())
            event.setDropAction(Qt.DropAction.MoveAction)
            event.accept()

    def dragLeaveEvent(self, event):
        self._set_drop_y(None)
        super().dragLeaveEvent(event)

    def dropEvent(self, event):
        self._set_drop_y(None)
        if event.source() is not self or self._drag_item is None or self.row(self._drag_item) < 0:
            event.ignore()
            return
        event.setDropAction(Qt.DropAction.MoveAction)
        event.accept()
        self.pages_moved.emit(self._drag_pages, self._drop_boundary(event.position().y()))

    def paintEvent(self, event):
        super().paintEvent(event)
        if self._drop_y is not None and self.count() > 1:
            boundary = self._drop_boundary(self._drop_y)
            rect = self.visualItemRect(self.item(boundary))
            gap = self.spacing() if boundary else self.spacing() // 2
            y = max(2, min(rect.top() - gap, self.viewport().height() - 3))
            painter = QPainter(self.viewport())
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setPen(QPen(QColor('#087f83'), 3, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            painter.drawLine(rect.left() + 8, y, rect.right() - 8, y)

    def stop_reorder(self):
        self._reorder_animation.stop()
        self._reorder_overlay.hide()
        self._moving_thumbnails.clear()

    def resizeEvent(self, event):
        self.stop_reorder()
        super().resizeEvent(event)

    def mousePressEvent(self, event):
        self.stop_reorder()
        super().mousePressEvent(event)

    def animate_reorder(self, before, after):
        if before == after or len(before) != len(after) or set(before) != set(after) or not self.isVisible():
            return
        self.stop_reorder()
        self.doItemsLayout()
        viewport = self.viewport().rect()
        old_rows = {page: row for row, page in enumerate(before)}
        frames = []
        for row in range(self.count()):
            old_row = old_rows[after[row]] if row < len(after) else row
            item = self.item(row)
            rect = self.visualItemRect(item)
            old_y = self.visualItemRect(self.item(old_row)).top()
            if rect.intersects(viewport) or rect.translated(0, old_y - rect.top()).intersects(viewport):
                frames.append((item.isSelected(), rect.topLeft(), old_y, self._thumbnail_pixmap(item, rect.size())))
        if any(point.y() != old_y for _, point, old_y, _ in frames):
            # Keep the moved selection above the cards it passes.
            self._moving_thumbnails = sorted(frames, key=lambda frame: frame[0])
            self._reorder_overlay.setGeometry(viewport)
            self._paint_reorder(0.0)
            self._reorder_overlay.show()
            self._reorder_overlay.raise_()
            self._reorder_animation.start()

    def _thumbnail_pixmap(self, item, size):
        ratio = self.devicePixelRatioF()
        image = QPixmap(size * ratio)
        image.setDevicePixelRatio(ratio)
        image.fill(Qt.GlobalColor.transparent)
        option = QStyleOptionViewItem()
        self.initViewItemOption(option)
        option.rect = QRect(QPoint(), size)
        if item.isSelected():
            option.state |= QStyle.StateFlag.State_Selected
        painter = QPainter(image)
        self.itemDelegate().paint(painter, option, self.indexFromItem(item))
        controls = self.itemWidget(item)
        if controls:
            controls.render(painter, QPoint(), renderFlags=QWidget.RenderFlag.DrawChildren)
        painter.end()
        return image

    def _paint_reorder(self, progress):
        if not self._moving_thumbnails:
            return
        ratio = self.devicePixelRatioF()
        frame = QPixmap(self.viewport().size() * ratio)
        frame.setDevicePixelRatio(ratio)
        frame.fill(self.viewport().palette().color(QPalette.ColorRole.Base))
        painter = QPainter(frame)
        for _, point, old_y, image in self._moving_thumbnails:
            y = old_y + (point.y() - old_y) * progress
            painter.drawPixmap(QPointF(point.x(), y), image)
        painter.end()
        self._reorder_overlay.setPixmap(frame)


class AppendPdfCard(QWidget):
    def __init__(self, callback):
        super().__init__()
        self.button = QPushButton('+', self)
        self.button.setObjectName('appendPdf')
        self.button.setFixedSize(114, 160)
        self.button.setToolTip(_('Pridať PDF na koniec — kliknite alebo sem pretiahnite PDF'))
        self.button.setAccessibleName(_('Pridať PDF na koniec dokumentu'))
        self.button.clicked.connect(callback)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        margin = max(0, (self.width() - self.button.width()) // 2)
        self.button.move(margin, margin)


class ToolbarButton(QToolButton):
    def __init__(self):
        super().__init__()
        self._hover = QVariantAnimation(self)
        self._hover.setStartValue(0.0)
        self._hover.setEndValue(4.0)
        self._hover.setDuration(160)
        self._hover.setEasingCurve(QEasingCurve.Type.InOutQuad)
        self._hover.valueChanged.connect(self.update)

    def event(self, event):
        event_type = event.type()
        if event_type == QEvent.Type.Enter and self.isEnabled():
            self._hover.setDirection(QVariantAnimation.Direction.Forward)
            self._hover.start()
        elif event_type == QEvent.Type.Leave and self._hover.currentTime() > 0:
            self._hover.setDirection(QVariantAnimation.Direction.Backward)
            self._hover.start()
        elif event_type == QEvent.Type.EnabledChange and not self.isEnabled():
            self._hover.stop()
            self._hover.setCurrentTime(0)
        return super().event(event)

    def paintEvent(self, event):
        option = QStyleOptionToolButton()
        self.initStyleOption(option)
        option.icon = QIcon()
        painter = QStylePainter(self)
        painter.drawComplexControl(QStyle.ComplexControl.CC_ToolButton, option)

        mode = QIcon.Mode.Normal if self.isEnabled() else QIcon.Mode.Disabled
        state = QIcon.State.On if self.isChecked() else QIcon.State.Off
        pixmap = self.icon().pixmap(self.size(), self.devicePixelRatioF(), mode, state)
        size = self.iconSize().width() + self._hover.currentValue()
        rect = QRectF((self.width() - size) / 2, (self.height() - size) / 2, size, size)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.drawPixmap(rect, pixmap, QRectF(pixmap.rect()))


class Editor(QMainWindow):
    def __init__(self):
        super().__init__()
        self.pdf = None
        self.page_index = 0
        self.selection = None
        self._editor_open = False
        self._editor_width = 320
        self._resizing_editor_panel = False
        self.ocr_worker = None
        self.ocr_timer = QTimer(self)
        self.ocr_timer.setSingleShot(True)
        self.ocr_timer.timeout.connect(self._start_next_ocr)
        self._searchable_progress = None
        self._searchable_pages = deque()
        self._searchable_error = None
        self._thumbnail_icons = {}
        self._raster_versions = {}
        self._find_pending = deque()
        self._find_ocr_pages = {}
        self._find_failed_pages = set()
        self._find_results = {}
        self._find_hit = None
        self._find_timer = QTimer(self)
        self._find_timer.setSingleShot(True)
        self._find_timer.timeout.connect(self._search_next_pages)
        self.pending = False
        self.edit_applied = False
        self.update_worker = None
        self.ready_update = None
        self._install_pending = False
        self._verified_update = None
        self._skip_update_offer = False
        self._install_directory = None
        self._update_manual = False
        self._closing_after_update = False
        self._close_approved = False
        self.settings = QSettings('OmniPDF', 'OmniPDF')
        self.update_timer = QTimer(self)
        self.update_timer.setInterval(6 * 60 * 60 * 1000)
        self.update_timer.timeout.connect(lambda: self.check_updates(automatic=True))
        self.scroll_sync_timer = QTimer(self)
        self.scroll_sync_timer.setSingleShot(True)
        self.scroll_sync_timer.timeout.connect(self._sync_scroll_page)
        self.add_pdf_item = None
        self.add_pdf_card = None
        self.auto_apply_timer = QTimer(self)
        self.auto_apply_timer.setSingleShot(True)
        self.auto_apply_timer.setInterval(650)
        self.auto_apply_timer.timeout.connect(lambda: self.apply_change(automatic=True))
        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(QIcon(str(APP_ICON)))
        self.resize(1340, 900)
        self.setMinimumSize(950, 640)
        self._build_ui()
        self._update_actions()
        self.setAcceptDrops(True)
        QApplication.instance().installEventFilter(self)
        if getattr(sys, 'frozen', False) and self.auto_update_action.isChecked():
            self.update_timer.start()
            QTimer.singleShot(5000, lambda: self.check_updates(automatic=True))

    def showEvent(self, event):
        super().showEvent(event)
        if QApplication.platformName() == 'windows':
            configure_title_bar(int(self.winId()))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.centralWidget() and self.find_bar.isVisible():
            self._position_find()

    def eventFilter(self, watched, event):
        if (not isinstance(watched, QWidget)
                or (watched is not self and not self.isAncestorOf(watched))):
            return super().eventFilter(watched, event)
        if event.type() == QEvent.Type.DragLeave:
            # Moving between child widgets must not flash the drop indicator.
            self.drop_leave_timer.start()
            return super().eventFilter(watched, event)
        if event.type() not in (QEvent.Type.DragEnter, QEvent.Type.DragMove, QEvent.Type.Drop):
            return super().eventFilter(watched, event)
        if not event.mimeData().hasUrls():
            self._set_drop_active(False)
            return super().eventFilter(watched, event)
        urls = event.mimeData().urls()
        path = Path(urls[0].toLocalFile()) if len(urls) == 1 and urls[0].isLocalFile() else None
        point = self.thumbnails.viewport().mapFrom(watched, event.position().toPoint())
        append = (self.pdf is not None and self.add_pdf_item is not None
                  and self.thumbnails.viewport().rect().contains(point)
                  and self.thumbnails.itemAt(point) is self.add_pdf_item)
        supported = ('.pdf',) if append else ('.pdf', '.jpg', '.jpeg', '.png')
        if (self._busy() or path is None or path.suffix.lower() not in supported
                or not path.is_file() or not event.possibleActions() & Qt.DropAction.CopyAction):
            self._set_drop_active(False)
            event.ignore()
            return True
        self._set_drop_active(event.type() != QEvent.Type.Drop, append=append)
        event.setDropAction(Qt.DropAction.CopyAction)
        event.accept()
        if event.type() == QEvent.Type.Drop:
            # Finish the drag before opening any dialog for unsaved changes.
            if append:
                QTimer.singleShot(0, lambda: self.insert_pdf(path=path, append=True))
            else:
                QTimer.singleShot(0, lambda: self.open_file(path=path))
        return True

    def _set_drop_active(self, active, append=False):
        self.drop_leave_timer.stop()
        if self.add_pdf_card is not None:
            button = self.add_pdf_card.button
            if bool(button.property('dragActive')) != bool(active and append):
                button.setProperty('dragActive', active and append)
                button.style().unpolish(button)
                button.style().polish(button)
                button.update()
        active = active and self.empty.isVisible()
        if self.drop_effect.isEnabled() == active:
            return
        self.drop_zone.setProperty('dragActive', active)
        self.drop_zone.style().unpolish(self.drop_zone)
        self.drop_zone.style().polish(self.drop_zone)
        self.drop_effect.setEnabled(active)
        if active:
            self.drop_animation.start()
        else:
            self.drop_animation.stop()
        self.drop_zone.update()

    def _build_ui(self):
        root = QWidget()
        layout = QVBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        tools = QFrame()
        tools.setObjectName('tools')
        tools.setFixedHeight(46)
        toolbar_layout = QGridLayout(tools)
        toolbar_layout.setContentsMargins(10, 7, 10, 7)
        toolbar_layout.setHorizontalSpacing(8)
        row = QHBoxLayout()
        row.setSpacing(3)
        brand = ToolbarButton()
        brand.setObjectName('brand')
        brand.setIcon(self.windowIcon())
        brand.setIconSize(QSize(22, 22))
        brand.setFixedSize(32, 32)
        brand.setAutoRaise(True)
        brand.setToolTip(f'{APP_NAME} {VERSION}')
        brand.setAccessibleName(_('Ponuka aplikácie Omni PDF'))
        self.app_menu = QMenu(self)
        self.searchable_action = self.app_menu.addAction(_('Uložiť ako prehľadávateľné PDF…'), lambda: self.save_copy(searchable=True))
        self.app_menu.addSeparator()
        self.app_menu.addAction(_('O aplikácii…'), self.show_about)
        self.check_updates_action = self.app_menu.addAction(_('Skontrolovať aktualizácie…'), self.check_updates)
        self.auto_update_action = self.app_menu.addAction(_('Automatické aktualizácie'))
        self.auto_update_action.setCheckable(True)
        self.auto_update_action.setChecked(self.settings.value('updates/automatic', True, type=bool))
        self.auto_update_action.setEnabled(bool(getattr(sys, 'frozen', False)))
        self.auto_update_action.toggled.connect(self._automatic_updates_toggled)
        brand.setMenu(self.app_menu)
        brand.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        row.addWidget(brand)
        self.file_label = QLabel()
        self.file_label.setObjectName('filename')
        self.file_label.setMinimumWidth(80)
        self.file_label.setMaximumWidth(160)
        self.file_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        row.addWidget(self.file_label, 1)
        self.open_button = self._tool_button(_('Otvoriť súbor (Ctrl+O)'), 'open', self.open_file, row)
        self.save_button = self._tool_button(_('Uložiť PDF (Ctrl+S alebo Ctrl+Shift+S)'), 'save', self.save_copy, row)
        self._toolbar_separator(row)
        self.undo_button = self._tool_button(_('Späť (Ctrl+Z)'), 'undo', self.undo, row)
        self.redo_button = self._tool_button(_('Dopredu (Ctrl+Y)'), 'redo', self.redo, row)
        row.addStretch()
        toolbar_layout.addLayout(row, 0, 0)
        navigation = QHBoxLayout()
        navigation.setSpacing(3)
        self.previous_button = self._tool_button(_('Predchádzajúca strana'), 'previous', lambda: self.change_page(self.page_index - 1), navigation)
        self.page_label = QLabel('0 / 0')
        self.page_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        navigation.addWidget(self.page_label)
        self.next_button = self._tool_button(_('Nasledujúca strana'), 'next', lambda: self.change_page(self.page_index + 1), navigation)
        toolbar_layout.addLayout(navigation, 0, 1, Qt.AlignmentFlag.AlignCenter)
        bar = QHBoxLayout()
        bar.setSpacing(3)
        self.pages_button = self._tool_button(_('Spravovať strany'), 'pages', None, bar)
        self.pages_menu = QMenu(self)
        self.duplicate_page_action = self.pages_menu.addAction(_('Duplikovať aktuálnu stranu'), self.duplicate_page)
        self.delete_page_action = self.pages_menu.addAction(_('Odstrániť vybrané strany'), self.delete_page)
        self.move_up_action = self.pages_menu.addAction(_('Presunúť vybrané strany vyššie'), lambda: self._move_selected(-1))
        self.move_down_action = self.pages_menu.addAction(_('Presunúť vybrané strany nižšie'), lambda: self._move_selected(1))
        self.rotate_left_action = self.pages_menu.addAction(_('Otočiť vybrané strany doľava'), lambda: self._rotate_selected(-90))
        self.rotate_right_action = self.pages_menu.addAction(_('Otočiť vybrané strany doprava'), lambda: self._rotate_selected(90))
        self.pages_menu.addSeparator()
        self.insert_pdf_action = self.pages_menu.addAction(_('Vložiť PDF za aktuálnu stranu…'), self.insert_pdf)
        self.pages_button.setMenu(self.pages_menu)
        self.pages_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self._toolbar_separator(bar)
        self.region_button = self._tool_button(_('Pridať textové pole'), 'text', None, bar)
        self.region_button.setCheckable(True)
        self.region_button.toggled.connect(self._region_toggled)
        self.cover_button = self._tool_button(_('Vybrať oblasť'), 'cover', None, bar)
        self.cover_button.setCheckable(True)
        self.cover_button.toggled.connect(self._cover_toggled)
        self._toolbar_separator(bar)
        self.minus_button = self._tool_button(_('Oddialiť (Ctrl+-)'), 'minus', lambda: self.view.zoom(0.8), bar)
        self.zoom_label = QLabel('100 %')
        self.zoom_label.setObjectName('zoomLevel')
        self.zoom_label.setMinimumWidth(42)
        self.zoom_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.zoom_label.setToolTip(_('Zväčšenie dokumentu'))
        bar.addWidget(self.zoom_label)
        self.plus_button = self._tool_button(_('Priblížiť (Ctrl++ alebo Ctrl+=)'), 'plus', lambda: self.view.zoom(1.25), bar)
        self.fit_button = self._tool_button(_('Na šírku (Ctrl+0)'), 'fit', lambda: self.view.fit_width(), bar)
        toolbar_layout.addLayout(bar, 0, 2, Qt.AlignmentFlag.AlignRight)
        side_width = max(row.minimumSize().width(), bar.minimumSize().width())
        toolbar_layout.setColumnMinimumWidth(0, side_width)
        toolbar_layout.setColumnMinimumWidth(2, side_width)
        toolbar_layout.setColumnStretch(0, 1)
        toolbar_layout.setColumnStretch(2, 1)
        self.file_label.hide()
        layout.addWidget(tools)

        self.find_bar = QFrame(root)
        self.find_bar.setObjectName('findBar')
        self.find_bar.setFixedWidth(356)
        shadow = QGraphicsDropShadowEffect(self.find_bar)
        shadow.setBlurRadius(20)
        shadow.setOffset(0, 4)
        shadow.setColor(QColor(30, 45, 56, 42))
        self.find_bar.setGraphicsEffect(shadow)
        find_layout = QVBoxLayout(self.find_bar)
        find_layout.setContentsMargins(8, 7, 8, 7)
        find_layout.setSpacing(4)
        find_row = QHBoxLayout()
        find_row.setSpacing(3)
        self.find_input = QLineEdit()
        self.find_input.setObjectName('findInput')
        self.find_input.setPlaceholderText(_('Hľadať v dokumente'))
        self.find_input.setAccessibleName(_('Hľadať v dokumente'))
        self.find_input.textChanged.connect(self._restart_find)
        self.find_input.returnPressed.connect(lambda: self._move_find(1))
        find_row.addWidget(self.find_input, 1)
        self.find_previous = self._tool_button(_('Predchádzajúci výsledok'), 'previous', lambda: self._move_find(-1), find_row, button_class=QToolButton)
        self.find_next = self._tool_button(_('Ďalší výsledok'), 'next', lambda: self._move_find(1), find_row, button_class=QToolButton)
        self._tool_button(_('Zavrieť hľadanie'), 'close', self._close_find, find_row, button_class=QToolButton)
        find_layout.addLayout(find_row)
        self.find_status = QLabel()
        self.find_status.setObjectName('findStatus')
        self.find_status.setWordWrap(True)
        self.find_status.hide()
        find_layout.addWidget(self.find_status)
        self.find_bar.hide()

        self.splitter = QSplitter()
        self.view = PageView()
        self.view.page_requested.connect(self._activate_scrolled_page)
        self.view.verticalScrollBar().valueChanged.connect(self._queue_scroll_sync)
        self.view.horizontalScrollBar().valueChanged.connect(lambda: self.view.raster_timer.start())
        self.view.selected.connect(self.select_text)
        self.view.region.connect(self.select_region)
        self.view.area_changed.connect(self.transform_area)
        self.view.text_range.connect(self.select_range)
        self.view.delete_requested.connect(self.delete_selection)
        self.view.selection_cleared.connect(self.cancel_selection)
        self.view.render_requested.connect(self.refresh_preview)
        self.view.zoom_changed.connect(lambda value: self.zoom_label.setText(f'{round(value * 100)} %'))
        self.splitter.addWidget(self.view)

        panel = QWidget()
        panel.setObjectName('panel')
        form = QVBoxLayout(panel)
        form.setContentsMargins(24, 26, 24, 24)
        form.setSpacing(14)
        title = QLabel(_('Upraviť text'))
        title.setObjectName('paneltitle')
        panel_header = QHBoxLayout()
        panel_header.addWidget(title, 1)
        self.cancel_button = self._tool_button(_('Zrušiť výber (Escape)'), 'close', self.cancel_selection, panel_header, button_class=QToolButton)
        self.cancel_button.setFixedSize(32, 32)
        self.cancel_button.setIconSize(QSize(16, 16))
        form.addLayout(panel_header)
        self.selection_preview = QLabel()
        self.selection_preview.setFixedHeight(120)
        self.selection_preview.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.selection_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.selection_preview.setAccessibleName(_('Zväčšený náhľad vybraného textu'))
        self.selection_preview.hide()
        form.addWidget(self.selection_preview)
        self.hint = QLabel(_('Otvorte PDF a kliknite na text, ktorý chcete zmeniť.'))
        self.hint.setWordWrap(True)
        self.hint.setObjectName('muted')
        form.addWidget(self.hint)
        label = QLabel(_('Nový text'))
        form.addWidget(label)
        self.text = QTextEdit()
        self.text.setAcceptRichText(False)
        self.text.setPlaceholderText(_('Vyberte text na strane…'))
        self.text.setMinimumHeight(120)
        self.text.setMaximumHeight(220)
        label.setBuddy(self.text)
        self.text.textChanged.connect(self._edited)
        form.addWidget(self.text)
        self.edit_error = QLabel()
        self.edit_error.setWordWrap(True)
        self.edit_error.setStyleSheet('color: #b42318;')
        self.edit_error.hide()
        form.addWidget(self.edit_error)
        formatting = QHBoxLayout()
        formatting.setSpacing(12)
        self.font_size = QComboBox()
        self.font_size.setObjectName('fontSize')
        self.font_size.setFixedSize(80, 28)
        self.font_size.setToolTip(_('Maximálna veľkosť písma'))
        self.font_size.setAccessibleName(_('Veľkosť písma'))
        for size in (4, 6, 7, 8, 9, 10, 11, 12, 14, 16, 18, 20, 24, 28, 32, 36, 48, 60, 72, 96):
            self.font_size.addItem(f'{size} pt', size)
        self.font_size.setCurrentIndex(self.font_size.findData(11))
        self.font_size.currentIndexChanged.connect(self._edited)
        formatting.addWidget(self.font_size)
        self.white_background = QCheckBox(_('Biely podklad'))
        self.white_background.setToolTip(_('Biely podklad pod nahradeným textom'))
        self.white_background.toggled.connect(self._edited)
        formatting.addWidget(self.white_background)
        formatting.addStretch()
        form.addLayout(formatting)
        form.addStretch()
        self.editor_panel = QScrollArea()
        self.editor_panel.setObjectName('editorPanel')
        self.editor_panel.setMaximumWidth(350)
        self.editor_panel.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Expanding)
        self.editor_panel.setWidgetResizable(True)
        self.editor_panel.setFrameShape(QFrame.Shape.NoFrame)
        self.editor_panel.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.editor_panel.setWidget(panel)
        self.splitter.addWidget(self.editor_panel)
        self.editor_panel.hide()
        self._editor_slide = QVariantAnimation(self)
        self._editor_slide.setStartValue(0.0)
        self._editor_slide.setEndValue(1.0)
        self._editor_slide.setDuration(200)
        self._editor_slide.setEasingCurve(QEasingCurve.Type.InOutQuad)
        self._editor_slide.valueChanged.connect(self._slide_editor_panel)
        self._editor_slide.finished.connect(self._finish_editor_slide)
        self.thumbnails = ThumbnailList()
        self.thumbnails.setObjectName('thumbnails')
        self.thumbnails.setAccessibleName(_('Náhľady strán'))
        self.thumbnails.setFixedWidth(160)
        self.thumbnails.setItemDelegate(ThumbnailDelegate(self.thumbnails))
        self.thumbnails.setSpacing(6)
        self.thumbnails.setUniformItemSizes(True)
        self.thumbnails.setVerticalScrollMode(QListWidget.ScrollMode.ScrollPerPixel)
        self.thumbnails.verticalScrollBar().setSingleStep(24)
        self.thumbnails.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.thumbnails.setIconSize(QSize(120, 160))
        self.thumbnails.currentRowChanged.connect(self._thumbnail_selected)
        self.thumbnails.itemSelectionChanged.connect(self._update_pagination)
        self.thumbnails.pages_moved.connect(self.move_pages)
        self.thumbnails.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.thumbnails.customContextMenuRequested.connect(self._thumbnail_menu)
        self.splitter.insertWidget(0, self.thumbnails)
        self.splitter.setCollapsible(0, False)
        self.splitter.setCollapsible(2, False)
        self.splitter.setSizes([160, 1180, 0])
        layout.addWidget(self.splitter, 1)

        self.empty = QWidget()
        empty_layout = QVBoxLayout(self.empty)
        empty_layout.addStretch()
        drop_zone = QFrame()
        self.drop_zone = drop_zone
        drop_zone.setObjectName('dropZone')
        drop_zone.setMaximumWidth(680)
        self.drop_effect = QGraphicsDropShadowEffect(drop_zone)
        self.drop_effect.setOffset(0, 0)
        self.drop_effect.setColor(QColor('#65b9b5'))
        self.drop_effect.setEnabled(False)
        drop_zone.setGraphicsEffect(self.drop_effect)
        self.drop_animation = QPropertyAnimation(self.drop_effect, b'blurRadius', self)
        self.drop_animation.setDuration(1400)
        self.drop_animation.setStartValue(10.0)
        self.drop_animation.setKeyValueAt(0.5, 26.0)
        self.drop_animation.setEndValue(10.0)
        self.drop_animation.setEasingCurve(QEasingCurve.Type.InOutSine)
        self.drop_animation.setLoopCount(-1)
        self.drop_leave_timer = QTimer(self)
        self.drop_leave_timer.setSingleShot(True)
        self.drop_leave_timer.setInterval(60)
        self.drop_leave_timer.timeout.connect(lambda: self._set_drop_active(False))
        zone_layout = QVBoxLayout(drop_zone)
        zone_layout.setContentsMargins(36, 32, 36, 36)
        headline = QLabel(_('Vaše PDF. Vaše úpravy.'))
        headline.setAlignment(Qt.AlignmentFlag.AlignCenter)
        headline.setObjectName('headline')
        zone_layout.addWidget(headline)
        subtitle = QLabel(_('Pretiahnite sem PDF, sken alebo fotografiu.\nAlebo vyberte súbor z počítača.'))
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        subtitle.setObjectName('subtitle')
        zone_layout.addWidget(subtitle)
        empty_button = QPushButton(_('Vybrať súbor'))
        empty_button.setObjectName('primary')
        empty_button.setFixedWidth(210)
        empty_button.clicked.connect(self.open_file)
        zone_layout.addWidget(empty_button, alignment=Qt.AlignmentFlag.AlignCenter)
        empty_layout.addWidget(drop_zone, alignment=Qt.AlignmentFlag.AlignCenter)
        empty_layout.addStretch()
        layout.addWidget(self.empty, 1)
        self.splitter.hide()
        self.setCentralWidget(root)
        empty_button.setFocus()
        self.statusBar().addPermanentWidget(QLabel(f'v{VERSION}'))
        self.statusBar().showMessage(_('Pripravené. Spracovanie prebieha lokálne bez nahrávania súborov.'))
        for keys, callback in [
            ('Ctrl+O', self.open_file), ('Ctrl+S', self.save_button.click),
            ('Ctrl+Shift+S', self.save_button.click), ('Ctrl+Z', self.undo),
            ('Ctrl+Y', self.redo), ('Ctrl+Shift+Z', self.redo), ('Esc', self._escape),
            ('Ctrl+F', self._open_find), ('F3', lambda: self._move_find(1)), ('Shift+F3', lambda: self._move_find(-1)),
            ('Ctrl++', self.plus_button.click), ('Ctrl+=', self.plus_button.click),
            ('Ctrl+-', self.minus_button.click), ('Ctrl+0', self.fit_button.click),
        ]:
            action = QAction(self)
            action.setShortcut(QKeySequence(keys))
            action.triggered.connect(callback)
            self.addAction(action)

    @staticmethod
    def _toolbar_separator(layout):
        line = QFrame()
        line.setObjectName('toolbarSeparator')
        line.setFixedSize(1, 20)
        layout.addSpacing(4)
        layout.addWidget(line)
        layout.addSpacing(4)

    def _tool_button(self, label, symbol, callback, layout, *, button_class=ToolbarButton):
        pixmap = QPixmap(24, 24)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(QColor('#243642'), 1.8, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        if symbol in ('undo', 'redo'):
            if symbol == 'redo':
                painter.translate(24, 0)
                painter.scale(-1, 1)
            path = QPainterPath()
            path.moveTo(4, 8)
            path.lineTo(13, 8)
            path.cubicTo(23, 8, 23, 20, 15, 20)
            path.moveTo(9, 3)
            path.lineTo(4, 8)
            path.lineTo(9, 13)
            painter.drawPath(path)
        elif symbol == 'close':
            painter.drawLine(6, 6, 18, 18)
            painter.drawLine(18, 6, 6, 18)
        elif symbol in ('previous', 'next'):
            if symbol == 'next':
                painter.translate(24, 0)
                painter.scale(-1, 1)
            path = QPainterPath()
            path.moveTo(15, 5)
            path.lineTo(8, 12)
            path.lineTo(15, 19)
            painter.drawPath(path)
        elif symbol in ('minus', 'plus'):
            painter.drawLine(5, 12, 19, 12)
            if symbol == 'plus':
                painter.drawLine(12, 5, 12, 19)
        elif symbol == 'fit':
            painter.drawRect(QRectF(6, 6, 12, 12))
            painter.drawLine(2, 4, 2, 20)
            painter.drawLine(22, 4, 22, 20)
        elif symbol == 'open':
            path = QPainterPath()
            path.moveTo(3, 19)
            path.lineTo(3, 6)
            path.lineTo(9, 6)
            path.lineTo(12, 9)
            path.lineTo(20, 9)
            path.moveTo(3, 19)
            path.lineTo(6, 11)
            path.lineTo(22, 11)
            path.lineTo(19, 19)
            path.closeSubpath()
            painter.drawPath(path)
        elif symbol == 'save':
            path = QPainterPath()
            path.moveTo(4, 3)
            path.lineTo(17, 3)
            path.lineTo(21, 7)
            path.lineTo(21, 21)
            path.lineTo(4, 21)
            path.closeSubpath()
            painter.drawPath(path)
            painter.drawRect(QRectF(8, 3, 8, 6))
            painter.drawRect(QRectF(8, 14, 9, 7))
        elif symbol == 'pages':
            painter.drawRect(QRectF(4, 3, 12, 15))
            painter.drawRect(QRectF(8, 7, 12, 15))
            painter.drawLine(11, 12, 17, 12)
            painter.drawLine(11, 16, 17, 16)
        else:
            if symbol == 'cover':
                painter.setPen(QPen(QColor('#344b58'), 2, Qt.PenStyle.DashLine))
                painter.drawRect(QRectF(3, 3, 18, 18))
            else:
                painter.drawRect(QRectF(3, 3, 18, 18))
                painter.drawLine(7, 7, 17, 7)
                painter.drawLine(12, 7, 12, 18)
                painter.drawLine(9, 18, 15, 18)
        painter.end()
        disabled = pixmap.copy()
        painter = QPainter(disabled)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
        painter.fillRect(disabled.rect(), QColor('#b8c2ca'))
        painter.end()
        icon = QIcon(pixmap)
        icon.addPixmap(disabled, QIcon.Mode.Disabled)
        button = button_class()
        button.setIcon(icon)
        button.setIconSize(QSize(17, 17))
        button.setFixedSize(28, 28)
        button.setAutoRaise(True)
        button.setToolTip(label)
        button.setAccessibleName(label)
        if callback:
            button.clicked.connect(callback)
        layout.addWidget(button)
        return button

    def _error(self, exc):
        message = _(ERRORS.get(str(exc), str(exc)))
        QMessageBox.warning(self, _('Akciu sa nepodarilo dokončiť'), message)

    def _busy(self):
        return self._searchable_progress is not None or (self._install_pending and self.update_worker is not None)

    def _has_editable_selection(self):
        return self.selection is not None and 'characters' not in self.selection and self.selection.get('kind') != 'area'

    def _set_editor_open(self, opened):
        if opened == self._editor_open:
            return
        self._editor_open = opened
        panel = self.editor_panel
        slide = self._editor_slide
        running = slide.state() == QVariantAnimation.State.Running
        if not opened and not running:
            self._editor_width = panel.width()
        focus = QApplication.focusWidget()
        if not opened and focus is not None and panel.isAncestorOf(focus):
            self.view.setFocus()
        # Clip the form during the transition so its controls and text do not reflow.
        panel.widget().setMinimumWidth(self._editor_width - panel.verticalScrollBar().sizeHint().width())
        panel.setMinimumWidth(0)
        self.splitter.handle(2).setEnabled(False)
        if panel.isHidden():
            panel.show()
            self._slide_editor_panel(0.0)
        slide.setDirection(QVariantAnimation.Direction.Forward if opened else QVariantAnimation.Direction.Backward)
        slide.start()

    def _slide_editor_panel(self, progress):
        sidebar, document, current = self.splitter.sizes()
        width = round(self._editor_width * progress)
        if width == current:
            return
        center = self.view.viewport().rect().center()
        scene_center = self.view.mapToScene(center)
        self._resizing_editor_panel = True
        try:
            self.splitter.setSizes([sidebar, document + current - width, width])
            if self.view.fit_to_width:
                scroll = self.view.verticalScrollBar()
                scroll.setValue(scroll.value() + self.view.mapFromScene(scene_center).y() - center.y())
        finally:
            self._resizing_editor_panel = False

    def _finish_editor_slide(self):
        if self._editor_open:
            self.editor_panel.setMinimumWidth(280)
        else:
            self.editor_panel.hide()
        self.editor_panel.widget().setMinimumWidth(0)
        self.splitter.handle(2).setEnabled(True)
        self._queue_scroll_sync()

    def _update_actions(self):
        ready = self.pdf is not None and not self._busy()
        has_pages = ready and self.pdf.page_count > 0
        has_editable_selection = self._has_editable_selection()
        editable = ready and has_editable_selection
        self._set_editor_open(has_editable_selection)
        self.open_button.setEnabled(not self._busy())
        for widget in (self.save_button, self.region_button, self.cover_button, self.minus_button, self.fit_button, self.plus_button, self.view):
            widget.setEnabled(has_pages)
        self.undo_button.setEnabled(ready and self.pdf.can_undo)
        self.redo_button.setEnabled(ready and self.pdf.can_redo)
        self.pages_button.setEnabled(ready)
        self.duplicate_page_action.setEnabled(has_pages)
        self.insert_pdf_action.setEnabled(ready)
        self.delete_page_action.setEnabled(has_pages)
        self.searchable_action.setEnabled(has_pages)
        self.rotate_left_action.setEnabled(has_pages)
        self.rotate_right_action.setEnabled(has_pages)
        for index in range(self.thumbnails.count()):
            item = self.thumbnails.item(index)
            controls = self.thumbnails.itemWidget(item)
            if item is self.add_pdf_item:
                controls.setEnabled(ready)
            else:
                controls.findChild(QToolButton, 'duplicatePage').setEnabled(ready)
                controls.findChild(QToolButton, 'deletePage').setEnabled(has_pages)
        self.text.setEnabled(ready and self.selection is not None)
        self.text.setReadOnly(not editable)
        self.cancel_button.setEnabled(ready and self.selection is not None)
        self.font_size.setEnabled(editable)
        self.white_background.setEnabled(editable and not self.selection.get('insert_only', False))
        self._update_pagination()
        dirty = bool(self.pdf and self.pdf.dirty) or self.pending
        title = f'{self.pdf.source.name} — {APP_NAME}' if self.pdf else APP_NAME
        self.setWindowTitle(f'{"* " if dirty else ""}{title}')

    def _edited(self, *args):
        if self.selection is not None and 'characters' not in self.selection:
            self.pending = True
            self.edit_error.hide()
            self.auto_apply_timer.start()
            self._update_actions()

    def _discard_pending(self):
        return not self.pending or self.apply_change()

    def _leave_document(self):
        if self._busy():
            return False
        if not self.pdf or not (self.pdf.dirty or self.pending):
            return True
        buttons = QMessageBox.StandardButton
        prompt = QMessageBox(QMessageBox.Icon.Question, _('Neuložené zmeny'), _('Uložiť zmeny do PDF?'),
                             buttons.Save | buttons.Discard | buttons.Cancel, self)
        save_button = prompt.button(buttons.Save)
        save_button.setObjectName('primary')
        save_button.style().unpolish(save_button)
        save_button.style().polish(save_button)
        prompt.setDefaultButton(save_button)
        # Qt needs an escape button to handle the title-bar close action.
        cancel_button = prompt.button(buttons.Cancel)
        prompt.setEscapeButton(cancel_button)
        cancel_button.hide()
        answer = prompt.exec()
        prompt.deleteLater()
        if answer == buttons.Save:
            return self.save_copy()
        return answer == buttons.Discard

    def _confirm_signed_pdf(self):
        return QMessageBox.question(
            self, _('Digitálne podpísané PDF'),
            _('Tento dokument obsahuje digitálny podpis. Aplikácia neoveruje jeho platnosť. Uložením upraveného PDF alebo vložením strán sa podpis zneplatní. Chcete pokračovať?'),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes

    def open_file(self, checked=False, path=None):
        if self._busy() or not self._leave_document():
            return
        if path is None:
            path, selected_filter = QFileDialog.getOpenFileName(self, _('Otvoriť súbor'), '', _('Dokumenty (*.pdf *.jpg *.jpeg *.png)'))
        if not path:
            return
        try:
            try:
                document = PdfDocument(path)
            except SignedPdfError:
                if not self._confirm_signed_pdf():
                    return
                document = PdfDocument(path, allow_signed=True)
        except Exception as exc:
            self._error(exc)
            return
        if self.pdf:
            if self.ocr_worker:
                self.ocr_worker.requestInterruption()
            self.pdf.close()
        self.pdf = document
        self.thumbnails.blockSignals(True)
        self.add_pdf_item = None
        self.add_pdf_card = None
        self.thumbnails.clear()
        self.thumbnails.blockSignals(False)
        self._thumbnail_icons.clear()
        self._raster_versions.clear()
        self.selection = None
        self.pending = False
        self.empty.hide()
        self.splitter.show()
        self.file_label.setText(document.source.name)
        self.file_label.setToolTip(str(document.source))
        self.file_label.show()
        self.page_index = 0
        self.view.reset_document()
        self.clear_selection()
        self.render_page(fit=True, scroll=True)
        self._restart_find()
        self._update_pagination()
        if document.recovered:
            self.statusBar().showMessage(_('Štruktúra PDF bola obnovená. Pred uložením skontrolujte strany.'))

    def render_page(self, fit=False, *, scroll=False, refresh_thumbnails=True):
        if not self.pdf:
            return
        if not self.pdf.page_count:
            self.view.reset_document()
            self._raster_versions.clear()
            self._refresh_thumbnails()
            self._update_actions()
            return
        try:
            page = self.pdf.document[self.page_index]
            native = self.pdf.spans(self.page_index)
            areas = native + (self.pdf.page_versions[self.page_index].ocr or [])
            self.view.configure_pages([(p.rect.width, p.rect.height) for p in self.pdf.document])
            self.view.set_page(None, 1, page, areas, self.pdf.characters(self.page_index), page_index=self.page_index)
            if fit:
                self.view.fit_width()
            if scroll:
                self.view.scroll_to_page(self.page_index)
            self._render_visible_pages()
            self.restore_highlight()
            self.update_selection_preview()
            if refresh_thumbnails:
                self._refresh_thumbnails()
            else:
                self.thumbnails.blockSignals(True)
                self._sync_thumbnail_page()
                self.thumbnails.blockSignals(False)
            self._update_actions()
            self._draw_find_hits()
            if not areas and self.pdf.page_versions[self.page_index].ocr is None:
                self.statusBar().showMessage(_('Text tejto strany sa rozpozná automaticky. Môžete tiež pridať textové pole alebo zakryť oblasť.'))
            else:
                self.statusBar().showMessage(_('Strana {page} z {count}. Ťahaním označte text a stlačte Delete. Kliknutím upravíte celý úsek.').format(page=self.page_index + 1, count=self.pdf.page_count))
            if self._needs_ocr(self.page_index, native):
                self.ocr_timer.start(0)
        except Exception as exc:
            self._error(exc)

    def _render_scale(self, page):
        target = self.view.transform().m11() * self.view.devicePixelRatioF() * 1.5
        # shortcut: full-page preview is capped at 16 MP, use tiles for extreme zoom on large pages.
        return min(max(0.1, target), 6000 / max(page.rect.width, page.rect.height), math.sqrt(16_000_000 / page.rect.get_area()))

    def _render_visible_pages(self):
        visible = self.view.visible_page_indices()
        wanted = set(visible)
        if visible:
            wanted.update((max(0, min(visible) - 1), min(self.pdf.page_count - 1, max(visible) + 1)))
        wanted.add(self.page_index)
        for index in list(self.view.page_scales):
            if index not in wanted:
                self.view.evict_page_raster(index)
                self._raster_versions.pop(index, None)
        for index in sorted(wanted):
            scale = self._render_scale(self.pdf.document[index])
            version = self.pdf.page_versions[index]
            if self._raster_versions.get(index) is not version or index not in self.view.page_scales or abs(scale - self.view.page_scales[index]) > 0.05:
                self.view.update_page_raster(index, self.pdf.render(index, scale), scale)
                self._raster_versions[index] = version

    def _activate_scrolled_page(self, index):
        if not self.pdf or self._busy() or index == self.page_index:
            return
        self.page_index = index
        self.render_page(refresh_thumbnails=False)

    def _queue_scroll_sync(self):
        if not self._resizing_editor_panel and not self.scroll_sync_timer.isActive():
            self.scroll_sync_timer.start(0)

    def _sync_scroll_page(self):
        if not self.pdf or self._busy() or not self.view.page_rects:
            return
        if self.view.start_point is None:
            self._activate_scrolled_page(self.view.current_visible_page())
        self.refresh_preview()

    def _refresh_thumbnails(self):
        if not self.pdf or self.thumbnails.isHidden():
            return
        self.thumbnails.stop_reorder()
        self.thumbnails.blockSignals(True)
        try:
            if self.add_pdf_item is None:
                self.add_pdf_item = QListWidgetItem()
                self.add_pdf_item.setFlags(Qt.ItemFlag.ItemIsEnabled)
                self.add_pdf_item.setSizeHint(QSize(120, 200))
                self.thumbnails.addItem(self.add_pdf_item)
                self.add_pdf_card = AppendPdfCard(lambda: self.insert_pdf(append=True))
                self.thumbnails.setItemWidget(self.add_pdf_item, self.add_pdf_card)
            while self.thumbnails.count() > self.pdf.page_count + 1:
                self.thumbnails.takeItem(self.thumbnails.count() - 2)
            while self.thumbnails.count() < self.pdf.page_count + 1:
                index = self.thumbnails.count() - 1
                item = QListWidgetItem(str(index + 1))
                item.setSizeHint(QSize(120, 200))
                self.thumbnails.insertItem(index, item)
                self._add_thumbnail_actions(item)
            icons = {}
            for index, version in enumerate(self.pdf.page_versions):
                icon = self._thumbnail_icons.get(version)
                if icon is None:
                    rect = self.pdf.document[index].rect
                    pixmap = self.pdf.render(index, min(120 / rect.width, 160 / rect.height))
                    image = QImage(pixmap.samples, pixmap.width, pixmap.height, pixmap.stride, QImage.Format.Format_RGB888).copy()
                    icon = QIcon(QPixmap.fromImage(image))
                icons[version] = icon
                item = self.thumbnails.item(index)
                if item.icon().cacheKey() != icon.cacheKey():
                    item.setIcon(icon)
            self._thumbnail_icons = icons
            if self.pdf.page_count:
                size = icon.actualSize(self.thumbnails.iconSize())
                self.add_pdf_card.button.setFixedSize(size)
                margin = max(0, (self.add_pdf_card.width() - size.width()) // 2)
                self.add_pdf_card.button.move(margin, margin)
            self._sync_thumbnail_page()
        finally:
            self.thumbnails.blockSignals(False)

    def _add_thumbnail_actions(self, item):
        controls = QWidget()
        column = QVBoxLayout(controls)
        column.setContentsMargins(4, 0, 4, 2)
        column.addStretch()
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        duplicate = self._tool_button(_('Duplikovať stranu'), 'pages',
            lambda: self._thumbnail_action(item, self.duplicate_page), row, button_class=QToolButton)
        duplicate.setObjectName('duplicatePage')
        row.addStretch()
        delete = self._tool_button(_('Odstrániť stranu'), 'close',
            lambda: self._thumbnail_action(item, self.delete_page), row, button_class=QToolButton)
        delete.setObjectName('deletePage')
        for button in (duplicate, delete):
            button.setFixedSize(20, 20)
            button.setIconSize(QSize(12, 12))
        column.addLayout(row)
        self.thumbnails.setItemWidget(item, controls)

    def _thumbnail_action(self, item, callback):
        if self._busy():
            return
        index = self.thumbnails.row(item)
        self.change_page(index)
        if self.page_index == index and not self.pending:
            self._set_thumbnail_pages([index])
            callback()

    def _thumbnail_selected(self, index):
        self.change_page(index)
        if self.pdf and self.pdf.page_count and self.page_index != index:
            self._set_thumbnail_pages([self.page_index])

    def _sync_thumbnail_page(self):
        index = self.page_index if self.pdf.page_count else -1
        if self.thumbnails.currentRow() != index:
            if len(self.thumbnails.selected_pages()) > 1:
                self.thumbnails.setCurrentRow(index, QItemSelectionModel.SelectionFlag.NoUpdate)
            else:
                self.thumbnails.setCurrentRow(index)

    def _set_thumbnail_pages(self, indices):
        blocked = self.thumbnails.blockSignals(True)
        try:
            self.thumbnails.clearSelection()
            self.thumbnails.setCurrentRow(self.page_index if indices else -1, QItemSelectionModel.SelectionFlag.NoUpdate)
            for index in indices:
                self.thumbnails.item(index).setSelected(True)
        finally:
            self.thumbnails.blockSignals(blocked)
        self._update_pagination()

    def _selected_pages(self):
        if not self.pdf or not self.pdf.page_count:
            return []
        return [i for i in self.thumbnails.selected_pages() if i < self.pdf.page_count] or [self.page_index]

    def _thumbnail_menu(self, point):
        item = self.thumbnails.itemAt(point)
        if item is None or item is self.add_pdf_item or self._busy():
            return
        index = self.thumbnails.row(item)
        self.change_page(index)
        if self.page_index == index and not self.pending:
            if not item.isSelected():
                self._set_thumbnail_pages([index])
            self.pages_menu.exec(self.thumbnails.viewport().mapToGlobal(point))

    def _pages_changed(self, index, *, scroll=True, selected=None):
        self.page_index = max(0, min(index, self.pdf.page_count - 1))
        self.region_button.setChecked(False)
        self.cover_button.setChecked(False)
        self.clear_selection()
        self._restart_find()
        self.render_page(fit=self.view.fit_to_width, scroll=scroll)
        self._set_thumbnail_pages((selected or [self.page_index]) if self.pdf.page_count else [])

    def move_pages(self, indices, boundary):
        if not self.pdf or self._busy() or not indices or not self._discard_pending():
            return
        before = self.pdf.page_versions
        try:
            destination = self.pdf.move_pages(indices, boundary)
        except Exception as exc:
            self._error(exc)
            return
        if before == self.pdf.page_versions:
            return
        self._pages_changed(destination, selected=range(destination, destination + len(indices)))
        self.thumbnails.animate_reorder(before, self.pdf.page_versions)
        self.statusBar().showMessage(_('Strany boli presunuté. Presun vrátite pomocou Ctrl+Z.'))

    def _move_selected(self, direction):
        indices = self._selected_pages()
        if indices:
            boundary = indices[0] - 1 if direction < 0 else indices[-1] + 2
            if 0 <= boundary <= self.pdf.page_count:
                self.move_pages(indices, boundary)

    def _rotate_selected(self, angle):
        indices = self._selected_pages()
        if not indices or self._busy() or not self._discard_pending():
            return
        try:
            self.pdf.rotate_pages(indices, angle)
        except Exception as exc:
            self._error(exc)
            return
        active = self.page_index if self.page_index in indices else indices[0]
        self._pages_changed(active, selected=indices)

    def delete_page(self):
        if not self.pdf or self._busy() or not self.pdf.page_count or not self._discard_pending():
            return
        indices = self._selected_pages()
        try:
            self.pdf.delete_pages(indices)
        except Exception as exc:
            self._error(exc)
            return
        self._pages_changed(indices[0])
        self.statusBar().showMessage(_('Strany boli odstránené. Obnovíte ich pomocou Ctrl+Z.'))

    def duplicate_page(self):
        if not self.pdf or self._busy() or not self.pdf.page_count or not self._discard_pending():
            return
        try:
            self.pdf.duplicate_page(self.page_index)
        except Exception as exc:
            self._error(exc)
            return
        self._pages_changed(self.page_index + 1)
        self.statusBar().showMessage(_('Kópia strany bola vložená za pôvodnú stranu.'))

    def insert_pdf(self, checked=False, path=None, *, append=False):
        if not self.pdf or self._busy() or not self._discard_pending():
            return
        if path is None:
            title = _('Pridať PDF na koniec dokumentu') if append else _('Vložiť PDF za aktuálnu stranu')
            path, selected_filter = QFileDialog.getOpenFileName(self, title, '', 'PDF (*.pdf)')
        if not path:
            return
        try:
            index = self.pdf.page_count - 1 if append or not self.pdf.page_count else self.page_index
            try:
                self.pdf.insert_pdf(path, index)
            except SignedPdfError:
                if not self._confirm_signed_pdf():
                    return
                self.pdf.insert_pdf(path, index, allow_signed=True)
        except Exception as exc:
            self._error(exc)
            return
        self._pages_changed(index + 1)
        self.statusBar().showMessage(_('Strany z PDF boli vložené. Výsledok uložte ako PDF.'))

    def refresh_preview(self):
        if not self.pdf or self._busy() or self.view.pixmap_item is None:
            return
        try:
            self._render_visible_pages()
            self.update_selection_preview()
            self._draw_find_hits()
        except Exception as exc:
            self._error(exc)

    def change_page(self, index):
        if not self.pdf or not 0 <= index < self.pdf.page_count or self._busy():
            return
        if not self._discard_pending():
            return
        self.page_index = index
        self.render_page(fit=True, scroll=True, refresh_thumbnails=False)
        self._update_pagination()

    def _update_pagination(self):
        count = self.pdf.page_count if self.pdf else 0
        self.page_label.setText(f'{self.page_index + 1 if count else 0} / {count}')
        self.page_label.setAccessibleName(_('Strana {page} z {count}').format(page=self.page_index + 1 if count else 0, count=count))
        ready = bool(count) and not self._busy()
        self.previous_button.setEnabled(ready and self.page_index > 0)
        self.next_button.setEnabled(ready and self.page_index < count - 1)
        selected = self._selected_pages()
        self.move_up_action.setEnabled(ready and bool(selected) and selected[0] > 0)
        self.move_down_action.setEnabled(ready and bool(selected) and selected[-1] < count - 1)

    def _escape(self):
        if not self.find_bar.isHidden():
            self._close_find()
        else:
            self.cancel_selection()

    def _open_find(self):
        if not self.pdf or not self.pdf.page_count or self._busy():
            return
        if self.find_bar.isHidden():
            self._position_find()
            self.find_bar.raise_()
            self.find_bar.show()
            self._restart_find()
        self.find_input.setFocus()
        self.find_input.selectAll()

    def _position_find(self):
        self.find_bar.move(self.centralWidget().width() - self.find_bar.width() - 14, self.splitter.y() + 8)

    def _close_find(self):
        self.find_bar.hide()
        self._restart_find()
        self.view.setFocus()

    def _restart_find(self, *_):
        self._find_timer.stop()
        self._find_pending.clear()
        self._find_ocr_pages.clear()
        self._find_failed_pages.clear()
        self._find_results.clear()
        self._find_hit = None
        if self.pdf and self.pdf.page_count and not self.find_bar.isHidden() and self.find_input.text().strip():
            count = self.pdf.page_count
            self._find_pending.extend(range(self.page_index, count))
            self._find_pending.extend(range(self.page_index))
            self._find_timer.start(80)
        self._update_find_status()
        self._draw_find_hits()

    def _search_page(self, index):
        query = self.find_input.text().strip()
        version = self.pdf.page_versions[index]
        self._find_failed_pages.discard(index)
        hits = []
        try:
            hits = self.pdf.find_text(index, query)
            if version.ocr_error is not None:
                self._find_failed_pages.add(index)
            elif self._needs_ocr(index):
                self._find_ocr_pages[index] = version
        except (RuntimeError, ValueError):
            self._find_failed_pages.add(index)
        folded = query.casefold()
        native_centers = [(pymupdf.Rect(box).tl + pymupdf.Rect(box).br) / 2 for fragments in hits for box in fragments]
        for line in version.ocr or []:
            box = pymupdf.Rect(line['bbox'])
            if folded in line['text'].casefold() and not any(point in box for point in native_centers):
                hits.append((tuple(box),))
        self._find_results[index] = hits

    def _search_next_pages(self):
        if not self.pdf or self.find_bar.isHidden():
            return
        for _ in range(min(4, len(self._find_pending))):
            self._search_page(self._find_pending.popleft())
        if self._find_pending:
            self._find_timer.start(1)
        if self._find_ocr_pages and not self.ocr_worker:
            self.ocr_timer.start(0)
        self._refresh_find()

    def _find_hits(self):
        return [(index, fragments) for index, hits in sorted(self._find_results.items()) for fragments in hits]

    def _refresh_find(self):
        hits = self._find_hits()
        if hits and self._find_hit not in hits and not self.pending:
            self._show_find_hit(next((hit for hit in hits if hit[0] >= self.page_index), hits[0]))
        else:
            self._update_find_status(hits)
            self._draw_find_hits()

    def _update_find_status(self, hits=None):
        hits = self._find_hits() if hits is None else hits
        self.find_previous.setEnabled(bool(hits))
        self.find_next.setEnabled(bool(hits))
        scanning = bool(self._find_pending or self._find_ocr_pages)
        incomplete = _('Niektoré strany sa nepodarilo prehľadať') if self._find_failed_pages else ''
        if hits:
            number = hits.index(self._find_hit) + 1 if self._find_hit in hits else 0
            status = _('{current} / {total}').format(current=number, total=len(hits))
            if scanning:
                status += ' · ' + _('Hľadám…')
        elif scanning:
            status = _('Hľadám…')
        elif incomplete:
            status = ''
        elif not self.find_bar.isHidden() and self.find_input.text().strip():
            status = _('Žiadne výsledky')
        else:
            status = ''
        message = ' · '.join(filter(None, (status, incomplete)))
        self.find_status.setText(message)
        self.find_status.setVisible(bool(message))
        self.find_bar.adjustSize()

    def _find_rect(self, index, box):
        page = self.view.page_rects[index]
        rect = pymupdf.Rect(box) * self.pdf.document[index].rotation_matrix
        return QRectF(page.x() + rect.x0, page.y() + rect.y0, rect.width, rect.height)

    def _draw_find_hits(self):
        if not self._find_results or not self.view.page_rects:
            if self.view.find_items:
                self.view.show_find_hits([])
            return
        hits = [(self._find_rect(index, box), (index, fragments) == self._find_hit)
                for index in self.view.visible_page_indices()
                for fragments in self._find_results.get(index, ()) for box in fragments]
        self.view.show_find_hits(hits)

    def _show_find_hit(self, hit):
        self._find_hit = hit
        index, fragments = hit
        if index != self.page_index:
            self.page_index = index
            self.render_page(refresh_thumbnails=False)
        self.view.ensureVisible(self._find_rect(index, fragments[0]), 45, 45)
        self._draw_find_hits()
        self._update_find_status()

    def _move_find(self, direction):
        if self.find_bar.isHidden() or self._busy():
            return
        if self.pending:
            self._discard_pending()
            return
        hits = self._find_hits()
        if hits:
            current = hits.index(self._find_hit) + direction if self._find_hit in hits else (0 if direction > 0 else -1)
            self._show_find_hit(hits[current % len(hits)])

    def _region_toggled(self, enabled):
        if enabled:
            self.cover_button.setChecked(False)
        self.view.set_region_mode(enabled, click_to_insert=enabled)
        if self.pdf:
            self.statusBar().showMessage(_('Kliknutím vložte textové pole alebo ho nakreslite ťahaním myši.') if enabled else _('Kliknite na text na strane.'))

    def _cover_toggled(self, enabled):
        if enabled:
            self.region_button.setChecked(False)
        elif self.selection and self.selection.get('kind') == 'area':
            self.clear_selection()
        self.view.set_region_mode(enabled or self.region_button.isChecked(), click_to_insert=self.region_button.isChecked())
        if self.pdf and enabled:
            self.statusBar().showMessage(_('Označte oblasť. Presuňte ju, zmeňte jej veľkosť alebo ju odstráňte klávesom Delete.'))

    def restore_highlight(self):
        if self.selection is None:
            self.view.highlight(None)
            return
        index = self.selection['page_index']
        matrix = self.pdf.document[index].rotation_matrix
        offset = self.view.page_rects[index].topLeft()
        transform = QTransform(matrix.a, matrix.b, matrix.c, matrix.d,
                               matrix.e + offset.x(), matrix.f + offset.y())
        if self.selection.get('kind') == 'area':
            self.view.area_page = index
            self.view.highlight_area(self.selection['bbox'], transform)
        elif 'characters' in self.selection:
            self.view.highlight_characters(self.selection['characters'], transform)
        else:
            self.view.highlight(self.selection['bbox'], transform)

    def update_selection_preview(self):
        if not self.pdf or not self._has_editable_selection():
            self.selection_preview.hide()
            return
        index = self.selection['page_index']
        page = self.pdf.document[index]
        box = pymupdf.Rect(self.selection['bbox']) * page.rotation_matrix
        clip = (box + (-14, -8, 14, 8)) & page.rect
        if clip.is_empty:
            self.selection_preview.hide()
            return
        scale = min(4, math.sqrt(4_000_000 / clip.get_area()))
        pix = self.pdf.render(index, scale, clip=clip)
        image = QImage(pix.samples, pix.width, pix.height, pix.stride, QImage.Format.Format_RGB888).copy()
        painter = QPainter(image)
        painter.setPen(QPen(QColor('#087f83'), max(1, scale)))
        painter.drawRect(QRectF(box.x0 * scale - pix.x, box.y0 * scale - pix.y, box.width * scale, box.height * scale))
        painter.end()
        form = self.editor_panel.widget()
        margins = form.layout().contentsMargins()
        width = max(self.editor_panel.viewport().width(), form.minimumWidth()) - margins.left() - margins.right()
        self.selection_preview.setPixmap(QPixmap.fromImage(image).scaled(
            max(1, width), self.selection_preview.height(),
            Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        self.selection_preview.show()

    def select_text(self, span):
        if not self._discard_pending():
            self.restore_highlight()
            return
        self.selection = {**span, 'page_index': self.page_index}
        self.edit_applied = False
        self.text.blockSignals(True)
        self.font_size.blockSignals(True)
        self.text.setPlainText(span['text'])
        size = round(max(4, min(96, span.get('size', 11))), 1)
        index = self.font_size.findData(size)
        if index < 0:
            index = next((i for i in range(self.font_size.count()) if self.font_size.itemData(i) > size), self.font_size.count())
            self.font_size.insertItem(index, f'{size:g} pt', size)
        self.font_size.setCurrentIndex(index)
        self.text.blockSignals(False)
        self.font_size.blockSignals(False)
        self.pending = False
        self.edit_error.hide()
        self.restore_highlight()
        self.hint.setText(_('Text sa po dopísaní automaticky zmení v náhľade. Delete na strane vymaže výber. PDF uložíte tlačidlom Uložiť PDF.'))
        self._update_actions()
        self.update_selection_preview()
        self.view.setFocus()

    def select_range(self, characters):
        if not self._discard_pending():
            self.restore_highlight()
            return
        if not characters:
            self.clear_selection()
            return
        box = pymupdf.Rect(characters[0]['bbox'])
        content = []
        previous_line = characters[0]['line']
        for char in characters:
            box |= pymupdf.Rect(char['bbox'])
            if char['line'] != previous_line:
                content.append('\n')
            content.append(char['text'])
            previous_line = char['line']
        self.selection = {'characters': characters, 'bbox': tuple(box), 'page_index': self.page_index}
        self.edit_applied = False
        self.pending = False
        self.edit_error.hide()
        self.text.blockSignals(True)
        self.text.setPlainText(''.join(content))
        self.text.blockSignals(False)
        self.restore_highlight()
        self.update_selection_preview()
        self.statusBar().showMessage(_('Označený text vymažete klávesom Delete. Tlačidlom Späť vymazanie vrátite.'))
        self._update_actions()
        self.view.setFocus()

    def select_region(self, bbox):
        if self.cover_button.isChecked():
            if not self._discard_pending():
                self.restore_highlight()
                return
            self.selection = {'kind': 'area', 'bbox': bbox, 'page_index': self.page_index,
                              'source_bbox': bbox, 'source_version': self.pdf.page_versions[self.page_index]}
            self.pending = False
            self.edit_applied = False
            self.text.blockSignals(True)
            self.text.clear()
            self.text.blockSignals(False)
            self.selection_preview.hide()
            self.edit_error.hide()
            self.statusBar().showMessage(_('Oblasť presuňte, zmeňte jej veľkosť alebo ju odstráňte klávesom Delete.'))
            self.restore_highlight()
            self._update_actions()
            self.view.setFocus()
            return
        self.select_text({'text': '', 'bbox': bbox, 'size': min(11, max(4, pymupdf.Rect(bbox).height * 0.65)), 'color': 0, 'insert_only': True})
        if self.selection and self.selection['bbox'] == bbox:
            self.hint.setText(_('Zadajte text do nového poľa. Náhľad sa aktualizuje automaticky.'))
            self._update_actions()
            self.text.setFocus()

    def transform_area(self, bbox):
        if not self.selection or self.selection.get('kind') != 'area':
            return
        previous = self.selection['bbox']
        if pymupdf.Rect(previous) == pymupdf.Rect(bbox):
            return
        index = self.selection['page_index']
        baseline = self.selection.get('baseline') or self.pdf.document.tobytes()
        original = self.selection['source_bbox']
        try:
            self.pdf.transform_region(index, original, bbox, baseline)
        except Exception as exc:
            self.restore_highlight()
            self._error(exc)
            return
        self.selection['baseline'] = baseline
        self.selection['bbox'] = bbox
        affected = () if pymupdf.Rect(original) == pymupdf.Rect(bbox) else (original, bbox)
        self._page_edited(index, self.selection['source_version'].ocr, *affected)
        self.statusBar().showMessage(_('Oblasť bola upravená. Zmenu môžete vrátiť tlačidlom Späť.'))

    def cancel_selection(self, checked=False):
        if self.pending:
            self.apply_change(automatic=True)
        self.region_button.setChecked(False)
        self.cover_button.setChecked(False)
        self.clear_selection()
        self.statusBar().showMessage(_('Výber aj aktívny nástroj boli zrušené.'))

    def clear_selection(self, checked=False):
        self.auto_apply_timer.stop()
        self.view.start_point = None
        self.view.anchor_cursor = None
        self.view.dragging_text = False
        self.view.area_bbox = None
        self.view.area_page = None
        self.view.area_drag = None
        self.view.setCursor(Qt.CursorShape.CrossCursor if self.view.region_mode else Qt.CursorShape.ArrowCursor)
        if self.view.area_preview is not None:
            self.view.scene().removeItem(self.view.area_preview)
            self.view.area_preview = None
        self.selection = None
        self.selection_preview.hide()
        self.pending = False
        self.edit_applied = False
        self.edit_error.hide()
        self.text.clear()
        self.view.highlight(None)
        self.hint.setText(_('Kliknite na text na strane alebo pridajte textové pole ikonou T. Skeny sa rozpoznajú automaticky.'))
        self._update_actions()

    def apply_change(self, automatic=False):
        if not self.pdf or self.selection is None or 'characters' in self.selection or self._busy():
            return False
        self.auto_apply_timer.stop()
        index = self.selection['page_index']
        previous_ocr = self.pdf.page_versions[index].ocr
        try:
            self.pdf.replace_text(index, self.selection['bbox'], self.text.toPlainText(), self.font_size.currentData(), self.selection.get('color', 0), self.white_background.isChecked(), update_previous=self.edit_applied, insert_only=self.selection.get('insert_only', False))
        except Exception as exc:
            self.edit_error.setText(_(ERRORS.get(str(exc), str(exc))))
            self.edit_error.show()
            if not automatic:
                self._error(exc)
            return False
        self.pending = False
        self.edit_applied = True
        self.edit_error.hide()
        self._page_edited(index, previous_ocr, self.selection['bbox'])
        self.statusBar().showMessage(_('Náhľad sa automaticky aktualizoval. PDF uložíte tlačidlom Uložiť PDF.'))
        return True

    def delete_selection(self):
        if not self.pdf or self.selection is None or self._busy():
            return
        self.auto_apply_timer.stop()
        index = self.selection['page_index']
        previous_ocr = self.pdf.page_versions[index].ocr
        try:
            if self.selection.get('kind') == 'area':
                if 'baseline' in self.selection:
                    self.pdf.transform_region(index, self.selection['source_bbox'], None, self.selection['baseline'])
                    previous_ocr = self.selection['source_version'].ocr
                else:
                    self.pdf.cover_region(index, self.selection['bbox'])
            elif 'characters' in self.selection:
                self.pdf.delete_characters(index, self.selection['characters'])
            elif self.selection.get('insert_only') and not self.edit_applied:
                self.clear_selection()
                return
            else:
                self.pdf.replace_text(index, self.selection['bbox'], '', update_previous=self.edit_applied, insert_only=self.selection.get('insert_only', False))
        except Exception as exc:
            self._error(exc)
            return
        box = self.selection.get('source_bbox', self.selection['bbox'])
        self.clear_selection()
        self._page_edited(index, previous_ocr, box)
        self.statusBar().showMessage(_('Výber bol vymazaný. Vymazanie vrátite tlačidlom Späť alebo Ctrl+Z.'))

    def _page_edited(self, index, previous_ocr, *boxes):
        if previous_ocr is not None:
            affected = [pymupdf.Rect(box) for box in boxes]
            self.pdf.page_versions[index].ocr = [line for line in previous_ocr if not any(
                rect.intersects(pymupdf.Rect(line['bbox'])) for rect in affected)]
        self._restart_find()
        self.render_page()

    def _navigate_history(self, operation):
        before = self.pdf.page_versions
        version = before[self.page_index] if before else None
        if not operation():
            return False
        index = self.pdf.page_versions.index(version) if version in self.pdf.page_versions else self.page_index
        self._pages_changed(index, scroll=index != self.page_index or self.pdf.page_count != len(self.view.page_rects))
        self.thumbnails.animate_reorder(before, self.pdf.page_versions)
        return True

    def undo(self):
        if not self.pdf or self._busy():
            return
        self.auto_apply_timer.stop()
        if self.pending and not self.edit_applied:
            self.clear_selection()
            self.render_page()
            return
        if self._navigate_history(self.pdf.undo):
            self.statusBar().showMessage(_('Posledná zmena bola vrátená späť.'))

    def redo(self):
        if not self.pdf or self._busy() or not self.pdf.can_redo:
            return
        self.auto_apply_timer.stop()
        if self._navigate_history(self.pdf.redo):
            self.statusBar().showMessage(_('Zmena bola znovu vykonaná.'))

    def save_copy(self, *, searchable=False):
        if not self.pdf or self._busy():
            return False
        if not self.pdf.page_count:
            self._error(ValueError('The document has no pages.'))
            return False
        if self.pending and not self.apply_change():
            return False
        suffix = _('upravene')
        target = self.pdf.source.with_name(self.pdf.source.stem + f'_{suffix}.pdf')
        number = 2
        while target.exists():
            target = self.pdf.source.with_name(f'{self.pdf.source.stem}_{suffix}_{number}.pdf')
            number += 1
        title = _('Uložiť ako prehľadávateľné PDF…') if searchable else _('Uložiť PDF')
        filename, selected_filter = QFileDialog.getSaveFileName(self, title, str(target), 'PDF (*.pdf)', options=QFileDialog.Option.DontConfirmOverwrite)
        if not filename:
            return False
        if not filename.lower().endswith('.pdf'):
            filename += '.pdf'
        try:
            replacing = self.pdf.source.suffix.casefold() == '.pdf' and Path(filename).resolve() == self.pdf.source
            if replacing:
                answer = QMessageBox.question(self, _('Nahradiť pôvodné PDF?'),
                                              _('Nahradiť pôvodný súbor {filename} upraveným PDF?').format(filename=self.pdf.source.name),
                                              QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                              QMessageBox.StandardButton.No)
                if answer != QMessageBox.StandardButton.Yes:
                    return False
            searchable = searchable or (replacing and self.pdf.searchable_source)
            if searchable and not self._prepare_searchable():
                return False
            self.pdf.save_copy(filename, replace_source=replacing, searchable=searchable)
        except Exception as exc:
            self._error(exc)
            return False
        self._update_actions()
        self.statusBar().showMessage(_('Uložené: {filename}').format(filename=filename))
        return True

    def _prepare_searchable(self):
        self._searchable_pages.extend(range(self.pdf.page_count))
        self._searchable_error = None
        for version in self.pdf.page_versions:
            version.ocr_error = None
        progress = QProgressDialog(_('Pripravujem prehľadávateľné PDF…'), _('Zrušiť'), 0, self.pdf.page_count, self)
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setMinimumDuration(0)
        progress.setAutoClose(False)
        progress.setAutoReset(False)
        self._searchable_progress = progress
        self.ocr_timer.start(0)
        try:
            accepted = progress.exec() == QProgressDialog.DialogCode.Accepted
        finally:
            self._searchable_progress = None
            self._searchable_pages.clear()
            progress.deleteLater()
            self._update_actions()
        if not accepted and self.ocr_worker:
            self.ocr_worker.requestInterruption()
        if self._searchable_error:
            raise ValueError(self._searchable_error)
        return accepted

    def _needs_ocr(self, index, native=None):
        version = self.pdf.page_versions[index]
        if version.ocr is not None or version.ocr_error is not None:
            return False
        if version.needs_ocr is None:
            if native is None:
                native = self.pdf.spans(index)
            page = self.pdf.document[index]
            bounds = page.rect * page.derotation_matrix
            # Edited scans can contain native text over the original full-page image.
            version.needs_ocr = not native or any(
                (bounds & pymupdf.Rect(image['bbox'])).get_area() >= bounds.get_area() * 0.8
                for image in page.get_image_info())
        return version.needs_ocr

    def _start_next_ocr(self):
        if not self.pdf or not self.pdf.page_count or self.ocr_worker or self._closing_after_update:
            return
        if self._searchable_progress is not None:
            self._advance_searchable()
            return
        if self._install_pending:
            return
        index = self.page_index if self._needs_ocr(self.page_index) else next(iter(self._find_ocr_pages), None)
        if index is not None:
            self._auto_ocr(self.pdf, index)

    def _advance_searchable(self):
        progress = self._searchable_progress
        if progress.wasCanceled():
            return
        if not self._searchable_pages:
            progress.accept()
            return
        index = self._searchable_pages[0]
        try:
            version = self.pdf.page_versions[index]
            if version.ocr_error is not None:
                raise ValueError(version.ocr_error)
            if self._needs_ocr(index):
                self._auto_ocr(self.pdf, index)
                return
        except Exception as exc:
            self._searchable_error = _('Stranu {page} sa nepodarilo prehľadať. {error}').format(page=index + 1, error=exc)
            progress.reject()
            return
        self._searchable_pages.popleft()
        progress.setValue(self.pdf.page_count - len(self._searchable_pages))
        self.ocr_timer.start(0)

    def _auto_ocr(self, document, index):
        if self.pdf is not document or self.ocr_worker or not self._needs_ocr(index):
            return
        try:
            worker = OcrWorker(document, index, self)
        except Exception as exc:
            document.page_versions[index].ocr_error = str(exc)
            self._find_ocr_pages.pop(index, None)
            if index in self._find_results:
                self._find_failed_pages.add(index)
            self.statusBar().showMessage(_('Automatické rozpoznanie textu zlyhalo: {message}').format(message=exc))
            self._update_find_status()
            self.ocr_timer.start(0)
            return
        self.ocr_worker = worker
        worker.completed.connect(self._ocr_completed)
        worker.failed.connect(self._ocr_failed)
        worker.finished.connect(self._ocr_finished)
        if index == self.page_index:
            self.statusBar().showMessage(_('Rozpoznávam text tejto strany pomocou Windows OCR…'))
        worker.start()

    def _ocr_completed(self, lines):
        worker = self.sender()
        if worker is None or worker is not self.ocr_worker or worker.isInterruptionRequested():
            return
        areas = []
        for line in lines:
            image_rect = pymupdf.Rect([value / worker.scale for value in line['bbox']])
            rect = image_rect * worker.derotation
            rect = pymupdf.Rect(rect.x0 - 1, rect.y0 - 2, rect.x1 + 1, rect.y1 + 2) & worker.bounds
            if rect.is_empty or any(rect.intersects(box) for box in worker.native):
                continue
            areas.append({'text': line['text'], 'bbox': tuple(rect), 'size': max(4, image_rect.height * 0.9),
                          'color': 0, 'rotation': worker.rotation})
        worker.version.ocr = areas
        self._ocr_page_updated(worker)
        if self.pdf is worker.document and self.pdf.page_count and worker.version is self.pdf.page_versions[self.page_index]:
            self.render_page(refresh_thumbnails=False)
            self.statusBar().showMessage(_('OCR dokončené: {count} oblastí zo skenu. Kliknite na text; rozpoznané údaje pred uložením skontrolujte.').format(count=len(areas)))

    def _ocr_page_updated(self, worker):
        if self.pdf is worker.document and worker.version in self.pdf.page_versions:
            index = self.pdf.page_versions.index(worker.version)
            self._find_ocr_pages.pop(index, None)
            if index in self._find_results:
                self._search_page(index)
            self._refresh_find()

    def _ocr_failed(self, message):
        worker = self.sender()
        if worker is not None:
            if worker is not self.ocr_worker or worker.isInterruptionRequested():
                return
            worker.version.ocr_error = message
            self._ocr_page_updated(worker)
            if not self.pdf or not self.pdf.page_count or self.pdf.page_versions[self.page_index] is not worker.version:
                return
        self.hint.setText(_('Text sa nepodarilo automaticky rozpoznať. Môžete pridať textové pole alebo zakryť oblasť.'))
        self.statusBar().showMessage(_('Automatické rozpoznanie textu zlyhalo: {message}').format(message=message))

    def _ocr_finished(self):
        worker = self.sender()
        if worker is None or worker is not self.ocr_worker:
            return
        self.ocr_worker = None
        worker.temp.cleanup()
        worker.deleteLater()
        self.ocr_timer.start(0)

    def _stop_ocr(self):
        self.ocr_timer.stop()
        if self.ocr_worker:
            worker, self.ocr_worker = self.ocr_worker, None
            worker.requestInterruption()
            worker.wait()
            worker.temp.cleanup()
            worker.deleteLater()

    def show_about(self):
        QMessageBox.about(self, _('O aplikácii {name}').format(name=APP_NAME),
            _('<b>{name} {version}</b><p>Editor PDF pre Windows.</p><p>Copyright © 2026 hudakjakub a prispievatelia.<br>GNU AGPL v3. Bez záruky. Program môžete upravovať a ďalej šíriť podľa licencie.</p><p><a href="{url}/tree/v{version}">Zdrojový kód</a> · <a href="{url}/blob/v{version}/LICENSE">Licencia</a></p>').format(name=APP_NAME, version=VERSION, url=PROJECT_URL))

    def _automatic_updates_toggled(self, enabled):
        self.settings.setValue('updates/automatic', enabled)
        if enabled and getattr(sys, 'frozen', False):
            self.update_timer.start()
            self.check_updates(automatic=True)
        else:
            self.update_timer.stop()

    def check_updates(self, checked=False, *, automatic=False):
        if self._closing_after_update or (automatic and not self.auto_update_action.isChecked()):
            return
        if self.update_worker is not None:
            return
        if self.ready_update is not None:
            if not automatic:
                self._offer_update()
            return
        self._update_manual = not automatic
        self.check_updates_action.setEnabled(False)
        self.check_updates_action.setText(_('Kontrolujú sa aktualizácie…'))
        self._start_update_worker()

    def _start_update_worker(self, verification=None):
        self.update_worker = UpdateWorker(self, verification)
        self.update_worker.completed.connect(self._update_completed)
        self.update_worker.failed.connect(self._update_failed)
        self.update_worker.downloading.connect(lambda: self.check_updates_action.setText(_('Sťahuje sa aktualizácia…')))
        self.update_worker.finished.connect(self._update_finished)
        self.update_worker.start()

    def _update_completed(self, result):
        if self._closing_after_update:
            return
        if self._install_pending:
            self._verified_update = result
            return
        release, installer = result
        if release is None:
            if self._update_manual:
                QMessageBox.information(self, _('Aktualizácie'), _('{name} {version} je aktuálna verzia.').format(name=APP_NAME, version=VERSION))
            return
        if installer is None:
            answer = QMessageBox.question(self, _('Nová verzia'),
                _('Je dostupná verzia {version}. Otvoriť stránku vydania?').format(version=release.version),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            if answer == QMessageBox.StandardButton.Yes:
                QDesktopServices.openUrl(QUrl(f'{PROJECT_URL}/releases/tag/v{release.version}'))
            return
        self.ready_update = (release, installer)
        self.statusBar().showMessage(_('Aktualizácia {version} je pripravená na inštaláciu.').format(version=release.version))

    def _update_failed(self, message):
        if self._install_pending:
            self.ready_update = None
        if not self._closing_after_update and (self._update_manual or self._install_pending):
            QMessageBox.warning(self, _('Aktualizácie'), _('Aktualizáciu sa nepodarilo overiť alebo stiahnuť. Skontrolujte pripojenie a skúste to znova.'))

    def _update_finished(self):
        worker = self.update_worker
        self.update_worker = None
        worker.deleteLater()
        skip_offer = self._skip_update_offer
        self._skip_update_offer = False
        self.centralWidget().setEnabled(True)
        self.check_updates_action.setEnabled(True)
        self.check_updates_action.setText(_('Nainštalovať aktualizáciu…') if self.ready_update else _('Skontrolovať aktualizácie…'))
        if self._closing_after_update:
            self.close()
        elif self._install_pending:
            if self._verified_update is not None:
                self._launch_update()
            self._install_pending = False
            self._verified_update = None
            self.ocr_timer.start(0)
        elif self.ready_update is not None and not skip_offer:
            self._offer_update()

    def _offer_update(self):
        if self._busy() or self._install_pending:
            return
        self._install_pending = True
        release, installer = self.ready_update
        executable_dir = Path(sys.executable).resolve().parent
        local = Path(os.environ.get('LOCALAPPDATA', str(Path.home() / 'AppData' / 'Local')))
        installed = (executable_dir / 'unins000.exe').is_file()
        self._install_directory = executable_dir if installed else local / 'Programs' / 'OmniPDF'
        message = _('Nainštalovať Omni PDF {version} a reštartovať aplikáciu? Pred reštartom budete môcť uložiť rozpracované PDF.').format(version=release.version)
        if not installed:
            message += _('\n\nPrenosná aplikácia sa nainštaluje do:\n{directory}\nExistujúca inštalácia v tomto priečinku sa aktualizuje. Pôvodný prenosný EXE zostane zachovaný.').format(directory=self._install_directory)
        answer = QMessageBox.question(self, _('Aktualizácia je pripravená'),
            message,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
        if answer != QMessageBox.StandardButton.Yes or self._busy() or not self._leave_document():
            self._install_pending = False
            self.ocr_timer.start(0)
            return
        self.centralWidget().setEnabled(False)
        self.check_updates_action.setEnabled(False)
        self.check_updates_action.setText(_('Overuje sa inštalátor…'))
        self._start_update_worker(verification=self.ready_update)

    def _launch_update(self):
        if self._busy():
            return
        release, installer = self._verified_update
        try:
            updates.launch_installer(installer, self._install_directory, os.getpid())
        except updates.UpdateError:
            self.ready_update = None
            self.check_updates_action.setText(_('Skontrolovať aktualizácie…'))
            QMessageBox.warning(self, _('Aktualizácia'), _('Inštalátor sa nepodarilo bezpečne spustiť. Skúste aktualizáciu znova.'))
            return
        self._close_approved = True
        if not self.close():
            self._close_approved = False

    def closeEvent(self, event):
        if self._install_pending and self.update_worker is not None:
            self.update_worker.requestInterruption()
            self._install_pending = False
            self._verified_update = None
            self._skip_update_offer = True
        if self._busy():
            QMessageBox.information(self, _('Rozpoznávanie textu'), _('Počkajte na dokončenie rozpoznávania textu.'))
            event.ignore()
        elif self._close_approved or self._leave_document():
            self.auto_apply_timer.stop()
            self.scroll_sync_timer.stop()
            self.view.raster_timer.stop()
            self._find_timer.stop()
            self._stop_ocr()
            if self.update_worker is not None:
                self._close_approved = True
                self._closing_after_update = True
                self.update_timer.stop()
                self.update_worker.requestInterruption()
                self.hide()
                event.ignore()
                return
            self.update_timer.stop()
            if self.pdf:
                self.pdf.close()
                self.pdf = None
            QApplication.instance().removeEventFilter(self)
            event.accept()
        else:
            event.ignore()


STYLE = '''
QWidget { font-family: "Segoe UI"; font-size: 13px; color: #243642; }
QMainWindow, QDialog, #panel { background: #ffffff; }
QToolTip { background: #ffffff; color: #243642; border: 1px solid #cad5dc; padding: 5px 8px; }
#tools { background: #f2f4f6; border-bottom: 1px solid #d4dce2; }
#findBar { background: #ffffff; border: 1px solid #dce3e8; border-radius: 9px; }
#findInput { padding: 4px 8px; }
#findStatus { color: #5e6f79; font-size: 12px; padding-left: 6px; }
#toolbarSeparator { background: #d4dce2; }
#muted { color: #5e6f79; }
#filename { color: #64737e; }
#paneltitle { font-size: 21px; font-weight: 600; }
#editorPanel { background: #ffffff; }
#thumbnails { background: #f5f8fa; border: none; border-right: 1px solid #dce3e8; }
#thumbnails::item { color: #243642; border: 1px solid transparent; border-radius: 4px; }
#thumbnails::item:selected { background: #dcefee; color: #07686c; border-color: #087f83; }
QPushButton#appendPdf { color: #8b9aa3; background: #ffffff; border: 2px dashed #b8c2ca; border-radius: 3px; padding: 0; font-size: 64px; font-weight: 400; }
QPushButton#appendPdf:hover, QPushButton#appendPdf:focus, QPushButton#appendPdf[dragActive="true"] { color: #087f83; border-color: #087f83; background: #eef8f7; }
QPushButton#appendPdf:disabled { color: #b8c2ca; background: #f5f8fa; border-color: #dce3e8; }
QMenu { background: #ffffff; color: #243642; border: 1px solid #cad5dc; padding: 4px; }
QMenu::item { background: transparent; color: #243642; padding: 7px 20px; }
QMenu::item:selected { background: #dcefee; color: #07686c; }
QMenu::item:disabled { color: #8b9aa3; }
QMenu::separator { height: 1px; background: #dce3e8; margin: 4px 8px; }
QComboBox QAbstractItemView { background: #ffffff; color: #243642; selection-background-color: #dcefee; selection-color: #07686c; }
QPushButton { background: #ffffff; border: 1px solid #cad5dc; border-radius: 5px; padding: 9px 14px; font-weight: 600; }
QPushButton:hover { background: #eef5f5; border-color: #087f83; }
QPushButton:checked { color: #07686c; background: #dcf0ef; border-color: #087f83; }
QPushButton#primary { color: #ffffff; background: #087f83; border: 1px solid #087f83; }
QPushButton#primary:hover { background: #07676b; }
QPushButton:disabled, QPushButton#primary:disabled { color: #8b9aa3; background: #eef2f4; border-color: #dce3e8; }
QPushButton:focus, QTextEdit:focus, QComboBox:focus { border: 2px solid #087f83; }
QToolButton { border: 1px solid transparent; border-radius: 2px; background: transparent; padding: 3px; }
QToolButton:hover, QToolButton:focus { border-color: #087f83; background: #eef5f5; }
#tools QToolButton { padding: 2px; }
#tools QToolButton:!checked:hover, #tools QToolButton:!checked:focus { border-color: transparent; background: transparent; }
#tools QToolButton:!checked:focus:!hover { background: #dce3e8; }
QToolButton:checked { border-color: #087f83; background: #dcefee; }
QToolButton:disabled { border-color: transparent; background: transparent; }
QToolButton::menu-indicator { image: none; }
QTextEdit, QLineEdit, QComboBox { background: #ffffff; border: 1px solid #cad5dc; border-radius: 5px; padding: 8px; selection-background-color: #bce1e0; }
QComboBox#fontSize { padding: 2px 6px; }
QCheckBox { spacing: 6px; }
QCheckBox:disabled { color: #8b9aa3; }
QCheckBox::indicator { width: 16px; height: 16px; border: 1px solid #8b9aa3; border-radius: 3px; background: #ffffff; }
QCheckBox::indicator:checked { background: #087f83; border-color: #087f83; image: url("__CHECK_MARK__"); }
QCheckBox::indicator:unchecked:hover, QCheckBox::indicator:focus { border-color: #087f83; }
QCheckBox::indicator:checked:hover { background: #07676b; border-color: #07676b; }
QCheckBox::indicator:disabled { background: #eef2f4; border-color: #cad5dc; }
QCheckBox::indicator:checked:disabled { background: #8b9aa3; border-color: #8b9aa3; }
QTextEdit:disabled { background: #f5f8fa; }
QScrollBar { background: #f2f4f6; border: none; }
QScrollBar:vertical { width: 12px; }
QScrollBar:horizontal { height: 12px; }
QScrollBar::handle { background: #b8c2ca; border: 3px solid #f2f4f6; border-radius: 5px; }
QScrollBar::handle:vertical { min-height: 28px; }
QScrollBar::handle:horizontal { min-width: 28px; }
QScrollBar::handle:hover { background: #8b9aa3; }
QScrollBar::handle:pressed { background: #607d8b; }
QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; border: none; background: transparent; }
QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }
QAbstractScrollArea::corner { background: #f2f4f6; border: none; }
QSplitter::handle { background: #dce3e8; width: 1px; }
QStatusBar { background: #f8fafb; border-top: 1px solid #dce3e8; color: #5e6f79; padding: 5px 12px; }
#headline { font-size: 34px; font-weight: 600; padding: 15px; }
#dropZone { border: 2px dashed #b8c8d0; border-radius: 8px; background: #ffffff; }
#dropZone[dragActive="true"] { border-color: #087f83; background: #eef8f7; }
#subtitle { font-size: 16px; color: #5e6f79; padding-bottom: 25px; }
QMessageBox { background: #ffffff; }
'''.replace('__CHECK_MARK__', (APP_ICON.parent / 'check.svg').as_posix())


def apply_light_theme(application):
    application.styleHints().setColorScheme(Qt.ColorScheme.Light)
    application.setAttribute(Qt.ApplicationAttribute.AA_DontUseNativeDialogs, True)
    application.setStyle('Fusion')
    palette = application.style().standardPalette()
    for role, color in (
        (QPalette.ColorRole.Window, '#ffffff'),
        (QPalette.ColorRole.WindowText, '#243642'),
        (QPalette.ColorRole.Base, '#ffffff'),
        (QPalette.ColorRole.AlternateBase, '#f5f8fa'),
        (QPalette.ColorRole.Text, '#243642'),
        (QPalette.ColorRole.Button, '#ffffff'),
        (QPalette.ColorRole.ButtonText, '#243642'),
        (QPalette.ColorRole.ToolTipBase, '#ffffff'),
        (QPalette.ColorRole.ToolTipText, '#243642'),
        (QPalette.ColorRole.Highlight, '#dcefee'),
        (QPalette.ColorRole.HighlightedText, '#07686c'),
        (QPalette.ColorRole.Link, '#087f83'),
        (QPalette.ColorRole.LinkVisited, '#07676b'),
        (QPalette.ColorRole.PlaceholderText, '#8b9aa3'),
        (QPalette.ColorRole.Accent, '#087f83'),
    ):
        palette.setColor(role, QColor(color))
    for role in (QPalette.ColorRole.WindowText, QPalette.ColorRole.Text, QPalette.ColorRole.ButtonText):
        palette.setColor(QPalette.ColorGroup.Disabled, role, QColor('#8b9aa3'))
    application.setPalette(palette)
    application.setStyleSheet(STYLE)


def smoke_test(application, output):
    result = {'app_name': APP_NAME, 'version': VERSION, 'frozen': bool(getattr(sys, 'frozen', False)),
              'qt_platform': application.platformName(), 'mupdf_version': pymupdf.VersionFitz,
              'resources_ok': False, 'pdf_render_ok': False, 'ocr_ok': False}
    try:
        root = Path(__file__).resolve().parent
        result['resources_ok'] = all((root / path).is_file() for path in
            ('assets/omni.svg', 'assets/check.svg', 'windows_ocr.ps1', 'LICENSE', 'THIRD_PARTY_NOTICES.md'))
        with tempfile.TemporaryDirectory(prefix='omnipdf-smoke-') as directory:
            source = Path(directory) / 'source.pdf'
            with pymupdf.open() as document:
                document.new_page().insert_text((50, 80), 'Original text', fontsize=12)
                document.save(source)
            editor = Editor()
            def fail(error):
                raise error
            editor._error = fail
            editor.open_file(path=source)
            span = editor.pdf.spans(0)[0]
            editor.pdf.replace_text(0, span['bbox'], 'New text', fontsize=12)
            editor.pdf.save_copy(Path(directory) / 'copy.pdf')
            pixmap = editor.pdf.render(0)
            result['pdf_render_ok'] = pixmap.width > 0 and 'New text' in editor.pdf.document[0].get_text()
            editor.pdf.close()
            editor.pdf = None
            editor.close()
            scan = Path(directory) / 'scan.png'
            with pymupdf.open() as document:
                page = document.new_page(width=420, height=140)
                page.insert_text((36, 80), 'INVOICE 12345', fontsize=32)
                page.get_pixmap(matrix=pymupdf.Matrix(2, 2)).save(scan)
            lines = recognize(scan)
            result['ocr_ok'] = any('12345' in line['text'] and pymupdf.Rect(line['bbox']).get_area() > 0 for line in lines)
        result['resources_ok'] = result['resources_ok'] and not QIcon(str(APP_ICON)).isNull()
    except Exception as exc:
        result['error'] = str(exc)
    if output:
        Path(output).write_text(json.dumps(result, ensure_ascii=False), encoding='utf-8')
    return 0 if result['resources_ok'] and result['pdf_render_ok'] and result['ocr_ok'] else 1


def main():
    parser = argparse.ArgumentParser(description='Omni PDF editor')
    parser.add_argument('file', nargs='?')
    parser.add_argument('--smoke-test', action='store_true')
    parser.add_argument('--output')
    arguments = parser.parse_args()
    set_app_id()
    application = QApplication(sys.argv)
    configure_language(application)
    application.setApplicationName(APP_NAME)
    application.setApplicationDisplayName(APP_NAME)
    application.setApplicationVersion(VERSION)
    application.setWindowIcon(QIcon(str(APP_ICON)))
    apply_light_theme(application)
    if arguments.smoke_test:
        return smoke_test(application, arguments.output)
    mutex = create_app_mutex()
    try:
        editor = Editor()
        editor.show()
        if arguments.file:
            editor.open_file(path=arguments.file)
        return application.exec()
    finally:
        release_app_mutex(mutex)


if __name__ == '__main__':
    sys.exit(main())
