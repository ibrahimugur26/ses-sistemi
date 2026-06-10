import os
import asyncio
import threading
import uuid
from flask import Flask, render_template, request, send_file, jsonify
import edge_tts
from gtts import gTTS

app = Flask(__name__)

# İndirilecek mp3 dosyaları için klasör
DOWNLOAD_FOLDER = os.path.join(os.path.dirname(__file__), "downloads")
os.makedirs(DOWNLOAD_FOLDER, exist_ok=True)

# Global görev takip sözlüğü
tasks = {}

async def edge_tts_generate(text, voice, output_path):
    communicate = edge_tts.Communicate(text, voice)
    await communicate.save(output_path)

def run_background_tts(task_id, text, voice, filepath, filename):
    try:
        if voice == "google-tr":
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
    return render_template('index.html')

@app.route('/generate', methods=['POST'])
def generate():
    data = request.json
    text = data.get("text", "").strip()
    voice = data.get("voice", "tr-TR-AhmetNeural")
    
    if not text:
        return jsonify({"error": "Lütfen metin girin."}), 400
        
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
        args=(task_id, text, voice, filepath, filename)
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
    filepath = os.path.join(DOWNLOAD_FOLDER, filename)
    if os.path.exists(filepath):
        return send_file(filepath, as_attachment=True)
    return "Dosya bulunamadı", 404

if __name__ == '__main__':
    print("[+] Web sunucusu baslatildi! Tarayicida http://127.0.0.1:5000 adresine gidin.")
    app.run(host='127.0.0.1', port=5000, debug=True)
