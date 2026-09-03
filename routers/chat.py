import json
import logging
import uuid

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from services import llm_client
from services.llm_client import LLMConnectionError

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1")

# เก็บแค่ในหน่วยความจำ: รีสตาร์ทเซิร์ฟเวอร์แล้วหายหมด และไม่ scale ข้ามหลาย process
# ถ้าจะทำ production จริงควรย้ายไป Redis หรือฐานข้อมูลแทน
#
# ค่าที่เก็บคือ "ประวัติข้อความทั้งหมด" ต่อ session (list ของ {role, content})
# ไม่ใช่ previous_response_id แบบเดิมอีกแล้ว เพราะ Chat Completions API เป็นแบบ
# stateless ผู้ให้บริการไม่จำบทสนทนาให้ ต้องส่ง history ทั้งหมดไปเองทุกครั้ง
# (ดูเหตุผลเพิ่มเติมที่ services/llm_client.py::_build_messages)
conversation_store: dict[str, list[dict[str, str]]] = {}

SESSION_COOKIE = "session_id"
SESSION_MAX_AGE = 60 * 60 * 24 * 7  # 7 วัน


def _ensure_session(session_id: str | None) -> tuple[str, bool]:
    """คืนค่า (session_id, is_new) ถ้าเป็น session ใหม่จะสร้างประวัติบทสนทนาว่างให้ด้วย"""
    if session_id and session_id in conversation_store:
        return session_id, False
    new_id = str(uuid.uuid4())
    conversation_store[new_id] = []
    return new_id, True


def _set_session_cookie(response: Response, session_id: str) -> None:
    response.set_cookie(
        key=SESSION_COOKIE,
        value=session_id,
        httponly=True,
        samesite="lax",
        max_age=SESSION_MAX_AGE,
    )


class ChatRequest(BaseModel):
    message: str


class ChatResponse(BaseModel):
    reply: str


@router.get("/models")
async def get_models():
    # เลียนแบบ proxy pattern: ไม่ส่ง API key ออกไปให้ frontend เห็นเด็ดขาด และตอน
    # error ก็ตอบ 200 พร้อม {"error": ...} แทนการโยน HTTPException ตรงๆ
    try:
        models = await llm_client.list_models()
        return {"models": models}
    except LLMConnectionError as exc:
        logger.warning("ไม่สามารถดึงรายชื่อโมเดลได้: %s", exc.message)
        return JSONResponse(status_code=200, content={"error": True, "message": exc.message})


@router.post("/chat/reset")
async def post_chat_reset(request: Request, response: Response):
    """ล้างประวัติบทสนทนาของ session นี้ โดยไม่ออก session_id ใหม่ — เบื้องหลังปุ่ม
    "เริ่มใหม่" (Usability Heuristic: User Control & Freedom) ผู้ใช้ได้เริ่มคุยใหม่
    ทั้งหมด แต่ cookie เดิมยังใช้ต่อได้ ไม่ต้องออก cookie ใหม่"""
    session_id, is_new = _ensure_session(request.cookies.get(SESSION_COOKIE))
    if is_new:
        _set_session_cookie(response, session_id)
    conversation_store[session_id] = []
    return {"ok": True}


@router.post("/chat", response_model=ChatResponse)
async def post_chat(chat_request: ChatRequest, request: Request, response: Response):
    session_id, is_new = _ensure_session(request.cookies.get(SESSION_COOKIE))
    if is_new:
        _set_session_cookie(response, session_id)
    history = conversation_store.get(session_id, [])

    try:
        reply_text = await llm_client.chat(history, chat_request.message)
    except LLMConnectionError as exc:
        logger.error("chat ล้มเหลว session=%s: %s", session_id, exc.message)
        return JSONResponse(status_code=502, content={"error": True, "message": exc.message})

    # ต่อประวัติด้วยข้อความรอบนี้ (ทั้งฝั่งผู้ใช้และ AI) เก็บไว้ใช้เป็น context รอบถัดไป
    conversation_store[session_id] = history + [
        {"role": "user", "content": chat_request.message},
        {"role": "assistant", "content": reply_text},
    ]
    return ChatResponse(reply=reply_text)


@router.post("/chat/stream")
async def post_chat_stream(chat_request: ChatRequest, request: Request):
    session_id, is_new = _ensure_session(request.cookies.get(SESSION_COOKIE))
    history = conversation_store.get(session_id, [])

    async def event_generator():
        received_done = False
        accumulated_text = ""
        try:
            async for event in llm_client.chat_stream(history, chat_request.message):
                if event["type"] == "delta":
                    accumulated_text += event["content"]
                    payload = {"delta": event["content"]}
                elif event["type"] == "error":
                    logger.error("stream error session=%s: %s", session_id, event["message"])
                    payload = {"error": True, "message": event["message"]}
                elif event["type"] == "done":
                    received_done = True
                    payload = {"done": True}
                else:
                    continue
                yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
        except Exception as exc:  
            logger.exception("stream ล้มเหลวโดยไม่คาดคิด session=%s", session_id)
            payload = {"error": True, "message": f"เกิดข้อผิดพลาดที่ไม่คาดคิด: {exc}"}
            yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
        finally:
            # บันทึกประวัติเฉพาะตอนสตรีมจบแบบสมบูรณ์ (received_done) เท่านั้น ถ้าโดน
            # ตัดกลางทางหรือผู้ใช้กด "หยุด" เอง จะไม่เก็บคำตอบครึ่งๆ กลางๆ ไว้เป็น
            # context ต่อ กันบทสนทนารอบถัดไปสับสนจากคำตอบที่ไม่สมบูรณ์
            if accumulated_text and received_done:
                conversation_store[session_id] = history + [
                    {"role": "user", "content": chat_request.message},
                    {"role": "assistant", "content": accumulated_text},
                ]
            if not received_done:
                yield f"data: {json.dumps({'done': True}, ensure_ascii=False)}\n\n"

    resp = StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
    if is_new:
        _set_session_cookie(resp, session_id)
    return resp
