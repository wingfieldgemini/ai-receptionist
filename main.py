"""FastAPI server for AI voice receptionist — Twilio webhook + WebSocket media stream."""

from __future__ import annotations
import asyncio
import base64
import json
import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.responses import PlainTextResponse, Response

from config import PORT
from conversation import Conversation
from prompts import SOFIA_GREETING
from services.twilio_handler import (
    generate_twiml,
    build_media_message,
    build_mark_message,
    build_clear_message,
)
from services.deepgram_stt import DeepgramSTT
from services.openai_brain import get_response
from services.elevenlabs_tts import synthesize_to_mulaw_chunks

# Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("🟢 AI Receptionist server starting")
    yield
    logger.info("🔴 AI Receptionist server shutting down")


app = FastAPI(title="Orpi Couzon AI Receptionist", lifespan=lifespan)


@app.get("/health")
async def health():
    return {"status": "ok", "timestamp": time.time()}


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
    speaking_event = asyncio.Event()  # Set when NOT speaking (cleared when speaking)
    speaking_event.set()

    async def process_transcript(text: str) -> None:
        """Process a final transcript: get AI response, synthesize, send audio."""
        nonlocal conversation
        if not conversation or not stream_sid:
            return

        # If Sofia is currently speaking, interrupt: clear the audio queue
        if not speaking_event.is_set():
            logger.info(f"[{conversation.call_sid}] ⚡ Interruption detected, clearing audio")
            try:
                await ws.send_text(build_clear_message(stream_sid))
            except Exception:
                pass
            speaking_event.set()
            conversation.is_speaking = False

        async with processing_lock:
            conversation.add_user_message(text)

            # Get AI response
            ai_response = await get_response(conversation.get_openai_messages())
            conversation.add_assistant_message(ai_response)

            # Synthesize and send audio
            speaking_event.clear()
            conversation.is_speaking = True
            try:
                async for audio_chunk in synthesize_to_mulaw_chunks(ai_response):
                    # Check if interrupted
                    if speaking_event.is_set():
                        logger.info(f"[{conversation.call_sid}] TTS interrupted, stopping")
                        break
                    msg = build_media_message(audio_chunk, stream_sid)
                    await ws.send_text(msg)
                
                # Send mark to know when audio finishes
                await ws.send_text(build_mark_message(stream_sid, "speech_end"))
            except Exception as e:
                logger.error(f"Error sending TTS audio: {e}")
            finally:
                speaking_event.set()
                conversation.is_speaking = False

    async def handle_transcripts(dg: DeepgramSTT) -> None:
        """Background task: receive Deepgram transcripts and process them."""
        async for transcript in dg.receive_transcripts():
            if transcript and conversation and conversation.is_active:
                await process_transcript(transcript)

    async def send_greeting() -> None:
        """Send Sofia's greeting message when call connects."""
        nonlocal conversation
        if not conversation or not stream_sid:
            return
        
        conversation.add_assistant_message(SOFIA_GREETING)
        speaking_event.clear()
        conversation.is_speaking = True
        try:
            async for audio_chunk in synthesize_to_mulaw_chunks(SOFIA_GREETING):
                msg = build_media_message(audio_chunk, stream_sid)
                await ws.send_text(msg)
            await ws.send_text(build_mark_message(stream_sid, "greeting_end"))
        except Exception as e:
            logger.error(f"Error sending greeting: {e}")
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
                logger.info(f"▶️ Stream started: stream={stream_sid} call={call_sid}")

                # Initialize conversation and Deepgram
                conversation = Conversation(call_sid)
                conversation.stream_sid = stream_sid
                deepgram = DeepgramSTT(call_sid)
                await deepgram.connect()

                # Start background transcript handler
                transcript_task = asyncio.create_task(handle_transcripts(deepgram))

                # Send greeting
                asyncio.create_task(send_greeting())

            elif event == "media":
                # Forward audio to Deepgram
                if deepgram:
                    payload = data.get("media", {}).get("payload", "")
                    if payload:
                        audio_bytes = base64.b64decode(payload)
                        await deepgram.send_audio(audio_bytes)

            elif event == "mark":
                mark_name = data.get("mark", {}).get("name", "")
                logger.debug(f"✓ Mark received: {mark_name}")

            elif event == "stop":
                logger.info(f"⏹️ Stream stopped")
                break

    except WebSocketDisconnect:
        logger.info("🔌 WebSocket disconnected")
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
    finally:
        # Cleanup
        if conversation:
            conversation.is_active = False
            duration = conversation.duration_seconds
            logger.info(f"📊 Call {conversation.call_sid} ended after {duration:.1f}s")

            # Extract fiche dossier
            if len(conversation.messages) > 2:  # More than just system + greeting
                try:
                    fiche = await conversation.extract_fiche()
                    fiche_json = fiche.model_dump_json(indent=2)
                    logger.info(f"📋 FICHE DOSSIER for {conversation.call_sid}:\n{fiche_json}")
                    print(f"\n{'='*60}")
                    print(f"📋 FICHE DOSSIER — Call {conversation.call_sid}")
                    print(f"{'='*60}")
                    print(fiche_json)
                    print(f"{'='*60}\n")
                except Exception as e:
                    logger.error(f"Failed to extract fiche: {e}")

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
