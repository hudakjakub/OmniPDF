# Changelog

## 0.1.10

- Select multiple thumbnails to move, rotate, or delete pages in one undoable step.
- Save a searchable PDF with an invisible OCR layer for scanned pages.
- Replace the original PDF after confirmation, with verification and a check for external changes.
- Open PDFs with recoverable structural errors without changing the original file.
- Show Find in a compact top-right panel.
- Show one insertion marker per thumbnail gap and animate reordered thumbnails.
- Preserve the background by default when replacing text, with a white fill available as an option.
- Slide the text editor in from the right when a text edit is selected.

## 0.1.9

- Update the PDF engine to MuPDF 1.28.2 with the fix for CVE-2026-3308.
- Preserve replacement characters, vertical text direction, and links on duplicated pages.
- Add undoable page reordering, bounded undo history, and background OCR that survives Undo and Redo.
- Add document Find for text and scans, with one result per wrapped phrase and a notice for incomplete searches.
- Reuse unchanged thumbnails and test actual OCR in the packaged Windows app.

## 0.1.8

- Publish stable download names while retaining a compatible installer for older updaters.

## 0.1.7

- Create a ready-to-type text box with a single click.

## 0.1.6

- Allow signed PDFs after explicit confirmation that saving a copy invalidates signatures.

## 0.1.5

- Display the application in Slovak or English based on the system UI language.

## 0.1.4

- Add standard keyboard shortcuts for saving and document zoom.

## 0.1.3

- Show move and resize cursors over the selected area and its handles.

## 0.1.2

- Preserve covered content when moving an area again and show the area while dragging.

## 0.1.1

- Allow removing the last page and adding a PDF to an empty document, with undo and redo.
- Replace the cover tool with a selectable, movable and resizable area.
- Preserve hidden PDF layers in previews and show the application version in the status bar.

## 0.1.0

- First public Windows release of Omni PDF.
- Local PDF text editing, scanned-document OCR, text boxes and background covers.
- Continuous document scrolling, page thumbnails, page deletion, duplication and PDF insertion.
- Automatic edit previews, undo/redo and safe PDF-copy export.
- Consistent light theme and keyboard shortcuts.
- Portable EXE and per-user installer, built and tested by GitHub Actions.
- Background update checks and verified downloads from GitHub Releases, with saved-work protection before restart.
