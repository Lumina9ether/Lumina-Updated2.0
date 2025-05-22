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

def detect_funnel_entry(text):
    lowered = text.lower()
    if any(kw in lowered for kw in ["i'm just looking", "what is this", "not sure", "thinking about"]):
        return "explorer"
    elif any(kw in lowered for kw in ["how do i start", "help me", "learn", "understand"]):
        return "curious"
    elif any(kw in lowered for kw in ["i'm ready", "get started", "invest", "sign up"]):
        return "ready"
    elif any(kw in lowered for kw in ["buy", "purchase", "checkout"]):
        return "buyer"
    elif any(kw in lowered for kw in ["need support", "have an issue", "need help"]):
        return "support"
    return "explorer"

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/ask", methods=["POST"])
def ask():
    data = request.get_json()
    question = data.get("question", "")
    if not question:
        return jsonify({"reply": "Please ask a question."})

    try:
        memory = load_memory()
        memory = update_memory_from_text(question, memory)
        memory = update_timeline_from_text(question, memory)

        funnel_tag = detect_funnel_entry(question)
        memory["funnel_entry_tag"] = funnel_tag
        save_memory(memory)

        context_intro = (
            f"User Name: {memory['personal'].get('name', '')}\n"
            f"Birthday: {memory['personal'].get('birthday', '')}\n"
            f"Location: {memory['personal'].get('location', '')}\n"
            f"Goal: {memory['business'].get('goal', '')}\n"
            f"Niche: {memory['business'].get('niche', '')}\n"
            f"Target Income: {memory['business'].get('income_target', '')}\n"
            f"Voice Style: {memory['preferences'].get('voice_style', '')}\n"
            f"Theme Color: {memory['preferences'].get('theme_color', '')}\n"
            f"Recent Mood: {memory['emotional'].get('recent_state', '')}, Motivation Level: {memory['emotional'].get('motivation_level', 0)}"
        )

        conversation = [
            {"role": "system", "content": "You are Lumina, a soulful AI guide that adapts to the user's evolving journey."},
            {"role": "system", "content": f"User memory context: {context_intro}"},
            {"role": "user", "content": question}
        ]

        response = client.chat.completions.create(
            model="gpt-4",
            messages=conversation
        )

        answer = response.choices[0].message.content.strip()
        return jsonify({"reply": answer, "cta": "", "tag": funnel_tag})
    except Exception as e:
        return jsonify({"reply": f"Error: {str(e)}"})

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
