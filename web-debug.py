#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import time
import traceback
import signal
from pathlib import Path
from playwright.sync_api import sync_playwright, Page

# =========================
# CONFIG
# =========================
LOGIN_URL = "https://eu-de.services.cloud.techzone.ibm.com:40459/"
USERNAME = "demo"
PASSWORD = "Guardium123!"
WELCOME_SELECTOR = "div.guard--welcome-page--page-subtitle"

KEEP_OPEN_ON_ERROR = True   # <- nawet przy błędzie zostaw przeglądarkę otwartą
SLOW_MO_MS = 120            # <- lekkie spowolnienie interfejsu

DEBUG_DIR = Path("debug")
DEBUG_DIR.mkdir(parents=True, exist_ok=True)

# =========================
# UTIL
# =========================
def ts_name(prefix: str) -> str:
    return f"{int(time.time())}_{prefix}"

def dump_page(page: Page, label: str):
    if page.is_closed():
        print(f"[DUMP] SKIP ({label}) – page is closed")
        return
    png = DEBUG_DIR / f"{ts_name(label)}.png"
    html = DEBUG_DIR / f"{ts_name(label)}.html"
    try:
        page.screenshot(path=png, full_page=True)
        print(f"[DUMP] {png.name}")
    except Exception as e:
        print(f"[DUMP][screenshot] {e}")
    try:
        html.write_text(page.content(), encoding="utf-8")
        print(f"[DUMP] {html.name}")
    except Exception as e:
        print(f"[DUMP][html] {e}")

def dump_json(obj, label: str):
    path = DEBUG_DIR / f"{ts_name(label)}.json"
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"[JSON] {path.name}")

