#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import time
import traceback
from pathlib import Path
from typing import Tuple

from playwright.sync_api import sync_playwright, Page, Frame

# =========================
# CONFIG
# =========================
LOGIN_URL = "https://useast.services.cloud.techzone.ibm.com:35391/"
USERNAME = "demo"
PASSWORD = "Guardium123!"
WELCOME_SELECTOR = "div.guard--welcome-page--page-subtitle"

CUSTOMER_UPLOADS_WAIT_S = 15
POST_PICK_BEFORE_UPLOAD_S = 2

# After confirming the final dialog (import confirmation), wait before closing browser
POST_FINAL_OK_WAIT_S = 15

FILE_TO_UPLOAD = Path(r"U:\-=GUARDIUM\Guardium 12.2 INSTALL\Guardium_V12_Quarterly_DPS_2026_Q1_20260216.enc")

# Browse button (your target)
BROWSE_BUTTON_XPATH = "xpath=//*[@id='guard/common/util/FileUploader_0']/div/form/span"

# Upload button (exactly as you provided)
UPLOAD_BUTTON_ABS_XPATH = "xpath=/html/body/form/table/tbody/tr[2]/td/div/table/tbody/tr[2]/td/span/button"

# Start import icon (exactly as you provided)
START_IMPORT_ICON_XPATH = "xpath=/html/body/form/table/tbody/tr[2]/td/div/table/tbody/tr[5]/td/table/tbody/tr[3]/td[1]/img[2]"

DEBUG_DIR = Path("debug")
DEBUG_DIR.mkdir(parents=True, exist_ok=True)

# =========================
# DEBUG HELPERS
# =========================
def dump_page(page: Page, label: str):
    ts = int(time.time())
    png = DEBUG_DIR / f"{ts}_{label}.png"
    html = DEBUG_DIR / f"{ts}_{label}.html"
    try:
        page.screenshot(path=png, full_page=True)
    except Exception:
        pass
    try:
        html.write_text(page.content(), encoding="utf-8")
    except Exception:
        pass
    print(f"[DUMP] {png.name} | {html.name}")

def dump_frame(frame: Frame, label: str, idx: int):
    ts = int(time.time())
    safe_name = (frame.name or f"frame_{idx}").replace("/", "_").replace("\\", "_").replace(":", "_")
    html = DEBUG_DIR / f"{ts}_{label}_idx{idx}_{safe_name}.html"
    meta = DEBUG_DIR / f"{ts}_{label}_idx{idx}_{safe_name}.txt"
    try:
        html.write_text(frame.content(), encoding="utf-8")
    except Exception:
        pass
    try:
        meta.write_text(f"name={frame.name}\nurl={frame.url}\n", encoding="utf-8")
    except Exception:
        pass
    print(f"[DUMP_FRAME] {html.name} | {meta.name}")

def wait_bbox_visible(locator, timeout_ms=60000, poll_ms=250):
    end = time.time() + timeout_ms / 1000
    while time.time() < end:
        try:
            if locator.count() > 0:
                box = locator.first.bounding_box()
                if box and box.get("width", 0) > 0 and box.get("height", 0) > 0:
                    return True
        except Exception:
            pass
        time.sleep(poll_ms / 1000)
    return False

def safe_click_cell(page: Page, text: str, timeout_ms=60000):
    """Klik w komórkę treści gridx (nie w expando)."""
    cell = page.locator(
        "div.gridxTreeExpandoContent.gridxCellContent",
        has_text=text
    ).first

    end = time.time() + timeout_ms / 1000
    while time.time() < end and cell.count() == 0:
        time.sleep(0.2)

    try:
        cell.scroll_into_view_if_needed()
    except Exception:
        pass
    try:
        cell.click(timeout=2000)
    except Exception:
        try:
            cell.evaluate("(el)=>el.click()")
        except Exception as e:
            raise TimeoutError(f"Nie mogę kliknąć '{text}': {e}")

