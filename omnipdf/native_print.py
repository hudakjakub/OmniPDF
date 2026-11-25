"""Prepare a private snapshot and run the Windows print preview host."""
import math
from pathlib import Path
import sys
import tempfile

from PySide6.QtCore import QEventLoop, QProcess


def run_helper(args):
    process = QProcess()
    loop = QEventLoop()
    errors = []
    process.finished.connect(loop.quit)
    process.errorOccurred.connect(lambda error: (errors.append(error), loop.quit()))
    kernel = None
    try:
        if sys.platform == 'win32' and getattr(sys, 'frozen', False):
            import ctypes
            kernel = ctypes.windll.kernel32
            if not kernel.SetDllDirectoryW(None):
                raise RuntimeError('The Windows print dialog could not be started.')
        process.start(str(args[0]), [str(arg) for arg in args[1:]])
        if not process.waitForStarted():
            raise RuntimeError('The Windows print dialog could not be started.')
    except (AttributeError, OSError) as error:
        raise RuntimeError('The Windows print dialog could not be started.') from error
    finally:
        if kernel is not None:
            kernel.SetDllDirectoryW(sys._MEIPASS)
    if process.state() != QProcess.ProcessState.NotRunning:
        loop.exec()
    if errors or process.exitStatus() != QProcess.ExitStatus.NormalExit:
        raise RuntimeError('The Windows print dialog could not be started.')
    return process.exitCode()


def helper_ready(helper):
    try:
        return run_helper([helper, '--check']) == 0
    except RuntimeError:
        return False


def print_native(document, helper):
    with tempfile.TemporaryDirectory(prefix='omnipdf-print-') as folder:
        for index in range(document.page_count):
            page = document.document[index]
            scale = min(300 / 72, math.sqrt(16_000_000 / page.rect.get_area()))
            document.render(index, scale).save(str(Path(folder) / f'{index:08d}.png'))
        result = run_helper([helper, folder, document.source.name])
        if result not in (0, 1):
            raise RuntimeError('The Windows print dialog could not complete the print job.')
        return result == 0
