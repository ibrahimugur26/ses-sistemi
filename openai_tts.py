"""openai.fm üzerinden (Playwright ile) seslendirme motoru."""
import asyncio
import os
import shutil
import tempfile

from playwright.async_api import async_playwright

OPENAI_SESLER = ["Alloy", "Ash", "Ballad", "Cedar", "Coral", "Fable", "Marin", "Nova", "Onyx", "Sage", "Verse"]

# Sitedeki vibe kutusuna yazılacak hazır talimatlar
OPENAI_VIBELER = {
    "Calm": (
        "Voice: Calm, soft and soothing.\n\n"
        "Tone: Relaxed, gentle and reassuring.\n\n"
        "Pacing: Slow and steady, with natural pauses."
    ),
    "Fitness Instructor": (
        "Voice: Energetic, upbeat and motivating.\n\n"
        "Tone: Enthusiastic and encouraging, like a personal trainer.\n\n"
        "Pacing: Fast and punchy, with strong emphasis."
    ),
    "Santa": (
        "Voice: Warm, jolly and deep, like Santa Claus.\n\n"
        "Tone: Cheerful, kind and festive.\n\n"
        "Pacing: Unhurried, with a hearty laugh now and then."
    ),
    "Sympathetic": (
        "Voice: Soft, caring and understanding.\n\n"
        "Tone: Empathetic and comforting.\n\n"
        "Pacing: Slow and gentle, with compassionate pauses."
    ),
    "Patient Teacher": (
        "Voice: Clear, friendly and patient.\n\n"
        "Tone: Encouraging and explanatory, like a good teacher.\n\n"
        "Pacing: Measured, with clear pronunciation and pauses for understanding."
    ),
}

MAX_PARCA = 900  # sitedeki 1000 karakter sınırının altında kalmak için


def metni_parcala(metin, max_uzunluk=MAX_PARCA):
    """Metni cümle sonlarından bölerek en fazla max_uzunluk karakterlik parçalara ayırır."""
    parcalar = []
    mevcut = ""
    for cumle in metin.replace("\n", " ").split(". "):
        cumle = cumle.strip() + ". "
        # tek cümle sınırı aşarsa kelime kelime böl
        while len(cumle) > max_uzunluk:
            kes = cumle.rfind(" ", 0, max_uzunluk)
            kes = kes if kes > 0 else max_uzunluk
            if mevcut:
                parcalar.append(mevcut.strip())
                mevcut = ""
            parcalar.append(cumle[:kes].strip())
            cumle = cumle[kes:].lstrip()
        if len(mevcut) + len(cumle) <= max_uzunluk:
            mevcut += cumle
        else:
            parcalar.append(mevcut.strip())
            mevcut = cumle
    if mevcut.strip():
        parcalar.append(mevcut.strip())
    return [p for p in parcalar if p]


async def _uret(metin, ses, vibe, hedef, ilerleme):
    parcalar = metni_parcala(metin)
    if not parcalar:
        raise ValueError("Metin boş.")

    gecici = tempfile.mkdtemp(prefix="openai_tts_")
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"]
            )
            context = await browser.new_context(accept_downloads=True)
            page = await context.new_page()
            async def sayfayi_hazirla():
                await page.goto("https://www.openai.fm", wait_until="networkidle", timeout=60000)
                try:
                    await page.get_by_text(ses, exact=True).first.click(timeout=5000)
                except Exception:
                    pass  # varsayılan ses ile devam et
                # Vibe kutusu (ilk textarea), script kutusu ikinci textarea
                await page.locator("textarea").first.fill(vibe)

            await sayfayi_hazirla()

            dosyalar = []
            for i, parca in enumerate(parcalar, start=1):
                ilerleme(i - 1, len(parcalar))
                yol = os.path.join(gecici, f"parca_{i:02d}.mp3")
                # Uzun metinlerde tek parçadaki geçici hata her şeyi bozmasın: 3 deneme
                for deneme in range(1, 4):
                    try:
                        script_kutusu = page.locator("textarea").nth(1)
                        await script_kutusu.fill("")
                        await script_kutusu.fill(parca)
                        async with page.expect_download(timeout=90000) as dl:
                            await page.get_by_text("Download", exact=False).last.click(timeout=10000)
                        download = await dl.value
                        await download.save_as(yol)
                        break
                    except Exception:
                        if deneme == 3:
                            raise
                        await asyncio.sleep(5)
                        await sayfayi_hazirla()  # sayfayı sıfırlayıp tekrar dene
                dosyalar.append(yol)
                if i < len(parcalar):
                    await asyncio.sleep(2)

            await browser.close()

        with open(hedef, "wb") as cikti:
            for yol in dosyalar:
                with open(yol, "rb") as girdi:
                    cikti.write(girdi.read())
        ilerleme(len(parcalar), len(parcalar))
    finally:
        shutil.rmtree(gecici, ignore_errors=True)


def openai_seslendir(metin, ses, vibe, hedef, ilerleme=lambda i, n: None):
    """Metni seslendirip tek bir mp3 olarak `hedef` yoluna yazar."""
    asyncio.run(_uret(metin, ses, vibe, hedef, ilerleme))
