import os
import time
import threading
import uuid
from flask import Flask, render_template, request, send_file, jsonify, Response
import edge_motoru
from openai_tts import OPENAI_SESLER, OPENAI_VIBELER, openai_seslendir

app = Flask(__name__)

# İndirilecek mp3 dosyaları için klasör
DOWNLOAD_FOLDER = os.path.join(os.path.dirname(__file__), "downloads")
os.makedirs(DOWNLOAD_FOLDER, exist_ok=True)

# Global görev takip sözlüğü
tasks = {}

# OpenAI motoru tarayıcı açtığı için aynı anda tek iş çalışsın (sunucu belleğini korur)
openai_kilit = threading.Semaphore(1)
OPENAI_MAX_KARAKTER = 150000
EDGE_MAX_KARAKTER = 300000
DOSYA_OMRU_SN = 60 * 60  # indirilen dosyalar 1 saat sonra silinir


def eski_dosyalari_temizle():
    simdi = time.time()
    for ad in os.listdir(DOWNLOAD_FOLDER):
        yol = os.path.join(DOWNLOAD_FOLDER, ad)
        try:
            if os.path.isfile(yol) and simdi - os.path.getmtime(yol) > DOSYA_OMRU_SN:
                os.remove(yol)
        except OSError:
            pass


def run_background_tts(task_id, provider, text, voice, vibe, filepath, filename, edge_ayar=None):
    srt_url = None
    try:
        if provider == "edge":
            def ilerleme(i, n):
                tasks[task_id] = {"status": "processing", "progress": f"{i}/{n}"}

            srt = edge_motoru.seslendir(
                text, voice, *edge_ayar["ayar"], filepath,
                altyazi=edge_ayar["altyazi"], ilerleme=ilerleme,
            )
            if srt:
                with open(filepath[:-4] + ".srt", "w", encoding="utf-8") as f:
                    f.write(srt)
                srt_url = f"/download/{filename[:-4]}.srt"
        elif provider == "openai":
            tasks[task_id] = {"status": "queued"}
            with openai_kilit:
                tasks[task_id] = {"status": "processing", "progress": "başlıyor"}

                def ilerleme(i, n):
                    tasks[task_id] = {"status": "processing", "progress": f"{i}/{n}"}

                openai_seslendir(text, voice, vibe, filepath, ilerleme)

        # Görev başarılı olarak tamamlandı
        tasks[task_id] = {
            "status": "completed",
            "download_url": f"/download/{filename}",
            "srt_url": srt_url,
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
    provider = "openai" if data.get("provider") == "openai" else "edge"

    if not text:
        return jsonify({"error": "Lütfen metin girin."}), 400

    vibe = ""
    edge_ayar = None
    if provider == "openai":
        voice = data.get("voice", "Fable")
        vibe = data.get("vibe", "").strip() or OPENAI_VIBELER["Calm"]
        if voice not in OPENAI_SESLER:
            return jsonify({"error": "Geçersiz OpenAI sesi."}), 400
        if len(text) > OPENAI_MAX_KARAKTER:
            return jsonify({"error": f"OpenAI için en fazla {OPENAI_MAX_KARAKTER} karakter girebilirsiniz."}), 400
    else:
        voice = data.get("voice", "tr-TR-AhmetNeural")
        if len(text) > EDGE_MAX_KARAKTER:
            return jsonify({"error": f"En fazla {EDGE_MAX_KARAKTER} karakter girebilirsiniz."}), 400
        edge_ayar = {
            "ayar": edge_motoru.ayar_dizgisi(data.get("rate"), data.get("volume"), data.get("pitch")),
            "altyazi": data.get("altyazi") if data.get("altyazi") in ("cumle", "kelime") else None,
        }

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
        args=(task_id, provider, text, voice, vibe, filepath, filename, edge_ayar),
        daemon=True
    )
    thread.start()

    # İstek yapan tarayıcıya anında task_id döndürerek bağlantıyı sonlandır
    return jsonify({
        "success": True,
        "task_id": task_id
    })


@app.route('/api/voices')
def api_voices():
    try:
        return jsonify(edge_motoru.sesleri_getir())
    except Exception as e:
        return jsonify({"error": f"Ses listesi alınamadı: {e}"}), 502


@app.route('/api/preview', methods=['POST'])
def api_preview():
    data = request.json or {}
    voice = data.get("voice", "tr-TR-AhmetNeural")
    text = (data.get("text") or "").strip()[:300] or edge_motoru.ornek_metin(voice)
    ayar = edge_motoru.ayar_dizgisi(data.get("rate"), data.get("volume"), data.get("pitch"))
    try:
        return Response(edge_motoru.onizleme(voice, text, *ayar), mimetype="audio/mpeg")
    except Exception as e:
        return jsonify({"error": str(e)}), 502


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
        uzanti = os.path.splitext(filename)[1]
        response = send_file(filepath, as_attachment=True)
        if custom_name:
            # Türkçe karakterlerin ve boşlukların sorunsuz inmesi için güvenli formatlama yapıyoruz
            if not custom_name.lower().endswith(uzanti):
                custom_name += uzanti
            # Tarayıcıya yeni dosya adını bildiriyoruz
            response.headers["Content-Disposition"] = f"attachment; filename={custom_name}"
        return response
    return "Dosya bulunamadı", 404


if __name__ == '__main__':
    print("[+] Web sunucusu baslatildi! Tarayicida http://127.0.0.1:5000 adresine gidin.")
    app.run(host='127.0.0.1', port=5000, debug=True)
