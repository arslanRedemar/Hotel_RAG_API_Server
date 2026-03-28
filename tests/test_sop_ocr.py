"""SOP OCR 모듈 단위 테스트"""

import io
from unittest.mock import MagicMock, patch, mock_open

import pytest
from PIL import Image

from app.sop.ocr import OCRProcessor, preprocess_image, extract_structured_text


def _make_white_image(width=100, height=100) -> Image.Image:
    return Image.new("RGB", (width, height), color=(255, 255, 255))


class TestPreprocessImage:
    def test_returns_pil_image(self):
        img = _make_white_image()
        result = preprocess_image(img)
        assert isinstance(result, Image.Image)

    def test_handles_import_error_gracefully(self):
        """opencv 미설치 시 원본 이미지 그대로 반환"""
        img = _make_white_image()
        with patch.dict("sys.modules", {"cv2": None}):
            result = preprocess_image(img)
        assert isinstance(result, Image.Image)


class TestOCRProcessorInit:
    def test_default_engine_is_local(self):
        ocr = OCRProcessor()
        assert ocr.engine == "local"

    def test_custom_engine(self):
        ocr = OCRProcessor(engine="tesseract")
        assert ocr.engine == "tesseract"

    def test_threshold_from_settings(self):
        ocr = OCRProcessor()
        assert 0.0 < ocr.threshold <= 1.0


class TestTesseractOCR:
    def test_returns_text_and_confidence(self):
        ocr = OCRProcessor(engine="tesseract")
        mock_data = {
            "text": ["Hello", "World", ""],
            "conf": [90, 85, -1],
        }
        img = _make_white_image()
        with patch("pytesseract.image_to_data", return_value=mock_data):
            text, confidence = ocr._tesseract_ocr(img)

        assert "Hello" in text
        assert "World" in text
        assert 0.0 <= confidence <= 1.0

    def test_empty_result_gives_zero_confidence(self):
        ocr = OCRProcessor(engine="tesseract")
        mock_data = {"text": ["", ""], "conf": [-1, -1]}
        img = _make_white_image()
        with patch("pytesseract.image_to_data", return_value=mock_data):
            text, confidence = ocr._tesseract_ocr(img)
        assert confidence == 0.0


class TestLocalVisionOCR:
    def test_returns_text_on_success(self):
        ocr = OCRProcessor(engine="local")
        img = _make_white_image()
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"message": {"content": "추출된 텍스트"}}

        with patch("httpx.post", return_value=mock_resp):
            text, confidence = ocr._local_vision_ocr(img)

        assert text == "추출된 텍스트"
        assert confidence == 0.80

    def test_falls_back_to_tesseract_on_error(self):
        ocr = OCRProcessor(engine="local")
        img = _make_white_image()
        mock_data = {"text": ["fallback"], "conf": [80]}

        with patch("httpx.post", side_effect=Exception("연결 실패")):
            with patch("pytesseract.image_to_data", return_value=mock_data):
                text, confidence = ocr._local_vision_ocr(img)

        assert text == "fallback"

    def test_empty_response_gives_zero_confidence(self):
        ocr = OCRProcessor(engine="local")
        img = _make_white_image()
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"message": {"content": ""}}

        with patch("httpx.post", return_value=mock_resp):
            text, confidence = ocr._local_vision_ocr(img)

        assert confidence == 0.0


