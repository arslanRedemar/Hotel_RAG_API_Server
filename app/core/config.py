from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # ===== 서버 =====
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    debug: bool = True
    hotel_name: str = "Hotel"

    # ===== OpenAI =====
    openai_api_key: str

    # ===== Vector Store =====
    chroma_persist_dir: str = "./data/chroma_db"

    # ===== RAG 파라미터 =====
    chunk_size: int = 500
    chunk_overlap: int = 50
    top_k_results: int = 5
    llm_model: str = "gpt-4o-mini"
    embedding_model: str = "text-embedding-3-small"

    # ===== MySQL =====
    mysql_url: str = "mysql+pymysql://root:password@localhost:3306/hotel_rag"

    # ===== Redis =====
    redis_url: str = "redis://localhost:6379/0"

    # ===== 보안 (JWT) =====
    secret_key: str = "changeme-use-openssl-rand-hex-32"
    access_token_expire_minutes: int = 480   # 8시간
    refresh_token_expire_days: int = 7

    # ===== 파일 저장소 =====
    file_storage_path: str = "./data/uploads"

    # ===== 이메일 (SMTP) =====
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""

    # ===== Web Push (VAPID) =====
    vapid_private_key: str = ""
    vapid_public_key: str = ""

    # ===== PMS 연동 =====
    pms_base_url: str = ""
    pms_api_key: str = ""

    # ===== OCR =====
    google_vision_api_key: str = ""

    # ===== 수익 관리 =====
    total_rooms: int = 200

    class Config:
        env_file = ".env"


settings = Settings()
