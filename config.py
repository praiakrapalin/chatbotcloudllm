from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """ค่าตั้งค่าทั้งหมดของแอปอ่านจากไฟล์ .env (ผ่าน pydantic-settings)
    ตัวแปรฝั่ง LLM ตั้งชื่อแบบกลางๆ ไม่ผูกกับผู้ให้บริการรายใดรายหนึ่ง เพราะโค้ดฝั่ง
    services/llm_client.py คุยด้วยฟอร์แมต OpenAI-compatible Chat Completions ซึ่งทั้ง
    LM Studio (รันในเครื่อง) และ OpenRouter (ออนไลน์) รองรับเหมือนกัน — ตอนจะย้ายจาก
    LM Studio ไป OpenRouter จึงแค่แก้ค่า 3 ตัวนี้ใน .env โดยไม่ต้องแตะโค้ดเลย
    """

    # ต้องรวม path เวอร์ชันไว้ในค่านี้ด้วย (เช่น http://127.0.0.1:1234/v1 หรือ
    # https://openrouter.ai/api/v1) เพราะโค้ดจะต่อ "/chat/completions" และ
    # "/models" เข้าไปเองตรงๆ ไม่มีการเดา path ให้
    LLM_BASE_URL: str
    LLM_API_KEY: str
    LLM_MODEL: str

    # ข้อความระบบที่ส่งเป็น role "system" ทุกครั้งที่เริ่มคุยกับโมเดล กำหนดโทนการตอบ
    SYSTEM_PROMPT: str = "คุณคือผู้ช่วย AI ที่เป็นมิตรและตอบเป็นภาษาไทย"

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )


settings = Settings()
