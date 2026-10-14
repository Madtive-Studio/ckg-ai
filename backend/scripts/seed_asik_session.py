"""One-time, human-in-the-loop ASIK login that seeds the saved browser session of one puskesmas.

ASIK shows a CAPTCHA at login. A scrape job started from the admin app has no way to show it to a person: with no
captcha-solving LLM configured it falls back to "manual" and tries to draw the image in the job log. Scrape jobs reuse a saved
browser session (``--use-session``) per puskesmas, so a person can solve the CAPTCHA ONCE here, in a visible browser window,
and later jobs skip the login until ASIK expires the session.

The ASIK credential is decrypted inside this process (the same way a scrape job does) and typed into the login form; it is
never printed or written to a file. You only solve the CAPTCHA in the window that opens.

Run it on the machine that runs the Celery worker (it must see the same session folder as the worker):

  cd backend
  .venv/bin/python -m scripts.seed_asik_session --puskesmas <UUID>

When the CKG page shows, the script saves the session and closes the window.
"""
from __future__ import annotations

import argparse
import os
import sys
import uuid


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--puskesmas", required=True, type=uuid.UUID)
    args = ap.parse_args()

    from app.crud import puskesmas as puskesmas_crud
    from app.database import SessionLocal
    from app.models.puskesmas import Puskesmas
    from app.tasks import scrape as scrape_task

    with SessionLocal() as db:
        pk = db.get(Puskesmas, args.puskesmas)
        if pk is None or not pk.asik_url:
            print("puskesmas not found or has no ASIK URL", file=sys.stderr)
            return 2
        creds = puskesmas_crud.get_cred_decrypted(pk, "asik") or {}
        username, password = creds.get("email", ""), creds.get("password", "")
        if not username or not password:
            print("no ASIK credential stored for this puskesmas", file=sys.stderr)
            return 2
        base_url = f"https://{pk.asik_url}"
        session_dir = scrape_task._asik_session_dir(pk.id)

    # The scraper helpers read the session folder from the environment when they are imported.
    os.environ["SCRAPER_SESSION_DIR"] = str(session_dir)
    sys.path.insert(0, str(scrape_task.SCRAPERS_ROOT / "asik"))
    from helpers import close_popups, login, navigate_to_pelayanan  # noqa: E402
    from helpers.browser import launch_persistent_context, restore_saved_auth_state, save_auth_state  # noqa: E402
    from playwright.sync_api import sync_playwright  # noqa: E402

    print(f"Opening a browser window for {pk.name}. Solve the CAPTCHA in the window; do not close it yourself.")
    with sync_playwright() as p:
        context = launch_persistent_context(p, headless=False, slow_mo=50)
        try:
            page = context.pages[0] if context.pages else context.new_page()
            restore_saved_auth_state(context, page)
            page.set_default_timeout(300_000)                 # time to read and type the CAPTCHA
            login(page, base_url, {"username": username, "password": password}, headless=False, config={})
            save_auth_state(context, page, base_url)
            navigate_to_pelayanan(page, base_url)
            close_popups(page)
            print("Logged in and the session is saved. Scrape jobs for this puskesmas can now run without the CAPTCHA.")
        finally:
            context.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
