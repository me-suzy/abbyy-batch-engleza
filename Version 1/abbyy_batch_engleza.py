from __future__ import annotations

import argparse
import datetime as dt
import os
import subprocess
import sys
import time
from pathlib import Path

try:
    import pyautogui
    import pygetwindow as gw
    from pywinauto import Desktop
except ImportError as exc:
    print(
        "Lipseste un pachet Python necesar. Ruleaza:\n"
        "  python -m pip install pyautogui pygetwindow pywinauto\n"
    )
    raise SystemExit(1) from exc


PDF_DIR = Path(r"D:\ENGLEZA")
FINEREADER_EXE = Path(r"C:\Program Files (x86)\ABBYY FineReader 15\FineReader.exe")
MIN_SIZE_BYTES = 300 * 1024

DONE_LOG = PDF_DIR / "_abbyy_convertite.txt"
FAILED_LOG = PDF_DIR / "_abbyy_erori.txt"
RUN_LOG = PDF_DIR / "_abbyy_rulare.log"
QUEUE_LOG = PDF_DIR / "_abbyy_lista_pdf_de_procesat.txt"

STARTUP_WAIT_SECONDS = 3
OPEN_DIALOG_WAIT_SECONDS = 2
FILE_LOAD_WAIT_SECONDS = 20
SAVE_DIALOG_WAIT_SECONDS = 4
AFTER_SAVE_WAIT_SECONDS = 3

pyautogui.PAUSE = 0.55
pyautogui.FAILSAFE = True


def now() -> str:
    return dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def log(message: str, target: Path = RUN_LOG) -> None:
    line = f"[{now()}] {message}"
    print(line, flush=True)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def append_unique(path: Path, value: str) -> None:
    existing = read_log_set(path)
    if value.lower() in existing:
        return
    with path.open("a", encoding="utf-8") as f:
        f.write(value + "\n")


def read_log_set(path: Path) -> set[str]:
    if not path.exists():
        return set()
    return {
        line.strip().lower()
        for line in path.read_text(encoding="utf-8", errors="ignore").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }


def set_clipboard(text: str) -> None:
    # Tkinter is included with normal Python installs and avoids an extra pyperclip dependency.
    import tkinter as tk

    root = tk.Tk()
    root.withdraw()
    root.clipboard_clear()
    root.clipboard_append(text)
    root.update()
    root.destroy()


def paste_text(text: str) -> None:
    set_clipboard(text)
    pyautogui.hotkey("ctrl", "v")


def set_file_dialog_name(title_re: str, value: str, timeout: int = 15) -> bool:
    """Set the File name field in a Windows Open/Save dialog, then press Enter."""
    try:
        dlg = Desktop(backend="uia").window(title_re=title_re)
        dlg.wait("visible enabled ready", timeout=timeout)
        dlg.set_focus()

        combos = dlg.descendants(control_type="ComboBox")
        for combo in combos:
            name = (combo.window_text() or "").lower()
            if "file name" in name or "nume" in name:
                combo.set_focus()
                combo.type_keys("^a{BACKSPACE}", set_foreground=True)
                paste_text(value)
                pyautogui.press("enter")
                return True

        edits = dlg.descendants(control_type="Edit")
        for edit in edits:
            name = (edit.window_text() or "").lower()
            if "search" in name or "cauta" in name:
                continue
            edit.set_focus()
            edit.type_keys("^a{BACKSPACE}", set_foreground=True)
            paste_text(value)
            pyautogui.press("enter")
            return True

    except Exception as exc:
        log(f"Nu am putut seta dialogul prin pywinauto ({title_re}): {exc}")

    return False


def has_window_title(text: str) -> bool:
    text = text.lower()
    return any(text in (w.title or "").lower() for w in gw.getAllWindows())


def wait_until_window_title_gone(text: str, timeout: int) -> bool:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if not has_window_title(text):
            return True
        time.sleep(1)
    return not has_window_title(text)