def attach_debug_listeners(page: Page):
    """Logi: konsola, błędy, dialogi, filechooser, frame navigation."""
    def on_console(msg):
        try:
            print(f"[CONSOLE] {msg.type}: {msg.text}")
        except Exception:
            pass

    def on_page_error(err):
        try:
            print(f"[PAGEERROR] {err}")
        except Exception:
            pass

    def on_frame_navigated(frame: Frame):
        try:
            print(f"[FRAME_NAV] name='{frame.name}' url='{frame.url}'")
        except Exception:
            pass

    def on_dialog(dialog):
        try:
            print(f"[DIALOG_EVENT] type={dialog.type} message='{dialog.message}'")
        except Exception:
            pass

    def on_filechooser(fc):
        try:
            print("[FILECHOOSER_EVENT] filechooser appeared")
        except Exception:
            pass

    page.on("console", on_console)
    page.on("pageerror", on_page_error)
    page.on("framenavigated", on_frame_navigated)
    page.on("dialog", on_dialog)
    page.on("filechooser", on_filechooser)

def probe_frames(page: Page, label: str):
    """Dump HTML wszystkich frame’ów do debug/ + podstawowe info."""
    print(f"\n[PROBE] ===== {label} =====")
    frames = page.frames
    print(f"[PROBE] page.frames count = {len(frames)}")
    for i, fr in enumerate(frames):
        try:
            nodes = fr.evaluate("() => document.getElementsByTagName('*').length")
        except Exception:
            nodes = -1
        try:
            c_browse = fr.locator(BROWSE_BUTTON_XPATH).count()
        except Exception:
            c_browse = -1
        print(f"[PROBE] FRAME[{i}] name='{fr.name}' url='{fr.url}' nodes={nodes} browse_count={c_browse}")
        dump_frame(fr, label, i)
    print(f"[PROBE] ===== END {label} =====\n")

# =========================
# SCOPE HELPERS
# =========================
def find_scope_with_browse(page: Page) -> Tuple[object, str]:
    """Znajdź gdzie jest Browse: w page albo w którymś frame."""
    try:
        if page.locator(BROWSE_BUTTON_XPATH).count() > 0:
            return page, "page(main)"
    except Exception:
        pass

    for i, fr in enumerate(page.frames):
        try:
            if fr.locator(BROWSE_BUTTON_XPATH).count() > 0:
                return fr, f"frame[{i}] name='{fr.name}' url='{fr.url}'"
        except Exception:
            continue

    return page, "page(main) [fallback-not-found]"

def click_locator(scope, selector: str, timeout_ms=60000, label="click"):
    loc = scope.locator(selector).first
    if not wait_bbox_visible(loc, timeout_ms=timeout_ms):
        raise TimeoutError(f"[{label}] Nie widać elementu: {selector}")
    try:
        loc.scroll_into_view_if_needed()
    except Exception:
        pass
    try:
        loc.click(timeout=2000)
    except Exception:
        try:
            loc.evaluate("(el)=>el.click()")
        except Exception as e:
            raise TimeoutError(f"[{label}] Nie mogę kliknąć {selector}: {e}")

# =========================
# FLOW
# =========================
def login(page: Page):
    print("[STEP] LOGIN")
    page.goto(LOGIN_URL, wait_until="domcontentloaded")
    page.fill("input[name='username']", USERNAME)
    page.fill("input[name='password']", PASSWORD)
    page.press("input[name='password']", "Enter")

    if not wait_bbox_visible(page.locator(WELCOME_SELECTOR), 60000):
        dump_page(page, "welcome_timeout")
        raise TimeoutError("Nie widać ekranu powitalnego po logowaniu")

    dump_page(page, "after_login")

def open_customer_uploads(page: Page):
    print("[STEP] NAV: open left tree")
    try:
        page.locator("span.dijitIcon.navToggleIcon").first.click()
    except Exception:
        pass

    print("[STEP] NAV: Harden")
    harden = page.locator("#navItemDesc_harden").locator("..")
    try:
        harden.first.click(timeout=1500)
    except Exception:
        harden.first.evaluate("(el)=>el.click()")

    print("[STEP] NAV: Vulnerability Assessment")
    safe_click_cell(page, "Vulnerability Assessment", 60000)

    print("[STEP] NAV: Customer Uploads")
    safe_click_cell(page, "Customer Uploads", 60000)
    dump_page(page, "after_customer_uploads_click")

