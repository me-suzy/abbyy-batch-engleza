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
CONVERTED_PDF_DIR = PDF_DIR / "PDF-uri convertite"

DONE_LOG = PDF_DIR / "_abbyy_convertite.txt"
FAILED_LOG = PDF_DIR / "_abbyy_erori.txt"
RUN_LOG = PDF_DIR / "_abbyy_rulare.log"
QUEUE_LOG = PDF_DIR / "_abbyy_lista_pdf_de_procesat.txt"
LOCK_FILE = PDF_DIR / "_abbyy_batch.lock"

STARTUP_WAIT_SECONDS = 3
OPEN_DIALOG_WAIT_SECONDS = 2
FILE_LOAD_WAIT_SECONDS = 20
SAVE_DIALOG_WAIT_SECONDS = 4
AFTER_SAVE_WAIT_SECONDS = 3
CHECK_INTERVAL_MINUTES = 3.5
MAX_CONVERSION_MINUTES = 180

pyautogui.PAUSE = 0.55
pyautogui.FAILSAFE = False


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


def process_is_alive(pid: int) -> bool:
    result = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-Command",
            f"if (Get-Process -Id {pid} -ErrorAction SilentlyContinue) {{ 'YES' }}",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    return "YES" in result.stdout


def acquire_run_lock() -> int:
    if LOCK_FILE.exists():
        existing = LOCK_FILE.read_text(encoding="utf-8", errors="ignore").strip()
        if existing.isdigit() and process_is_alive(int(existing)):
            raise RuntimeError(
                f"Scriptul pare deja pornit cu PID {existing}. "
                "Nu pornesc a doua instanta."
            )
        LOCK_FILE.unlink(missing_ok=True)

    fd = os.open(str(LOCK_FILE), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    os.write(fd, str(os.getpid()).encode("ascii"))
    return fd


def release_run_lock(fd: int | None) -> None:
    if fd is not None:
        os.close(fd)
        LOCK_FILE.unlink(missing_ok=True)


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


def finereader_process_ids() -> list[int]:
    result = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-Command",
            "Get-Process FineReader -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Id",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    ids: list[int] = []
    for line in result.stdout.splitlines():
        line = line.strip()
        if line.isdigit():
            ids.append(int(line))
    return ids


def force_kill_finereader() -> None:
    subprocess.run(
        ["taskkill", "/IM", "FineReader.exe", "/F"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )


def cleanup_stale_finereader() -> None:
    ids = finereader_process_ids()
    if not ids:
        return

    log(f"Curat {len(ids)} instanta(e) FineReader ramase inainte de urmatorul PDF.")
    answer_no_to_save_changes()
    time.sleep(2)
    force_kill_finereader()
    time.sleep(3)


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


def activate_window_by_title(text: str, timeout: int = 10) -> bool:
    text = text.lower()
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        windows = [
            w
            for w in gw.getAllWindows()
            if text in (w.title or "").lower()
        ]
        if windows:
            win = windows[0]
            try:
                if win.isMinimized:
                    win.restore()
                win.activate()
                time.sleep(0.8)
                return True
            except Exception:
                time.sleep(0.5)
        else:
            time.sleep(0.5)
    return False


def focus_finereader(action: str, timeout: int = 10) -> None:
    if activate_finereader(timeout=timeout):
        return
    log(f"Atentie: nu pot aduce FineReader in fata inainte de: {action}")


def launch_finereader() -> subprocess.Popen:
    if not FINEREADER_EXE.exists():
        raise FileNotFoundError(f"Nu gasesc FineReader: {FINEREADER_EXE}")
    cleanup_stale_finereader()
    log(f"Deschid FineReader: {FINEREADER_EXE}")
    return subprocess.Popen([str(FINEREADER_EXE)], cwd=str(PDF_DIR))


def close_finereader(proc: subprocess.Popen | None, force_kill: bool) -> None:
    log("Inchid FineReader cu Ctrl+Q.")
    focus_finereader("Ctrl+Q", timeout=10)
    pyautogui.hotkey("ctrl", "q")
    time.sleep(3)
    answer_no_to_save_changes()
    time.sleep(7)

    still_running = proc is not None and proc.poll() is None
    if still_running:
        log("FineReader pare inca deschis; incerc Alt+F, Sageata sus, Enter.")
        focus_finereader("Alt+F Exit", timeout=10)
        pyautogui.hotkey("alt", "f")
        pyautogui.press("up")
        pyautogui.press("enter")
        time.sleep(3)
        answer_no_to_save_changes()
        time.sleep(7)

    still_running = proc is not None and proc.poll() is None
    if still_running and force_kill:
        log("FineReader inca ruleaza; folosesc taskkill pentru a continua lotul.")
        force_kill_finereader()
        time.sleep(2)


def answer_no_to_save_changes() -> bool:
    # FineReader may ask whether to save changes to the original PDF.
    # We already saved the DOCX, so answer No and do not modify the source PDF.
    try:
        dialogs = Desktop(backend="uia").windows(title_re=r".*ABBYY FineReader 15.*")
        for dlg in dialogs:
            texts = " ".join(
                child.window_text()
                for child in dlg.descendants()
                if child.window_text()
            ).lower()
            if "do you want to save the changes" in texts:
                log("A aparut intrebarea de salvare a PDF-ului original; aleg No.")
                no_button = dlg.child_window(title="No", control_type="Button")
                no_button.click_input()
                return True
    except Exception as exc:
        log(f"Nu am putut trata promptul Save changes prin pywinauto: {exc}")

    return False


def click_conversion_close_button() -> bool:
    try:
        dialogs = Desktop(backend="uia").windows(title_re=r".*Conversion.*")
        for dlg in dialogs:
            close_button = dlg.child_window(title="Close", control_type="Button")
            if close_button.exists(timeout=1):
                log("Dialogul Conversion gasit; apas Close direct.")
                close_button.click_input()
                time.sleep(1)
                return True
    except Exception as exc:
        log(f"Nu am putut verifica dialogul Conversion prin pywinauto: {exc}")

    return False


def close_conversion_dialog() -> bool:
    if click_conversion_close_button():
        return True

    if activate_window_by_title("Conversion", timeout=5):
        log("Dialogul Conversion este in fata; apas Enter pentru Close.")
        pyautogui.press("enter")
        time.sleep(1)
        return True

    focus_finereader("Enter pe Conversion Close", timeout=10)
    pyautogui.press("enter")
    time.sleep(1)
    return False


def output_docx_is_stable(output_docx: Path, previous_size: int | None) -> tuple[bool, int | None]:
    if not output_docx.exists():
        return False, None

    size = output_docx.stat().st_size
    if size <= 0:
        return False, size

    if previous_size is not None and previous_size == size:
        log(f"DOCX exista si are marime stabila: {output_docx.name} ({size} bytes).")
        return True, size

    log(f"DOCX exista, astept confirmare marime stabila: {output_docx.name} ({size} bytes).")
    return False, size


def wait_for_conversion_finished(check_seconds: int, max_seconds: int, output_docx: Path) -> bool:
    start = time.monotonic()
    check_no = 0
    last_docx_size: int | None = None

    while True:
        elapsed = int(time.monotonic() - start)
        if elapsed >= max_seconds:
            log(f"Conversia nu a terminat in {max_seconds // 60} minute; opresc incercarea.")
            return False

        remaining_to_next = min(check_seconds, max_seconds - elapsed)
        check_no += 1
        log(
            f"Astept {remaining_to_next // 60} minute pana la verificarea #{check_no} "
            "a dialogului Conversion."
        )
        sleep_with_log(remaining_to_next, "verificare conversie ABBYY")

        focus_finereader(f"verificare conversie #{check_no}", timeout=10)
        if click_conversion_close_button():
            log(f"Conversia este gata la verificarea #{check_no}.")
            return True

        stable, last_docx_size = output_docx_is_stable(output_docx, last_docx_size)
        if stable:
            log("Consider conversia terminata fiindca DOCX-ul este deja scris si stabil.")
            return True

        log(f"Conversia nu este gata la verificarea #{check_no}; continui.")


def move_converted_pdf(pdf: Path) -> None:
    if not pdf.exists():
        return

    CONVERTED_PDF_DIR.mkdir(parents=True, exist_ok=True)
    target = CONVERTED_PDF_DIR / pdf.name
    if target.exists():
        stem = target.stem
        suffix = target.suffix
        stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
        target = CONVERTED_PDF_DIR / f"{stem}_{stamp}{suffix}"

    try:
        pdf.replace(target)
        log(f"Mut PDF convertit: {pdf.name} -> {target}")
    except OSError as exc:
        log(f"Nu pot muta inca PDF-ul convertit {pdf.name}; probabil este folosit de ABBYY: {exc}")


def click_menu_item_by_text(text: str, timeout: int = 5) -> bool:
    expected = text.replace("&", "").strip().lower()
    end = time.monotonic() + timeout

    while time.monotonic() < end:
        try:
            items = Desktop(backend="uia").descendants(control_type="MenuItem")
            for item in items:
                label = (item.window_text() or "").replace("&", "").strip().lower()
                if label == expected:
                    item.click_input()
                    time.sleep(0.5)
                    return True
        except Exception:
            time.sleep(0.3)

        time.sleep(0.3)

    return False


def choose_microsoft_word_export() -> bool:
    focus_finereader("alegere Microsoft Word", timeout=10)
    width, height = pyautogui.size()
    pyautogui.moveTo(width - 20, height // 2, duration=0.1)
    pyautogui.hotkey("alt", "f")
    time.sleep(0.6)

    if click_menu_item_by_text("Convert To", timeout=3):
        if click_menu_item_by_text("Microsoft Word", timeout=3):
            return True

    # Fallback for the menu layout shown by ABBYY:
    # File -> Convert To -> Microsoft Word. This is intentionally not the old
    # down-3/down-3 path, which could land on Scan To -> Image File.
    log("Nu am putut selecta Microsoft Word prin UIA; folosesc fallback precis din tastatura.")
    focus_finereader("fallback Microsoft Word", timeout=10)
    pyautogui.hotkey("alt", "f")
    time.sleep(0.3)
    pyautogui.press("down", presses=2, interval=0.12)
    pyautogui.press("right")
    pyautogui.press("down", presses=1, interval=0.12)
    pyautogui.press("enter")
    return True


def save_dialog_is_word(output_docx: Path) -> bool:
    if not activate_window_by_title("Save document as", timeout=8):
        log("Nu gasesc dialogul Save document as dupa alegerea Microsoft Word.")
        return False

    try:
        dlg = Desktop(backend="uia").window(title_re=r".*Save document as.*")
        dlg.wait("visible", timeout=3)
        text = " ".join(
            child.window_text()
            for child in dlg.descendants()
            if child.window_text()
        ).lower()
        if "microsoft word document" in text and ".docx" in text:
            return True
        log(f"Dialogul Save As nu pare setat pe Word/docx. Text detectat: {text[:500]}")
        return False
    except Exception as exc:
        log(f"Nu pot verifica dialogul Save As prin UIA: {exc}")
        return False


def save_as_word_via_menu(output_docx: Path) -> None:
    if not choose_microsoft_word_export():
        raise RuntimeError("Nu pot selecta exportul Microsoft Word din meniul ABBYY.")

    time.sleep(SAVE_DIALOG_WAIT_SECONDS)

    if not save_dialog_is_word(output_docx):
        pyautogui.press("esc")
        raise RuntimeError("Dialogul Save As nu este setat pe Microsoft Word Document (*.docx).")

    # FineReader already fills the correct .docx filename in D:\ENGLEZA.
    # Press Enter only, which activates the Save button.
    log(f"Save As este deschis; apas Enter pentru Save: {output_docx.name}")
    activate_window_by_title("Save document as", timeout=5)
    pyautogui.press("enter")
    time.sleep(AFTER_SAVE_WAIT_SECONDS)


def open_pdf_from_start_screen(pdf: Path) -> bool:
    # User's start sequence: TAB, ENTER, then load the file in the open dialog.
    focus_finereader("Open PDF", timeout=10)
    pyautogui.press("tab")
    pyautogui.press("enter")
    time.sleep(OPEN_DIALOG_WAIT_SECONDS)
    exact_path = str(pdf)
    log(f"Pun in Open un singur PDF, cu calea completa: {exact_path}")

    # Do not use Ctrl+A here. In this dialog it can select all files from the list.
    # The File name field is focused after the dialog opens, so we only insert one full path.
    activate_window_by_title("Select Files to Open", timeout=5)
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
        focus_finereader("Enter dupa incarcarea PDF-ului", timeout=10)
        pyautogui.press("enter")
        time.sleep(2)

        save_as_word_via_menu(output_docx)
        conversion_finished = wait_for_conversion_finished(
            args.check_interval_seconds,
            args.max_conversion_seconds,
            output_docx,
        )
        time.sleep(3)

        if output_docx.exists() and output_docx.stat().st_size > 0:
            append_unique(DONE_LOG, str(pdf))
            move_converted_pdf(pdf)
            if conversion_finished:
                log(f"Convertit OK: {pdf.name} -> {output_docx.name}")
            else:
                log(f"Convertit OK dupa verificare DOCX existenta: {pdf.name} -> {output_docx.name}")
            return True

        msg = f"Conversia nu s-a confirmat sau nu gasesc docx dupa conversie: {pdf}"
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
        default=None,
        help="Compatibilitate: seteaza maximul de minute pentru conversie.",
    )
    parser.add_argument(
        "--check-minutes",
        type=float,
        default=CHECK_INTERVAL_MINUTES,
        help="La cate minute verifica daca ABBYY a terminat conversia. Implicit: 3.5.",
    )
    parser.add_argument(
        "--max-conversion-minutes",
        type=float,
        default=MAX_CONVERSION_MINUTES,
        help="Maximul de minute pentru un PDF inainte sa fie marcat cu eroare. Implicit: 180.",
    )
    parser.add_argument(
        "--after-close-minutes",
        type=float,
        default=3,
        help="Cate minute asteapta dupa inchiderea ABBYY. Implicit: 3.",
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
        dest="force_kill",
        action="store_true",
        default=True,
        help="Daca ABBYY nu se inchide din tastatura, inchide procesul cu taskkill. Activ implicit.",
    )
    parser.add_argument(
        "--no-force-kill",
        dest="force_kill",
        action="store_false",
        help="Nu forta inchiderea ABBYY daca ramane blocat.",
    )
    args = parser.parse_args()
    if args.conversion_minutes is not None:
        args.max_conversion_minutes = args.conversion_minutes
    args.check_interval_seconds = int(args.check_minutes * 60)
    args.max_conversion_seconds = int(args.max_conversion_minutes * 60)
    args.after_close_wait = int(args.after_close_minutes * 60)
    return args


def main() -> int:
    args = parse_args()
    lock_fd: int | None = None

    if os.name != "nt":
        print("Acest script este pentru Windows.")
        return 1
    if not PDF_DIR.exists():
        print(f"Nu gasesc folderul: {PDF_DIR}")
        return 1

    try:
        if not args.dry_run:
            lock_fd = acquire_run_lock()

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

    except RuntimeError as exc:
        log(f"OPRIT: {exc}")
        return 1

    finally:
        release_run_lock(lock_fd)


if __name__ == "__main__":
    raise SystemExit(main())
