from flask import Flask, request, jsonify, render_template
from flask_cors import CORS
import openai
import os
import uuid
import json
import re
from datetime import datetime
from google.cloud import texttospeech

app = Flask(__name__)
CORS(app)

client = openai.OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = "lumina-voice-ai.json"
tts_client = texttospeech.TextToSpeechClient()

MEMORY_FILE = "memory.json"
user_sessions = {}  # Session tracking for tier logic

def load_memory():
    try:
        with open(MEMORY_FILE, "r") as f:
            return json.load(f)
    except:
        return {}

def save_memory(data):
    with open(MEMORY_FILE, "w") as f:
        json.dump(data, f, indent=2)

def check_missing_memory(memory):
    missing = []
    if not memory["personal"].get("name"):
        missing.append("name")
    if not memory["business"].get("goal"):
        missing.append("goal")
    if not memory["preferences"].get("voice_style"):
        missing.append("voice_style")
    return missing

def update_timeline_from_text(text, memory):
    keywords = ["mark today as", "record", "log", "note", "milestone"]
    if any(k in text.lower() for k in keywords):
        match = re.search(r"(?:mark today as|record|log|note|milestone):?\s*(.+)", text, re.IGNORECASE)
        if match:
            event = match.group(1).strip()
            today = datetime.now().strftime("%Y-%m-%d")
            timeline = memory.get("timeline", [])
            timeline.append({"date": today, "event": event})
            memory["timeline"] = timeline
    return memory

def update_memory_from_text(text, memory):
    if "my name is" in text.lower():
        name = re.search(r"my name is ([a-zA-Z ,.'-]+)", text, re.IGNORECASE)
        if name:
            memory["personal"]["name"] = name.group(1).strip()
    if "my goal is" in text.lower():
        goal = re.search(r"my goal is (.+)", text, re.IGNORECASE)
        if goal:
            memory["business"]["goal"] = goal.group(1).strip()
    if "speak in" in text.lower():
        style = re.search(r"speak in (.+)", text, re.IGNORECASE)
        if style:
            memory["preferences"]["voice_style"] = style.group(1).strip()
    return memory

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/ask", methods=["POST"])
def ask():
    session_id = request.remote_addr
    data = request.get_json()
    question = data.get("question", "").lower()

    steps = user_sessions.get(session_id, {"step": 0, "answers": []})

    if steps["step"] == 0:
        response = "Do you already have a business, or are you just getting started?"
    elif steps["step"] == 1:
        steps["answers"].append(question)
        response = "Do you prefer to work at your own pace, or have someone guide you?"
    elif steps["step"] == 2:
        steps["answers"].append(question)
        response = "Would you like help building your AI system, or want it fully done-for-you?"
    elif steps["step"] == 3:
        steps["answers"].append(question)

        a1, a2, a3 = steps["answers"]
        tier = "spark"
        if "guide" in a2 or "guided" in a2:
            tier = "ignite"
        if "done-for-you" in a3 or "fully" in a3:
            tier = "sovereign"

        response = f"Based on your answers, I recommend the {tier.capitalize()} package."
        user_sessions.pop(session_id, None)
        return jsonify({"reply": response, "cta": tier})

    steps["step"] += 1
    user_sessions[session_id] = steps
    return jsonify({"reply": response})

@app.route("/speak", methods=["POST"])
def speak():
    data = request.get_json()
    text = data.get("text", "")
    if not text:
        return jsonify({"audio": ""})

    try:
        synthesis_input = texttospeech.SynthesisInput(text=text)
        voice = texttospeech.VoiceSelectionParams(
            language_code="en-US",
            name="en-US-Wavenet-F",
            ssml_gender=texttospeech.SsmlVoiceGender.FEMALE
        )
        audio_config = texttospeech.AudioConfig(audio_encoding=texttospeech.AudioEncoding.MP3)
        response = tts_client.synthesize_speech(input=synthesis_input, voice=voice, audio_config=audio_config)

        filename = f"static/audio_{uuid.uuid4().hex}.mp3"
        with open(filename, "wb") as out:
            out.write(response.audio_content)

        return jsonify({"audio": "/" + filename})
    except Exception as e:
        return jsonify({"audio": "", "error": str(e)})

@app.route("/timeline")
def timeline():
    memory = load_memory()
    return jsonify({"timeline": memory.get("timeline", [])})

@app.route("/memory")
def memory_view():
    return jsonify(load_memory())

@app.route("/update-memory", methods=["POST"])
def update_memory():
    data = request.get_json()
    memory = load_memory()
    memory["personal"]["name"] = data.get("name", "")
    memory["business"]["goal"] = data.get("goal", "")
    memory["preferences"]["voice_style"] = data.get("voice_style", "")
    memory["business"]["income_target"] = data.get("income_target", "")
    memory["emotional"]["recent_state"] = data.get("mood", "")
    save_memory(memory)
    return jsonify({"status": "success"})

@app.route("/save-lead", methods=["POST"])
def save_lead():
    data = request.get_json()
    email = data.get("email")
    tier = data.get("tierUrl")

    if not email:
        return jsonify({"status": "error", "message": "Missing email"}), 400

    lead_data = {
        "email": email,
        "tier": tier,
        "timestamp": datetime.now().isoformat()
    }

    leads = []
    try:
        with open("leads.json", "r") as f:
            leads = json.load(f)
    except:
        leads = []

    leads.append(lead_data)
    with open("leads.json", "w") as f:
        json.dump(leads, f, indent=2)

    return jsonify({"status": "success"})

if __name__ == "__main__":
    app.run(debug=True)
