#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import time
import traceback
from pathlib import Path
from typing import Tuple, Optional, List

from playwright.sync_api import sync_playwright, Page, Frame

# =========================
# CONFIG
# =========================
LOGIN_URL = "https://eu-de.services.cloud.techzone.ibm.com:36561"
USERNAME = "demo"
PASSWORD = "Guardium123!"
WELCOME_SELECTOR = "div.guard--welcome-page--page-subtitle"

CUSTOMER_UPLOADS_WAIT_S = 15
POST_PICK_BEFORE_UPLOAD_S = 2

# Po ilu sekundach robić fallback ESC (gdy alert jeszcze się nie pojawił)
DIALOG_ESC_FALLBACK_AFTER_S = 5

# Ile maksymalnie czekać na alert (Upload/Import)
DIALOG_MAX_WAIT_S = 60

# Ile maksymalnie czekać na pojawienie się tabeli/wiersza po uploadzie
IMPORT_ROW_MAX_WAIT_S = 90

FILE_TO_UPLOAD = Path(r"U:\-=GUARDIUM\Guardium 12.2 INSTALL\Guardium_V12_Quarterly_DPS_2026_Q1_20260216.enc")

# Browse (Twoje wskazanie)
BROWSE_BUTTON_XPATH = "xpath=//*[@id='guard/common/util/FileUploader_0']/div/form/span"

# Upload button (Twoje wskazanie)
UPLOAD_BUTTON_ABS_XPATH = "xpath=/html/body/form/table/tbody/tr[2]/td/div/table/tbody/tr[2]/td/span/button"

# Zostaw browser otwarty po imporcie (zamrożenie)
KEEP_BROWSER_OPEN = True

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

    def on_filechooser(_fc):
        try:
            print("[FILECHOOSER_EVENT] filechooser appeared")
        except Exception:
            pass

    def on_dialog(dialog):
        try:
            print(f"[DIALOG_EVENT] type={dialog.type} message='{dialog.message}'")
        except Exception:
            pass

    page.on("console", on_console)
    page.on("pageerror", on_page_error)
    page.on("framenavigated", on_frame_navigated)
    page.on("filechooser", on_filechooser)
    page.on("dialog", on_dialog)

# =========================
# SCOPE HELPERS
# =========================
def find_scope_with_browse(page: Page) -> Tuple[object, str]:
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

def find_best_scope_for_import(page: Page) -> Tuple[object, str]:
    """
    Import tabela często jest w ramce 'harden_custupld' / subscribedGroupUpload.action.
    Jeśli nie znajdziemy, używamy page(main).
    """
    # prefer frame by URL fragment
    for i, fr in enumerate(page.frames):
        try:
            if "subscribedGroupUpload.action" in (fr.url or ""):
                return fr, f"frame[{i}] url contains subscribedGroupUpload.action"
        except Exception:
            pass
    # prefer frame by name
    for i, fr in enumerate(page.frames):
        try:
            if (fr.name or "") == "harden_custupld":
                return fr, f"frame[{i}] name='harden_custupld'"
        except Exception:
            pass
    return page, "page(main)"

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
# DIALOG HANDLING (ESC semantics)
# =========================
def click_and_dismiss_native_dialog_with_esc_fallback(
    page: Page,
    click_fn,
    label: str,
    esc_after_s: int = DIALOG_ESC_FALLBACK_AFTER_S,
    max_wait_s: int = DIALOG_MAX_WAIT_S
) -> Optional[str]:
    got = {"hit": False, "msg": None}

    def handler(dialog):
        try:
            got["hit"] = True
            got["msg"] = dialog.message
            print(f"[NATIVE_DIALOG:{label}] Captured -> dismiss() (ESC). msg={repr(dialog.message)}")
            dialog.dismiss()
        except Exception as e:
            print(f"[NATIVE_DIALOG:{label}] dismiss failed: {e}")
            try:
                dialog.accept()
            except Exception:
                pass

    page.once("dialog", handler)

    print(f"[STEP] {label}: click")
    click_fn()

    start = time.time()
    esc_sent = False

    while time.time() - start < max_wait_s:
        if got["hit"]:
            return got["msg"]

        if (not esc_sent) and (time.time() - start >= esc_after_s):
            esc_sent = True
            print(f"[FALLBACK:{label}] no dialog after {esc_after_s}s -> sending ESC to page")
            try:
                page.keyboard.press("Escape")
            except Exception:
                pass

        time.sleep(0.1)

    print(f"[WARN:{label}] Native dialog NOT captured within {max_wait_s}s.")
    return None

