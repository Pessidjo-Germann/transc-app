import os
import asyncio
import threading
import queue

from dotenv import load_dotenv
from flask import Flask
from flask_sock import Sock
from google import genai

load_dotenv()

GEMINI_KEY = os.getenv("AIzaSyD1rWGPg2oXkqyUG0as7vi0ZPIVIwBwCGY")
MODEL      = "gemini-live-2.5-flash-preview"

app  = Flask(__name__)
sock = Sock(app)

# ------------------------------------------------------------------
# Pont vers Gemini Live (thread asyncio dédié)
# ------------------------------------------------------------------
class GeminiBridge:
    def __init__(self):
        self.client = genai.Client(api_key=GEMINI_KEY)
        self.in_q   = queue.Queue()   # bytes audio
        self.out_q  = queue.Queue()   # str transcription
        self.thread = threading.Thread(target=self._run_loop, daemon=True)
        self.thread.start()

    def _run_loop(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(self._gemini_loop())

    async def _gemini_loop(self):
        config = {
            "response_modalities": ["TEXT"],
            "input_audio_transcription": {}
        }
        async with self.client.aio.live.connect(model=MODEL, config=config) as session:
            async def sender():
                while True:
                    data = await asyncio.get_event_loop().run_in_executor(
                        None, self.in_q.get
                    )
                    audio_blob = genai.types.Blob(
                        data=data, mime_type="audio/pcm;rate=16000"
                    )
                    await session.send_realtime_input(audio=audio_blob)

            async def receiver():
                async for msg in session.receive():
                    if msg.server_content and msg.server_content.input_transcription:
                        self.out_q.put(msg.server_content.input_transcription.text)

            await asyncio.gather(sender(), receiver())

    # API synchrone utilisée par Flask
    def send_audio(self, data: bytes):
        self.in_q.put(data)

    def get_transcript(self):
        try:
            return self.out_q.get_nowait()
        except queue.Empty:
            return None

bridge = GeminiBridge()

# ------------------------------------------------------------------
# WebSocket Flask
# ------------------------------------------------------------------
def transcription_sender(ws):
    """Écoute la file de sortie et envoie les transcriptions au client."""
    while not ws.closed:
        try:
            txt = bridge.get_transcript()
            if txt:
                print("🎤 Transcription ->", txt)
                ws.send(txt)
            # Petite pause pour ne pas surcharger le CPU
            threading.Event().wait(0.1)
        except Exception as e:
            print(f"Erreur dans le sender : {e}")
            break

@sock.route('/ws/transcribe')
def transcribe(ws):
    print("🟢 Client connected")
    # Crée et démarre un thread pour envoyer les transcriptions
    sender_thread = threading.Thread(target=transcription_sender, args=(ws,))
    sender_thread.daemon = True
    sender_thread.start()

    try:
        while not ws.closed:
            # Attend et reçoit les données audio du client
            audio_chunk = ws.receive()
            if audio_chunk is None:
                break
            print(f"📦 Received {len(audio_chunk)} bytes")
            bridge.send_audio(audio_chunk)
    except Exception as e:
        print(f"Erreur de réception: {e}")
    finally:
        print("🔴 Client disconnected")
        # Le thread sender s'arrêtera car ws.closed sera True

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=6000, debug=True)