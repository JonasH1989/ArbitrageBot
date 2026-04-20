#!/usr/bin/env python3
"""Test dashboard with Playwright"""
import asyncio
from playwright.async_api import async_playwright

async def test_dashboard():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        
        print("🌐 Oeffne Dashboard...")
        await page.goto("http://localhost:8501", timeout=30000)
        await page.wait_for_load_state("networkidle", timeout=15000)
        
        print("✅ Seite geladen!")
        
        # Check title
        title = await page.title()
        print(f"📄 Title: {title}")
        
        # Check for sidebar
        sidebar = await page.locator("[data-testid='stSidebar']").count()
        print(f"📊 Sidebar gefunden: {sidebar > 0}")
        
        # Check for volume slider
        volume_slider = await page.locator("text=🔊 Lautstaerke").count()
        print(f"🔊 Lautstaärke-Slider gefunden: {volume_slider > 0}")
        
        # Check for pairs section
        pairs = await page.locator("text=📋 Paare").count()
        print(f"📋 Paare-Sektion gefunden: {pairs > 0}")
        
        # Get any errors from console
        errors = []
        page.on("console", lambda msg: errors.append(msg.text) if msg.type == "error" else None)
        
        await asyncio.sleep(2)
        
        if errors:
            print(f"❌ Console Errors: {errors}")
        else:
            print("✅ Keine Console Errors!")
        
        await browser.close()
        print("🎉 Test abgeschlossen!")

if __name__ == "__main__":
    asyncio.run(test_dashboard())
