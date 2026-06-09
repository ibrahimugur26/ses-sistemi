import os
import asyncio
from flask import Flask, render_template, request, send_file, jsonify
import edge_tts
from gtts import gTTS
import uuid

app = Flask(__name__)

# İndirilecek mp3 dosyaları için klasör
DOWNLOAD_FOLDER = os.path.join(os.path.dirname(__file__), "downloads")
os.makedirs(DOWNLOAD_FOLDER, exist_ok=True)

async def edge_tts_generate(text, voice, output_path):
    communicate = edge_tts.Communicate(text, voice)
    await communicate.save(output_path)

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
        
    # Her işlem için benzersiz bir dosya adı oluşturuyoruz ki dosyalar karışmasın
    filename = f"ses_{uuid.uuid4().hex[:8]}.mp3"
    filepath = os.path.join(DOWNLOAD_FOLDER, filename)
    
    try:
        if voice == "google-tr":
            # Standart Google Sesi
            tts = gTTS(text=text, lang="tr", slow=False)
            tts.save(filepath)
        else:
            # Microsoft Edge Yüksek Kaliteli Ses
            asyncio.run(edge_tts_generate(text, voice, filepath))
            
        return jsonify({"success": True, "download_url": f"/download/{filename}"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/download/<filename>')
def download(filename):
    filepath = os.path.join(DOWNLOAD_FOLDER, filename)
    if os.path.exists(filepath):
        return send_file(filepath, as_attachment=True)
    return "Dosya bulunamadı", 404

if __name__ == '__main__':
    print("[+] Web sunucusu baslatildi! Tarayicida http://127.0.0.1:5000 adresine gidin.")
    app.run(host='127.0.0.1', port=5000, debug=True)