def wait_for_dynamic_content(page: Page):
    probe_frames(page, "probe_before_wait")
    print(f"[WAIT] Customer Uploads dynamic content: sleep {CUSTOMER_UPLOADS_WAIT_S}s")
    time.sleep(CUSTOMER_UPLOADS_WAIT_S)
    dump_page(page, "after_customer_uploads_wait")
    probe_frames(page, "probe_after_wait")

def set_file_prev_style_with_diagnostics(page: Page, scope, file_path: Path) -> bool:
    """
    Prefer: expect_file_chooser + chooser.set_files
    If not captured, send ESC (close possible native dialog) then fallback to set_input_files.
    Returns True if textbox confirms file name.
    """
    if not file_path.exists():
        raise FileNotFoundError(f"Plik nie istnieje: {file_path}")

    print("[STEP] FILE: try expect_file_chooser on Browse")
    dump_page(page, "before_try_filechooser")

    chooser_set = False
    browse = scope.locator(BROWSE_BUTTON_XPATH).first

    # 1) Prefer: capture filechooser
    try:
        if browse.count() > 0:
            try:
                browse.scroll_into_view_if_needed()
            except Exception:
                pass

            try:
                with page.expect_file_chooser(timeout=5000) as fc_info:
                    try:
                        browse.click(timeout=2000)
                    except Exception:
                        browse.evaluate("(el)=>el.click()")

                chooser = fc_info.value
                chooser.set_files(str(file_path))
                chooser_set = True
                print("[OK] chooser.set_files() executed")
                dump_page(page, "after_chooser_set_files")
            except Exception as e:
                print(f"[WARN] filechooser not captured: {e}")
                chooser_set = False
    except Exception as e:
        print(f"[WARN] browse/chooser flow failed: {e}")
        chooser_set = False

    # If not captured, possible native dialog -> ESC
    if not chooser_set:
        print("[DIAG] Sending ESC to close possible native file dialog")
        try:
            page.keyboard.press("Escape")
            time.sleep(0.7)
        except Exception:
            pass
        dump_page(page, "after_escape_attempt")

    # 2) Fallback: set_input_files (overlay/offscreen)
    if not chooser_set:
        print("[STEP] FILE: fallback to set_input_files (overlay/offscreen)")
        loc_overlay = scope.locator(
            "xpath=//*[normalize-space(text())='DPS Upload']"
            "/following::span[contains(@class,'dijitUploader')][1]"
            "//input[@type='file' and @name='uploadedfile']"
        ).first

        loc_offscreen = scope.locator(
            "xpath=//*[normalize-space(text())='DPS Upload']"
            "/following::input[@type='file' and @name='uploadedfile'"
            " and contains(@class,'dijitOffScreen')][1]"
        ).first

        if loc_overlay.count() == 0 and loc_offscreen.count() == 0:
            try:
                scope.locator("xpath=//*[normalize-space(text())='DPS Upload']").first.scroll_into_view_if_needed()
                time.sleep(0.3)
            except Exception:
                pass

        try:
            if loc_overlay.count() > 0:
                print("[INFO] set_input_files -> overlay input")
                loc_overlay.set_input_files(str(file_path))
            elif loc_offscreen.count() > 0:
                print("[INFO] set_input_files -> offscreen input")
                loc_offscreen.set_input_files(str(file_path))
            else:
                dump_page(page, "dps_inputs_not_found")
                raise RuntimeError("Nie znalazłem input[type=file] pod 'DPS Upload'")
        except Exception:
            dump_page(page, "dps_set_input_files_error")
            raise

        dump_page(page, "after_set_input_files")

    # 3) Validate textbox contains filename
    tb = scope.locator(
        "xpath=//*[normalize-space(text())='DPS Upload']"
        "/following::*[contains(@class,'dijitTextBox')][1]//input[@type='text']"
    ).first

    print("[STEP] CHECK filename echoed in textbox")
    confirmed = False
    for i in range(40):  # ~20s
        try:
            val = tb.input_value(timeout=500)
        except Exception:
            val = ""
        print(f"[DEBUG] textbox value try {i}: '{val}'")
        if val and file_path.name in val:
            print("[OK] filename visible in textbox (plik wskazany)")
            confirmed = True
            break
        time.sleep(0.5)

    dump_page(page, "after_file_chosen_confirm")
    if not confirmed:
        print("[DIAG] File not confirmed -> dumping frames")
        probe_frames(page, "probe_after_file_not_confirmed")

    return confirmed

