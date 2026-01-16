import socket
import json
import threading

import config
from vosk import Model, KaldiRecognizer
from openai import OpenAI

client = OpenAI(api_key=config.OPENAI_API_KEY)

# ===== MODELS =====
MODEL_RU = "PATH TO MODEL , ex: /Users/sam/Downloads/vosk-model-ru-0.22"
MODEL_EN = "PATH TO MODEL"
SAMPLE_RATE = 16000

# ===== TCP CONFIG =====
HOST = "0.0.0.0"
PORT = 6000

print("Loading RU model...")
model_ru = Model(MODEL_RU)

print("Loading EN model...")
model_en = Model(MODEL_EN)

current_lang = "ru"
rec = KaldiRecognizer(model_ru, SAMPLE_RATE)

# ===== SIMPLE MEMORY =====
conversation_history = []
HISTORY_LIMIT = 10


def generate_reply(text: str) -> str:
    """
    GPT reply with anti-hallucination rules.
    """
    text = text.strip()
    if not text:
        return ""

    conversation_history.append({"role": "user", "content": text})
    recent = conversation_history[-HISTORY_LIMIT:]

    system_prompt = (
        "You are a real-time offline voice assistant. "
        "You CANNOT browse the internet. "
        "Use the same language as the user. "
        "If unsure about facts, clearly say you don't know. "
        "Do not invent people, games or places if you are not sure. "
        "Short, clear sentences. Year is 2026. No markdown, no lists. "
        "If the user switches to Kazakh, continue replying in Kazakh "
        "until they clearly ask you to switch language again."
    )

    try:
        completion = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "system", "content": system_prompt}, *recent],
            temperature=0.1,
            max_tokens=100,
        )
        reply = completion.choices[0].message.content.strip()
        return reply.replace("\n", " ")
    except Exception as e:
        print("LLM error:", e)
        return "Кешір, жауап генерациясында қате болды."


def tts_bytes(text: str) -> bytes:
    """
    OpenAI TTS -> raw PCM16 24kHz mono
    """
    text = text.strip()
    if not text:
        return b""

    try:
        resp = client.audio.speech.create(
            model="gpt-4o-mini-tts",
            voice="onyx",
            input=text,
            response_format="pcm",
        )
        audio_bytes = resp.read()
        print(f"TTS: {len(audio_bytes)} bytes")
        return audio_bytes
    except Exception as e:
        print("TTS ERROR:", e)
        return b""


def handle_lang_markers(conn: socket.socket, data: bytes):
    """
    Detect and handle __lang_ru__ / __lang_en__ markers inside data.
    Returns (processed_data).
    """
    global current_lang, rec

    if b"__lang_ru__" in data:
        data = data.replace(b"__lang_ru__", b"")
        current_lang = "ru"
        rec = KaldiRecognizer(model_ru, SAMPLE_RATE)
        print("LANG -> RU")
        try:
            conn.sendall(b"LANG_RU_OK\n")
        except OSError:
            pass

    if b"__lang_en__" in data:
        data = data.replace(b"__lang_en__", b"")
        current_lang = "en"
        rec = KaldiRecognizer(model_en, SAMPLE_RATE)
        print("LANG -> EN")
        try:
            conn.sendall(b"LANG_EN_OK\n")
        except OSError:
            pass

    return data


def handle_client(conn: socket.socket, addr):
    global current_lang, rec

    print(f"Client {addr} connected")
    listening = False

    try:
        while True:
            data = conn.recv(2048)
            if not data:
                break

            # 1) handle language markers, strip them from stream
            data = handle_lang_markers(conn, data)
            if not data:
                # e.g. packet contained only __lang_ru__
                continue

            # 2) normal STT pipeline
            if rec.AcceptWaveform(data):
                if listening:
                    try:
                        conn.sendall(b"__listening_off__\n")
                    except OSError:
                        pass
                    listening = False

                res = json.loads(rec.Result())
                text = res.get("text", "").strip()
                if text:
                    print(f"[{current_lang}] FINAL: {text}")

                    reply = generate_reply(text)

                    # text to OLED
                    try:
                        conn.sendall((reply + "\n").encode("utf-8"))
                    except OSError:
                        break

                    # TTS
                    audio = tts_bytes(reply)
                    if audio:
                        try:
                            conn.sendall(b"__speaking_on__\n")
                        except OSError:
                            pass

                        try:
                            header = f"__audio_len__ {len(audio)}\n"
                            conn.sendall(header.encode("utf-8"))
                            conn.sendall(audio)
                        except OSError:
                            break

                        try:
                            conn.sendall(b"__speaking_off__\n")
                        except OSError:
                            pass

            else:
                pres = json.loads(rec.PartialResult())
                ptext = pres.get("partial", "").strip()
                if ptext:
                    print(f"[{current_lang}] PARTIAL: {ptext}", end="\r")
                    if not listening:
                        try:
                            conn.sendall(b"__listening_on__\n")
                        except OSError:
                            pass
                        listening = True

    finally:
        conn.close()
        print("Client disconnected")


def main():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind((HOST, PORT))
        s.listen(1)
        print(f"Server listening on {HOST}:{PORT}")

        while True:
            conn, addr = s.accept()
            threading.Thread(
                target=handle_client,
                args=(conn, addr),
                daemon=True,
            ).start()


if __name__ == "__main__":
    main()
