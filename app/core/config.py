from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    debug: bool = True

    openai_api_key: str

    chroma_persist_dir: str = "./data/chroma_db"

    chunk_size: int = 500
    chunk_overlap: int = 50
    top_k_results: int = 5

    llm_model: str = "gpt-4o-mini"
    embedding_model: str = "text-embedding-3-small"

    # MySQL
    mysql_url: str = "mysql+pymysql://root:password@localhost:3306/hotel_rag"

    class Config:
        env_file = ".env"


settings = Settings()
