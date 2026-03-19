"""FastAPI server for AI voice receptionist — Twilio webhook + WebSocket media stream."""

from __future__ import annotations
import asyncio
import base64
import json
import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.responses import Response

from config import PORT, SERVER_URL
from conversation import Conversation
from prompts import SOFIA_GREETING
from services.twilio_handler import (
    generate_twiml,
    build_media_message,
    build_mark_message,
    build_clear_message,
)
from services.deepgram_stt import DeepgramSTT, test_deepgram
from services.openai_brain import get_response, test_openai
from services.elevenlabs_tts import synthesize_to_mulaw_chunks, test_elevenlabs

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(f"🟢 AI Receptionist starting — SERVER_URL={SERVER_URL}")
    yield
    logger.info("🔴 AI Receptionist shutting down")


app = FastAPI(title="Orpi Couzon AI Receptionist", lifespan=lifespan)


@app.get("/health")
async def health():
    return {"status": "ok", "timestamp": time.time()}


@app.get("/test")
async def test_apis():
    """Test all external API connections."""
    logger.info("🧪 Running API tests...")
    results = {
        "openai": await test_openai(),
        "elevenlabs": await test_elevenlabs(),
        "deepgram": await test_deepgram(),
    }
    logger.info(f"🧪 Results: {results}")
    return results


@app.post("/incoming-call")
async def incoming_call(request: Request):
    """Twilio webhook — returns TwiML to connect a media stream."""
    form = await request.form()
    call_sid = form.get("CallSid", "unknown")
    from_number = form.get("From", "unknown")
    logger.info(f"📞 Incoming call: {call_sid} from {from_number}")
    twiml = generate_twiml()
    return Response(content=twiml, media_type="application/xml")


@app.websocket("/media-stream")
async def media_stream(ws: WebSocket):
    """Bidirectional WebSocket for Twilio media stream."""
    await ws.accept()
    logger.info("🔌 WebSocket connected")

    conversation: Conversation | None = None
    deepgram: DeepgramSTT | None = None
    stream_sid: str | None = None
    transcript_task: asyncio.Task | None = None
    processing_lock = asyncio.Lock()
    speaking_event = asyncio.Event()
    speaking_event.set()

    async def process_transcript(text: str) -> None:
        nonlocal conversation
        if not conversation or not stream_sid:
            return

        if not speaking_event.is_set():
            logger.info(f"[{conversation.call_sid}] ⚡ Interruption")
            try:
                await ws.send_text(build_clear_message(stream_sid))
            except Exception:
                pass
            speaking_event.set()
            conversation.is_speaking = False

        async with processing_lock:
            conversation.add_user_message(text)
            ai_response = await get_response(conversation.get_openai_messages())
            conversation.add_assistant_message(ai_response)

            speaking_event.clear()
            conversation.is_speaking = True
            try:
                async for audio_chunk in synthesize_to_mulaw_chunks(ai_response):
                    if speaking_event.is_set():
                        break
                    await ws.send_text(build_media_message(audio_chunk, stream_sid))
                await ws.send_text(build_mark_message(stream_sid, "speech_end"))
            except Exception as e:
                logger.error(f"TTS send error: {e}")
            finally:
                speaking_event.set()
                conversation.is_speaking = False

    async def handle_transcripts(dg: DeepgramSTT) -> None:
        async for transcript in dg.receive_transcripts():
            if transcript and conversation and conversation.is_active:
                await process_transcript(transcript)

    async def send_greeting() -> None:
        nonlocal conversation
        if not conversation or not stream_sid:
            return
        conversation.add_assistant_message(SOFIA_GREETING)
        speaking_event.clear()
        conversation.is_speaking = True
        try:
            async for audio_chunk in synthesize_to_mulaw_chunks(SOFIA_GREETING):
                await ws.send_text(build_media_message(audio_chunk, stream_sid))
            await ws.send_text(build_mark_message(stream_sid, "greeting_end"))
            logger.info(f"[{conversation.call_sid}] ✅ Greeting sent")
        except Exception as e:
            logger.error(f"Greeting error: {e}")
        finally:
            speaking_event.set()
            conversation.is_speaking = False

    try:
        async for raw_message in ws.iter_text():
            try:
                data = json.loads(raw_message)
            except json.JSONDecodeError:
                continue

            event = data.get("event")

            if event == "connected":
                logger.info("📡 Twilio stream connected")

            elif event == "start":
                start_data = data.get("start", {})
                stream_sid = start_data.get("streamSid")
                call_sid = start_data.get("callSid", "unknown")
                logger.info(f"▶️ Stream started: {stream_sid} call={call_sid}")

                conversation = Conversation(call_sid)
                conversation.stream_sid = stream_sid
                deepgram = DeepgramSTT(call_sid)
                await deepgram.connect()
                transcript_task = asyncio.create_task(handle_transcripts(deepgram))
                asyncio.create_task(send_greeting())

            elif event == "media":
                if deepgram:
                    payload = data.get("media", {}).get("payload", "")
                    if payload:
                        await deepgram.send_audio(base64.b64decode(payload))

            elif event == "stop":
                logger.info("⏹️ Stream stopped")
                break

    except WebSocketDisconnect:
        logger.info("🔌 WebSocket disconnected")
    except Exception as e:
        logger.error(f"WebSocket error ({type(e).__name__}): {e}")
    finally:
        if conversation:
            conversation.is_active = False
            logger.info(f"📊 Call {conversation.call_sid} ended after {conversation.duration_seconds:.1f}s")
            if len(conversation.messages) > 2:
                try:
                    fiche = await conversation.extract_fiche()
                    logger.info(f"📋 FICHE: {fiche.model_dump_json(indent=2)}")
                except Exception as e:
                    logger.error(f"Fiche error: {e}")

        if transcript_task:
            transcript_task.cancel()
            try:
                await transcript_task
            except asyncio.CancelledError:
                pass

        if deepgram:
            await deepgram.close()
        logger.info("🧹 Cleanup complete")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=PORT, reload=True)