def click_upload_then_ok(page: Page, scope):
    """
    Click Upload, wait for dialog, accept OK.
    Returns dialog message (for logging).
    """
    print(f"[WAIT] After pick file: sleep {POST_PICK_BEFORE_UPLOAD_S}s before Upload")
    time.sleep(POST_PICK_BEFORE_UPLOAD_S)
    dump_page(page, "before_upload_click")

    print("[STEP] Click Upload + expect dialog OK")
    try:
        with page.expect_event("dialog", timeout=20000) as dlg_info:
            click_locator(scope, UPLOAD_BUTTON_ABS_XPATH, timeout_ms=60000, label="upload")
        dialog = dlg_info.value
        msg = dialog.message
        print(f"[DIALOG] (upload) message: {msg}")
        dialog.accept()
        print("[OK] Upload dialog accepted (OK)")
        dump_page(page, "after_upload_dialog_ok")
        return msg
    except Exception as e:
        dump_page(page, "upload_dialog_not_captured")
        probe_frames(page, "probe_after_upload_dialog_not_captured")
        raise RuntimeError(f"Nie udało się przechwycić/zaakceptować okna OK po upload: {e}")

def click_start_import_then_ok(page: Page, scope):
    """
    After upload OK: click the import icon and accept the next dialog OK.
    """
    print("[STEP] Start Import: click icon + expect dialog OK")
    dump_page(page, "before_start_import_click")
    try:
        with page.expect_event("dialog", timeout=30000) as dlg_info:
            click_locator(scope, START_IMPORT_ICON_XPATH, timeout_ms=60000, label="start_import")
        dialog = dlg_info.value
        msg = dialog.message
        print(f"[DIALOG] (import) message: {msg}")
        dialog.accept()
        print("[OK] Import dialog accepted (OK)")
        dump_page(page, "after_import_dialog_ok")
        return msg
    except Exception as e:
        dump_page(page, "import_dialog_not_captured")
        probe_frames(page, "probe_after_import_dialog_not_captured")
        raise RuntimeError(f"Nie udało się przechwycić/zaakceptować okna OK po starcie importu: {e}")

def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context(ignore_https_errors=True)
        page = context.new_page()

        attach_debug_listeners(page)

        try:
            login(page)
            open_customer_uploads(page)

            # wait + diagnostics
            wait_for_dynamic_content(page)

            # find scope where Browse exists
            scope, scope_desc = find_scope_with_browse(page)
            print(f"[INFO] Browse scope selected: {scope_desc}")

            # pick file (stable version + ESC fallback)
            confirmed = set_file_prev_style_with_diagnostics(page, scope, FILE_TO_UPLOAD)
            if not confirmed:
                print("[WARN] File not confirmed in textbox, continuing anyway (may still work).")

            # Upload -> OK
            click_upload_then_ok(page, scope)

            # Start import -> OK
            click_start_import_then_ok(page, scope)

            # final wait before close
            print(f"[WAIT] Final wait {POST_FINAL_OK_WAIT_S}s before closing browser")
            time.sleep(POST_FINAL_OK_WAIT_S)

            print("\n✅ DONE\n")

        except Exception:
            print("\n❌ ERROR")
            traceback.print_exc()
            dump_page(page, "fatal_error")
            try:
                probe_frames(page, "probe_after_fatal_error")
            except Exception:
                pass

        finally:
            try:
                browser.close()
            except Exception:
                pass
            print("🛑 Browser closed")

if __name__ == "__main__":
    main()