# =========================
# CLICK RECORDER (JS)
# =========================
CLICK_INJECT_SCRIPT = r"""
(() => {
  try {
    if (window.__clickRecorderInjected) return;
    window.__clickRecorderInjected = true;

    window.__clicklog = [];

    const getRect = el => {
      const r = el.getBoundingClientRect();
      return { x: r.x, y: r.y, w: r.width, h: r.height };
    };
    const shortText = el => {
      const t = (el.innerText || '').trim().replace(/\s+/g, ' ');
      return t.slice(0, 200);
    };
    const cssPath = el => {
      if (!(el instanceof Element)) return '';
      const path = [];
      while (el && el.nodeType === Node.ELEMENT_NODE) {
        let selector = el.nodeName.toLowerCase();
        if (el.id) {
          selector += '#' + CSS.escape(el.id);
          path.unshift(selector);
          break;
        } else {
          let sib = el, nth = 1;
          while ((sib = sib.previousElementSibling)) {
            if (sib.nodeName.toLowerCase() === selector) nth++;
          }
          selector += `:nth-of-type(${nth})`;
        }
        path.unshift(selector);
        el = el.parentNode;
      }
      return path.join(' > ');
    };
    const styleSnap = el => {
      const cs = getComputedStyle(el);
      return {
        display: cs.display, visibility: cs.visibility,
        opacity: cs.opacity, pointerEvents: cs.pointerEvents
      };
    };
    const fileInputsSnapshot = () =>
      [...document.querySelectorAll("input[type='file']")].map(i => ({
        name: i.name || null, id: i.id || null, class: i.className || null,
        rect: getRect(i), disabled: !!i.disabled, offsetParent: !!i.offsetParent,
        ...styleSnap(i), tabindex: i.getAttribute('tabindex') || null,
        ariaLabelledby: i.getAttribute('aria-labelledby') || null
      }));

    // highlighter
    let highlight = document.getElementById('__clickRecorderHighlight__');
    if (!highlight) {
      highlight = document.createElement('div');
      highlight.id = '__clickRecorderHighlight__';
      Object.assign(highlight.style, {
        position: 'fixed', border: '3px solid #ff2d00',
        boxShadow:'0 0 0 3px rgba(255,45,0,0.2)',
        zIndex: '2147483647', pointerEvents: 'none', display: 'none'
      });
      document.documentElement.appendChild(highlight);
    }

    const handler = ev => {
      const t = ev.target;
      const rect = getRect(t);
      const entry = {
        ts: Date.now(),
        type: ev.type,
        button: ev.button,
        point: { x: ev.clientX, y: ev.clientY },
        scroll: { x: window.scrollX, y: window.scrollY },
        target: {
          tag: t.tagName, id: t.id || null, class: t.className || null,
          role: t.getAttribute('role'), nameAttr: t.getAttribute('name'),
          ariaLabel: t.getAttribute('aria-label'), text: shortText(t),
          rect, cssPath: cssPath(t), styles: styleSnap(t)
        },
        nearFileInputs: fileInputsSnapshot()
      };
      (window.__clicklog || (window.__clicklog=[])).push(entry);

      Object.assign(highlight.style, {
        left: rect.x + 'px', top: rect.y + 'px',
        width: rect.w + 'px', height: rect.h + 'px', display: 'block'
      });
      setTimeout(() => { highlight.style.display = 'none'; }, 600);
    };

    ['click'].forEach(evt => document.addEventListener(evt, handler, true));

    // oznacz sekcje
    const mark = (xpath, color) => {
      try {
        const res = document.evaluate(xpath, document, null, XPathResult.FIRST_ORDERED_NODE_TYPE, null);
        const el = res.singleNodeValue;
        if (!el) return false;
        el.style.outline = `3px solid ${color}`;
        el.style.outlineOffset = '0px';
        return true;
      } catch (e) { return false; }
    };
    mark("//*[normalize-space(text())='Customer Uploads']/ancestor::div[1]", "#00e676");
    mark("//*[normalize-space(text())='DPS Upload']/ancestor::div[1]", "#2979ff");

    window.__diagSnapshot = () => {
      const q = xp => {
        try {
          const n = document.evaluate(xp, document, null, XPathResult.FIRST_ORDERED_NODE_TYPE, null).singleNodeValue;
          if (!n) return null;
          return {
            xpath: xp,
            rect: getRect(n),
            styles: styleSnap(n),
            text: shortText(n),
            outerHTML: n.outerHTML
          };
        } catch (e) { return null; }
      };
      return {
        ts: Date.now(),
        url: location.href,
        customerUploads: q("//*[normalize-space(text())='Customer Uploads']/ancestor::div[1]"),
        dpsUpload: q("//*[normalize-space(text())='DPS Upload']/ancestor::div[1]"),
        fileInputs: fileInputsSnapshot()
      };
    };

    console.log('[CLICK-RECORDER] injected');
  } catch (e) {
    console.error('[CLICK-RECORDER] injection error', e);
  }
})();
"""

def enable_click_recorder(page: Page):
    # zgodne z różnymi wersjami Playwright (property vs method)
    def on_console(msg):
        try:
            typ_attr = getattr(msg, "type", None)
            txt_attr = getattr(msg, "text", None)
            typ = typ_attr() if callable(typ_attr) else typ_attr
            txt = txt_attr() if callable(txt_attr) else txt_attr
            print(f"[BROWSER] {typ} {txt}")
        except Exception as e:
            print(f"[BROWSER][console-dump-error] {e}")

    page.on("console", on_console)
    page.add_init_script(CLICK_INJECT_SCRIPT)
    try:
        page.evaluate(CLICK_INJECT_SCRIPT)
    except Exception:
        pass

def flush_clicklog(page: Page, label="clicklog"):
    try:
        log = page.evaluate("() => window.__clicklog || []")
        dump_json(log, label)
    except Exception as e:
        print(f"[clicklog] error: {e}")

def snapshot_state(page: Page, label="state_snapshot"):
    try:
        state = page.evaluate("() => (window.__diagSnapshot && window.__diagSnapshot()) || null")
        dump_json(state, label)
    except Exception as e:
        print(f"[snapshot] error: {e}")

