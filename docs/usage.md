# Using Omni PDF

## Edit a document

1. Open a PDF, JPG or PNG using the open button or by dragging a file into the window. The app asks what to do with unsaved changes before opening another document.
2. Click a text span or drag across the exact text you want to edit. The side panel opens when you release the mouse. The preview updates automatically shortly after typing stops. If the text does not fit, the last valid version remains visible and the panel explains the problem.
3. Press **Delete** on the page to remove the selection. Press **Escape** to cancel the selection or active tool. The selection stays on its original page when you scroll.
4. Click the **T** tool to add a text box. Click once for a default-sized box or drag to choose its size, then start typing. Use the dashed rectangle tool to move, resize or delete an area. Press **Escape** to return to editing the text in its new position.
5. Text on scanned pages and photographs is recognized in the background. Check recognized text before saving.

The left sidebar shows page thumbnails. Click a thumbnail to navigate, or use **Ctrl+click** and **Shift+click** to select multiple pages. Drag selected thumbnails to reorder them. The page management menu offers actions such as rotating, duplicating and deleting pages. Use the **+** card to append another PDF; it remains available even after deleting the last page.

Use **Ctrl+F** to find text across the document. Press **Enter** or **F3** for the next match, **Shift+F3** for the previous match, and **Escape** to close search. The app can also save a searchable PDF with an invisible text layer for scanned pages.

Save with **Ctrl+S** or **Ctrl+Shift+S**. You may save a copy or confirm replacing the original PDF. If the original has changed on disk, save a copy or reopen it.

Print with the printer button or **Ctrl+P**. The system print dialog offers a preview and printer settings when the system print component is available; otherwise, the app uses a separate preview and standard print dialog.

Other shortcuts: **Ctrl+O** opens a file, **Ctrl+Z** undoes, **Ctrl+Y** or **Ctrl+Shift+Z** redoes, **Ctrl++** or **Ctrl+=** zooms in, **Ctrl+-** zooms out, and **Ctrl+0** fits the page width.

## Updates

The application menu contains the current version, a manual update check and a switch for automatic checks. In packaged builds, checks occur on startup and every six hours. When an update is available, the app asks for consent before downloading it, shows progress, and verifies the size and SHA-256 reported by GitHub. Downloads can be cancelled.

You can defer an update. Before restarting, the app offers to save unfinished work. Cancelling that prompt also cancels the update. An update replaces the EXE in its current folder and starts the new version. The folder must be writable. Source runs offer a link to the release page.

If you are using a public release through v0.1.19, download the new portable EXE once to switch to in-place updates.

## Limitations

- Replacement text may use a different font from the original. For text over an image, select and remove the area, then add a text box.
- A covered area uses a single background color and may stand out on a photograph, gradient or pattern.
- OCR depends on the recognition languages installed in Windows. Straighten and crop scans or photographs before importing, and check recognized numbers.
- The app does not recalculate totals or taxes.
- Encrypted PDFs and files that prohibit editing are rejected. Digitally signed PDFs can be opened or inserted after confirmation; signature validity is not verified and changes invalidate the original signature.
- Pages with unapplied redaction annotations cannot be edited.
