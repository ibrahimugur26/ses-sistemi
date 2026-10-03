"""edge-tts ile seslendirme motoru: ses listesi, ön dinleme, uzun metni parçalayıp birleştirme, SRT."""
import asyncio
import re

import edge_tts

PARCA_KARAKTER = 3000
DENEME = 3
PARALEL = 3  # aynı anda üretilen parça sayısı

ORNEK_METINLER = {
    "tr": "Merhaba, ben yapay zeka sesiyim. Beni dinlediğin için teşekkürler.",
    "en": "Hello, this is a quick preview of my voice.",
    "de": "Hallo, das ist eine kurze Hörprobe meiner Stimme.",
    "fr": "Bonjour, ceci est un aperçu rapide de ma voix.",
    "es": "Hola, esta es una vista previa rápida de mi voz.",
    "it": "Ciao, questa è una breve anteprima della mia voce.",
    "pt": "Olá, esta é uma prévia rápida da minha voz.",
    "ru": "Привет, это краткий образец моего голоса.",
    "ar": "مرحباً، هذه معاينة سريعة لصوتي.",
    "ja": "こんにちは、これは私の声の簡単なプレビューです。",
    "ko": "안녕하세요, 제 목소리의 빠른 미리듣기입니다.",
    "zh": "你好，这是我声音的快速试听。",
    "nl": "Hallo, dit is een korte voorbeeldweergave van mijn stem.",
    "pl": "Cześć, to jest krótki podgląd mojego głosu.",
    "hi": "नमस्ते, यह मेरी आवाज़ का एक छोटा सा नमूना है।",
}

_ses_listesi = None
_onizleme_onbellek = {}


def ayar_dizgisi(rate, volume, pitch):
    """Kaydırıcı değerlerini (-100..100) edge-tts biçimine çevirir."""
    def sinirla(v):
        return max(-100, min(100, int(v or 0)))
    return f"{sinirla(rate):+d}%", f"{sinirla(volume):+d}%", f"{sinirla(pitch):+d}Hz"


def sesleri_getir():
    global _ses_listesi
    if _ses_listesi is None:
        _ses_listesi = asyncio.run(edge_tts.list_voices())
    return _ses_listesi


def ornek_metin(ses):
    return ORNEK_METINLER.get(ses.split("-")[0], ORNEK_METINLER["en"])


async def _sentez(metin, ses, rate, volume, pitch, sinir=None):
    ses_bayt = bytearray()
    sinirlar = []
    com = edge_tts.Communicate(
        metin, ses, rate=rate, volume=volume, pitch=pitch,
        boundary=sinir or "SentenceBoundary",
    )
    async for parca in com.stream():
        if parca["type"] == "audio":
            ses_bayt.extend(parca["data"])
        elif sinir and parca["type"] == sinir:
            sinirlar.append((parca["offset"] / 1e7, (parca["offset"] + parca["duration"]) / 1e7, parca["text"]))
    return bytes(ses_bayt), sinirlar


def onizleme(ses, metin, rate, volume, pitch):
    """Kısa metni seslendirip mp3 baytlarını döndürür (aynı istek önbellekten gelir)."""
    anahtar = (ses, metin, rate, volume, pitch)
    if anahtar not in _onizleme_onbellek:
        if len(_onizleme_onbellek) > 200:
            _onizleme_onbellek.pop(next(iter(_onizleme_onbellek)))
        _onizleme_onbellek[anahtar] = asyncio.run(_sentez(metin, ses, rate, volume, pitch))[0]
    return _onizleme_onbellek[anahtar]


def metni_parcala(metin, max_uzunluk=PARCA_KARAKTER):
    """Cümle/satır sonlarından bölerek en fazla max_uzunluk karakterlik parçalar üretir."""
    cumleler = re.split(r"(?<=[.!?…])\s+|\n+", metin)
    parcalar, mevcut = [], ""
    for cumle in cumleler:
        cumle = cumle.strip()
        while len(cumle) > max_uzunluk:  # tek cümle bile sınırı aşıyorsa kelimelerden böl
            kes = cumle.rfind(" ", 0, max_uzunluk)
            kes = kes if kes > 0 else max_uzunluk
            if mevcut:
                parcalar.append(mevcut)
                mevcut = ""
            parcalar.append(cumle[:kes].strip())
            cumle = cumle[kes:].strip()
        if not cumle:
            continue
        if mevcut and len(mevcut) + 1 + len(cumle) > max_uzunluk:
            parcalar.append(mevcut)
            mevcut = cumle
        else:
            mevcut = f"{mevcut} {cumle}".strip()
    if mevcut:
        parcalar.append(mevcut)
    return parcalar


