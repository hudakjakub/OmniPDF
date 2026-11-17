"""Local OCR using the Windows language packs installed for the current user."""
import json
import subprocess
from pathlib import Path


def recognize(image_path: str | Path) -> list[dict]:
    script = Path(__file__).with_name("windows_ocr.ps1")
    try:
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(script), "-ImagePath", str(Path(image_path).resolve())],
            capture_output=True, timeout=120, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError(f"Nepodarilo sa spustiť Windows OCR: {exc}") from exc
    if result.returncode:
        error = result.stderr.decode("utf-8", errors="replace").strip()
        if "NO_OCR_LANGUAGE" in error:
            raise RuntimeError("Nie je nainštalovaný žiadny jazyk pre Windows OCR. Nainštalujte jazykový balík s rozpoznávaním textu v nastaveniach Windows.")
        raise RuntimeError(f"Windows OCR zlyhalo: {error}")
    try:
        lines = json.loads(result.stdout.decode("utf-8-sig"))
        return [{"text": line["text"], "bbox": tuple(line["bbox"])} for line in lines]
    except (UnicodeError, ValueError, TypeError, KeyError) as exc:
        raise RuntimeError("Windows OCR vrátilo neplatný výsledok.") from exc
