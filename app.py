import os
import time
import asyncio
import threading
import uuid
from flask import Flask, render_template, request, send_file, jsonify
import edge_tts
from gtts import gTTS
from openai_tts import OPENAI_SESLER, OPENAI_VIBELER, openai_seslendir

app = Flask(__name__)

# İndirilecek mp3 dosyaları için klasör
DOWNLOAD_FOLDER = os.path.join(os.path.dirname(__file__), "downloads")
os.makedirs(DOWNLOAD_FOLDER, exist_ok=True)

# Global görev takip sözlüğü
tasks = {}

# OpenAI motoru tarayıcı açtığı için aynı anda tek iş çalışsın (sunucu belleğini korur)
openai_kilit = threading.Semaphore(1)
OPENAI_MAX_KARAKTER = 8000
DOSYA_OMRU_SN = 60 * 60  # indirilen dosyalar 1 saat sonra silinir


async def edge_tts_generate(text, voice, output_path):
    communicate = edge_tts.Communicate(text, voice)
    await communicate.save(output_path)


def eski_dosyalari_temizle():
    simdi = time.time()
    for ad in os.listdir(DOWNLOAD_FOLDER):
        yol = os.path.join(DOWNLOAD_FOLDER, ad)
        try:
            if os.path.isfile(yol) and simdi - os.path.getmtime(yol) > DOSYA_OMRU_SN:
                os.remove(yol)
        except OSError:
            pass


def run_background_tts(task_id, provider, text, voice, vibe, filepath, filename):
    try:
        if provider == "openai":
            tasks[task_id] = {"status": "queued"}
            with openai_kilit:
                tasks[task_id] = {"status": "processing", "progress": "başlıyor"}

                def ilerleme(i, n):
                    tasks[task_id] = {"status": "processing", "progress": f"{i}/{n}"}

                openai_seslendir(text, voice, vibe, filepath, ilerleme)
        elif voice == "google-tr":
            # Standart Google Sesi
            tts = gTTS(text=text, lang="tr", slow=False)
            tts.save(filepath)
        else:
            # Microsoft Edge Yüksek Kaliteli Ses
            asyncio.run(edge_tts_generate(text, voice, filepath))

        # Görev başarılı olarak tamamlandı
        tasks[task_id] = {
            "status": "completed",
            "download_url": f"/download/{filename}"
        }
    except Exception as e:
        # Görev sırasında hata oluştu
        tasks[task_id] = {
            "status": "failed",
            "error": str(e)
        }


@app.route('/')
def index():
    return render_template('index.html', openai_sesler=OPENAI_SESLER, openai_vibeler=OPENAI_VIBELER)


@app.route('/generate', methods=['POST'])
def generate():
    data = request.json or {}
    text = data.get("text", "").strip()
    provider = data.get("provider", "microsoft")

    if not text:
        return jsonify({"error": "Lütfen metin girin."}), 400

    vibe = ""
    if provider == "openai":
        voice = data.get("voice", "Fable")
        vibe = data.get("vibe", "").strip() or OPENAI_VIBELER["Calm"]
        if voice not in OPENAI_SESLER:
            return jsonify({"error": "Geçersiz OpenAI sesi."}), 400
        if len(text) > OPENAI_MAX_KARAKTER:
            return jsonify({"error": f"OpenAI için en fazla {OPENAI_MAX_KARAKTER} karakter girebilirsiniz."}), 400
    else:
        provider = "microsoft"
        voice = data.get("voice", "tr-TR-AhmetNeural")

    eski_dosyalari_temizle()

    # Benzersiz bir görev ve dosya kimliği oluşturuyoruz
    task_id = str(uuid.uuid4())
    filename = f"ses_{uuid.uuid4().hex[:8]}.mp3"
    filepath = os.path.join(DOWNLOAD_FOLDER, filename)

    # Görevi hafızaya ekle ve durumunu "processing" yap
    tasks[task_id] = {
        "status": "processing"
    }

    # Arka planda seslendirme işini başlat
    thread = threading.Thread(
        target=run_background_tts,
        args=(task_id, provider, text, voice, vibe, filepath, filename),
        daemon=True
    )
    thread.start()

    # İstek yapan tarayıcıya anında task_id döndürerek bağlantıyı sonlandır
    return jsonify({
        "success": True,
        "task_id": task_id
    })


@app.route('/status/<task_id>', methods=['GET'])
def task_status(task_id):
    task = tasks.get(task_id)
    if not task:
        return jsonify({"error": "Görev bulunamadı."}), 404
    return jsonify(task)


@app.route('/download/<filename>')
def download(filename):
    filename = os.path.basename(filename)
    filepath = os.path.join(DOWNLOAD_FOLDER, filename)
    if os.path.exists(filepath):
        custom_name = request.args.get('name')
        response = send_file(filepath, as_attachment=True)
        if custom_name:
            # Türkçe karakterlerin ve boşlukların sorunsuz inmesi için güvenli formatlama yapıyoruz
            if not custom_name.lower().endswith('.mp3'):
                custom_name += '.mp3'
            # Tarayıcıya yeni dosya adını bildiriyoruz
            response.headers["Content-Disposition"] = f"attachment; filename={custom_name}"
        return response
    return "Dosya bulunamadı", 404


if __name__ == '__main__':
    print("[+] Web sunucusu baslatildi! Tarayicida http://127.0.0.1:5000 adresine gidin.")
    app.run(host='127.0.0.1', port=5000, debug=True)
