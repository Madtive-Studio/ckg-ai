"""
=============================================================================
ASIK CKG Pelayanan Scraper — main entry point
=============================================================================
Scrapes patient data from sehatindonesiaku.kemkes.go.id/ckg-pelayanan.

How CAPTCHA is handled:
  - Default: HEADLESS browser with CAPTCHA solved via terminal input
  - Use --no-headless to launch a VISIBLE browser and solve CAPTCHA in the UI
  - Once logged in, the script takes over automatically
  - Navigates to CKG Umum → Pelayanan
  - Scrapes "Sedang Pemeriksaan" and "Selesai Pemeriksaan" tabs
  - For each patient row, enters the detail page and reads every
    eligible form (green-check for Mandiri; Ya + Selesai diperiksa for Nakes)
  - Saves everything to JSON

Usage:
  python scraper.py                                  # Default: headless + terminal CAPTCHA
  python scraper.py --use-session                    # Headless + session (fastest)
  python scraper.py --no-headless                    # Visible browser (CAPTCHA in UI)
  python scraper.py --no-headless --use-session      # Visible + session reuse
  python scraper.py --tab sedang                     # Only Sedang Pemeriksaan
  python scraper.py --tab selesai                    # Only Selesai Pemeriksaan
  python scraper.py --max-pages 5                    # Limit pagination
  python scraper.py --date 2026-04-16                # Defaults to today if omitted
  python scraper.py --output data.json               # Custom output file

Logic lives in:
  helpers/constants.py   — paths, tab/month maps, load_config
  helpers/browser.py     — APIInterceptor + persistent session
  helpers/auth.py        — login, navigate, popup removal
  helpers/calendar.py    — date range picker
  helpers/pagination.py  — next-page / page-number navigation
  patient_scraper.py     — per-patient deep scraper (detail + forms)
=============================================================================
"""

# --- parent-death watchdog: kill ourselves if the launching terminal closes ---
import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parent.parent))
from _lifecycle import install as _install_lifecycle  # noqa: E402
_install_lifecycle()
# --- end watchdog ---

import argparse
import json
import time
from datetime import datetime
from pathlib import Path

from playwright.sync_api import sync_playwright, Page
from rich.console import Console
from rich.table import Table as RichTable
from rich.panel import Panel

from helpers import (
    OUTPUT_DIR,
    SCREENSHOT_DIR,
    SESSION_DIR,
    TAB_OPTIONS,
    APIInterceptor,
    install_decoded_list_hook,
    read_decoded_list,
    reset_decoded_list,
    load_config,
    launch_persistent_context,
    restore_saved_auth_state,
    save_auth_state,
    login,
    navigate_to_pelayanan,
    close_popups,
    set_date_filter,
    click_next_page,
    navigate_to_page_num,
)
from helpers.auth import SessionExpiredError, verify_session
from patient_scraper import (
    VERIFY_COUNTS,
    bump_verify,
    scrape_patient_via_api,
    open_detail_via_mulai,
)

console = Console()


class DateFilterMismatchError(RuntimeError):
    """The list is not filtered to the requested date — the whole run must stop, not just one patient."""


