# Changelog

## 0.1.17

- Present the project documentation, workflow labels and application screenshot in English.

## 0.1.16

- Integrate the latest PDF and OCR features with printing, update controls, and the reorganized project.

## 0.1.15

- Improve the GitHub project page with an application preview and a clearer CI/CD overview.

## 0.1.14

- Organize application modules, tests and documentation into dedicated folders.
- Refresh the project page and visualize the CI/CD workflow.

## 0.1.13

- Provide document preview in the Windows print dialog when the print host is available.

## 0.1.12

- Add a subtle border around the selected text preview.

## 0.1.11

- Show a navigable document preview before printing.

## 0.1.10

- Print documents with Ctrl+P and the system print dialog.
- Select multiple thumbnails to move, rotate, or delete pages in one undoable step.
- Save a searchable PDF with an invisible OCR layer for scanned pages.
- Replace the original PDF after confirmation, with verification and a check for external changes.
- Open PDFs with recoverable structural errors without changing the original file.
- Show Find in a compact top-right panel.
- Show one insertion marker per thumbnail gap and animate reordered thumbnails.
- Preserve the background by default when replacing text, with a white fill available as an option.
- Slide the text editor in from the right when a text edit is selected.

## 0.1.9

- Ask before downloading updates, show cancellable download progress and restart after installation.
- Explain when Windows security policy blocks the installer.
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

- Display the application in the system UI language where supported.

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
