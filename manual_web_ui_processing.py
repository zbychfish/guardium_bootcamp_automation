#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import time
import traceback
from pathlib import Path
from typing import Optional, List, Tuple
from playwright.sync_api import sync_playwright, Page, Frame


def guardium_customer_upload_import(
    login_url: str,
    username: str,
    password: str,
    file_to_upload: str,
    *,
    headless: bool = True,
    ignore_https_errors: bool = True,
    customer_uploads_wait_s: int = 15,
    post_pick_before_upload_s: int = 2,
    dialog_esc_fallback_after_s: int = 5,
    dialog_max_wait_s: int = 60,
    import_row_max_wait_s: int = 90,
    slow_mo_ms: int = 0,
) -> bool:
    """
    Automatyzuje:
    - login
    - Harden -> Vulnerability Assessment -> Customer Uploads
    - wybór pliku w DPS Upload
    - Upload + zamknięcie alertu (dismiss / ESC-semantyka)
    - Import (klik ikonki z onclick*='processUploaded' dla wiersza z plikiem)
    - zamknięcie kolejnego alertu (dismiss)
    - zamknięcie przeglądarki i zakończenie

    Zwraca:
      True jeśli przebieg do końca bez wyjątku.
    Rzuca wyjątek:
      w razie błędów (timeouty, brak elementów, brak pliku itd.)
    """

    # -------------------------
    # Stałe / selektory UI
    # -------------------------
    WELCOME_SELECTOR = "div.guard--welcome-page--page-subtitle"
    BROWSE_BUTTON_XPATH = "xpath=//*[@id='guard/common/util/FileUploader_0']/div/form/span"
    UPLOAD_BUTTON_ABS_XPATH = "xpath=/html/body/form/table/tbody/tr[2]/td/div/table/tbody/tr[2]/td/span/button"

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
            cell.evaluate("(el)=>el.click()")

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
            loc.evaluate("(el)=>el.click()")

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

    def click_and_dismiss_native_dialog_with_esc_fallback(page: Page, click_fn, label: str) -> Optional[str]:
        got = {"hit": False, "msg": None}

        def handler(dialog):
            try:
                got["hit"] = True
                got["msg"] = dialog.message
                # dismiss() = ESC-semantyka dla alert/confirm
                dialog.dismiss()
            except Exception:
                try:
                    dialog.accept()
                except Exception:
                    pass

        # handler PRZED kliknięciem (eliminuje race)
        page.once("dialog", handler)

        click_fn()

        start = time.time()
        esc_sent = False
        while time.time() - start < dialog_max_wait_s:
            if got["hit"]:
                return got["msg"]

            # fallback ESC po N sekundach (ale dalej czekamy na natywny dialog)
            if (not esc_sent) and (time.time() - start >= dialog_esc_fallback_after_s):
                esc_sent = True
                try:
                    page.keyboard.press("Escape")
                except Exception:
                    pass

            time.sleep(0.1)

        return None

    def set_file_prev_style(page: Page, scope, file_path: Path) -> bool:
        """
        Prefer: expect_file_chooser + chooser.set_files
        Fallback: ESC + set_input_files (overlay/offscreen)
        """
        chooser_set = False
        browse = scope.locator(BROWSE_BUTTON_XPATH).first

        # Prefer: przechwyć chooser
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
                except Exception:
                    chooser_set = False
        except Exception:
            chooser_set = False

        # Jeśli nie przechwyciliśmy choosera, możliwe że otworzył się systemowy dialog -> ESC
        if not chooser_set:
            try:
                page.keyboard.press("Escape")
                time.sleep(0.7)
            except Exception:
                pass

        # Fallback: set_input_files
        if not chooser_set:
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
                raise RuntimeError("Nie znalazłem input[type=file] pod 'DPS Upload'")

        # Soft check textbox
        tb = scope.locator(
            "xpath=//*[normalize-space(text())='DPS Upload']"
            "/following::*[contains(@class,'dijitTextBox')][1]//input[@type='text']"
        ).first

        confirmed = False
        for _ in range(40):
            try:
                val = tb.input_value(timeout=500)
            except Exception:
                val = ""
            if val and file_path.name in val:
                confirmed = True
                break
            time.sleep(0.5)

        return confirmed

    def build_filename_tokens(filename: str) -> List[str]:
        parts = filename.split("_")
        tokens = []
        tokens.append(filename)
        tokens.append("_".join(parts[:5]))
        tokens.append("_".join(parts[:4]))
        if len(parts) >= 3:
            tokens.append("_".join(parts[-3:]))
        if filename.endswith(".enc"):
            tokens.append(filename.replace(".enc", ""))
        tokens.append("Quarterly_DPS")
        # unique, non-empty
        out = []
        for t in tokens:
            if t and t not in out:
                out.append(t)
        return out

    def click_import_icon_for_file(page: Page, scope, filename: str):
        tokens = build_filename_tokens(filename)
        end = time.time() + import_row_max_wait_s

        while time.time() < end:
            # szybki „sygnał życia”: czy w ogóle widzimy ikonki importu?
            try:
                if scope.locator("img.ConfigImageIcon[onclick*='processUploaded']").count() == 0:
                    time.sleep(0.5)
                    continue
            except Exception:
                time.sleep(0.5)
                continue

            for tok in tokens:
                sel = (
                    "xpath=//tr[td[contains(normalize-space(.), %s)]]"
                    "//img[contains(@class,'ConfigImageIcon') and contains(@onclick,'processUploaded')]" % repr(tok)
                )
                icon = scope.locator(sel).first
                try:
                    if icon.count() > 0 and wait_bbox_visible(icon, timeout_ms=1500):
                        try:
                            icon.scroll_into_view_if_needed()
                        except Exception:
                            pass
                        try:
                            icon.click(timeout=2000)
                        except Exception:
                            icon.evaluate("(el)=>el.click()")
                        return
                except Exception:
                    pass

            time.sleep(0.5)

        raise TimeoutError(f"Nie znalazłem ikony Import (processUploaded) dla '{filename}' w czasie {import_row_max_wait_s}s")

    # -------------------------
    # MAIN EXECUTION
    # -------------------------
    fp = Path(file_to_upload)
    if not fp.exists():
        raise FileNotFoundError(f"Plik nie istnieje: {fp}")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless, slow_mo=slow_mo_ms)
        context = browser.new_context(ignore_https_errors=ignore_https_errors)
        page = context.new_page()

        try:
            # LOGIN
            page.goto(login_url, wait_until="domcontentloaded")
            page.fill("input[name='username']", username)
            page.fill("input[name='password']", password)
            page.press("input[name='password']", "Enter")

            if not wait_bbox_visible(page.locator(WELCOME_SELECTOR), 60000):
                raise TimeoutError("Nie widać ekranu powitalnego po logowaniu")

            # NAV -> Customer Uploads
            try:
                page.locator("span.dijitIcon.navToggleIcon").first.click()
            except Exception:
                pass

            harden = page.locator("#navItemDesc_harden").locator("..")
            try:
                harden.first.click(timeout=1500)
            except Exception:
                harden.first.evaluate("(el)=>el.click()")

            safe_click_cell(page, "Vulnerability Assessment", 60000)
            safe_click_cell(page, "Customer Uploads", 60000)

            # wait for dynamic content
            time.sleep(customer_uploads_wait_s)

            # Pick file
            scope_browse, _ = find_scope_with_browse(page)
            _confirmed = set_file_prev_style(page, scope_browse, fp)

            # Upload -> dismiss alert
            time.sleep(post_pick_before_upload_s)

            def upload_click():
                click_locator(scope_browse, UPLOAD_BUTTON_ABS_XPATH, timeout_ms=60000, label="upload")

            _msg1 = click_and_dismiss_native_dialog_with_esc_fallback(page, upload_click, label="UPLOAD_DIALOG")

            # Import -> click icon -> dismiss alert
            scope_import, _ = find_best_scope_for_import(page)

            def import_click():
                click_import_icon_for_file(page, scope_import, fp.name)

            _msg2 = click_and_dismiss_native_dialog_with_esc_fallback(page, import_click, label="IMPORT_DIALOG")

            return True

        except Exception:
            # Jeśli chcesz, możesz tu logować traceback / robić screenshot
            traceback.print_exc()
            raise
        finally:
            try:
                browser.close()
            except Exception:
                pass