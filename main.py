"""Local Windows editor for PDFs and scanned documents."""
import math
import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

import pymupdf
from PySide6.QtCore import QEasingCurve, QEvent, QPropertyAnimation, QRectF, QSettings, QSize, Qt, QThread, QTimer, QUrl, Signal
from PySide6.QtGui import QAction, QColor, QDesktopServices, QIcon, QImage, QKeySequence, QPainter, QPainterPath, QPalette, QPen, QPixmap, QTransform
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QFileDialog, QFrame,
    QGraphicsDropShadowEffect, QGraphicsScene, QGraphicsView, QGridLayout, QHBoxLayout, QLabel, QMainWindow,
    QMenu, QMessageBox, QPushButton, QScrollArea, QSizePolicy, QSplitter, QStyledItemDelegate,
    QStyle, QStyleOptionViewItem, QTextEdit, QToolButton, QVBoxLayout, QWidget,
)
from PySide6.QtWidgets import QListWidget, QListWidgetItem

from pdf_document import PdfDocument
from windows_ocr import recognize
from app_info import APP_NAME, VERSION, PROJECT_URL
import updates
from window_chrome import configure_title_bar, set_app_id, create_app_mutex, release_app_mutex


APP_ICON = Path(__file__).with_name('assets') / 'omni.svg'


