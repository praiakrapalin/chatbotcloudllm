import json
import logging
from collections.abc import AsyncGenerator
from typing import Any

import httpx

from config import settings

logger = logging.getLogger(__name__)

# connect: เวลาผูก TCP handshake, write: เวลาส่ง request, read: เวลารอโทเค็นตอบกลับ
# (ตั้งไว้นานเพราะโมเดลบางตัว โดยเฉพาะที่รันในเครื่องเอง ตอบช้า), pool: เวลารอ
# connection ว่างจาก connection pool
REQUEST_TIMEOUT = httpx.Timeout(connect=5.0, write=10.0, read=120.0, pool=5.0)


class LLMConnectionError(Exception):
    """โยนทุกครั้งที่คุยกับผู้ให้บริการ LLM ไม่สำเร็จ พร้อมข้อความภาษาไทยที่ปลอดภัย
    พอจะส่งกลับไปแสดงให้ผู้ใช้เห็นตรงๆ ได้เลย (ไม่หลุด stack trace หรือรายละเอียดภายใน)"""

    def __init__(self, message: str, status_code: int = 502):
        self.message = message
        self.status_code = status_code
        super().__init__(message)


def _auth_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {settings.LLM_API_KEY}"}


def _build_messages(history: list[dict[str, str]], message: str) -> list[dict[str, str]]:
    """ประกอบ payload แบบ Chat Completions มาตรฐาน (messages: [{role, content}])
    เพราะ endpoint นี้เป็น endpoint เดียวที่ทั้ง LM Studio และ OpenRouter รองรับ
    เหมือนกัน ต่างจาก Native API v1 เดิมของ LM Studio (input + previous_response_id)
    ที่ผูกติดกับ LM Studio เท่านั้นและใช้กับ OpenRouter ไม่ได้

    API แบบนี้เป็น stateless คือผู้ให้บริการไม่จำบทสนทนาให้ ต้องส่ง history
    ทั้งหมดที่คุยกันมาไปพร้อมกับข้อความใหม่ทุกครั้ง (history มาจาก conversation_store
    ฝั่ง router ซึ่งเก็บแยกตาม session)
    """
    messages: list[dict[str, str]] = []
    if settings.SYSTEM_PROMPT:
        messages.append({"role": "system", "content": settings.SYSTEM_PROMPT})
    messages.extend(history)
    messages.append({"role": "user", "content": message})
    return messages


def _friendly_error_from_response(exc: httpx.HTTPStatusError) -> LLMConnectionError:
    # แปลง error code มาตรฐานจาก HTTP ให้เป็นข้อความไทยที่เข้าใจง่าย แทนที่จะโชว์
    # JSON error ดิบๆ จากผู้ให้บริการให้ผู้ใช้เห็น
    status = exc.response.status_code
    try:
        body = exc.response.json()
        detail = body.get("error", {}).get("message", "")
    except (ValueError, AttributeError):
        detail = exc.response.text

    if status == 401:
        message = "เชื่อมต่อไม่สำเร็จ: API key ไม่ถูกต้องหรือหมดอายุ กรุณาตรวจสอบค่า LLM_API_KEY"
    elif status == 400:
        message = f"คำขอไม่ถูกต้อง: {detail}" if detail else "คำขอไม่ถูกต้อง"
    elif status == 404:
        message = f"ไม่พบโมเดลนี้: {detail}" if detail else "ไม่พบโมเดลที่ระบุ กรุณาตรวจสอบค่า LLM_MODEL"
    elif status == 429:
        message = "ถูกจำกัดอัตราการเรียกใช้งาน (rate limit) กรุณาลองใหม่อีกครั้งภายหลัง"
    elif status == 503:
        message = "ผู้ให้บริการ AI ไม่พร้อมให้บริการตอนนี้"
    else:
        message = f"ผู้ให้บริการ AI ตอบกลับด้วยข้อผิดพลาด ({status})"
    return LLMConnectionError(message, status_code=502)


async def list_models() -> list[dict[str, Any]]:
    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
        try:
            response = await client.get(
                f"{settings.LLM_BASE_URL}/models",
                headers=_auth_headers(),
            )
            response.raise_for_status()
        except httpx.ConnectError as exc:
            raise LLMConnectionError(
                "เชื่อมต่อผู้ให้บริการ AI ไม่ได้ กรุณาตรวจสอบว่าเปิดเซิร์ฟเวอร์ไว้และตั้งค่า LLM_BASE_URL ถูกต้อง"
            ) from exc
        except httpx.TimeoutException as exc:
            raise LLMConnectionError("ผู้ให้บริการ AI ตอบสนองช้าเกินไป (timeout)") from exc
        except httpx.HTTPStatusError as exc:
            raise _friendly_error_from_response(exc) from exc

        # เอนด์พอยต์ /models แบบ OpenAI-compatible คืนผลเป็น {"data": [...]}
        return response.json().get("data", [])


