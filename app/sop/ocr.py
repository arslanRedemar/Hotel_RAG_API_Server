"""OCR 처리 모듈 — 로컬 비전 모델 우선, 저신뢰도 시 클라우드 폴백 (SOP-F06)"""

import base64
import io
import logging
from pathlib import Path

import httpx
import pytesseract
from PIL import Image

from app.core.config import settings
from app.core.cost_monitor import record_usage

try:
    import fitz  # PyMuPDF
except ImportError:
    fitz = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)


# ── 이미지 전처리 ────────────────────────────────────────────


def preprocess_image(pil_image: Image.Image) -> Image.Image:
    """OCR 정확도 향상을 위한 이미지 전처리 (그레이스케일 → 이진화 → 기울기 보정)"""
    try:
        import cv2
        import numpy as np

        img = cv2.cvtColor(np.array(pil_image), cv2.COLOR_RGB2BGR)
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        denoised = cv2.GaussianBlur(gray, (3, 3), 0)
        _, binary = cv2.threshold(denoised, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

        # 기울기 보정
        coords = np.column_stack(np.where(binary < 128))
        if len(coords) > 100:
            angle = cv2.minAreaRect(coords)[-1]
            angle = -(90 + angle) if angle < -45 else -angle
            if abs(angle) > 0.5:
                h, w = binary.shape
                M = cv2.getRotationMatrix2D((w // 2, h // 2), angle, 1.0)
                binary = cv2.warpAffine(
                    binary, M, (w, h),
                    flags=cv2.INTER_CUBIC,
                    borderMode=cv2.BORDER_REPLICATE,
                )

        # 해상도 업스케일 (작은 폰트 대응)
        h, w = binary.shape
        binary = cv2.resize(
            binary,
            (int(w * 1.5), int(h * 1.5)),
            interpolation=cv2.INTER_CUBIC,
        )
        return Image.fromarray(binary)

    except ImportError:
        logger.warning("opencv-python-headless 미설치. 전처리를 건너뜁니다.")
        return pil_image


# ── 텍스트 PDF 구조적 추출 ───────────────────────────────────


def extract_structured_text(file_path: str) -> list[dict]:
    """텍스트 PDF에서 테이블 포함 구조적 텍스트 추출 (pdfplumber)"""
    try:
        import pdfplumber
    except ImportError:
        logger.warning("pdfplumber 미설치. PyPDF 폴백 사용.")
        return _extract_text_pypdf(file_path)

    results = []
    with pdfplumber.open(file_path) as pdf:
        for page_num, page in enumerate(pdf.pages, start=1):
            text = page.extract_text() or ""
            tables = page.extract_tables() or []

            table_texts = []
            for table in tables:
                rows = [
                    " | ".join(cell if cell else "" for cell in row)
                    for row in table
                    if table
                ]
                table_texts.append("\n".join(rows))

            combined = text
            if table_texts:
                combined += "\n\n[테이블]\n" + "\n\n".join(table_texts)

            results.append({
                "page": page_num,
                "text": combined,
                "confidence": 1.0,
                "engine_used": "pdfplumber",
            })
    return results


def _extract_text_pypdf(file_path: str) -> list[dict]:
    from pypdf import PdfReader
    reader = PdfReader(file_path)
    return [
        {
            "page": i + 1,
            "text": page.extract_text() or "",
            "confidence": 1.0,
            "engine_used": "pypdf",
        }
        for i, page in enumerate(reader.pages)
    ]


# ── OCRProcessor ─────────────────────────────────────────────


class OCRProcessor:
    """SOP-F06: 로컬 비전 모델 우선, 신뢰도 미달 시 클라우드 폴백.

    engine 선택:
    - "local"        : Ollama 로컬 비전 모델 (기본값)
    - "tesseract"    : pytesseract
    - "google_vision": Google Vision API
    """

    def __init__(self, engine: str = "local") -> None:
        self.engine = engine
        self.threshold = settings.local_llm_confidence_threshold

    # ── 공개 메서드 ───────────────────────────────────────────

    def is_scanned_pdf(self, file_path: str) -> bool:
        """PDF 텍스트 레이어 유무 확인 — 텍스트 500자 미만이면 스캔 PDF로 판정"""
        if fitz is None:
            logger.warning("PyMuPDF 미설치. 스캔 PDF로 가정합니다.")
            return True
        doc = fitz.open(file_path)
        text = "".join(page.get_text() for page in doc)
        doc.close()
        return len(text.strip()) < 500

    def extract_text_from_pdf(self, file_path: str) -> list[dict]:
        """PDF 유형 자동 판별 후 적절한 추출 방법 선택"""
        if self.is_scanned_pdf(file_path):
            logger.info("스캔 PDF 감지 → OCR 처리: %s", file_path)
            return self.extract_text_from_scanned_pdf(file_path)
        logger.info("텍스트 PDF 감지 → 직접 추출: %s", file_path)
        return extract_structured_text(file_path)

    def extract_text_from_scanned_pdf(self, file_path: str) -> list[dict]:
        """스캔 PDF를 이미지로 변환 후 OCR 처리.

        반환: [{"page": 1, "text": "...", "confidence": 0.95, "engine_used": "local"}, ...]
        """
        try:
            import pdf2image
        except ImportError as e:
            raise RuntimeError("pdf2image 미설치. pip install pdf2image") from e

        images = pdf2image.convert_from_path(file_path, dpi=300)
        results = []

        for page_num, raw_image in enumerate(images, start=1):
            image = preprocess_image(raw_image)

            if self.engine == "local":
                text, confidence = self._local_vision_ocr(raw_image)
                engine_used = "local"
                if confidence < self.threshold:
                    logger.info(
                        "OCR 신뢰도 낮음(%.2f) → 클라우드 폴백 (페이지 %d)",
                        confidence, page_num,
                    )
                    text, confidence = self._google_vision_ocr(raw_image)
                    engine_used = "google_vision"
            elif self.engine == "tesseract":
                text, confidence = self._tesseract_ocr(image)
                engine_used = "tesseract"
            elif self.engine == "google_vision":
                text, confidence = self._google_vision_ocr(raw_image)
                engine_used = "google_vision"
            else:
                text, confidence, engine_used = "", 0.0, "unknown"

            results.append({
                "page": page_num,
                "text": text,
                "confidence": round(confidence, 3),
                "engine_used": engine_used,
            })

        return results

    def extract_text_from_docx(self, file_path: str) -> list[dict]:
        """DOCX 텍스트 추출"""
        from docx import Document as DocxDocument
        doc = DocxDocument(file_path)
        text = "\n".join(p.text for p in doc.paragraphs if p.text.strip())
        return [{"page": 1, "text": text, "confidence": 1.0, "engine_used": "python-docx"}]

    # ── 내부 OCR 메서드 ───────────────────────────────────────

    def _local_vision_ocr(self, image: Image.Image) -> tuple[str, float]:
        """Ollama 로컬 비전 모델 호출 (DeepSeek-VL2 / GOT-OCR2)"""
        buf = io.BytesIO()
        image.save(buf, format="PNG")
        img_b64 = base64.b64encode(buf.getvalue()).decode()

        payload = {
            "model": settings.local_ocr_model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/png;base64,{img_b64}"},
                        },
                        {
                            "type": "text",
                            "text": "이 이미지의 텍스트를 정확히 추출하세요. 원본 형식(줄바꿈, 번호 등)을 최대한 유지하세요.",
                        },
                    ],
                }
            ],
            "stream": False,
        }
        try:
            resp = httpx.post(
                f"{settings.local_llm_endpoint}/api/chat",
                json=payload,
                timeout=60,
            )
            resp.raise_for_status()
            text = resp.json().get("message", {}).get("content", "")
            confidence = 0.80 if text.strip() else 0.0
            return text, confidence
        except Exception as exc:
            logger.warning("로컬 OCR 실패 (%s) → tesseract 폴백", exc)
            return self._tesseract_ocr(image)

    def _tesseract_ocr(self, image: Image.Image) -> tuple[str, float]:
        data = pytesseract.image_to_data(
            image, lang="kor+eng", output_type=pytesseract.Output.DICT
        )
        text = " ".join(w for w in data["text"] if w.strip())
        conf_values = [c for c in data["conf"] if c != -1]
        confidence = sum(conf_values) / len(conf_values) / 100 if conf_values else 0.0
        return text, confidence

    def _google_vision_ocr(self, image: Image.Image) -> tuple[str, float]:
        """Google Vision API OCR (SOP-F06 클라우드 폴백)"""
        if not settings.google_vision_api_key:
            logger.warning("GOOGLE_VISION_API_KEY 미설정 → tesseract 폴백")
            return self._tesseract_ocr(image)

        buf = io.BytesIO()
        image.save(buf, format="PNG")
        img_b64 = base64.b64encode(buf.getvalue()).decode()

        url = f"https://vision.googleapis.com/v1/images:annotate?key={settings.google_vision_api_key}"
        body = {
            "requests": [{
                "image": {"content": img_b64},
                "features": [{"type": "DOCUMENT_TEXT_DETECTION"}],
            }]
        }
        try:
            resp = httpx.post(url, json=body, timeout=30)
            resp.raise_for_status()
            annotation = resp.json()["responses"][0].get("fullTextAnnotation", {})
            text = annotation.get("text", "")
            confidence = 0.95 if text else 0.0
            record_usage(module="sop_ocr", prompt_tokens=0, completion_tokens=0, model="gpt-4o-mini")
            return text, confidence
        except Exception as exc:
            logger.error("Google Vision OCR 실패: %s", exc)
            return "", 0.0
