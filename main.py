"""FastAPI server for AI voice receptionist — Twilio webhook + WebSocket media stream.

Optimized pipeline:
  Caller speaks → Deepgram STT → OpenAI (streaming) → ElevenLabs (streaming ulaw_8000) → Twilio
  
Key optimizations:
  - OpenAI streams sentences as they're generated
  - ElevenLabs streams audio as it's synthesized (native ulaw_8000, no resampling)
  - Quick acknowledgments while processing complex queries
  - Better interruption handling with clear messages
"""

from __future__ import annotations
import asyncio
import base64
import json
import logging
import random
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
from services.openai_brain import get_response_streaming, test_openai
from services.elevenlabs_tts import synthesize_to_mulaw_chunks, synthesize_single_mulaw, test_elevenlabs

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

# Quick acknowledgment phrases Sofia uses while processing
FILLERS = [
    "D'accord.",
    "Je note.",
    "Très bien.",
    "Parfait.",
    "Je comprends.",
    "Bien sûr.",
]


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(f"🟢 AI Receptionist starting — SERVER_URL={SERVER_URL}")
    yield
    logger.info("🔴 AI Receptionist shutting down")


app = FastAPI(title="Orpi Couzon AI Receptionist", lifespan=lifespan)


@app.get("/health")
async def health():
    return {"status": "ok", "timestamp": time.time()}


@app.post("/vapi-webhook")
async def vapi_webhook(request: Request):
    """Handle Vapi server messages (end-of-call-report, transcript)."""
    try:
        data = await request.json()
        msg_type = data.get("message", {}).get("type", "")
        logger.info(f"📨 Vapi webhook: {msg_type}")
        
        if msg_type == "end-of-call-report":
            transcript = data.get("message", {}).get("transcript", "")
            summary = data.get("message", {}).get("summary", "")
            logger.info(f"📋 Call ended. Summary: {summary[:200] if summary else 'N/A'}")
        
        return {"status": "ok"}
    except Exception as e:
        logger.error(f"Vapi webhook error: {e}")
        return {"status": "error", "message": str(e)}


