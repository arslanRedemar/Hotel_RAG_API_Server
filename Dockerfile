FROM python:3.11-slim

WORKDIR /app

# 시스템 의존성
# - tesseract-ocr: OCR 엔진 (SOP-F06)
# - poppler-utils: pdf2image 의존성
# - libgl1: OpenCV headless 의존성
# - curl: 헬스체크용
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    tesseract-ocr \
    tesseract-ocr-kor \
    poppler-utils \
    libgl1 \
    && rm -rf /var/lib/apt/lists/*

# 의존성 먼저 복사 (레이어 캐시 활용)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 소스 복사
COPY . .

# 데이터 디렉토리 생성
RUN mkdir -p data/docs data/chroma_db data/uploads

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