# =========================
# STABILNE WAIT/CLICK (bez .wait_for())
# =========================
def until_true(fn, timeout_ms=60000, poll_ms=250):
    deadline = time.time() + (timeout_ms / 1000.0)
    last_err = None
    while time.time() < deadline:
        try:
            if fn():
                return True
        except Exception as e:
            last_err = e
        time.sleep(poll_ms / 1000.0)
    if last_err:
        print(f"[until_true] last error: {last_err}")
    return False

def wait_for_visible_by_bbox(locator, timeout_ms=60000):
    return until_true(
        lambda: (lambda b: b and b.get("width",0) > 0 and b.get("height",0) > 0)(
            locator.first.bounding_box()
        ),
        timeout_ms=timeout_ms, poll_ms=250
    )

def safe_click(locator, timeout_ms=60000):
    # próba normalna
    if wait_for_visible_by_bbox(locator, timeout_ms=timeout_ms):
        try:
            locator.first.scroll_into_view_if_needed()
        except Exception:
            pass
        try:
            locator.first.click(timeout=1500)
            return
        except Exception:
            pass
    # fallback: JS click nawet jeśli bbox==0
    locator.first.evaluate("(el)=>el.click()")

# =========================
# FLOW
# =========================
def login(page: Page):
    print("[STEP] LOGIN")
    page.goto(LOGIN_URL, wait_until="domcontentloaded")
    page.fill("input[name='username']", USERNAME)
    page.fill("input[name='password']", PASSWORD)
    page.press("input[name='password']", "Enter")

    welcome = page.locator(WELCOME_SELECTOR)
    if not wait_for_visible_by_bbox(welcome, timeout_ms=60000):
        dump_page(page, "welcome_timeout")
        raise TimeoutError("WELCOME_SELECTOR not visible")

    enable_click_recorder(page)
    dump_page(page, "after_login")

def stay_open_loop(page: Page):
    """
    Zostaw przeglądarkę otwartą, aż użytkownik naciśnie ENTER.
    W tle rób snapshot po każdym ENTERZE cząstkowym (podwójne ENTER kończy).
    """
    print("\n---\n"
          "🔴 Okno ZOSTAJE OTWARTE. "
          "Kliknij ręcznie: Harden → Vulnerability Assessment → Customer Uploads.\n"
          "Potem naciśnij ENTER, żeby zapisać logi i zakończyć.\n---\n")

    # snapshot startu
    snapshot_state(page, "state_start")
    dump_page(page, "manual_before")

    # czekaj na ENTER
    try:
        input()
    except KeyboardInterrupt:
        pass

    # snapshot końcowy
    flush_clicklog(page, "clicklog_final")
    snapshot_state(page, "state_final")
    dump_page(page, "manual_after")

# =========================
# MAIN
# =========================
def main():
    # bezpieczne zamykanie po Ctrl+C – i tak czekamy na ENTER
    def _ignore_sigint(signum, frame):
        print("[SIGINT] Zignorowano (okno zostaje otwarte do ENTER).")
    try:
        signal.signal(signal.SIGINT, _ignore_sigint)
    except Exception:
        pass

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, slow_mo=SLOW_MO_MS)
        context = browser.new_context(ignore_https_errors=True)
        page = context.new_page()

        fatal = None
        try:
            login(page)
            # NIC więcej automatycznie – zostawiamy Tobie klikanie
            stay_open_loop(page)

        except Exception:
            fatal = traceback.format_exc()
            print("\n❌ ERROR\n", fatal)
            dump_page(page, "fatal_error")

        finally:
            if KEEP_OPEN_ON_ERROR and fatal:
                # Zostaw otwarte mimo błędu – czekaj na ENTER
                print("\n[HOLD] Wystąpił błąd, ale okno zostaje OTWARTE. "
                      "Naciśnij ENTER, aby zamknąć…")
                try:
                    input()
                except KeyboardInterrupt:
                    pass

            # zamykanie
            try:
                browser.close()
            except Exception:
                pass
            print("🛑 Browser closed")

if __name__ == "__main__":
    main()