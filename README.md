# AI Chatbot (FastAPI + Vercel)

Chatbot ที่คุยกับโมเดล AI ผ่าน OpenAI-compatible Chat Completions API

## โครงสร้างโปรเจกต์

```
api/index.py        entrypoint ที่ Vercel เรียกใช้ (import app จาก main.py)
main.py             สร้าง FastAPI app, mount static/templates
config.py           อ่านค่าตั้งค่าจาก environment variables
routers/chat.py      endpoint ของ /api/v1/*
services/llm_client.py  โค้ดคุยกับผู้ให้บริการ LLM
static/, templates/  หน้าเว็บ (HTML/CSS/JS)
```

## รันในเครื่องตัวเอง

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env             # แล้วใส่ค่า LLM_API_KEY ของตัวเอง
uvicorn main:app --reload
```

เปิด http://127.0.0.1:8000

## ตั้งค่า .env

| ตัวแปร | ตัวอย่าง | หมายเหตุ |
|---|---|---|
| `LLM_BASE_URL` | `https://openrouter.ai/api/v1` | ต้องจบด้วย `/v1` |
| `LLM_API_KEY` | (จาก dashboard ผู้ให้บริการ) | อย่า commit ค่านี้ขึ้น git |
| `LLM_MODEL` | `openai/gpt-4o-mini` | ดูรายชื่อโมเดลได้จาก `/api/v1/models` ของแอปเอง |
| `SYSTEM_PROMPT` | (ข้อความ system prompt) | มีค่า default ให้แล้วถ้าไม่ตั้ง |

จะสลับไปใช้ LM Studio ที่รันในเครื่องแทนก็ได้ แค่ตั้ง `LLM_BASE_URL=http://127.0.0.1:1234/v1`
และเปิด LM Studio local server ไว้ — ไม่ต้องแก้โค้ดเลย

## Deploy ขึ้น Vercel

1. Push โค้ดนี้ขึ้น GitHub repo ของตัวเอง
2. เข้า https://vercel.com -> New Project -> เลือก repo นี้
3. ที่ Project Settings -> Environment Variables ใส่ `LLM_BASE_URL`, `LLM_API_KEY`,
   `LLM_MODEL`, `SYSTEM_PROMPT` (ค่าเดียวกับที่ตั้งใน `.env` ตอนรันในเครื่อง)
4. กด Deploy — Vercel จะอ่าน `vercel.json` แล้วรัน `api/index.py` เป็น serverless function ให้เอง

### ข้อจำกัดที่ควรรู้ (สำคัญสำหรับเอาไปต่อยอด)

`routers/chat.py` เก็บประวัติบทสนทนาไว้ใน dict ในหน่วยความจำของโปรเซส
(`conversation_store`) ซึ่ง**ใช้ได้ตอนรันในเครื่องเท่านั้น** บน Vercel ที่เป็น
serverless — แต่ละ request อาจไปตกที่ instance คนละตัว และ instance ถูกปิดทิ้งได้
ตลอดเวลา ทำให้ AI อาจ "ลืม" บทสนทนาก่อนหน้าแบบไม่สม่ำเสมอ

ถ้าจะทำให้จำบทสนทนาได้จริงบน Vercel ต้องย้าย `conversation_store` ไปเก็บที่
ภายนอกที่ทุก instance เข้าถึงร่วมกันได้ เช่น Vercel KV (Redis) หรือฐานข้อมูล
โดย key ยังใช้ `session_id` เดิมได้เลย — ส่วนนี้ตั้งใจปล่อยไว้ให้เป็นแบบฝึกหัด
