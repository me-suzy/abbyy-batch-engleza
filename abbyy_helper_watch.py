from __future__ import annotations

import datetime as dt
import time
from pathlib import Path

import pyautogui
from pywinauto import Desktop


PDF_DIR = Path(r"D:\ENGLEZA")
DONE_LOG = PDF_DIR / "_abbyy_convertite.txt"
HELPER_LOG = PDF_DIR / "_abbyy_helper.log"
CONVERTED_PDF_DIR = PDF_DIR / "PDF-uri convertite"


def log(message: str) -> None:
    line = f"[{dt.datetime.now():%Y-%m-%d %H:%M:%S}] {message}"
    print(line, flush=True)
    with HELPER_LOG.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def answer_no_to_save_changes() -> None:
    try:
        for dlg in Desktop(backend="uia").windows(title_re=r".*ABBYY FineReader 15.*"):
            texts = []
            for child in dlg.descendants():
                text = child.window_text()
                if text:
                    texts.append(text)
            joined = " ".join(texts).lower()
            if "do you want to save the changes" not in joined:
                continue

            no_button = dlg.child_window(title="No", control_type="Button")
            if no_button.exists(timeout=1):
                no_button.click_input()
                log("Am ales No la promptul de salvare a PDF-ului original.")
            else:
                dlg.set_focus()
                pyautogui.press("n")
                log("Am apasat N pentru No la promptul de salvare a PDF-ului original.")
    except Exception as exc:
        log(f"Eroare la verificarea promptului Save changes: {exc}")


def read_done_paths() -> list[Path]:
    if not DONE_LOG.exists():
        return []
    paths = []
    for line in DONE_LOG.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        path = Path(line)
        if path.suffix.lower() == ".pdf":
            paths.append(path)
    return paths


def move_done_pdfs() -> None:
    CONVERTED_PDF_DIR.mkdir(parents=True, exist_ok=True)
    for pdf in read_done_paths():
        docx = pdf.with_suffix(".docx")
        if not pdf.exists() or not docx.exists():
            continue

        target = CONVERTED_PDF_DIR / pdf.name
        if target.exists():
            continue

        try:
            pdf.replace(target)
            log(f"Mutat PDF convertit: {pdf.name}")
        except Exception as exc:
            log(f"Nu pot muta inca {pdf.name}: {exc}")


def main() -> None:
    log("Watcher pornit.")
    while True:
        answer_no_to_save_changes()
        move_done_pdfs()
        time.sleep(10)


if __name__ == "__main__":
    main()
