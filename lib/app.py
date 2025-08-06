import os
import asyncio
import threading
import queue

from dotenv import load_dotenv
from flask import Flask
from flask_sock import Sock
import google.generativeai as genai

load_dotenv()

GEMINI_KEY = os.getenv("AIzaSyD1rWGPg2oXkqyUG0as7vi0ZPIVIwBwCGY")
MODEL      = "gemini-live-2.5-flash-preview"

app  = Flask(__name__)
sock = Sock(app)

# Ensemble pour stocker toutes les connexions client WebSocket actives
clients = set()

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

# --- Pont de simulation pour les tests sans clé API ---
class MockGeminiBridge:
    def __init__(self):
        self.out_q = queue.Queue()
        self.msg_counter = 0

    def send_audio(self, data: bytes):
        self.msg_counter += 1
        # Simule une transcription après avoir reçu des données audio
        msg = f"Message simulé #{self.msg_counter}"
        print(f"[MOCK] Génération du message : '{msg}'")
        self.out_q.put(msg)

# --- Sélection du pont à utiliser ---
# Mettre à False pour utiliser le vrai pont Gemini avec une clé API valide
USE_MOCK_BRIDGE = True

if USE_MOCK_BRIDGE:
    print("--- ATTENTION : Utilisation du pont de simulation (Mock Bridge) ---")
    bridge = MockGeminiBridge()
else:
    bridge = GeminiBridge()


# ------------------------------------------------------------------
# Thread de Diffusion (Broadcast)
# ------------------------------------------------------------------
def broadcast_transcriptions():
    """
    Récupère les transcriptions depuis le pont Gemini et les diffuse
    à tous les clients connectés.
    """
    while True:
        # Attend qu'une transcription soit disponible dans la file
        txt = bridge.out_q.get()
        if txt:
            print(f"🎤 Diffusion -> {txt}")
            # Crée une copie de l'ensemble pour éviter les erreurs de concurrence
            # si un client se connecte/déconnecte pendant la diffusion
            clients_copy = clients.copy()
            for client_ws in clients_copy:
                try:
                    client_ws.send(txt)
                except Exception as e:
                    # Gère le cas où un client s'est déconnecté subitement
                    print(f"Erreur lors de l'envoi à un client : {e}")


# Démarrer le thread de diffusion une seule fois
broadcaster_thread = threading.Thread(target=broadcast_transcriptions, daemon=True)
broadcaster_thread.start()


# ------------------------------------------------------------------
# WebSocket Flask
# ------------------------------------------------------------------
@sock.route('/ws/transcribe')
def transcribe(ws):
    # Ajoute le nouveau client à l'ensemble des clients actifs
    clients.add(ws)
    print(f"🟢 Client connecté. Total : {len(clients)}")

    try:
        while not ws.closed:
            # Attend et reçoit les données audio du client
            audio_chunk = ws.receive()
            if audio_chunk is None:
                break
            print(f"📦 Reçu {len(audio_chunk)} bytes d'un client")
            bridge.send_audio(audio_chunk)
    except Exception as e:
        print(f"Erreur de réception : {e}")
    finally:
        # Retire le client de l'ensemble lors de la déconnexion
        clients.remove(ws)
        print(f"🔴 Client déconnecté. Total : {len(clients)}")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=6000, debug=True)