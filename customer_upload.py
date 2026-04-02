#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import time
import traceback
from pathlib import Path
from playwright.sync_api import sync_playwright, Page

# =========================
# CONFIG
# =========================
LOGIN_URL = "https://eu-de.services.cloud.techzone.ibm.com:27494/"
USERNAME = "demo"
PASSWORD = "Guardium123!"
WELCOME_SELECTOR = "div.guard--welcome-page--page-subtitle"

# <<< PODMIEŃ TO NA SWOJĄ ŚCIEŻKĘ >>>
FILE_TO_UPLOAD = Path(r"U:\-=GUARDIUM\Guardium 12.2 INSTALL\Guardium_V12_Quarterly_DPS_2026_Q1_20260216.enc")

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
    end = time.time() + timeout_ms/1000
    while time.time() < end:
        try:
            if locator.count() > 0:
                box = locator.first.bounding_box()
                if box and box.get("width", 0) > 0 and box.get("height", 0) > 0:
                    return True
        except Exception:
            pass
        time.sleep(poll_ms/1000)
    return False

def safe_click_cell(page: Page, text: str, timeout_ms=60000):
    """
    Kliknięcie w *komórkę treści* wiersza gridx (NIE w ikonę expando).
    """
    cell = page.locator(
        "div.gridxTreeExpandoContent.gridxCellContent",
        has_text=text
    ).first
    # Czekaj aż cell pojawi się w DOM
    end = time.time() + timeout_ms/1000
    while time.time() < end and cell.count() == 0:
        time.sleep(0.2)

    # Scroll + click (z fallbackiem JS)
    try:
        cell.scroll_into_view_if_needed()
    except Exception:
        pass
    try:
        cell.click(timeout=2000)
    except Exception:
        # Fallback: JS click
        try:
            cell.evaluate("(el)=>el.click()")
        except Exception as e:
            raise TimeoutError(f"Nie mogę kliknąć '{text}': {e}")

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

    print("[STEP] NAV: Harden (przycisk boczny ID)")
    # To stabilizuje drzewo pod „Harden”
    harden = page.locator("#navItemDesc_harden").locator("..")
    # Klik przez JS (czasem overlay)
    try:
        harden.first.click(timeout=1500)
    except Exception:
        harden.first.evaluate("(el)=>el.click()")

    print("[STEP] NAV: Vulnerability Assessment (komórka treści)")
    safe_click_cell(page, "Vulnerability Assessment", 60000)

    print("[STEP] NAV: Customer Uploads (komórka treści)")
    safe_click_cell(page, "Customer Uploads", 60000)

    dump_page(page, "after_customer_uploads_click")

def pick_file_in_dps_upload(page: Page, file_path: Path):
    if not file_path.exists():
        raise FileNotFoundError(f"Plik nie istnieje: {file_path}")

    print("[STEP] LOCATE DPS Upload inputs")

    # 1) input overlay wewnątrz przycisku „Browse” (opacity:0, absolute)
    loc_overlay = page.locator(
        "xpath=//*[normalize-space(text())='DPS Upload']"
        "/following::span[contains(@class,'dijitUploader')][1]"
        "//input[@type='file' and @name='uploadedfile']"
    ).first

    # 2) input offscreen (valueNode, class=dijitOffScreen)
    loc_offscreen = page.locator(
        "xpath=//*[normalize-space(text())='DPS Upload']"
        "/following::input[@type='file' and @name='uploadedfile'"
        " and contains(@class,'dijitOffScreen')][1]"
    ).first

    # Jeśli sekcja jeszcze nie jest w DOM – spróbuj zjechać do „DPS Upload”
    if loc_overlay.count() == 0 and loc_offscreen.count() == 0:
        page.locator("xpath=//*[normalize-space(text())='DPS Upload']").first.scroll_into_view_if_needed()
        time.sleep(0.3)

    used = None
    try:
        if loc_overlay.count() > 0:
            print("[INFO] set_input_files -> overlay input")
            loc_overlay.set_input_files(str(file_path))
            used = "overlay"
        elif loc_offscreen.count() > 0:
            print("[INFO] set_input_files -> offscreen input")
            loc_offscreen.set_input_files(str(file_path))
            used = "offscreen"
        else:
            dump_page(page, "dps_inputs_not_found")
            raise RuntimeError("Nie znalazłem input[type=file] pod 'DPS Upload'")
    except Exception:
        dump_page(page, "dps_set_input_files_error")
        raise

    # Walidacja: pole tekstowe „Select file to upload” powinno mieć nazwę pliku
    tb = page.locator(
        "xpath=//*[normalize-space(text())='DPS Upload']"
        "/following::*[contains(@class,'dijitTextBox')][1]//input[@type='text']"
    ).first

    print("[STEP] CHECK filename echoed in textbox")
    for i in range(40):  # ~20s
        try:
            val = tb.input_value(timeout=500)
        except Exception:
            val = ""
        print(f"[DEBUG] textbox value try {i}: '{val}'")
        if val and file_path.name in val:
            print("[OK] filename visible in textbox")
            break
        time.sleep(0.5)

    dump_page(page, "after_file_chosen")

    # (Opcjonalnie) kliknij „Upload” – jeśli chcesz tylko wskazać plik, usuń ten blok
    btn_upload = page.locator(
        "xpath=("
        "//*[normalize-space(text())='DPS Upload']"
        "/following::span[contains(@class,'dijitButtonText') and normalize-space(.)='Upload']"
        ")[1]/ancestor::span[contains(@class,'dijitButton')]"
    ).first
    if btn_upload.count() > 0:
        print("[STEP] Click 'Upload' (optional)")
        try:
            btn_upload.click(timeout=1500)
        except Exception:
            btn_upload.evaluate("(el)=>el.click()")
        # Poczekaj, aż tabela „Import DPS” pokaże wpis
        for i in range(120):  # ~60s
            body = page.inner_text("body")
            ok = ("None currently uploaded" not in body) or (file_path.name in body)
            print(f"[DEBUG] import table poll {i}: ok={ok}")
            if ok:
                dump_page(page, "dps_import_table_updated")
                print("[OK] Upload potwierdzony w tabeli")
                break
            time.sleep(0.5)

def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)  # zostaw otwarte dla obserwacji
        context = browser.new_context(ignore_https_errors=True)
        page = context.new_page()
        try:
            login(page)
            open_customer_uploads(page)
            pick_file_in_dps_upload(page, FILE_TO_UPLOAD)
            print("\n✅ DONE\n")
            time.sleep(3)
        except Exception:
            print("\n❌ ERROR")
            traceback.print_exc()
            dump_page(page, "fatal_error")
        finally:
            try:
                browser.close()
            except Exception:
                pass
            print("🛑 Browser closed")

if __name__ == "__main__":
    main()