class CKGPelayananScraper:

    def __init__(self, args):
        self.args = args
        self.config = load_config()
        self.base_url = self.config.get("base_url", "https://sehatindonesiaku.kemkes.go.id")
        self.interceptor = APIInterceptor(verbose=bool(getattr(args, "capture_network", None)))
        self.results = {
            "belum_pemeriksaan": [],
            "sedang_pemeriksaan": [],
            "selesai_pemeriksaan": [],
        }
        # Multi-date mode: results_by_date[date_iso] = {"belum_…": [...], …}.
        # Populated only when --dates is used; final output shape switches
        # to {"by_date": {...}} so the worker can attribute each record to
        # the correct Patient.filter_date.
        self.results_by_date: dict[str, dict[str, list]] = {}
        self.date = None
        self.date_filter_source = None
        # --dates parsed list (empty when single-date mode).
        self.dates_list: list[str] = []
        if getattr(args, "dates", None):
            self.dates_list = [d.strip() for d in args.dates.split(",") if d.strip()]
        # --mandiri-only: open ONLY Pemeriksaan Mandiri forms (skip Nakes +
        # Tatalaksana). CLI flag wins; falls back to config for standalone use.
        self.mandiri_only = bool(
            getattr(args, "mandiri_only", False) or self.config.get("mandiri_only", False)
        )
        # --niks: comma-separated NIK allowlist. When set, only list-claim rows
        # whose patient_nik is in the set are deep-scraped (the rest are skipped
        # without opening any form tab). Used by the Mandiri-only backfill.
        self.niks: set[str] = set()
        if getattr(args, "niks", None):
            self.niks = {n.strip() for n in args.niks.split(",") if n.strip()}

    def run(self):
        self.start_time = time.time()
        self.captcha_duration = 0.0
        selected_tabs = TAB_OPTIONS[self.args.tab]
        tab_label = " + ".join(name for name, _ in selected_tabs)
        headless = self.args.headless
        browser_mode = "[bold red]HEADLESS[/bold red]" if headless else "[bold green]VISIBLE[/bold green]"
        console.print(Panel(
            f"[bold green]ASIK CKG Pelayanan Scraper[/bold green]\n"
            f"Tabs: {tab_label}\n"
            f"Browser: {browser_mode}\n"
            f"Mode: [bold yellow]DEEP MODE[/bold yellow] — will enter each patient detail page",
            title="Starting",
        ))

        OUTPUT_DIR.mkdir(exist_ok=True)
        SCREENSHOT_DIR.mkdir(exist_ok=True)

        with sync_playwright() as p:
            slow_mo = 0 if headless else 50

            if self.args.use_session:
                if SESSION_DIR.exists():
                    console.print("[cyan]Reusing saved session...[/cyan]")
                context = launch_persistent_context(p, headless=headless, slow_mo=slow_mo)
                page = context.pages[0] if context.pages else context.new_page()
                restore_saved_auth_state(context, page)
                browser = None
            else:
                browser = p.chromium.launch(headless=headless, slow_mo=slow_mo)
                context = browser.new_context(
                    viewport={"width": 1920, "height": 1080},
                    locale="id-ID",
                    timezone_id="Asia/Jakarta",
                )
                page = context.new_page()

            page.set_default_timeout(self.config.get("timeout", 60000))
            # Listen at the context level so any tab opened via context.new_page()
            # (form tabs today, detail tabs in Phase 2) is also captured.
            context.on("response", self.interceptor.on_response)
            install_decoded_list_hook(context)   # ASIK encodes the list response; the page decodes it, we read what it decoded

            try:
                # Step 1: Login (manual CAPTCHA or headless terminal solve)
                self.captcha_duration = login(page, self.base_url, self.config.get("credentials", {}),
                                              headless=headless, config=self.config)
                if self.args.use_session:
                    save_auth_state(context, page, self.base_url)

                # Step 2: Navigate to CKG Umum → Pelayanan
                navigate_to_pelayanan(page, self.base_url)

                # Step 3: Close any popups
                close_popups(page)

                # Step 4: Set date filter
                if self.dates_list:
                    self.date_filter_source = "cli_multi"
                    # Walk every date in one browser session — set filter,
                    # scrape every tab, snapshot, reset, repeat.
                    for d_iso in self.dates_list:
                        console.print(
                            f"\n[bold magenta]== Date {d_iso} ==[/bold magenta]"
                        )
                        self.date = d_iso
                        set_date_filter(page, d_iso)
                        # Reset per-date result accumulator.
                        self.results = {
                            "belum_pemeriksaan": [],
                            "sedang_pemeriksaan": [],
                            "selesai_pemeriksaan": [],
                        }
                        for tab_name, result_key in selected_tabs:
                            self._scrape_tab(page, tab_name, result_key)
                        # Snapshot this date's results before moving on.
                        self.results_by_date[d_iso] = {
                            "belum_pemeriksaan": list(self.results["belum_pemeriksaan"]),
                            "sedang_pemeriksaan": list(self.results["sedang_pemeriksaan"]),
                            "selesai_pemeriksaan": list(self.results["selesai_pemeriksaan"]),
                        }
                        # Persist a partial multi-date snapshot after every date so
                        # a crash mid-range loses at most one date's tab progress.
                        self._save_results()
                    self._save_results()
                else:
                    if self.args.date:
                        self.date = self.args.date
                        self.date_filter_source = "cli"
                    elif self.config.get("date"):
                        self.date = self.config.get("date")
                        self.date_filter_source = "config"
                    else:
                        self.date = datetime.now().strftime("%Y-%m-%d")
                        self.date_filter_source = "default_today"
                    set_date_filter(page, self.date)

                    # Step 5-6: Scrape selected tabs
                    for tab_name, result_key in selected_tabs:
                        self._scrape_tab(page, tab_name, result_key)

                    # Step 7: Save
                    self._save_results()

            except Exception as e:
                console.print(f"\n[bold red]Error: {e}[/bold red]")
                try:
                    page.screenshot(path=str(SCREENSHOT_DIR / "error.png"))
                    console.print(f"  Screenshot saved: {SCREENSHOT_DIR / 'error.png'}")
                except Exception:
                    pass
                raise
            finally:
                if getattr(self.args, "capture_network", None):
                    try:
                        n = self.interceptor.dump(self.args.capture_network)
                        console.print(f"\n[bold cyan]Network capture:[/bold cyan] "
                                      f"wrote {n} response(s) to {self.args.capture_network}")
                    except Exception as e:
                        console.print(f"[yellow]Could not dump network capture: {e}[/yellow]")

                if browser is not None:
                    browser.close()
                else:
                    context.close()

    # ─────────────────────────────────────────────────────────────────────
    # Per-tab scraping: click the tab, detect total pages, enter deep loop
    # ─────────────────────────────────────────────────────────────────────
    def _scrape_tab(self, page: Page, tab_name: str, result_key: str):
        console.print(f"\n[bold cyan]Scraping tab: {tab_name}[/bold cyan]")

        self.interceptor.clear()
        reset_decoded_list(page)

        # Click the tab — find the DEEPEST visible element whose own text
        # matches (avoids clicking a wrapper that swallows the event).
        tab_clicked = page.evaluate("""(tabName) => {
            const walker = document.createTreeWalker(
                document.body, NodeFilter.SHOW_ELEMENT, null
            );
            let best = null;
            let bestDepth = -1;

            function depth(el) {
                let d = 0;
                let p = el;
                while (p.parentElement) { p = p.parentElement; d++; }
                return d;
            }

            while (walker.nextNode()) {
                const el = walker.currentNode;
                const ownText = Array.from(el.childNodes)
                    .filter(n => n.nodeType === Node.TEXT_NODE)
                    .map(n => n.textContent.trim())
                    .join(' ')
                    .trim();

                const innerTrimmed = el.innerText ? el.innerText.trim() : '';
                const matchesOwn = ownText === tabName;
                const matchesInner = innerTrimmed.startsWith(tabName) &&
                                     innerTrimmed.length < tabName.length + 15;

                if ((matchesOwn || matchesInner) && el.offsetParent !== null) {
                    const d = depth(el);
                    if (d > bestDepth) {
                        bestDepth = d;
                        best = el;
                    }
                }
            }

            if (best) {
                best.scrollIntoView({ block: 'center' });
                best.click();
                return true;
            }

            // Fallback: role="tab"
            const roleTabs = document.querySelectorAll('[role="tab"]');
            for (const tab of roleTabs) {
                if (tab.innerText && tab.innerText.trim().startsWith(tabName)) {
                    tab.scrollIntoView({ block: 'center' });
                    tab.click();
                    return true;
                }
            }

            return false;
        }""", tab_name)

        if not tab_clicked:
            try:
                page.get_by_role("tab", name=tab_name).click()
                tab_clicked = True
            except Exception:
                pass
            if not tab_clicked:
                try:
                    page.get_by_text(tab_name, exact=True).click()
                    tab_clicked = True
                except Exception:
                    pass

        if not tab_clicked:
            console.print(f"  [bold red]Could not find tab '{tab_name}'[/bold red]")
            return

        page.wait_for_timeout(3000)
        console.print(f"  Clicked tab: '{tab_name}'")
        page.screenshot(path=str(SCREENSHOT_DIR / f"tab_{result_key}.png"))

        close_popups(page, silent=True)

        # Read badge count (e.g. "Selesai Pemeriksaan 7")
        try:
            badge_text = page.evaluate("""(tabName) => {
                const walker = document.createTreeWalker(
                    document.body, NodeFilter.SHOW_ELEMENT, null
                );
                while (walker.nextNode()) {
                    const el = walker.currentNode;
                    const txt = el.innerText ? el.innerText.trim() : '';
                    if (txt.startsWith(tabName) && txt.length < tabName.length + 15) {
                        const match = txt.match(/(\\d+)/);
                        if (match) return match[1];
                    }
                }
                return null;
            }""", tab_name)
            if badge_text:
                console.print(f"  Expected records (from badge): {badge_text}")
        except Exception:
            pass

        # Detect total pages from pagination
        total_pages = page.evaluate("""() => {
            const pagBtns = document.querySelectorAll(
                '[class*="pagination"] a, [class*="pagination"] button, ' +
                '.pagination a, .pagination button, .pagination li, ' +
                'nav[aria-label*="page" i] button, nav[aria-label*="page" i] a'
            );
            let maxPage = 0;
            for (const btn of pagBtns) {
                const num = parseInt(btn.innerText.trim());
                if (!isNaN(num) && num > maxPage) maxPage = num;
            }
            const body = document.body.innerText;
            const ofMatch = body.match(/(?:of|dari)\\s+(\\d+)\\s*(?:page|halaman)/i);
            if (ofMatch) {
                const n = parseInt(ofMatch[1]);
                if (n > maxPage) maxPage = n;
            }
            return maxPage > 0 ? maxPage : null;
        }""")

        if total_pages:
            console.print(f"  Detected total pages: {total_pages}")

        rows = self._deep_scrape_patients(page, tab_name, result_key, total_pages)
        self.results[result_key] = rows
        console.print(f"  [green]Total rows for '{tab_name}': {len(rows)}[/green]")

    # ─────────────────────────────────────────────────────────────────────
    # Deep scrape. Reads the patient list the page decoded, then per patient
    # clicks "Mulai" and reads the detail page in a separate tab (the list
    # page never navigates away — see patient_scraper.open_detail_via_mulai).
    # Forms (both Mandiri and Nakes) are read by opening their URLs in new
    # tabs and scraping the SurveyJS DOM (patient_scraper.scrape_patient_via_api).
    # ─────────────────────────────────────────────────────────────────────
    def _deep_scrape_patients(self, page: Page, tab_name: str, result_key: str,
                              detected_total_pages: int | None = None) -> list[dict]:
        enriched_rows = []
        max_pages = self.args.max_pages or detected_total_pages or self.config.get("max_pages", 500)
        page_num = 1
        # Belum / Sedang tabs with patients are not yet verified (asik/CLAUDE.md "Not yet verified").
        tab_signal = {"Belum Pemeriksaan": "tab_belum", "Sedang Pemeriksaan": "tab_sedang"}.get(tab_name)

        while page_num <= max_pages:
            total_pages_label = detected_total_pages or "?"
            records = self._records_from_list_claim(page)

            if not records:
                if page_num == 1:
                    console.print("  [yellow]No list-claim records captured — tab might be empty[/yellow]")
                else:
                    console.print(f"  Page {page_num}: No list-claim records — stopping")
                break

            console.print(f"\n  [cyan]API scraping page {page_num}/{total_pages_label} "
                          f"({len(records)} patients)[/cyan]")

            for rec in records:
                max_patients = getattr(self.args, "max_patients", None)
                if max_patients is not None and len(enriched_rows) >= max_patients:
                    console.print(f"  [yellow]--max-patients {max_patients} reached, stopping[/yellow]")
                    return enriched_rows

                # NIK allowlist (Mandiri-only backfill): skip rows we weren't
                # asked to scrape without opening any form tab.
                if self.niks and (rec.get("patient_nik") or "").strip() not in self.niks:
                    continue

                reg_id = rec.get("reg_id")
                faskes_code = rec.get("faskes_code")
                ticket_number = rec.get("ticket_number") or ""
                label = f"{(rec.get('patient_full_name') or '?').strip()} ({ticket_number})"

                # Per-patient scrape with mid-run session-expiry recovery.
                # If the detail page or a form bounces to login, re-run login
                # (CAPTCHA), restore the list (date / tab / page) and retry the
                # same patient once.
                _attempted_relogin = False
                while True:
                    stage = "detail"
                    try:
                        data = open_detail_via_mulai(page, ticket_number=ticket_number, reg_id=reg_id)
                        stage = "forms"

                        # Date-integrity guard. The list is filtered by examination date, which only the
                        # detail carries (list rows have just the registration date, which may be earlier).
                        # A different examination date means the filter did not take and we're reading the
                        # page's DEFAULT range — refuse to emit rows mislabeled with the requested date.
                        if self.date and data.get("screening_date") != self.date:
                            raise DateFilterMismatchError(
                                f"Date filter mismatch on '{tab_name}' page {page_num}: requested "
                                f"{self.date} but {ticket_number} was examined on "
                                f"{data.get('screening_date')}. Aborting to avoid emitting wrong-dated records."
                            )

                        detail = scrape_patient_via_api(
                            page.context,
                            base_url=self.base_url,
                            faskes_code=faskes_code,
                            screening_date=data.get("screening_date") or self.date,
                            reg_id=reg_id,
                            mitra="",
                            patient_label=label,
                            pelayanan_nakes_only=bool(self.config.get("pelayanan_nakes_only", False)),
                            include_blank_forms=bool(self.config.get("include_blank_forms", False)),
                            skip_forms=bool(getattr(self.args, "list_only", False)),
                            mandiri_only=self.mandiri_only,
                            scrape_tatalaksana=bool(self.config.get("scrape_tatalaksana", True)),
                            detail=data,
                        )
                        enriched_rows.append(detail)
                        self._save_progress(result_key, enriched_rows)
                        if tab_signal:
                            bump_verify(f"{tab_signal}_ok")
                        break
                    except DateFilterMismatchError:
                        raise
                    except SessionExpiredError as e:
                        if _attempted_relogin:
                            console.print(f"    [red]Re-login still failed for {label}: {e}[/red]")
                            enriched_rows.append({
                                "error": f"SessionExpiredError after re-login: {e}",
                                "source_row": f"Page {page_num} reg_id={reg_id}",
                            })
                            break
                        console.print(f"    [yellow]Session expired mid-scrape — re-running login flow[/yellow]")
                        _attempted_relogin = True
                        try:
                            page.context.clear_cookies()
                        except Exception:
                            pass
                        try:
                            login(page, self.base_url, self.config.get("credentials", {}),
                                  headless=getattr(self.args, "headless", True), config=self.config)
                            if self.args.use_session:
                                save_auth_state(page.context, page, self.base_url)
                        except Exception as login_err:
                            console.print(f"    [red]Re-login failed: {login_err}[/red]")
                            enriched_rows.append({
                                "error": f"re-login failed: {login_err}",
                                "source_row": f"Page {page_num} reg_id={reg_id}",
                            })
                            break
                        # Login left the list page, so its date / tab / page are gone — rebuild them.
                        try:
                            self._restore_list(page, tab_name, page_num)
                        except Exception as restore_err:
                            console.print(f"    [red]Could not restore the patient list after re-login: {restore_err}[/red]")
                            enriched_rows.append({
                                "error": f"list restore failed: {restore_err}",
                                "source_row": f"Page {page_num} reg_id={reg_id}",
                            })
                            break
                        # Loop retries the same patient with fresh credentials.
                    except Exception as e:
                        console.print(f"    [red]Error scraping {label}: {e}[/red]")
                        if stage == "detail":
                            bump_verify("detail_failed")
                        if tab_signal:
                            bump_verify(f"{tab_signal}_error")
                        enriched_rows.append({
                            "error": str(e),
                            "source_row": f"Page {page_num} reg_id={reg_id}",
                        })
                        break

            self.interceptor.clear()
            reset_decoded_list(page)
            if not click_next_page(page):
                console.print(f"  No more pages (finished at page {page_num})")
                break

            page.wait_for_timeout(2000)
            page_num += 1

        return enriched_rows

    def _restore_list(self, page: Page, tab_name: str, page_num: int) -> None:
        """Bring the list back to the requested date, tab and page (after a re-login navigated away from it)."""
        navigate_to_pelayanan(page, self.base_url)
        close_popups(page, silent=True)
        if self.date:
            set_date_filter(page, self.date)
        self._ensure_on_tab(page, tab_name)
        navigate_to_page_num(page, page_num)
        page.wait_for_timeout(2000)

    def _records_from_list_claim(self, page: Page, wait_ms: int = 4000) -> list[dict]:
        """Pull the patient list the SPA just loaded.

        The SPA fires a list request every time the user changes date / tab / page. Older ASIK answered
        ``/api/pkg/list-claim`` with plain JSON (read from the interceptor); current ASIK answers
        ``/api/pkg/ssi/list-kunjungan-umum`` with an encoded payload that the page decodes itself, so the rows are
        read from the decoded copy the page parsed. We wait briefly for the list to land if it hasn't yet.
        """
        deadline = time.time() + (wait_ms / 1000.0)
        while time.time() < deadline:
            for entry in reversed(self.interceptor.all_responses):
                if entry["url"].endswith("/api/pkg/list-claim") and entry["status"] == 200:
                    body = entry.get("body") or {}
                    data = body.get("data") or []
                    if isinstance(data, list):
                        return data
            decoded = read_decoded_list(page)
            if decoded:
                return decoded
            page.wait_for_timeout(200)
        return []

    def _ensure_on_tab(self, page: Page, tab_name: str):
        """Verify we're on /ckg-pelayanan with the right tab selected."""
        if "/ckg-pelayanan" not in page.url:
            page.goto(f"{self.base_url}/ckg-pelayanan", wait_until="networkidle")
            page.wait_for_timeout(3000)
            close_popups(page, silent=True)

        already_on_tab = page.evaluate("""(tabName) => {
            const candidates = document.querySelectorAll('[role="tab"], button, a, div, span');
            for (const el of candidates) {
                const text = el.innerText ? el.innerText.trim() : '';
                if (!text.startsWith(tabName)) continue;
                if (el.offsetParent === null) continue;

                const ariaSelected = el.getAttribute('aria-selected');
                const ariaCurrent = el.getAttribute('aria-current');
                const cls = (el.className || '').toString().toLowerCase();
                if (ariaSelected === 'true' || ariaCurrent === 'page' ||
                    cls.match(/active|selected|current/)) {
                    return true;
                }
            }
            return false;
        }""", tab_name)

        if already_on_tab:
            return

        page.evaluate("""(tabName) => {
            const walker = document.createTreeWalker(
                document.body, NodeFilter.SHOW_ELEMENT, null
            );
            let best = null;
            let bestDepth = -1;
            function depth(el) {
                let d = 0; let p = el;
                while (p.parentElement) { p = p.parentElement; d++; }
                return d;
            }
            while (walker.nextNode()) {
                const el = walker.currentNode;
                const ownText = Array.from(el.childNodes)
                    .filter(n => n.nodeType === Node.TEXT_NODE)
                    .map(n => n.textContent.trim()).join(' ').trim();
                const innerTrimmed = el.innerText ? el.innerText.trim() : '';
                const matchesOwn = ownText === tabName;
                const matchesInner = innerTrimmed.startsWith(tabName) &&
                                     innerTrimmed.length < tabName.length + 15;
                if ((matchesOwn || matchesInner) && el.offsetParent !== null) {
                    const d = depth(el);
                    if (d > bestDepth) { bestDepth = d; best = el; }
                }
            }
            if (best) best.click();
        }""", tab_name)
        page.wait_for_timeout(2000)

    # ─────────────────────────────────────────────────────────────────────
    # Persistence
    # ─────────────────────────────────────────────────────────────────────
    def _save_progress(self, result_key: str, rows: list[dict]):
        """Checkpoint after every patient so a mid-run crash loses at most one row."""
        progress_file = OUTPUT_DIR / f"progress_{result_key}.json"
        try:
            with open(progress_file, "w", encoding="utf-8") as f:
                json.dump(rows, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def _save_results(self):
        if self.dates_list:
            total = sum(
                len(v) for day in self.results_by_date.values() for v in day.values()
            )
        else:
            total = sum(len(v) for v in self.results.values())

        date_suffix = self.date or datetime.now().strftime("%Y-%m-%d")
        output_file = self.args.output or str(
            OUTPUT_DIR / f"ckg_pelayanan_{date_suffix}.json"
        )

        total_elapsed = round(time.time() - self.start_time, 2)
        captcha_wait = round(self.captcha_duration, 2)
        scraping_time = round(total_elapsed - captcha_wait, 2)

        if self.dates_list:
            output = {
                "metadata": {
                    "source": f"{self.base_url}/ckg-pelayanan",
                    "scraped_at": datetime.now().isoformat(),
                    "date_filter": {
                        "value": self.dates_list,
                        "source": self.date_filter_source,
                    },
                    "total_records": total,
                    "verify_counts": dict(VERIFY_COUNTS),
                    "timing": {
                        "total_elapsed_seconds": total_elapsed,
                        "captcha_wait_seconds": captcha_wait,
                        "scraping_seconds": scraping_time,
                    },
                },
                "by_date": self.results_by_date,
            }
        else:
            output = {
                "metadata": {
                    "source": f"{self.base_url}/ckg-pelayanan",
                    "scraped_at": datetime.now().isoformat(),
                    "date_filter": {
                        "value": self.date,
                        "source": self.date_filter_source,
                    },
                    "total_records": total,
                    "tabs": {
                        "belum_pemeriksaan": len(self.results["belum_pemeriksaan"]),
                        "sedang_pemeriksaan": len(self.results["sedang_pemeriksaan"]),
                        "selesai_pemeriksaan": len(self.results["selesai_pemeriksaan"]),
                    },
                    "verify_counts": dict(VERIFY_COUNTS),
                    "timing": {
                        "total_elapsed_seconds": total_elapsed,
                        "captcha_wait_seconds": captcha_wait,
                        "scraping_seconds": scraping_time,
                    },
                },
                "belum_pemeriksaan": self.results["belum_pemeriksaan"],
                "sedang_pemeriksaan": self.results["sedang_pemeriksaan"],
                "selesai_pemeriksaan": self.results["selesai_pemeriksaan"],
            }

        Path(output_file).parent.mkdir(parents=True, exist_ok=True)
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(output, f, ensure_ascii=False, indent=2)

        if total == 0:
            console.print("\n[bold yellow]No data collected for the selected filters.[/bold yellow]")
            console.print(f"[yellow]An empty result file was still saved to: {output_file}[/yellow]")

        summary = RichTable(title="Scrape Results")
        summary.add_column("Tab", style="cyan")
        summary.add_column("Records", style="green", justify="right")
        summary.add_row("Belum Pemeriksaan", str(len(self.results["belum_pemeriksaan"])))
        summary.add_row("Sedang Pemeriksaan", str(len(self.results["sedang_pemeriksaan"])))
        summary.add_row("Selesai Pemeriksaan", str(len(self.results["selesai_pemeriksaan"])))
        summary.add_row("[bold]Total[/bold]", f"[bold]{total}[/bold]")
        summary.add_row("", "")
        summary.add_row("Total elapsed", f"{total_elapsed}s")
        summary.add_row("CAPTCHA wait", f"{captcha_wait}s")
        summary.add_row("Scraping time", f"{scraping_time}s")
        console.print(summary)

        console.print(Panel(
            f"[bold green]Saved to: {output_file}[/bold green]",
            title="Done!",
        ))

        for tab_name, key in [("Belum Pemeriksaan", "belum_pemeriksaan"),
                              ("Sedang Pemeriksaan", "sedang_pemeriksaan"),
                              ("Selesai Pemeriksaan", "selesai_pemeriksaan")]:
            rows = self.results[key]
            if rows:
                console.print(f"\n  [cyan]Sample from '{tab_name}':[/cyan]")
                for row in rows[:2]:
                    console.print(f"    {json.dumps(row, ensure_ascii=False)[:200]}")


# =============================================================================
# CLI
# =============================================================================
def main():
    parser = argparse.ArgumentParser(
        description="ASIK CKG Pelayanan Scraper",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python scraper.py                              # Default: headless + terminal CAPTCHA
  python scraper.py --use-session                # Headless + session reuse (fastest)
  python scraper.py --no-headless                # Visible browser (manual CAPTCHA in UI)
  python scraper.py --no-headless --use-session  # Visible + session reuse
  python scraper.py --tab belum                  # Only Belum Pemeriksaan
  python scraper.py --tab sedang                 # Only Sedang Pemeriksaan
  python scraper.py --tab selesai                # Only Selesai Pemeriksaan
  python scraper.py --tab all                    # All three tabs
  python scraper.py --max-pages 5                # Limit to 5 pages per tab
  python scraper.py --output data.json           # Custom output filename
        """,
    )
    parser.add_argument("--use-session", action="store_true",
                        help="Save/reuse browser session to skip CAPTCHA on repeat runs")
    parser.add_argument("--max-pages", type=int, default=None,
                        help="Max pages to scrape per tab")
    parser.add_argument("--tab", type=str, default="all",
                        choices=["all", "both", "sedang", "selesai", "belum"],
                        help="Choose which patient list tab to scrape")
    parser.add_argument("--output", type=str, default=None,
                        help="Output JSON file path")
    parser.add_argument("--date", type=str, default=None,
                        help="Date filter (YYYY-MM-DD). Defaults to today.")
    parser.add_argument("--dates", type=str, default=None,
                        help="Comma-separated YYYY-MM-DD list. Multi-date mode: "
                             "walks every date in one browser session and emits "
                             '{"by_date": {date: {...buckets...}}}. Overrides --date.')
    parser.add_argument("--headless", action=argparse.BooleanOptionalAction, default=True,
                        help="Run browser headless (CAPTCHA solved via terminal). Default: True. Use --no-headless for visible browser.")
    parser.add_argument("--capture-network", type=str, default=None, metavar="PATH",
                        help="Dump every captured XHR/fetch JSON response to this path "
                             "and log each response live. For Phase 0 reconnaissance.")
    parser.add_argument("--max-patients", type=int, default=None,
                        help="Stop after scraping N patients (debugging / reconnaissance).")
    parser.add_argument("--list-only", action="store_true",
                        help="Skip Mandiri + Nakes form-tab opening per patient. "
                             "Per-patient detail-screening still fires for NIK + Nama, "
                             "but no SurveyJS DOM reads. Used by GDP report's "
                             "skip_asik_detail mode for ~10x speedup.")
    parser.add_argument("--mandiri-only", action="store_true",
                        help="Open ONLY Pemeriksaan Mandiri forms (skip Pelayanan "
                             "Nakes + Tatalaksana). Output's pelayanan_nakes is empty "
                             "and tatalaksana absent. Used by the Mandiri-only backfill "
                             "to patch existing patients without re-scraping everything.")
    parser.add_argument("--niks", type=str, default=None,
                        help="Comma-separated NIK allowlist. Only list-claim rows whose "
                             "patient_nik is in the set are deep-scraped; the rest are "
                             "skipped without opening any form tab.")

    args = parser.parse_args()
    scraper = CKGPelayananScraper(args)
    scraper.run()


if __name__ == "__main__":
    main()