async def chat(history: list[dict[str, str]], message: str) -> str:
    """ส่งข้อความคุยหนึ่งรอบแบบไม่สตรีม คืนค่าข้อความตอบกลับ (reply_text) เพียงอย่างเดียว
    (ไม่มี response_id ให้คืนแล้ว เพราะ API นี้ไม่ได้เก็บ state ให้)"""
    payload: dict[str, Any] = {
        "model": settings.LLM_MODEL,
        "messages": _build_messages(history, message),
    }

    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
        try:
            response = await client.post(
                f"{settings.LLM_BASE_URL}/chat/completions",
                headers=_auth_headers(),
                json=payload,
            )
            response.raise_for_status()
        except httpx.ConnectError as exc:
            raise LLMConnectionError(
                "เชื่อมต่อผู้ให้บริการ AI ไม่ได้ กรุณาตรวจสอบว่าเปิดเซิร์ฟเวอร์ไว้และตั้งค่า LLM_BASE_URL ถูกต้อง"
            ) from exc
        except httpx.TimeoutException as exc:
            raise LLMConnectionError("ผู้ให้บริการ AI ตอบสนองช้าเกินไป (timeout)") from exc
        except httpx.HTTPStatusError as exc:
            raise _friendly_error_from_response(exc) from exc

        data = response.json()
        choices = data.get("choices", [])
        if not choices:
            return ""
        return choices[0].get("message", {}).get("content", "")


async def chat_stream(
    history: list[dict[str, str]], message: str
) -> AsyncGenerator[dict[str, Any], None]:
    """สตรีมคำตอบทีละชิ้นตามฟอร์แมต SSE มาตรฐานของ Chat Completions
    ส่งออกเป็น dict รูปแบบ:
    {"type": "delta", "content": str} | {"type": "error", "message": str} | {"type": "done"}
    (ไม่มี response_id เหมือนเดิมอีกแล้ว — ฝั่ง router เป็นคนรวบข้อความที่สตรีมมา
    แล้วเก็บเป็นประวัติเองแทน)
    """
    payload: dict[str, Any] = {
        "model": settings.LLM_MODEL,
        "messages": _build_messages(history, message),
        "stream": True,
    }

    try:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
            async with client.stream(
                "POST",
                f"{settings.LLM_BASE_URL}/chat/completions",
                headers=_auth_headers(),
                json=payload,
            ) as response_llm:
                if response_llm.status_code >= 400:
                    body = await response_llm.aread()
                    try:
                        detail = json.loads(body).get("error", {}).get("message", "")
                    except (ValueError, AttributeError):
                        detail = body.decode("utf-8", errors="ignore")
                    yield {
                        "type": "error",
                        "message": f"ผู้ให้บริการ AI ตอบกลับด้วยข้อผิดพลาด: {detail or response_llm.status_code}",
                    }
                    return

                async for line in response_llm.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    raw = line[len("data:"):].strip()
                    if not raw:
                        continue
                    # สตรีมแบบ OpenAI-compatible จบด้วยบรรทัด "data: [DONE]" ที่ไม่ใช่ JSON
                    if raw == "[DONE]":
                        yield {"type": "done"}
                        return
                    try:
                        event = json.loads(raw)
                    except ValueError:
                        logger.warning("ข้าม SSE data ที่ parse ไม่ได้: %r", raw)
                        continue

                    choices = event.get("choices", [])
                    if not choices:
                        continue
                    content = choices[0].get("delta", {}).get("content")
                    if content:
                        yield {"type": "delta", "content": content}
    except httpx.ConnectError:
        yield {
            "type": "error",
            "message": "เชื่อมต่อผู้ให้บริการ AI ไม่ได้ กรุณาตรวจสอบว่าเปิดเซิร์ฟเวอร์ไว้และตั้งค่า LLM_BASE_URL ถูกต้อง",
        }
    except httpx.TimeoutException:
        yield {"type": "error", "message": "ผู้ให้บริการ AI ตอบสนองช้าเกินไป (timeout)"}
    except httpx.HTTPError as exc:
        logger.exception("ข้อผิดพลาด httpx ที่ไม่คาดคิดระหว่างสตรีม")
        yield {"type": "error", "message": f"เกิดข้อผิดพลาดในการเชื่อมต่อ: {exc}"}
    except Exception as exc:
        logger.exception("ข้อผิดพลาดที่ไม่คาดคิดระหว่างสตรีม")
        yield {"type": "error", "message": f"เกิดข้อผิดพลาดที่ไม่คาดคิด: {exc}"}