def sleep_with_log(seconds: int, reason: str) -> None:
    end = time.monotonic() + seconds
    while True:
        remaining = int(end - time.monotonic())
        if remaining <= 0:
            return
        if remaining == seconds or remaining % 300 == 0 or remaining <= 30:
            log(f"Astept {remaining}s: {reason}")
        time.sleep(min(30, max(1, remaining)))


def activate_finereader(timeout: int = 30) -> bool:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        windows = [
            w
            for w in gw.getAllWindows()
            if "ABBYY FineReader" in w.title or "FineReader" in w.title
        ]
        if windows:
            win = windows[0]
            try:
                if win.isMinimized:
                    win.restore()
                win.activate()
                time.sleep(1)
                return True
            except Exception:
                time.sleep(1)
        else:
            time.sleep(1)
    return False


def launch_finereader() -> subprocess.Popen:
    if not FINEREADER_EXE.exists():
        raise FileNotFoundError(f"Nu gasesc FineReader: {FINEREADER_EXE}")
    log(f"Deschid FineReader: {FINEREADER_EXE}")
    return subprocess.Popen([str(FINEREADER_EXE)], cwd=str(PDF_DIR))


def close_finereader(proc: subprocess.Popen | None, force_kill: bool) -> None:
    log("Inchid FineReader cu Ctrl+Q.")
    activate_finereader(timeout=10)
    pyautogui.hotkey("ctrl", "q")
    time.sleep(10)

    still_running = proc is not None and proc.poll() is None
    if still_running:
        log("FineReader pare inca deschis; incerc Alt+F, Sageata sus, Enter.")
        activate_finereader(timeout=10)
        pyautogui.hotkey("alt", "f")
        pyautogui.press("up")
        pyautogui.press("enter")
        time.sleep(10)

    still_running = proc is not None and proc.poll() is None
    if still_running and force_kill:
        log("FineReader inca ruleaza; folosesc taskkill pentru a continua lotul.")
        subprocess.run(
            ["taskkill", "/IM", "FineReader.exe", "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )


def save_as_word_via_menu(output_docx: Path) -> None:
    # User's menu path: Alt+F, down x3, right, down x3, enter.
    pyautogui.hotkey("alt", "f")
    pyautogui.press("down", presses=3, interval=0.15)
    pyautogui.press("right")
    pyautogui.press("down", presses=3, interval=0.15)
    pyautogui.press("enter")

    time.sleep(SAVE_DIALOG_WAIT_SECONDS)

    # FineReader already fills the correct .docx filename in D:\ENGLEZA.
    # Press Enter only, which activates the Save button.
    log(f"Save As este deschis; apas Enter pentru Save: {output_docx.name}")
    pyautogui.press("enter")
    time.sleep(AFTER_SAVE_WAIT_SECONDS)


def open_pdf_from_start_screen(pdf: Path) -> bool:
    # User's start sequence: TAB, ENTER, then load the file in the open dialog.
    pyautogui.press("tab")
    pyautogui.press("enter")
    time.sleep(OPEN_DIALOG_WAIT_SECONDS)
    exact_path = str(pdf)
    log(f"Pun in Open un singur PDF, cu calea completa: {exact_path}")

    # Do not use Ctrl+A here. In this dialog it can select all files from the list.
    # The File name field is focused after the dialog opens, so we only insert one full path.
    pyautogui.write(exact_path, interval=0.001)
    time.sleep(0.5)
    pyautogui.press("enter")

    if wait_until_window_title_gone("Select Files to Open", timeout=12):
        return True

    log("Dialogul Open este inca deschis; opresc acest PDF ca sa nu scriu .docx in Open.")
    pyautogui.press("esc")
    return False


def process_pdf(pdf: Path, args: argparse.Namespace) -> bool:
    output_docx = pdf.with_suffix(".docx")
    log(f"Incep: {pdf.name}")
    proc: subprocess.Popen | None = None

    try:
        proc = launch_finereader()
        time.sleep(args.startup_wait)
        if not activate_finereader(timeout=30):
            raise RuntimeError("Nu pot activa fereastra FineReader.")

        if not open_pdf_from_start_screen(pdf):
            raise RuntimeError("PDF-ul nu s-a deschis; verifica daca in File name apare calea completa .pdf.")
        time.sleep(args.file_load_wait)

        # Step 5 from the requested flow.
        pyautogui.press("enter")
        time.sleep(2)

        save_as_word_via_menu(output_docx)
        sleep_with_log(args.conversion_wait, "conversie ABBYY")

        # Processing finished dialog: Enter closes the Close button.
        pyautogui.press("enter")
        time.sleep(3)

        if output_docx.exists() and output_docx.stat().st_size > 0:
            append_unique(DONE_LOG, str(pdf))
            log(f"Convertit OK: {pdf.name} -> {output_docx.name}")
            return True

        msg = f"NU gasesc docx dupa conversie: {pdf}"
        append_unique(FAILED_LOG, msg)
        log(msg)
        return False

    except Exception as exc:
        msg = f"EROARE la {pdf}: {exc}"
        append_unique(FAILED_LOG, msg)
        log(msg)
        return False

    finally:
        close_finereader(proc, force_kill=args.force_kill)
        sleep_with_log(args.after_close_wait, "pauza intre fisiere")


def build_queue() -> list[Path]:
    done = read_log_set(DONE_LOG)
    candidates = sorted(
        p
        for p in PDF_DIR.glob("*.pdf")
        if p.is_file() and p.stat().st_size >= MIN_SIZE_BYTES
    )

    queue: list[Path] = []
    for pdf in candidates:
        output_docx = pdf.with_suffix(".docx")
        if str(pdf).lower() in done:
            continue
        if output_docx.exists() and output_docx.stat().st_size > 0:
            append_unique(DONE_LOG, str(pdf))
            continue
        queue.append(pdf)

    QUEUE_LOG.write_text(
        "\n".join(str(p) for p in queue) + ("\n" if queue else ""),
        encoding="utf-8",
    )
    return queue


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Automatizeaza ABBYY FineReader 15 pentru PDF-urile din D:\\ENGLEZA."
    )
    parser.add_argument("--dry-run", action="store_true", help="Arata lista fara sa porneasca ABBYY.")
    parser.add_argument("--one", action="store_true", help="Proceseaza doar primul PDF din coada.")
    parser.add_argument(
        "--conversion-minutes",
        type=float,
        default=25,
        help="Cate minute asteapta conversia pentru fiecare PDF. Implicit: 25.",
    )
    parser.add_argument(
        "--after-close-minutes",
        type=float,
        default=4,
        help="Cate minute asteapta dupa inchiderea ABBYY. Implicit: 4.",
    )
    parser.add_argument(
        "--startup-wait",
        type=int,
        default=STARTUP_WAIT_SECONDS,
        help="Secunde de asteptare dupa pornirea ABBYY. Implicit: 10.",
    )
    parser.add_argument(
        "--file-load-wait",
        type=int,
        default=FILE_LOAD_WAIT_SECONDS,
        help="Secunde de asteptare dupa alegerea PDF-ului. Implicit: 20.",
    )
    parser.add_argument(
        "--force-kill",
        action="store_true",
        help="Daca ABBYY nu se inchide din tastatura, inchide procesul cu taskkill.",
    )
    args = parser.parse_args()
    args.conversion_wait = int(args.conversion_minutes * 60)
    args.after_close_wait = int(args.after_close_minutes * 60)
    return args


def main() -> int:
    args = parse_args()

    if os.name != "nt":
        print("Acest script este pentru Windows.")
        return 1
    if not PDF_DIR.exists():
        print(f"Nu gasesc folderul: {PDF_DIR}")
        return 1

    queue = build_queue()
    log(f"PDF-uri eligibile ramase in coada: {len(queue)}")

    if args.dry_run:
        for idx, pdf in enumerate(queue, start=1):
            print(f"{idx:03d}. {pdf}")
        print(f"\nLista a fost scrisa si aici: {QUEUE_LOG}")
        return 0

    if args.one:
        queue = queue[:1]

    for idx, pdf in enumerate(queue, start=1):
        log(f"=== {idx}/{len(queue)} ===")
        process_pdf(pdf, args)

    log("Lot terminat.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