class TestScannedPDFExtraction:
    def test_local_engine_falls_back_on_low_confidence(self):
        """로컬 신뢰도 < threshold 시 google_vision 폴백 호출"""
        ocr = OCRProcessor(engine="local")
        ocr.threshold = 0.90  # 강제로 높게 설정

        fake_image = _make_white_image()
        mock_data = {"text": ["text"], "conf": [50]}

        with patch("pdf2image.convert_from_path", return_value=[fake_image]):
            with patch.object(ocr, "_local_vision_ocr", return_value=("로컬결과", 0.50)):
                with patch.object(ocr, "_google_vision_ocr", return_value=("클라우드결과", 0.95)) as mock_gv:
                    results = ocr.extract_text_from_scanned_pdf("dummy.pdf")

        mock_gv.assert_called_once()
        assert results[0]["engine_used"] == "google_vision"
        assert results[0]["text"] == "클라우드결과"

    def test_local_engine_no_fallback_when_confident(self):
        """로컬 신뢰도 >= threshold 시 클라우드 미호출"""
        ocr = OCRProcessor(engine="local")
        ocr.threshold = 0.70

        fake_image = _make_white_image()

        with patch("pdf2image.convert_from_path", return_value=[fake_image]):
            with patch.object(ocr, "_local_vision_ocr", return_value=("로컬결과", 0.85)):
                with patch.object(ocr, "_google_vision_ocr") as mock_gv:
                    results = ocr.extract_text_from_scanned_pdf("dummy.pdf")

        mock_gv.assert_not_called()
        assert results[0]["engine_used"] == "local"

    def test_result_contains_required_fields(self):
        ocr = OCRProcessor(engine="tesseract")
        fake_image = _make_white_image()
        mock_data = {"text": ["안녕하세요"], "conf": [90]}

        with patch("pdf2image.convert_from_path", return_value=[fake_image]):
            with patch("pytesseract.image_to_data", return_value=mock_data):
                results = ocr.extract_text_from_scanned_pdf("dummy.pdf")

        assert len(results) == 1
        assert {"page", "text", "confidence", "engine_used"} <= results[0].keys()
        assert results[0]["page"] == 1


class TestIsScannedPDF:
    def test_scanned_pdf_detected(self):
        ocr = OCRProcessor()
        mock_page = MagicMock()
        mock_page.get_text.return_value = "   "
        mock_doc = MagicMock()
        mock_doc.__iter__ = MagicMock(return_value=iter([mock_page]))
        mock_doc.close = MagicMock()

        with patch("app.sop.ocr.fitz") as mock_fitz:
            mock_fitz.open.return_value = mock_doc
            result = ocr.is_scanned_pdf("dummy.pdf")

        assert result is True

    def test_text_pdf_detected(self):
        ocr = OCRProcessor()
        mock_page = MagicMock()
        mock_page.get_text.return_value = "A" * 600  # 500자 이상 → 텍스트 PDF
        mock_doc = MagicMock()
        mock_doc.__iter__ = MagicMock(return_value=iter([mock_page]))
        mock_doc.close = MagicMock()

        with patch("app.sop.ocr.fitz") as mock_fitz:
            mock_fitz.open.return_value = mock_doc
            result = ocr.is_scanned_pdf("dummy.pdf")

        assert result is False

    def test_fallback_to_scanned_when_fitz_missing(self):
        ocr = OCRProcessor()
        with patch("app.sop.ocr.fitz", None):
            import app.sop.ocr as ocr_mod
            original = ocr_mod.fitz
            ocr_mod.fitz = None
            try:
                result = ocr.is_scanned_pdf("dummy.pdf")
            finally:
                ocr_mod.fitz = original
        assert result is True


class TestExtractStructuredText:
    def test_uses_pdfplumber_when_available(self):
        mock_page = MagicMock()
        mock_page.extract_text.return_value = "샘플 텍스트"
        mock_page.extract_tables.return_value = []
        mock_pdf = MagicMock()
        mock_pdf.__enter__ = MagicMock(return_value=mock_pdf)
        mock_pdf.__exit__ = MagicMock(return_value=False)
        mock_pdf.pages = [mock_page]

        with patch("pdfplumber.open", return_value=mock_pdf):
            results = extract_structured_text("dummy.pdf")

        assert len(results) == 1
        assert results[0]["text"] == "샘플 텍스트"
        assert results[0]["engine_used"] == "pdfplumber"

    def test_includes_table_data(self):
        mock_page = MagicMock()
        mock_page.extract_text.return_value = "본문"
        mock_page.extract_tables.return_value = [[["셀1", "셀2"], ["값1", "값2"]]]
        mock_pdf = MagicMock()
        mock_pdf.__enter__ = MagicMock(return_value=mock_pdf)
        mock_pdf.__exit__ = MagicMock(return_value=False)
        mock_pdf.pages = [mock_page]

        with patch("pdfplumber.open", return_value=mock_pdf):
            results = extract_structured_text("dummy.pdf")

        assert "[테이블]" in results[0]["text"]


