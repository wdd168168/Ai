"""真实浏览器验证：登录 -> 逐页打开 -> 收集报错 -> 截图（含手机宽度）。"""
import asyncio
import os
import sys

from playwright.async_api import async_playwright

BASE = "http://127.0.0.1:8800"
PAGES = [
    ("overview", "/overview"),
    ("accounts", "/accounts"),
    ("personas", "/personas"),
    ("chats", "/chats"),
    ("contacts", "/contacts"),
    ("proactive", "/proactive"),
    ("style", "/style"),
    ("voice", "/voice"),
    ("logs", "/logs"),
    ("settings", "/settings"),
]
OUT = "/tmp/shots"
os.makedirs(OUT, exist_ok=True)


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            executable_path="/usr/local/bin/chromium",
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        ctx = await browser.new_context(viewport={"width": 1440, "height": 900})
        page = await ctx.new_page()
        errors = []
        page.on("console", lambda m: errors.append(f"[console.{m.type}] {m.text}") if m.type == "error" else None)
        page.on("pageerror", lambda e: errors.append(f"[pageerror] {e}"))

        await page.goto(f"{BASE}/login", wait_until="networkidle")
        await page.screenshot(path=f"{OUT}/00-login.png")

        await page.fill('input[placeholder="admin"]', "admin")
        await page.fill('input[type="password"]', "Zaka2026!Op")
        await page.click('button:has-text("登")')
        try:
            await page.wait_for_url(lambda u: "/login" not in u, timeout=15000)
            print("LOGIN_OK", page.url)
        except Exception:
            print("LOGIN_FAIL", page.url)
            await page.screenshot(path=f"{OUT}/00-login-fail.png")
            print("\n".join(errors[-10:]))
            await browser.close()
            sys.exit(1)

        for slug, path in PAGES:
            await page.goto(f"{BASE}{path}", wait_until="networkidle")
            await page.wait_for_timeout(900)
            await page.screenshot(path=f"{OUT}/{slug}.png", full_page=True)
            title = (await page.title()) or ""
            body_len = len(await page.inner_text("body"))
            print(f"PAGE {path:12s} title={title[:20]!r} textlen={body_len}")

        # 手机宽度横向溢出检查
        await page.set_viewport_size({"width": 390, "height": 844})
        overflow = {}
        for slug, path in PAGES:
            await page.goto(f"{BASE}{path}", wait_until="networkidle")
            await page.wait_for_timeout(500)
            ov = await page.evaluate(
                "() => document.documentElement.scrollWidth - document.documentElement.clientWidth"
            )
            overflow[path] = ov
        print("MOBILE_OVERFLOW", overflow)
        await page.screenshot(path=f"{OUT}/mobile-settings.png", full_page=True)

        print("ERRORS", len(errors))
        for e in errors[:15]:
            print(" ", e)
        await browser.close()


asyncio.run(main())
