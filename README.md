# Orpi Couzon AI Voice Receptionist

An AI-powered voice receptionist (Sofia) for the Orpi Couzon real estate agency on the Côte d'Azur. Sofia answers incoming calls, qualifies callers (tenants or landlords), collects key information, and generates a structured dossier for the agency director Vincent.

## Architecture

```
Caller → Twilio (+33 number) → FastAPI (WebSocket) → Deepgram STT → OpenAI GPT-4o-mini → ElevenLabs TTS → audio back to caller
```

## Prerequisites

- **Python 3.11+** (tested with 3.13)
- Accounts and API keys for:
  - [Twilio](https://www.twilio.com/) — phone number + media streams
  - [Deepgram](https://deepgram.com/) — real-time speech-to-text
  - [OpenAI](https://platform.openai.com/) — GPT-4o-mini for conversation
  - [ElevenLabs](https://elevenlabs.io/) — text-to-speech

## Quick Start

### 1. Clone and install

```bash
cd ai-receptionist
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Configure environment

```bash
cp .env.example .env
# Edit .env with your actual API keys
```

### 3. Local testing with ngrok

```bash
# Terminal 1: Start the server
uvicorn main:app --host 0.0.0.0 --port 8000

# Terminal 2: Expose with ngrok
ngrok http 8000
```

Update your `.env` with the ngrok URL:
```
SERVER_URL=https://abc123.ngrok-free.app
```

### 4. Configure Twilio

1. Go to your Twilio Console → Phone Numbers → your +33 number
2. Under **Voice & Fax → A Call Comes In**, set:
   - Webhook: `https://your-url/incoming-call`
   - Method: POST
3. Save

### 5. Test

Call your Twilio number. Sofia will greet you and start the qualification flow.

## Deploy to Railway

### 1. Push to GitHub

```bash
git init
git add .
git commit -m "Initial commit"
git remote add origin https://github.com/your-user/ai-receptionist.git
git push -u origin main
```

### 2. Deploy on Railway

1. Go to [Railway](https://railway.app/) → New Project → Deploy from GitHub
2. Select your repository
3. Add environment variables (all keys from `.env.example`)
4. Set `SERVER_URL` to your Railway deployment URL (e.g., `https://ai-receptionist-production.up.railway.app`)
5. Deploy

### 3. Update Twilio webhook

Point your Twilio number's webhook to:
```
https://your-railway-url/incoming-call
```

## How It Works

1. **Incoming call** hits `/incoming-call` → returns TwiML to start a WebSocket media stream
2. **WebSocket** `/media-stream` receives real-time audio from Twilio (mulaw 8kHz, base64)
3. **Deepgram** transcribes the audio in real-time (Nova-2, French)
4. **OpenAI** generates Sofia's response based on the full conversation + system prompt
5. **ElevenLabs** synthesizes the response to speech
6. Audio is **resampled** (16kHz PCM → 8kHz mulaw) and sent back through the WebSocket
7. On call end, a **fiche dossier** (structured JSON) is extracted and logged

## Features

- 🇫🇷 Full French conversation with natural tone
- 🏠 Tenant (locataire) and landlord (propriétaire) qualification flows
- 📊 Automatic priority scoring (haute/moyenne/basse)
- 📋 Structured fiche dossier extraction at end of call
- ⚡ Interruption handling — caller can speak while Sofia is talking
- 🔄 Graceful WebSocket disconnection handling

## File Structure

| File | Description |
|------|-------------|
| `main.py` | FastAPI server, webhook, WebSocket handler |
| `config.py` | Environment variable loading |
| `conversation.py` | Per-call conversation state manager |
| `prompts.py` | Sofia system prompt + fiche extraction prompt |
| `schemas.py` | Pydantic data models |
| `services/twilio_handler.py` | TwiML, audio encoding/decoding |
| `services/deepgram_stt.py` | Real-time STT streaming |
| `services/openai_brain.py` | AI conversation + fiche extraction |
| `services/elevenlabs_tts.py` | TTS with resampling |

## License

Private — Orpi Couzon agency.
