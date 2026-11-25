"""Local OCR using the Windows language packs installed for the current user."""
import json
import subprocess
import time
from pathlib import Path
from .i18n import _


def recognize(image_path: str | Path, *, cancelled=lambda: False) -> list[dict]:
    script = Path(__file__).with_name("windows_ocr.ps1")
    args = ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(script), "-ImagePath", str(Path(image_path).resolve())]
    deadline = time.monotonic() + 120
    try:
        with subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)) as process:
            try:
                while not cancelled():
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise subprocess.TimeoutExpired(args, 120)
                    try:
                        stdout, stderr = process.communicate(timeout=min(remaining, 0.2))
                    except subprocess.TimeoutExpired:
                        continue
                    break
                else:
                    return []
            finally:
                if process.poll() is None:
                    process.kill()
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError(_("Nepodarilo sa spustiť Windows OCR: {error}").format(error=exc)) from exc
    if process.returncode:
        error = stderr.decode("utf-8", errors="replace").strip()
        if "NO_OCR_LANGUAGE" in error:
            raise RuntimeError(_("Nie je nainštalovaný žiadny jazyk pre Windows OCR. Nainštalujte jazykový balík s rozpoznávaním textu v nastaveniach Windows."))
        raise RuntimeError(_("Windows OCR zlyhalo: {error}").format(error=error))
    try:
        lines = json.loads(stdout.decode("utf-8-sig"))
        return [{"text": line["text"], "bbox": tuple(line["bbox"])} for line in lines]
    except (UnicodeError, ValueError, TypeError, KeyError) as exc:
        raise RuntimeError(_("Windows OCR vrátilo neplatný výsledok.")) from exc
