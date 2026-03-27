FROM python:3.13-slim

WORKDIR /app

# 시스템 의존성 (PyMySQL은 순수 Python이므로 별도 빌드 도구 불필요)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# 의존성 먼저 복사 (레이어 캐시 활용)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 소스 복사
COPY . .

# 문서 및 벡터 DB 저장 디렉토리
RUN mkdir -p data/docs data/chroma_db

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
