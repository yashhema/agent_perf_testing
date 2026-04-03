#!/usr/bin/env python3
"""Take screenshots of all orchestrator pages using Playwright.

Handles JWT token auth by injecting token into localStorage.

Usage:
    python take_screenshots.py
    python take_screenshots.py --url http://localhost:8000
"""

import argparse
import json
import os
import time
import requests
from pathlib import Path

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    print("pip install playwright && playwright install chromium")
    exit(1)

BASE_URL = "http://localhost:8000"
SCREENSHOT_DIR = Path(__file__).parent.parent / "docs" / "runbook_screenshots"


def take_all(url, user, password):
    SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)

    # Get JWT token via API
    print("Logging in via API...")
    resp = requests.post(f"{url}/api/auth/login", data={"username": user, "password": password})
    if resp.status_code != 200:
        print(f"Login failed: {resp.status_code} {resp.text}")
        return
    token = resp.json()["access_token"]
    print(f"Got token: {token[:20]}...")

    pages = [
        ("01_login", "/login", "Login Page"),
        ("02_dashboard", "/admin/dashboard", "Admin Dashboard"),
        ("03_servers_targets", "/admin/servers", "Servers — Targets Tab"),
        ("04_load_profiles", "/admin/load-profiles", "Load Profiles"),
        ("05_agents", "/admin/agents", "Agents & Detection Rules"),
        ("06_agent_sets", "/admin/subgroup-definitions", "Agent Sets"),
        ("07_snapshots", "/snapshots", "Snapshot Manager"),
        ("08_tests", "/os-level-tests", "Tests — OS Level & Agent Set"),
        ("09_all_tests", "/baseline-tests", "All Baseline Tests"),
    ]

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1400, "height": 900})
        page = context.new_page()

        # Take login page screenshot first (before auth)
        print(f"\n[01] Login page...")
        page.goto(f"{url}/login", wait_until="networkidle")
        page.fill("#username", user)
        page.fill("#password", password)
        page.screenshot(path=str(SCREENSHOT_DIR / "01_login.png"), full_page=True)
        print(f"  Saved: 01_login.png")

        # Now inject token and navigate to authenticated pages
        # The app stores token in localStorage as 'token'
        page.goto(f"{url}/login", wait_until="networkidle")
        page.evaluate(f"localStorage.setItem('token', '{token}')")

        # Click login to trigger redirect
        page.fill("#username", user)
        page.fill("#password", password)
        page.click("#btn-login")
        time.sleep(3)
        page.wait_for_load_state("networkidle")
        time.sleep(2)

        current_url = page.url
        print(f"  After login: {current_url}")

        if "/login" in current_url:
            print("  WARNING: Still on login page. Trying direct navigation with token...")
            # Force navigate with token already in localStorage
            page.goto(f"{url}/admin/dashboard", wait_until="networkidle")
            time.sleep(2)
            if "/login" in page.url:
                print("  ERROR: Cannot authenticate. Check token storage mechanism.")
                # Let's try a different approach — set cookie or header
                print("  Trying with cookie approach...")
                context.close()
                context = browser.new_context(
                    viewport={"width": 1400, "height": 900},
                    extra_http_headers={"Authorization": f"Bearer {token}"},
                )
                page = context.new_page()

        # Take screenshots of all pages
        for filename, path, title in pages[1:]:  # skip login, already done
            print(f"\n[{filename[:2]}] {title}...")
            try:
                page.goto(f"{url}{path}", wait_until="networkidle")
                time.sleep(2)

                # Check if redirected to login
                if "/login" in page.url:
                    # Inject token again
                    page.evaluate(f"localStorage.setItem('token', '{token}')")
                    page.goto(f"{url}{path}", wait_until="networkidle")
                    time.sleep(2)

                page.screenshot(path=str(SCREENSHOT_DIR / f"{filename}.png"), full_page=True)
                print(f"  Saved: {filename}.png (url: {page.url})")
            except Exception as e:
                print(f"  ERROR: {e}")

        # Try to click on an agent to show detection rules panel
        try:
            print(f"\n[05b] Agents with detection rules expanded...")
            page.goto(f"{url}/admin/agents", wait_until="networkidle")
            time.sleep(2)
            # Click first agent link
            agent_links = page.query_selector_all("a[onclick*='selectAgent']")
            if agent_links:
                agent_links[0].click()
                time.sleep(2)
                page.screenshot(path=str(SCREENSHOT_DIR / "05b_agents_rules.png"), full_page=True)
                print(f"  Saved: 05b_agents_rules.png")
        except Exception as e:
            print(f"  Could not expand agent: {e}")

        # Try to open create OS test modal
        try:
            print(f"\n[10] Create OS Level Test modal...")
            page.goto(f"{url}/os-level-tests", wait_until="networkidle")
            time.sleep(2)
            btn = page.query_selector("button:has-text('New OS Level Test')")
            if btn:
                btn.click()
                time.sleep(1)
                page.screenshot(path=str(SCREENSHOT_DIR / "10_create_os_modal.png"), full_page=True)
                print(f"  Saved: 10_create_os_modal.png")
        except Exception as e:
            print(f"  Could not open modal: {e}")

        browser.close()

    print(f"\n{'='*50}")
    print(f"Screenshots saved to: {SCREENSHOT_DIR}")
    print(f"Files:")
    for f in sorted(SCREENSHOT_DIR.glob("*.png")):
        size_kb = f.stat().st_size / 1024
        print(f"  {f.name} ({size_kb:.0f} KB)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://localhost:8000")
    parser.add_argument("--user", default="admin")
    parser.add_argument("--password", default="admin")
    args = parser.parse_args()
    take_all(args.url, args.user, args.password)