# =========================
# FILE PICK (working version)
# =========================
def set_file_prev_style_with_diagnostics(page: Page, scope, file_path: Path) -> bool:
    if not file_path.exists():
        raise FileNotFoundError(f"Plik nie istnieje: {file_path}")

    print("[STEP] FILE: try expect_file_chooser on Browse")

    chooser_set = False
    browse = scope.locator(BROWSE_BUTTON_XPATH).first

    # 1) Prefer: file chooser captured
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

        if loc_overlay.count() > 0:
            loc_overlay.set_input_files(str(file_path))
        elif loc_offscreen.count() > 0:
            loc_offscreen.set_input_files(str(file_path))
        else:
            dump_page(page, "dps_inputs_not_found")
            raise RuntimeError("Nie znalazłem input[type=file] pod 'DPS Upload'")

    # Validate textbox contains filename (soft check)
    tb = scope.locator(
        "xpath=//*[normalize-space(text())='DPS Upload']"
        "/following::*[contains(@class,'dijitTextBox')][1]//input[@type='text']"
    ).first

    confirmed = False
    for i in range(40):
        try:
            val = tb.input_value(timeout=500)
        except Exception:
            val = ""
        if val and file_path.name in val:
            confirmed = True
            break
        time.sleep(0.5)

    print(f"[INFO] file textbox confirmed={confirmed}")
    return confirmed

# =========================
# IMPORT CLICK (robust)
# =========================
def build_filename_tokens(filename: str) -> List[str]:
    """
    UI może ucinać nazwę — budujemy kilka tokenów do dopasowania.
    """
    parts = filename.split("_")
    tokens = []
    # pełna nazwa
    tokens.append(filename)
    # sensowny fragment (pierwsze 5 segmentów)
    tokens.append("_".join(parts[:5]))
    # jeszcze krótszy fragment
    tokens.append("_".join(parts[:4]))
    # ostatnie segmenty (np. Q1 + data)
    if len(parts) >= 3:
        tokens.append("_".join(parts[-3:]))
    # bez rozszerzenia
    if filename.endswith(".enc"):
        tokens.append(filename.replace(".enc", ""))
    # unikalny kawałek
    tokens.append("Quarterly_DPS")
    return list(dict.fromkeys([t for t in tokens if t]))  # unique, non-empty

def click_import_icon_for_file(page: Page, scope, filename: str):
    """
    Szuka wiersza z tokenem i klika ikonę:
      img.ConfigImageIcon[onclick*="processUploaded"]
    """
    tokens = build_filename_tokens(filename)
    print(f"[STEP] Import: searching row by tokens: {tokens}")

    end = time.time() + IMPORT_ROW_MAX_WAIT_S
    last_diag = 0

    while time.time() < end:
        # diagnostyka co ~5s: ile jest ikon importu na stronie
        if time.time() - last_diag >= 5:
            last_diag = time.time()
            try:
                cnt_icons = scope.locator("img.ConfigImageIcon[onclick*='processUploaded']").count()
            except Exception:
                cnt_icons = -1
            print(f"[DIAG] import icons count in scope = {cnt_icons}")

        for tok in tokens:
            # XPath: wiersz, który ma TD zawierające token + w tym wierszu ikonę importu
            row_import = scope.locator(
                "xpath=//tr[td[contains(normalize-space(.), %s)]]"
                "//img[contains(@class,'ConfigImageIcon') and contains(@onclick,'processUploaded')]" % repr(tok)
            ).first

            try:
                if row_import.count() > 0 and wait_bbox_visible(row_import, timeout_ms=1500):
                    print(f"[OK] Found import icon for token='{tok}' -> clicking")
                    try:
                        row_import.scroll_into_view_if_needed()
                    except Exception:
                        pass
                    try:
                        row_import.click(timeout=2000)
                    except Exception:
                        row_import.evaluate("(el)=>el.click()")
                    dump_page(page, "after_import_icon_click")
                    return
            except Exception:
                pass

        time.sleep(0.5)

    dump_page(page, "import_icon_not_found_timeout")
    raise TimeoutError(f"Nie znalazłem ikony Import (processUploaded) dla pliku '{filename}' w czasie {IMPORT_ROW_MAX_WAIT_S}s")