_BITRATE = {  # (mpeg1, layer3) ve (mpeg2/2.5, layer3), kbps
    1: [0, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320, 0],
    2: [0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160, 0],
}
_ORNEKLEME = {3: [44100, 48000, 32000], 2: [22050, 24000, 16000], 0: [11025, 12000, 8000]}


def mp3_suresi(veri):
    """MPEG Layer III kare başlıklarını gezerek gerçek süreyi (sn) hesaplar."""
    i, n, toplam = 0, len(veri), 0.0
    if veri[:3] == b"ID3":
        i = 10 + ((veri[6] & 0x7F) << 21 | (veri[7] & 0x7F) << 14 | (veri[8] & 0x7F) << 7 | (veri[9] & 0x7F))
    while i + 4 <= n:
        b1, b2 = veri[i + 1], veri[i + 2]
        if veri[i] != 0xFF or (b1 & 0xE0) != 0xE0 or (b1 >> 1 & 3) != 1:
            i += 1
            continue
        surum = b1 >> 3 & 3  # 3 = MPEG1, 2 = MPEG2, 0 = MPEG2.5
        bitrate = _BITRATE[1 if surum == 3 else 2][b2 >> 4]
        sri = b2 >> 2 & 3
        if surum == 1 or bitrate == 0 or sri == 3:
            i += 1
            continue
        hiz = _ORNEKLEME[surum][sri]
        ornek = 1152 if surum == 3 else 576
        uzunluk = (144 if surum == 3 else 72) * bitrate * 1000 // hiz + (b2 >> 1 & 1)
        toplam += ornek / hiz
        i += uzunluk
    return toplam


def _zaman(sn):
    ms = int(round(sn * 1000))
    return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"


def srt_olustur(satirlar):
    return "\n".join(
        f"{i}\n{_zaman(b)} --> {_zaman(s)}\n{t}\n" for i, (b, s, t) in enumerate(satirlar, start=1)
    )


async def _uret(metin, ses, rate, volume, pitch, altyazi, ilerleme):
    parcalar = metni_parcala(metin)
    if not parcalar:
        raise ValueError("Metin boş.")
    sinir = {"cumle": "SentenceBoundary", "kelime": "WordBoundary"}.get(altyazi)
    kilit = asyncio.Semaphore(PARALEL)
    biten = 0

    async def parca_uret(parca):
        nonlocal biten
        async with kilit:
            for deneme in range(1, DENEME + 1):
                try:
                    veri, sinirlar = await asyncio.wait_for(_sentez(parca, ses, rate, volume, pitch, sinir), timeout=120)
                    if not veri:
                        raise RuntimeError("Ses verisi boş döndü.")
                    break
                except Exception:
                    if deneme == DENEME:
                        raise
                    await asyncio.sleep(3 * deneme)
        biten += 1
        ilerleme(biten, len(parcalar))
        return veri, sinirlar

    ilerleme(0, len(parcalar))
    sonuclar = await asyncio.gather(*(parca_uret(p) for p in parcalar))  # sıra korunur

    ses_bayt, satirlar, kaydirma = bytearray(), [], 0.0
    for veri, sinirlar in sonuclar:
        satirlar += [(b + kaydirma, s + kaydirma, t) for b, s, t in sinirlar]
        kaydirma += mp3_suresi(veri)
        ses_bayt.extend(veri)
    return bytes(ses_bayt), srt_olustur(satirlar) if sinir else None


def seslendir(metin, ses, rate, volume, pitch, hedef, altyazi=None, ilerleme=lambda i, n: None):
    """Metni seslendirip mp3'ü `hedef` yoluna yazar; altyazı istenmişse SRT metnini döndürür."""
    ses_bayt, srt = asyncio.run(_uret(metin, ses, rate, volume, pitch, altyazi, ilerleme))
    with open(hedef, "wb") as f:
        f.write(ses_bayt)
    return srt