@app.post("/api/send-confirmation")
async def api_send_confirmation(request: Request):
    """API endpoint to send confirmation email — called by Vapi tool."""
    from services.email_sender import send_confirmation_email
    try:
        data = await request.json()
        
        # Extract from Vapi tool call format or direct JSON
        message = data.get("message", {})
        tool_calls = message.get("toolCalls", [])
        
        if tool_calls:
            # Vapi tool call format
            params = tool_calls[0].get("function", {}).get("arguments", {})
        else:
            # Direct API call
            params = data
        
        success = send_confirmation_email(
            candidate_name=params.get("candidate_name", "Inconnu"),
            candidate_phone=params.get("candidate_phone", "Non communiqué"),
            candidate_email=params.get("candidate_email", ""),
            bien_ref=params.get("bien_ref", ""),
            bien_description=params.get("bien_description", ""),
            disponibilites=params.get("disponibilites", ""),
            call_type=params.get("call_type", "location"),
            notes=params.get("notes", ""),
        )
        
        if success:
            return {"results": [{"result": "Email de confirmation envoyé avec succès."}]}
        else:
            return {"results": [{"result": "L'email n'a pas pu être envoyé. Les coordonnées ont été enregistrées."}]}
    except Exception as e:
        logger.error(f"Send confirmation error: {e}")
        return {"results": [{"result": f"Erreur: {str(e)}"}]}


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
    interrupted = asyncio.Event()  # Set when caller interrupts

    # Track speaking state
    is_speaking = False

    async def send_audio_chunks(chunks_gen, check_interrupt: bool = True) -> bool:
        """Send audio chunks to Twilio. Returns False if interrupted."""
        nonlocal is_speaking
        try:
            async for audio_chunk in chunks_gen:
                if check_interrupt and interrupted.is_set():
                    return False
                await ws.send_text(build_media_message(audio_chunk, stream_sid))
            return True
        except Exception as e:
            logger.error(f"Audio send error: {e}")
            return False

    async def process_transcript(text: str) -> None:
        """Process a transcript: get AI response with streaming pipeline.
        
        Error resilience:
        - If OpenAI takes >3s for first sentence, play a filler while waiting
        - If ElevenLabs fails for one sentence, skip it and continue
        """
        nonlocal is_speaking
        if not conversation or not stream_sid:
            return

        # Handle interruption if Sofia is speaking
        if is_speaking:
            logger.info(f"[{conversation.call_sid}] ⚡ Interruption detected")
            interrupted.set()
            try:
                await ws.send_text(build_clear_message(stream_sid))
            except Exception:
                pass
            is_speaking = False
            # Small delay to let clear take effect
            await asyncio.sleep(0.1)

        async with processing_lock:
            interrupted.clear()
            conversation.add_user_message(text)
            
            is_speaking = True
            t_start = time.time()
            full_response_parts = []
            first_sentence = True
            filler_sent = False

            try:
                # Wrap streaming in a filler-aware loop
                sentence_iter = get_response_streaming(conversation.get_openai_messages()).__aiter__()
                
                while True:
                    if interrupted.is_set():
                        break
                    
                    try:
                        if first_sentence:
                            # Wait up to 3s for first sentence; if slow, send filler
                            try:
                                sentence = await asyncio.wait_for(
                                    sentence_iter.__anext__(), timeout=3.0
                                )
                            except asyncio.TimeoutError:
                                if not filler_sent:
                                    filler = random.choice(FILLERS)
                                    logger.info(f"[{conversation.call_sid}] 🕐 OpenAI slow, sending filler: {filler}")
                                    filler_sent = True
                                    try:
                                        await send_audio_chunks(
                                            synthesize_to_mulaw_chunks(filler),
                                            check_interrupt=True,
                                        )
                                    except Exception:
                                        pass
                                # Now wait without timeout for the actual response
                                sentence = await sentence_iter.__anext__()
                        else:
                            sentence = await sentence_iter.__anext__()
                    except StopAsyncIteration:
                        break

                    if interrupted.is_set():
                        break

                    full_response_parts.append(sentence)

                    if first_sentence:
                        t_first = time.time()
                        logger.info(f"[{conversation.call_sid}] ⏱️ First sentence in {t_first - t_start:.2f}s")
                        first_sentence = False

                    # Stream this sentence to TTS → Twilio (skip on ElevenLabs failure)
                    try:
                        completed = await send_audio_chunks(
                            synthesize_to_mulaw_chunks(sentence),
                            check_interrupt=True,
                        )
                        if not completed:
                            break
                    except Exception as e:
                        logger.warning(f"[{conversation.call_sid}] TTS failed for sentence, skipping: {e}")
                        continue

                # Send end mark
                if not interrupted.is_set():
                    await ws.send_text(build_mark_message(stream_sid, "speech_end"))

            except Exception as e:
                logger.error(f"Pipeline error: {e}")
            finally:
                is_speaking = False
                full_response = " ".join(full_response_parts)
                if full_response:
                    conversation.add_assistant_message(full_response)
                    t_end = time.time()
                    logger.info(f"[{conversation.call_sid}] ⏱️ Full response in {t_end - t_start:.2f}s")

    async def handle_transcripts(dg: DeepgramSTT) -> None:
        async for transcript in dg.receive_transcripts():
            if transcript and conversation and conversation.is_active:
                await process_transcript(transcript)

    async def send_greeting() -> None:
        nonlocal is_speaking
        if not conversation or not stream_sid:
            return
        conversation.add_assistant_message(SOFIA_GREETING)
        is_speaking = True
        try:
            await send_audio_chunks(synthesize_to_mulaw_chunks(SOFIA_GREETING), check_interrupt=False)
            await ws.send_text(build_mark_message(stream_sid, "greeting_end"))
            logger.info(f"[{conversation.call_sid}] ✅ Greeting sent")
        except Exception as e:
            logger.error(f"Greeting error: {e}")
        finally:
            is_speaking = False

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

            elif event == "mark":
                mark_name = data.get("mark", {}).get("name", "")
                logger.debug(f"📍 Mark received: {mark_name}")

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
            logger.info(
                f"📊 Call {conversation.call_sid} ended after "
                f"{conversation.duration_seconds:.1f}s, "
                f"{len(conversation.messages)} messages"
            )
            if len(conversation.messages) > 4:
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