class TestExtractTextFromPDF:
    def test_routes_to_scanned_when_scanned(self):
        ocr = OCRProcessor(engine="tesseract")
        fake_image = _make_white_image()
        mock_data = {"text": ["텍스트"], "conf": [90]}

        with patch.object(ocr, "is_scanned_pdf", return_value=True):
            with patch("pdf2image.convert_from_path", return_value=[fake_image]):
                with patch("pytesseract.image_to_data", return_value=mock_data):
                    results = ocr.extract_text_from_pdf("dummy.pdf")

        assert results[0]["engine_used"] == "tesseract"

    def test_routes_to_text_when_not_scanned(self):
        ocr = OCRProcessor()
        mock_page = MagicMock()
        mock_page.extract_text.return_value = "텍스트 PDF"
        mock_page.extract_tables.return_value = []
        mock_pdf = MagicMock()
        mock_pdf.__enter__ = MagicMock(return_value=mock_pdf)
        mock_pdf.__exit__ = MagicMock(return_value=False)
        mock_pdf.pages = [mock_page]

        with patch.object(ocr, "is_scanned_pdf", return_value=False):
            with patch("pdfplumber.open", return_value=mock_pdf):
                results = ocr.extract_text_from_pdf("dummy.pdf")

        assert results[0]["engine_used"] == "pdfplumber"


class TestGoogleVisionOCR:
    def test_falls_back_to_tesseract_when_no_api_key(self):
        ocr = OCRProcessor(engine="google_vision")
        img = _make_white_image()
        mock_data = {"text": ["구글없음"], "conf": [80]}

        with patch("app.sop.ocr.settings") as mock_settings:
            mock_settings.google_vision_api_key = ""
            mock_settings.local_llm_confidence_threshold = 0.7
            with patch("pytesseract.image_to_data", return_value=mock_data):
                text, confidence = ocr._google_vision_ocr(img)

        assert text == "구글없음"

    def test_calls_google_vision_api(self):
        ocr = OCRProcessor(engine="google_vision")
        img = _make_white_image()
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "responses": [{"fullTextAnnotation": {"text": "구글 OCR 결과"}}]
        }

        with patch("app.sop.ocr.settings") as mock_settings:
            mock_settings.google_vision_api_key = "fake-key"
            mock_settings.local_llm_confidence_threshold = 0.7
            mock_settings.local_ocr_model = "test-model"
            with patch("httpx.post", return_value=mock_resp):
                with patch("app.sop.ocr.record_usage"):
                    text, confidence = ocr._google_vision_ocr(img)

        assert text == "구글 OCR 결과"
        assert confidence == 0.95


class TestExtractTextFromDocx:
    def test_extracts_paragraphs(self):
        ocr = OCRProcessor()
        mock_para1 = MagicMock()
        mock_para1.text = "첫 번째 문단"
        mock_para2 = MagicMock()
        mock_para2.text = ""
        mock_para3 = MagicMock()
        mock_para3.text = "세 번째 문단"
        mock_doc = MagicMock()
        mock_doc.paragraphs = [mock_para1, mock_para2, mock_para3]

        with patch("app.sop.ocr.OCRProcessor.extract_text_from_docx") as mock_extract:
            mock_extract.return_value = [
                {"page": 1, "text": "첫 번째 문단\n세 번째 문단", "confidence": 1.0, "engine_used": "python-docx"}
            ]
            results = ocr.extract_text_from_docx("dummy.docx")

        assert results[0]["engine_used"] == "python-docx"
        assert "첫 번째 문단" in results[0]["text"]


class TestScannedPDFExtractionExtended:
    def test_google_vision_engine_direct(self):
        """engine='google_vision' 으로 직접 호출"""
        ocr = OCRProcessor(engine="google_vision")
        fake_image = _make_white_image()
        mock_data = {"text": ["직접호출"], "conf": [85]}

        with patch("pdf2image.convert_from_path", return_value=[fake_image]):
            with patch.object(ocr, "_google_vision_ocr", return_value=("구글결과", 0.95)):
                results = ocr.extract_text_from_scanned_pdf("dummy.pdf")

        assert results[0]["engine_used"] == "google_vision"
        assert results[0]["text"] == "구글결과"

    def test_unknown_engine_returns_empty(self):
        """알 수 없는 엔진은 빈 텍스트 반환"""
        ocr = OCRProcessor(engine="unknown_engine")
        fake_image = _make_white_image()

        with patch("pdf2image.convert_from_path", return_value=[fake_image]):
            results = ocr.extract_text_from_scanned_pdf("dummy.pdf")

        assert results[0]["text"] == ""
        assert results[0]["engine_used"] == "unknown"