# =========================
# MAIN FLOW
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

def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context(ignore_https_errors=True)
        page = context.new_page()

        attach_debug_listeners(page)

        try:
            login(page)
            open_customer_uploads(page)

            print(f"[WAIT] Customer Uploads dynamic content: sleep {CUSTOMER_UPLOADS_WAIT_S}s")
            time.sleep(CUSTOMER_UPLOADS_WAIT_S)
            dump_page(page, "after_customer_uploads_wait")

            # Scope dla file pick (Browse)
            scope_browse, desc_browse = find_scope_with_browse(page)
            print(f"[INFO] Browse scope selected: {desc_browse}")

            confirmed = set_file_prev_style_with_diagnostics(page, scope_browse, FILE_TO_UPLOAD)
            print(f"[INFO] file selected confirmed={confirmed}")

            # Upload + dismiss alert
            print(f"[WAIT] After pick file: sleep {POST_PICK_BEFORE_UPLOAD_S}s before Upload")
            time.sleep(POST_PICK_BEFORE_UPLOAD_S)
            dump_page(page, "before_upload_click")

            def upload_click():
                click_locator(scope_browse, UPLOAD_BUTTON_ABS_XPATH, timeout_ms=60000, label="upload")

            msg1 = click_and_dismiss_native_dialog_with_esc_fallback(
                page, upload_click, label="UPLOAD_DIALOG",
                esc_after_s=DIALOG_ESC_FALLBACK_AFTER_S,
                max_wait_s=DIALOG_MAX_WAIT_S
            )
            print(f"[INFO] Upload dialog message: {repr(msg1)}")
            dump_page(page, "after_upload_dialog_handled")

            # IMPORTANT: po uploadzie aplikacja może przejść do innego frame'a
            scope_import, desc_import = find_best_scope_for_import(page)
            print(f"[INFO] Import scope selected: {desc_import}")

            # Klik import icon (processUploaded) dla naszego pliku
            # i od razu obsłuż kolejny alert (dismiss)
            def import_click():
                click_import_icon_for_file(page, scope_import, FILE_TO_UPLOAD.name)

            msg2 = click_and_dismiss_native_dialog_with_esc_fallback(
                page, import_click, label="IMPORT_DIALOG",
                esc_after_s=DIALOG_ESC_FALLBACK_AFTER_S,
                max_wait_s=DIALOG_MAX_WAIT_S
            )
            print(f"[INFO] Import dialog message: {repr(msg2)}")
            dump_page(page, "after_import_dialog_handled")

            print("\n🟡 STOP HERE (automation frozen). Browser left open for manual verification.\n")
            while True:
                time.sleep(60)

        except Exception:
            print("\n❌ ERROR")
            traceback.print_exc()
            dump_page(page, "fatal_error")
        finally:
            if KEEP_BROWSER_OPEN:
                print("🟠 KEEP_BROWSER_OPEN=True -> Browser remains open.")
                try:
                    while True:
                        time.sleep(60)
                except KeyboardInterrupt:
                    pass
            else:
                try:
                    browser.close()
                except Exception:
                    pass
                print("🛑 Browser closed")

if __name__ == "__main__":
    main()