ERRORS = {
    'Encrypted PDFs are not supported.': 'PDF je chránené heslom. Otvorte odomknutú kópiu.',
    'The PDF is damaged and required repair.': 'PDF je poškodené. Skúste ho znova exportovať.',
    'This PDF does not permit editing.': 'Toto PDF má zakázané úpravy.',
    'Digitally signed PDFs are not supported.': 'Digitálne podpísané PDF nie je možné upraviť bez zneplatnenia podpisu.',
    'PDFs with signature fields are not supported.': 'Toto PDF obsahuje digitálny podpis.',
    'Only PDF, JPG and PNG files are supported.': 'Vyberte PDF alebo obrázok vo formáte JPG či PNG.',
    'The document has no pages.': 'Dokument nemá žiadnu stranu.',
    'Select a valid page.': 'Vyberte platnú stranu.',
    'Only PDF files can be inserted.': 'Na vloženie ďalších strán vyberte PDF súbor.',
    'Select a valid area inside the page.': 'Označte oblasť vnútri strany.',
    'Enter valid text and font size.': 'Zadajte platný text a veľkosť písma.',
    'The selected area overlaps neighboring text.': 'Okraj oblasti zasahuje do susedného textu. Označte celý text alebo zmenšite oblasť.',
    'The replacement text does not fit in the selected area.': 'Text sa nezmestí do oblasti. Zmenšite písmo alebo označte väčšiu oblasť.',
    'The original file cannot be overwritten.': 'Originál sa neprepisuje. Vyberte nový názov PDF.',
    'Choose a new output file; existing files cannot be overwritten.': 'Tento súbor už existuje. Vyberte nový názov PDF.',
    'The saved PDF could not be verified.': 'Uložené PDF sa nepodarilo overiť.',
    'The selected text is no longer available.': 'Výber už nie je aktuálny. Označte text znova.',
    'Select text to delete.': 'Najprv označte text, ktorý chcete vymazať.',
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
        self.setAccessibleName('Strana PDF. Ťahaním označte text, klávesom Delete ho vymažte.')
        self.areas = []
        self.characters = []
        self.page_rect = QRectF()
        self.rotation = pymupdf.Matrix(1, 1)
        self.derotation = pymupdf.Matrix(1, 1)
        self.selection_item = None
        self.area_bbox = None
        self.area_page = None
        self.area_drag = None
        self.area_preview = None
        self.start_point = None
        self.region_mode = False
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

    def set_region_mode(self, enabled):
        self.region_mode = enabled
        self.setCursor(Qt.CursorShape.CrossCursor if enabled else Qt.CursorShape.ArrowCursor)

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
        if self.region_mode and self.area_bbox is not None and self.area_page == self.active_index:
            rect = self.display_rect(self.area_bbox)
            margin = 6 / self.transform().m11()
            if rect.adjusted(-margin, -margin, margin, margin).contains(point):
                x = -1 if abs(point.x() - rect.left()) <= margin else 1 if abs(point.x() - rect.right()) <= margin else 0
                y = -1 if abs(point.y() - rect.top()) <= margin else 1 if abs(point.y() - rect.bottom()) <= margin else 0
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
            self.start_point = None
            if rect.width() >= 6 and rect.height() >= 6:
                bbox = pymupdf.Rect(rect.x() - self.page_rect.x(), rect.y() - self.page_rect.y(), rect.right() - self.page_rect.x(), rect.bottom() - self.page_rect.y()) * self.derotation
                self.region.emit(tuple(bbox))
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

    def __init__(self, image_path, parent):
        super().__init__(parent)
        self.image_path = image_path

    def run(self):
        try:
            self.completed.emit(recognize(self.image_path))
        except Exception as exc:
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


class AppendPdfCard(QWidget):
    def __init__(self, callback):
        super().__init__()
        self.button = QPushButton('+', self)
        self.button.setObjectName('appendPdf')
        self.button.setFixedSize(114, 160)
        self.button.setToolTip('Pridať PDF na koniec — kliknite alebo sem pretiahnite PDF')
        self.button.setAccessibleName('Pridať PDF na koniec dokumentu')
        self.button.clicked.connect(callback)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        margin = max(0, (self.width() - self.button.width()) // 2)
        self.button.move(margin, margin)


class Editor(QMainWindow):
    def __init__(self):
        super().__init__()
        self.pdf = None
        self.page_index = 0
        self.selection = None
        self.ocr_areas = {}
        self.ocr_attempted = set()
        self.ocr_worker = None
        self.ocr_temp = None
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
        logo = QLabel()
        logo.setObjectName('brandLogo')
        logo.setFixedSize(24, 24)
        logo.setPixmap(self.windowIcon().pixmap(QSize(24, 24)))
        logo.setAccessibleName(f'Logo {APP_NAME}')
        row.addWidget(logo)
        brand = QToolButton()
        brand.setText(APP_NAME)
        brand.setObjectName('brand')
        brand.setToolTip(f'{APP_NAME} {VERSION}')
        brand.setAccessibleName('Ponuka aplikácie Omni PDF')
        self.app_menu = QMenu(self)
        self.app_menu.addAction('O aplikácii…', self.show_about)
        self.check_updates_action = self.app_menu.addAction('Skontrolovať aktualizácie…', self.check_updates)
        self.auto_update_action = self.app_menu.addAction('Automatické aktualizácie')
        self.auto_update_action.setCheckable(True)
        self.auto_update_action.setChecked(self.settings.value('updates/automatic', True, type=bool))
        self.auto_update_action.setEnabled(bool(getattr(sys, 'frozen', False)))
        self.auto_update_action.toggled.connect(self._automatic_updates_toggled)
        brand.setMenu(self.app_menu)
        brand.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        row.addWidget(brand)
        logo.setToolTip(f'{APP_NAME} · Editor PDF\nSúbory zostávajú v počítači')
        self.file_label = QLabel('PDF, JPG alebo PNG')
        self.file_label.setObjectName('filename')
        self.file_label.setMinimumWidth(80)
        self.file_label.setMaximumWidth(160)
        self.file_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        row.addWidget(self.file_label, 1)
        self.open_button = self._tool_button('Otvoriť súbor (Ctrl+O)', 'open', self.open_file, row)
        self.save_button = self._tool_button('Uložiť kópiu (Ctrl+Shift+S)', 'save', self.save_copy, row)
        self._toolbar_separator(row)
        self.undo_button = self._tool_button('Späť (Ctrl+Z)', 'undo', self.undo, row)
        self.redo_button = self._tool_button('Dopredu (Ctrl+Y)', 'redo', self.redo, row)
        row.addStretch()
        toolbar_layout.addLayout(row, 0, 0)
        navigation = QHBoxLayout()
        navigation.setSpacing(3)
        self.previous_button = self._tool_button('Predchádzajúca strana', 'previous', lambda: self.change_page(self.page_index - 1), navigation)
        self.page_label = QLabel('0 / 0')
        self.page_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        navigation.addWidget(self.page_label)
        self.next_button = self._tool_button('Nasledujúca strana', 'next', lambda: self.change_page(self.page_index + 1), navigation)
        toolbar_layout.addLayout(navigation, 0, 1, Qt.AlignmentFlag.AlignCenter)
        bar = QHBoxLayout()
        bar.setSpacing(3)
        self.pages_button = self._tool_button('Spravovať strany', 'pages', None, bar)
        self.pages_menu = QMenu(self)
        self.duplicate_page_action = self.pages_menu.addAction('Duplikovať aktuálnu stranu', self.duplicate_page)
        self.delete_page_action = self.pages_menu.addAction('Odstrániť aktuálnu stranu', self.delete_page)
        self.pages_menu.addSeparator()
        self.insert_pdf_action = self.pages_menu.addAction('Vložiť PDF za aktuálnu stranu…', self.insert_pdf)
        self.pages_button.setMenu(self.pages_menu)
        self.pages_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self._toolbar_separator(bar)
        self.region_button = self._tool_button('Pridať textové pole', 'text', None, bar)
        self.region_button.setCheckable(True)
        self.region_button.toggled.connect(self._region_toggled)
        self.cover_button = self._tool_button('Vybrať oblasť', 'cover', None, bar)
        self.cover_button.setCheckable(True)
        self.cover_button.toggled.connect(self._cover_toggled)
        self._toolbar_separator(bar)
        self.minus_button = self._tool_button('Oddialiť', 'minus', lambda: self.view.zoom(0.8), bar)
        self.zoom_label = QLabel('100 %')
        self.zoom_label.setObjectName('zoomLevel')
        self.zoom_label.setMinimumWidth(42)
        self.zoom_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.zoom_label.setToolTip('Zväčšenie dokumentu')
        bar.addWidget(self.zoom_label)
        self.plus_button = self._tool_button('Priblížiť', 'plus', lambda: self.view.zoom(1.25), bar)
        self.fit_button = self._tool_button('Na šírku', 'fit', lambda: self.view.fit_width(), bar)
        toolbar_layout.addLayout(bar, 0, 2, Qt.AlignmentFlag.AlignRight)
        side_width = max(row.minimumSize().width(), bar.minimumSize().width())
        toolbar_layout.setColumnMinimumWidth(0, side_width)
        toolbar_layout.setColumnMinimumWidth(2, side_width)
        toolbar_layout.setColumnStretch(0, 1)
        toolbar_layout.setColumnStretch(2, 1)
        layout.addWidget(tools)

        self.splitter = QSplitter()
        self.view = PageView()
        self.view.page_requested.connect(self._activate_scrolled_page)
        self.view.verticalScrollBar().valueChanged.connect(lambda: self.scroll_sync_timer.start(0))
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
        title = QLabel('Upraviť text')
        title.setObjectName('paneltitle')
        panel_header = QHBoxLayout()
        panel_header.addWidget(title, 1)
        self.cancel_button = self._tool_button('Zrušiť výber (Escape)', 'close', self.cancel_selection, panel_header)
        self.cancel_button.setFixedSize(32, 32)
        self.cancel_button.setIconSize(QSize(16, 16))
        form.addLayout(panel_header)
        self.selection_preview = QLabel()
        self.selection_preview.setFixedHeight(120)
        self.selection_preview.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.selection_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.selection_preview.setAccessibleName('Zväčšený náhľad vybraného textu')
        self.selection_preview.hide()
        form.addWidget(self.selection_preview)
        self.hint = QLabel('Otvorte PDF a kliknite na text, ktorý chcete zmeniť.')
        self.hint.setWordWrap(True)
        self.hint.setObjectName('muted')
        form.addWidget(self.hint)
        label = QLabel('Nový text')
        form.addWidget(label)
        self.text = QTextEdit()
        self.text.setAcceptRichText(False)
        self.text.setPlaceholderText('Vyberte text na strane…')
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
        self.font_size.setToolTip('Maximálna veľkosť písma')
        self.font_size.setAccessibleName('Veľkosť písma')
        for size in (4, 6, 7, 8, 9, 10, 11, 12, 14, 16, 18, 20, 24, 28, 32, 36, 48, 60, 72, 96):
            self.font_size.addItem(f'{size} pt', size)
        self.font_size.setCurrentIndex(self.font_size.findData(11))
        self.font_size.currentIndexChanged.connect(self._edited)
        formatting.addWidget(self.font_size)
        self.white_background = QCheckBox('Biely podklad')
        self.white_background.setToolTip('Biely podklad pod nahradeným textom')
        self.white_background.setChecked(True)
        self.white_background.toggled.connect(self._edited)
        formatting.addWidget(self.white_background)
        formatting.addStretch()
        form.addLayout(formatting)
        form.addStretch()
        panel_scroll = QScrollArea()
        panel_scroll.setObjectName('editorPanel')
        panel_scroll.setMinimumWidth(280)
        panel_scroll.setMaximumWidth(350)
        panel_scroll.setWidgetResizable(True)
        panel_scroll.setFrameShape(QFrame.Shape.NoFrame)
        panel_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        panel_scroll.setWidget(panel)
        self.splitter.addWidget(panel_scroll)
        self.thumbnails = QListWidget()
        self.thumbnails.setObjectName('thumbnails')
        self.thumbnails.setAccessibleName('Náhľady strán')
        self.thumbnails.setFixedWidth(160)
        self.thumbnails.setItemDelegate(ThumbnailDelegate(self.thumbnails))
        self.thumbnails.setSpacing(6)
        self.thumbnails.setUniformItemSizes(True)
        self.thumbnails.setVerticalScrollMode(QListWidget.ScrollMode.ScrollPerPixel)
        self.thumbnails.verticalScrollBar().setSingleStep(24)
        self.thumbnails.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.thumbnails.setIconSize(QSize(120, 160))
        self.thumbnails.currentRowChanged.connect(self._thumbnail_selected)
        self.thumbnails.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.thumbnails.customContextMenuRequested.connect(self._thumbnail_menu)
        self.splitter.insertWidget(0, self.thumbnails)
        self.splitter.setCollapsible(0, False)
        self.splitter.setSizes([160, 860, 320])
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
        headline = QLabel('Vaše PDF. Vaše úpravy.')
        headline.setAlignment(Qt.AlignmentFlag.AlignCenter)
        headline.setObjectName('headline')
        zone_layout.addWidget(headline)
        subtitle = QLabel('Pretiahnite sem PDF, sken alebo fotografiu.\nAlebo vyberte súbor z počítača.')
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        subtitle.setObjectName('subtitle')
        zone_layout.addWidget(subtitle)
        empty_button = QPushButton('Vybrať súbor')
        empty_button.setObjectName('primary')
        empty_button.setFixedWidth(210)
        empty_button.clicked.connect(self.open_file)
        zone_layout.addWidget(empty_button, alignment=Qt.AlignmentFlag.AlignCenter)
        empty_layout.addWidget(drop_zone, alignment=Qt.AlignmentFlag.AlignCenter)
        empty_layout.addStretch()
        layout.addWidget(self.empty, 1)
        self.splitter.hide()
        self.setCentralWidget(root)
        self.statusBar().addPermanentWidget(QLabel(f'v{VERSION}'))
        self.statusBar().showMessage('Pripravené. Spracovanie prebieha lokálne bez nahrávania súborov.')
        for keys, callback in [('Ctrl+O', self.open_file), ('Ctrl+Shift+S', self.save_copy), ('Ctrl+Z', self.undo), ('Ctrl+Y', self.redo), ('Ctrl+Shift+Z', self.redo), ('Esc', self.cancel_selection)]:
            action = QAction(self)
            action.setShortcut(QKeySequence(keys))
            action.triggered.connect(callback)
            self.addAction(action)

    @staticmethod
    def _button(label, callback, layout, primary=False):
        button = QPushButton(label)
        if primary:
            button.setObjectName('primary')
        if callback:
            button.clicked.connect(callback)
        layout.addWidget(button)
        return button

    @staticmethod
    def _toolbar_separator(layout):
        line = QFrame()
        line.setObjectName('toolbarSeparator')
        line.setFixedSize(1, 20)
        layout.addSpacing(4)
        layout.addWidget(line)
        layout.addSpacing(4)

    def _tool_button(self, label, symbol, callback, layout):
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
        button = QToolButton()
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
        message = ERRORS.get(str(exc), str(exc))
        QMessageBox.warning(self, 'Akciu sa nepodarilo dokončiť', message)

    def _busy(self):
        return self.ocr_worker is not None

    def _update_actions(self):
        ready = self.pdf is not None and not self._busy()
        has_pages = ready and self.pdf.page_count > 0
        editable = ready and self.selection is not None and 'characters' not in self.selection and self.selection.get('kind') != 'area'
        self.open_button.setEnabled(not self._busy())
        for widget in (self.save_button, self.region_button, self.cover_button, self.minus_button, self.fit_button, self.plus_button, self.view):
            widget.setEnabled(has_pages)
        self.undo_button.setEnabled(ready and self.pdf.can_undo)
        self.redo_button.setEnabled(ready and self.pdf.can_redo)
        self.pages_button.setEnabled(ready)
        self.duplicate_page_action.setEnabled(has_pages)
        self.insert_pdf_action.setEnabled(ready)
        self.delete_page_action.setEnabled(has_pages)
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
        answer = QMessageBox.question(self, 'Neuložené zmeny', 'Uložiť zmeny do novej PDF kópie?', QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel, QMessageBox.StandardButton.Save)
        if answer == QMessageBox.StandardButton.Save:
            return self.save_copy()
        return answer == QMessageBox.StandardButton.Discard

    def open_file(self, checked=False, path=None):
        if self._busy() or not self._leave_document():
            return
        if path is None:
            path, _ = QFileDialog.getOpenFileName(self, 'Otvoriť súbor', '', 'Dokumenty (*.pdf *.jpg *.jpeg *.png)')
        if not path:
            return
        try:
            document = PdfDocument(path)
        except Exception as exc:
            self._error(exc)
            return
        if self.pdf:
            self.pdf.close()
        self.pdf = document
        self.thumbnails.blockSignals(True)
        self.add_pdf_item = None
        self.add_pdf_card = None
        self.thumbnails.clear()
        self.thumbnails.blockSignals(False)
        self.ocr_areas.clear()
        self.ocr_attempted.clear()
        self.selection = None
        self.pending = False
        self.empty.hide()
        self.splitter.show()
        self.file_label.setText(document.source.name)
        self.file_label.setToolTip(str(document.source))
        self.page_index = 0
        self.view.reset_document()
        self.clear_selection()
        self.render_page(fit=True, scroll=True)
        self._update_pagination()

    def render_page(self, fit=False, *, scroll=False, refresh_thumbnails=True):
        if not self.pdf:
            return
        if not self.pdf.page_count:
            self.view.reset_document()
            self._refresh_thumbnails()
            self._update_actions()
            return
        try:
            page = self.pdf.document[self.page_index]
            native = self.pdf.spans(self.page_index)
            areas = native + self.ocr_areas.get(self.page_index, [])
            self.view.configure_pages([(p.rect.width, p.rect.height) for p in self.pdf.document])
            if refresh_thumbnails:
                for index in list(self.view.page_scales):
                    self.view.evict_page_raster(index)
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
                self.thumbnails.setCurrentRow(self.page_index)
                self.thumbnails.blockSignals(False)
            self._update_actions()
            if not areas:
                self.statusBar().showMessage('Text tejto strany sa rozpozná automaticky. Môžete tiež pridať textové pole alebo zakryť oblasť.')
                if self.page_index not in self.ocr_attempted and not self._busy():
                    self.ocr_attempted.add(self.page_index)
                    QTimer.singleShot(0, lambda document=self.pdf, index=self.page_index: self._auto_ocr(document, index))
            else:
                self.statusBar().showMessage(f'Strana {self.page_index + 1} z {self.pdf.page_count}. Ťahaním označte text a stlačte Delete. Kliknutím upravíte celý úsek.')
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
        for index in sorted(wanted):
            scale = self._render_scale(self.pdf.document[index])
            if abs(scale - self.view.page_scales.get(index, 0)) > 0.05:
                self.view.update_page_raster(index, self.pdf.render(index, scale), scale)

    def _activate_scrolled_page(self, index):
        if not self.pdf or self._busy() or index == self.page_index:
            return
        self.page_index = index
        self.render_page(refresh_thumbnails=False)

    def _sync_scroll_page(self):
        if not self.pdf or self._busy() or not self.view.page_rects:
            return
        if self.view.start_point is None:
            self._activate_scrolled_page(self.view.current_visible_page())
        self.refresh_preview()

    def _refresh_thumbnails(self):
        if not self.pdf or self.thumbnails.isHidden():
            return
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
            for index in range(self.pdf.page_count):
                rect = self.pdf.document[index].rect
                pixmap = self.pdf.render(index, min(120 / rect.width, 160 / rect.height))
                image = QImage(pixmap.samples, pixmap.width, pixmap.height, pixmap.stride, QImage.Format.Format_RGB888).copy()
                self.thumbnails.item(index).setIcon(QIcon(QPixmap.fromImage(image)))
            if self.pdf.page_count:
                self.add_pdf_card.button.setFixedSize(pixmap.width, pixmap.height)
                margin = max(0, (self.add_pdf_card.width() - pixmap.width) // 2)
                self.add_pdf_card.button.move(margin, margin)
            self.thumbnails.setCurrentRow(self.page_index if self.pdf.page_count else -1)
        finally:
            self.thumbnails.blockSignals(False)

    def _add_thumbnail_actions(self, item):
        controls = QWidget()
        column = QVBoxLayout(controls)
        column.setContentsMargins(4, 0, 4, 2)
        column.addStretch()
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        duplicate = self._tool_button('Duplikovať stranu', 'pages',
            lambda: self._thumbnail_action(item, self.duplicate_page), row)
        duplicate.setObjectName('duplicatePage')
        row.addStretch()
        delete = self._tool_button('Odstrániť stranu', 'close',
            lambda: self._thumbnail_action(item, self.delete_page), row)
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
            callback()

    def _thumbnail_selected(self, index):
        self.change_page(index)
        self.thumbnails.blockSignals(True)
        self.thumbnails.setCurrentRow(self.page_index)
        self.thumbnails.blockSignals(False)

    def _thumbnail_menu(self, point):
        item = self.thumbnails.itemAt(point)
        if item is None or item is self.add_pdf_item or self._busy():
            return
        index = self.thumbnails.row(item)
        self.change_page(index)
        if self.page_index == index and not self.pending:
            self.pages_menu.exec(self.thumbnails.viewport().mapToGlobal(point))

    def _pages_changed(self, index, *, scroll=True):
        self.page_index = max(0, min(index, self.pdf.page_count - 1))
        self.ocr_areas.clear()
        self.ocr_attempted.clear()
        self.region_button.setChecked(False)
        self.cover_button.setChecked(False)
        self.clear_selection()
        self.render_page(fit=self.view.fit_to_width, scroll=scroll)

    def delete_page(self):
        if not self.pdf or self._busy() or not self.pdf.page_count or not self._discard_pending():
            return
        try:
            self.pdf.delete_page(self.page_index)
        except Exception as exc:
            self._error(exc)
            return
        self._pages_changed(self.page_index)
        self.statusBar().showMessage('Strana bola odstránená. Obnovíte ju pomocou Ctrl+Z.')

    def duplicate_page(self):
        if not self.pdf or self._busy() or not self.pdf.page_count or not self._discard_pending():
            return
        try:
            self.pdf.duplicate_page(self.page_index)
        except Exception as exc:
            self._error(exc)
            return
        self._pages_changed(self.page_index + 1)
        self.statusBar().showMessage('Kópia strany bola vložená za pôvodnú stranu.')

    def insert_pdf(self, checked=False, path=None, *, append=False):
        if not self.pdf or self._busy() or not self._discard_pending():
            return
        if path is None:
            title = 'Pridať PDF na koniec dokumentu' if append else 'Vložiť PDF za aktuálnu stranu'
            path, _ = QFileDialog.getOpenFileName(self, title, '', 'PDF (*.pdf)')
        if not path:
            return
        try:
            index = self.pdf.page_count - 1 if append or not self.pdf.page_count else self.page_index
            self.pdf.insert_pdf(path, index)
        except Exception as exc:
            self._error(exc)
            return
        self._pages_changed(index + 1)
        self.statusBar().showMessage('Strany z PDF boli vložené. Výsledok uložte ako kópiu.')

    def refresh_preview(self):
        if not self.pdf or self._busy() or self.view.pixmap_item is None:
            return
        try:
            self._render_visible_pages()
            self.update_selection_preview()
        except Exception as exc:
            self._error(exc)

    def change_page(self, index):
        if not self.pdf or not 0 <= index < self.pdf.page_count or self._busy():
            return
        if not self._discard_pending():
            return
        self.page_index = index
        self.render_page(fit=True, scroll=True)
        self._update_pagination()

    def _update_pagination(self):
        count = self.pdf.page_count if self.pdf else 0
        self.page_label.setText(f'{self.page_index + 1 if count else 0} / {count}')
        self.page_label.setAccessibleName(f'Strana {self.page_index + 1 if count else 0} z {count}')
        ready = bool(count) and not self._busy()
        self.previous_button.setEnabled(ready and self.page_index > 0)
        self.next_button.setEnabled(ready and self.page_index < count - 1)

    def _region_toggled(self, enabled):
        if enabled:
            self.cover_button.setChecked(False)
        self.view.set_region_mode(enabled)
        if self.pdf:
            self.statusBar().showMessage('Ťahaním myši nakreslite nové textové pole.' if enabled else 'Kliknite na text na strane.')

    def _cover_toggled(self, enabled):
        if enabled:
            self.region_button.setChecked(False)
        elif self.selection and self.selection.get('kind') == 'area':
            self.clear_selection()
        self.view.set_region_mode(enabled or self.region_button.isChecked())
        if self.pdf and enabled:
            self.statusBar().showMessage('Označte oblasť. Presuňte ju, zmeňte jej veľkosť alebo ju odstráňte klávesom Delete.')

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
        if not self.pdf or self.selection is None:
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
        self.selection_preview.setPixmap(QPixmap.fromImage(image).scaled(
            max(1, self.selection_preview.width()), self.selection_preview.height(),
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
        self.update_selection_preview()
        self.hint.setText('Text sa po dopísaní automaticky zmení v náhľade. Delete na strane vymaže výber. PDF uložíte tlačidlom Uložiť kópiu.')
        self._update_actions()
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
        self.hint.setText('Označený text vymažete klávesom Delete. Tlačidlom Späť vymazanie vrátite.')
        self._update_actions()
        self.view.setFocus()

    def select_region(self, bbox):
        if self.cover_button.isChecked():
            if not self._discard_pending():
                self.restore_highlight()
                return
            self.selection = {'kind': 'area', 'bbox': bbox, 'page_index': self.page_index,
                              'source_bbox': bbox, 'source_ocr': list(self.ocr_areas.get(self.page_index, []))}
            self.pending = False
            self.edit_applied = False
            self.text.blockSignals(True)
            self.text.clear()
            self.text.blockSignals(False)
            self.selection_preview.hide()
            self.edit_error.hide()
            self.hint.setText('Oblasť presuňte, zmeňte jej veľkosť alebo ju odstráňte klávesom Delete.')
            self.restore_highlight()
            self._update_actions()
            self.view.setFocus()
            return
        self.select_text({'text': '', 'bbox': bbox, 'size': min(11, max(4, pymupdf.Rect(bbox).height * 0.65)), 'color': 0, 'insert_only': True})
        if self.selection and self.selection['bbox'] == bbox:
            self.hint.setText('Zadajte text do nového poľa. Náhľad sa aktualizuje automaticky.')
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
        affected = (pymupdf.Rect(original), pymupdf.Rect(bbox))
        self.ocr_areas[index] = [s for s in self.selection['source_ocr'] if not any(rect.intersects(pymupdf.Rect(s['bbox'])) for rect in affected)]
        self.selection['baseline'] = baseline
        self.selection['bbox'] = bbox
        self.render_page()
        self.statusBar().showMessage('Oblasť bola upravená. Zmenu môžete vrátiť tlačidlom Späť.')

    def cancel_selection(self, checked=False):
        if self.pending:
            self.apply_change(automatic=True)
        self.region_button.setChecked(False)
        self.cover_button.setChecked(False)
        self.clear_selection()
        self.statusBar().showMessage('Výber aj aktívny nástroj boli zrušené.')

    def clear_selection(self, checked=False):
        self.auto_apply_timer.stop()
        self.view.start_point = None
        self.view.anchor_cursor = None
        self.view.dragging_text = False
        self.view.area_bbox = None
        self.view.area_page = None
        self.view.area_drag = None
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
        self.hint.setText('Kliknite na text na strane alebo pridajte textové pole ikonou T. Skeny sa rozpoznajú automaticky.')
        self._update_actions()

    def apply_change(self, automatic=False):
        if not self.pdf or self.selection is None or 'characters' in self.selection or self._busy():
            return False
        self.auto_apply_timer.stop()
        index = self.selection['page_index']
        try:
            self.pdf.replace_text(index, self.selection['bbox'], self.text.toPlainText(), self.font_size.currentData(), self.selection.get('color', 0), self.white_background.isChecked(), update_previous=self.edit_applied, insert_only=self.selection.get('insert_only', False))
        except Exception as exc:
            self.edit_error.setText(ERRORS.get(str(exc), str(exc)))
            self.edit_error.show()
            if not automatic:
                self._error(exc)
            return False
        rect = pymupdf.Rect(self.selection['bbox'])
        self.ocr_areas[index] = [s for s in self.ocr_areas.get(index, []) if not rect.intersects(pymupdf.Rect(s['bbox']))]
        self.pending = False
        self.edit_applied = True
        self.edit_error.hide()
        self.render_page()
        self.statusBar().showMessage('Náhľad sa automaticky aktualizoval. PDF uložíte tlačidlom Uložiť kópiu.')
        return True

    def delete_selection(self):
        if not self.pdf or self.selection is None or self._busy():
            return
        self.auto_apply_timer.stop()
        index = self.selection['page_index']
        try:
            if self.selection.get('kind') == 'area':
                if 'baseline' in self.selection:
                    self.pdf.transform_region(index, self.selection['source_bbox'], None, self.selection['baseline'])
                    self.ocr_areas[index] = self.selection['source_ocr']
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
        rect = pymupdf.Rect(self.selection.get('source_bbox', self.selection['bbox']))
        self.ocr_areas[index] = [s for s in self.ocr_areas.get(index, []) if not rect.intersects(pymupdf.Rect(s['bbox']))]
        self.clear_selection()
        self.render_page()
        self.statusBar().showMessage('Výber bol vymazaný. Vymazanie vrátite tlačidlom Späť alebo Ctrl+Z.')

    def undo(self):
        if not self.pdf or self._busy():
            return
        self.auto_apply_timer.stop()
        if self.pending and not self.edit_applied:
            self.clear_selection()
            self.render_page()
            return
        if self.pdf.undo():
            self._pages_changed(self.page_index, scroll=self.pdf.page_count != len(self.view.page_rects))
            self.statusBar().showMessage('Posledná zmena bola vrátená späť.')

    def redo(self):
        if not self.pdf or self._busy() or not self.pdf.can_redo:
            return
        self.auto_apply_timer.stop()
        if self.pdf.redo():
            self._pages_changed(self.page_index, scroll=self.pdf.page_count != len(self.view.page_rects))
            self.statusBar().showMessage('Zmena bola znovu vykonaná.')

    def save_copy(self):
        if not self.pdf or self._busy():
            return False
        if not self.pdf.page_count:
            self._error(ValueError('The document has no pages.'))
            return False
        if self.pending and not self.apply_change():
            return False
        target = self.pdf.source.with_name(self.pdf.source.stem + '_upravene.pdf')
        number = 2
        while target.exists():
            target = self.pdf.source.with_name(f'{self.pdf.source.stem}_upravene_{number}.pdf')
            number += 1
        filename, _ = QFileDialog.getSaveFileName(self, 'Uložiť novú PDF kópiu', str(target), 'PDF (*.pdf)', options=QFileDialog.Option.DontConfirmOverwrite)
        if not filename:
            return False
        if not filename.lower().endswith('.pdf'):
            filename += '.pdf'
        try:
            self.pdf.save_copy(filename)
        except Exception as exc:
            self._error(exc)
            return False
        self._update_actions()
        self.statusBar().showMessage(f'Uložené: {filename}')
        return True

    def _auto_ocr(self, document, index):
        if self._closing_after_update:
            return
        if self._install_pending and self.pdf is document:
            QTimer.singleShot(500, lambda: self._auto_ocr(document, index))
            return
        if self.pdf is document and self.page_index == index and not self._busy():
            self.start_ocr()
        elif self.pdf is document:
            self.ocr_attempted.discard(index)

    def start_ocr(self):
        if not self.pdf or self._busy() or not self._discard_pending():
            return
        self.ocr_attempted.add(self.page_index)
        self.ocr_temp = tempfile.TemporaryDirectory(prefix='faktura-ocr-')
        path = Path(self.ocr_temp.name) / 'page.png'
        try:
            page = self.pdf.document[self.page_index]
            self.ocr_scale = min(3.0, 3500 / max(page.rect.width, page.rect.height))
            self.pdf.render(self.page_index, self.ocr_scale).save(path)
        except Exception as exc:
            self.ocr_temp.cleanup()
            self.ocr_temp = None
            self._error(exc)
            return
        self.ocr_worker = OcrWorker(path, self)
        self.ocr_worker.completed.connect(self._ocr_completed)
        self.ocr_worker.failed.connect(self._ocr_failed)
        self.ocr_worker.finished.connect(self._ocr_finished)
        self._update_actions()
        self.statusBar().showMessage('Rozpoznávam text tejto strany pomocou Windows OCR…')
        self.ocr_worker.start()

    def _ocr_completed(self, lines):
        page = self.pdf.document[self.page_index]
        native = self.pdf.spans(self.page_index)
        areas = []
        for line in lines:
            rect = pymupdf.Rect([value / self.ocr_scale for value in line['bbox']]) * page.derotation_matrix
            rect = pymupdf.Rect(rect.x0 - 1, rect.y0 - 2, rect.x1 + 1, rect.y1 + 2) & (page.rect * page.derotation_matrix)
            if rect.is_empty or any(rect.intersects(pymupdf.Rect(s['bbox'])) for s in native):
                continue
            areas.append({'text': line['text'], 'bbox': tuple(rect), 'size': max(4, (rect.height - 4) * 0.9), 'color': 0})
        self.ocr_areas[self.page_index] = areas
        self.render_page()
        self.statusBar().showMessage(f'OCR dokončené: {len(areas)} oblastí zo skenu. Kliknite na text; rozpoznané údaje pred uložením skontrolujte.')

    def _ocr_failed(self, message):
        self.hint.setText('Text sa nepodarilo automaticky rozpoznať. Môžete pridať textové pole alebo zakryť oblasť.')
        self.statusBar().showMessage(f'Automatické rozpoznanie textu zlyhalo: {message}')

    def _ocr_finished(self):
        self.ocr_worker.deleteLater()
        self.ocr_worker = None
        self.ocr_temp.cleanup()
        self.ocr_temp = None
        self._update_actions()

    def show_about(self):
        QMessageBox.about(self, f'O aplikácii {APP_NAME}',
            f'<b>{APP_NAME} {VERSION}</b><p>Editor PDF pre Windows.</p>'
            '<p>Copyright © 2026 hudakjakub a prispievatelia.<br>'
            'GNU AGPL v3. Bez záruky. Program môžete upravovať a ďalej šíriť podľa licencie.</p>'
            f'<p><a href="{PROJECT_URL}/tree/v{VERSION}">Zdrojový kód</a> · '
            f'<a href="{PROJECT_URL}/blob/v{VERSION}/LICENSE">Licencia</a></p>')

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
        self.check_updates_action.setText('Kontrolujú sa aktualizácie…')
        self._start_update_worker()

    def _start_update_worker(self, verification=None):
        self.update_worker = UpdateWorker(self, verification)
        self.update_worker.completed.connect(self._update_completed)
        self.update_worker.failed.connect(self._update_failed)
        self.update_worker.downloading.connect(lambda: self.check_updates_action.setText('Sťahuje sa aktualizácia…'))
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
                QMessageBox.information(self, 'Aktualizácie', f'{APP_NAME} {VERSION} je aktuálna verzia.')
            return
        if installer is None:
            answer = QMessageBox.question(self, 'Nová verzia',
                f'Je dostupná verzia {release.version}. Otvoriť stránku vydania?',
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            if answer == QMessageBox.StandardButton.Yes:
                QDesktopServices.openUrl(QUrl(f'{PROJECT_URL}/releases/tag/v{release.version}'))
            return
        self.ready_update = (release, installer)
        self.statusBar().showMessage(f'Aktualizácia {release.version} je pripravená na inštaláciu.')

    def _update_failed(self, message):
        if self._install_pending:
            self.ready_update = None
        if not self._closing_after_update and (self._update_manual or self._install_pending):
            QMessageBox.warning(self, 'Aktualizácie', 'Aktualizáciu sa nepodarilo overiť alebo stiahnuť. '
                                'Skontrolujte pripojenie a skúste to znova.')

    def _update_finished(self):
        worker = self.update_worker
        self.update_worker = None
        worker.deleteLater()
        skip_offer = self._skip_update_offer
        self._skip_update_offer = False
        self.centralWidget().setEnabled(True)
        self.check_updates_action.setEnabled(True)
        self.check_updates_action.setText('Nainštalovať aktualizáciu…' if self.ready_update else 'Skontrolovať aktualizácie…')
        if self._closing_after_update:
            self.close()
        elif self._install_pending:
            if self._verified_update is not None:
                self._launch_update()
            self._install_pending = False
            self._verified_update = None
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
        message = (f'Nainštalovať Omni PDF {release.version} a reštartovať aplikáciu? '
                   'Pred reštartom budete môcť uložiť rozpracované PDF.')
        if not installed:
            message += (f'\n\nPrenosná aplikácia sa nainštaluje do:\n{self._install_directory}\n'
                        'Existujúca inštalácia v tomto priečinku sa aktualizuje. Pôvodný prenosný EXE zostane zachovaný.')
        answer = QMessageBox.question(self, 'Aktualizácia je pripravená',
            message,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
        if answer != QMessageBox.StandardButton.Yes or self._busy() or not self._leave_document():
            self._install_pending = False
            return
        self.centralWidget().setEnabled(False)
        self.check_updates_action.setEnabled(False)
        self.check_updates_action.setText('Overuje sa inštalátor…')
        self._start_update_worker(verification=self.ready_update)

    def _launch_update(self):
        if self._busy():
            return
        release, installer = self._verified_update
        try:
            updates.launch_installer(installer, self._install_directory, os.getpid())
        except updates.UpdateError:
            self.ready_update = None
            self.check_updates_action.setText('Skontrolovať aktualizácie…')
            QMessageBox.warning(self, 'Aktualizácia', 'Inštalátor sa nepodarilo bezpečne spustiť. Skúste aktualizáciu znova.')
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
            QMessageBox.information(self, 'Rozpoznávanie textu', 'Počkajte na dokončenie rozpoznávania textu.')
            event.ignore()
        elif self._close_approved or self._leave_document():
            self.auto_apply_timer.stop()
            self.scroll_sync_timer.stop()
            self.view.raster_timer.stop()
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
#brand { font-size: 13px; font-weight: 600; padding-right: 8px; }
#tools { background: #f2f4f6; border-bottom: 1px solid #d4dce2; }
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
              'qt_platform': application.platformName(), 'resources_ok': False, 'pdf_render_ok': False}
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
        result['resources_ok'] = result['resources_ok'] and not QIcon(str(APP_ICON)).isNull()
    except Exception as exc:
        result['error'] = str(exc)
    if output:
        Path(output).write_text(json.dumps(result, ensure_ascii=False), encoding='utf-8')
    return 0 if result['resources_ok'] and result['pdf_render_ok'] else 1


def main():
    parser = argparse.ArgumentParser(description='Omni PDF editor')
    parser.add_argument('file', nargs='?')
    parser.add_argument('--smoke-test', action='store_true')
    parser.add_argument('--output')
    arguments = parser.parse_args()
    set_app_id()
    application = QApplication(sys.argv)
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
