import io
from PIL import Image
import pymupdf

from app.services.ocr.engine import OCREngine
from app.services.ocr.image_processor import preprocess_image_for_ocr

MAX_PDF_PAGES = 10
RENDER_DPI = 150
TEXT_POOR_THRESHOLD = 50  # Characters
MAX_PDF_RENDER_DIMENSION = 4096
MAX_PDF_RENDER_PIXELS = 10_000_000  # 10 Megapixels max raster allocation per page


def process_pdf_bytes(
    pdf_bytes: bytes,
    ocr_engine: OCREngine,
    timeout_seconds: int = 15,
) -> tuple[str, int, list[str]]:
    """
    Extract text from PDF using native text extraction where available,
    falling back to rendered page OCR for scanned or text-poor pages.
    Enforces bounded page count and render limits.
    Returns: (combined_text, total_pages_detected, warnings)
    """
    if not pdf_bytes:
        raise ValueError("PDF data is empty.")

    warnings: list[str] = []

    try:
        doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    except Exception as e:
        raise ValueError(f"Corrupt or unreadable PDF document: {str(e)}")

    total_pages = len(doc)
    if total_pages == 0:
        doc.close()
        raise ValueError("PDF document contains no pages.")

    pages_to_process = min(total_pages, MAX_PDF_PAGES)
    if total_pages > MAX_PDF_PAGES:
        warnings.append(
            f"PDF contains {total_pages} pages; processing bounded to the first {MAX_PDF_PAGES} pages."
        )

    page_texts: list[str] = []
    scanned_pages_ocred = 0

    try:
        for page_idx in range(pages_to_process):
            page = doc[page_idx]
            native_text = page.get_text().strip()

            if len(native_text) >= TEXT_POOR_THRESHOLD:
                # Page contains usable native digital text
                page_texts.append(native_text)
            else:
                # Text-poor or scanned page: validate raster limits before rendering
                zoom = RENDER_DPI / 72.0
                rect = page.rect
                expected_width = int(rect.width * zoom)
                expected_height = int(rect.height * zoom)
                expected_pixels = expected_width * expected_height

                if expected_width <= 0 or expected_height <= 0:
                    raise ValueError(
                        f"PDF page {page_idx + 1} has invalid dimensions ({rect.width}x{rect.height} pt)."
                    )

                if (
                    expected_width > MAX_PDF_RENDER_DIMENSION
                    or expected_height > MAX_PDF_RENDER_DIMENSION
                    or expected_pixels > MAX_PDF_RENDER_PIXELS
                ):
                    raise ValueError(
                        f"PDF page {page_idx + 1} render dimensions ({expected_width}x{expected_height} = {expected_pixels}px) "
                        f"exceed safety limits (max dimension {MAX_PDF_RENDER_DIMENSION}px, max area {MAX_PDF_RENDER_PIXELS}px)."
                    )

                matrix = pymupdf.Matrix(zoom, zoom)
                pix = page.get_pixmap(matrix=matrix, alpha=False)

                # Convert pixmap to PIL Image
                mode = "RGB" if pix.n >= 3 else "L"
                img = Image.frombytes(mode, (pix.width, pix.height), pix.samples)

                # Preprocess and extract text via OCR adapter
                processed_img = preprocess_image_for_ocr(img)
                ocr_text = ocr_engine.extract_text_from_image(
                    processed_img, timeout_seconds=timeout_seconds
                )
                scanned_pages_ocred += 1

                combined_page = native_text + "\n" + ocr_text.strip() if native_text else ocr_text.strip()
                if combined_page.strip():
                    page_texts.append(combined_page.strip())
    except pymupdf.FileDataError as e:
        raise ValueError(f"Corrupt PDF structure encountered during page rendering: {str(e)}")
    except Exception as e:
        # Re-raise engine or value errors
        raise
    finally:
        doc.close()

    full_text = "\n\n".join(page_texts).strip()

    if scanned_pages_ocred > 0:
        warnings.append(f"Scanned page rendering and OCR performed on {scanned_pages_ocred} page(s).")

    if not full_text:
        warnings.append("No readable text could be extracted from this PDF document.")

    return full_text, total_pages, warnings
