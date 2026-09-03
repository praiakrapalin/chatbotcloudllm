import logging
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from routers.chat import router as chat_router

# หาโฟลเดอร์ static/templates จาก path ของไฟล์นี้เอง แทนที่จะพึ่ง current working
# directory ตอนรัน เพราะบน serverless (เช่น Vercel) ไม่การันตีว่า process จะเริ่ม
# ทำงานจาก root ของโปรเจกต์เสมอไป
BASE_DIR = Path(__file__).resolve().parent

# ตั้ง logging กลางไว้ตั้งแต่จุดเริ่มโปรแกรม เพื่อให้ log จากทุกโมดูล (routers, services)
# ออกมาในฟอร์แมตเดียวกันหมด แทนที่จะต้องตั้งซ้ำในแต่ละไฟล์
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
)

app = FastAPI(
    title="AI Chatbot",
    description="Chatbot ที่คุยกับโมเดล AI ผ่าน OpenAI-compatible Chat Completions API",
    version="0.1.0",
)

# เปิด CORS แบบกว้าง ("*") เพราะเป็นโปรเจกต์ทดลอง/รันในเครื่องเท่านั้น ไม่มี
# frontend แยกโดเมนจริงจังที่ต้องจำกัดสิทธิ์
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# เสิร์ฟไฟล์หน้าบ้าน (css/js) และ template ของหน้าแชทแบบ server-rendered เพียงหน้าเดียว
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")

app.include_router(chat_router)


@app.get("/")
async def index(request: Request):
    return templates.TemplateResponse(request, "index.html")


@app.get("/health")
async def health():
    # ใช้เช็คว่าเซิร์ฟเวอร์ยังรันอยู่เฉยๆ (ไม่ได้เช็คว่าคุยกับผู้ให้บริการ AI ได้ไหม)
    return {"status": "ok"}
