import io
from PIL import Image, ImageEnhance, ImageFilter, ImageOps

from app.services.ocr.engine import OCREngine

MAX_IMAGE_DIMENSION = 4096
MAX_IMAGE_PIXELS = 10_000_000  # 10 Megapixels max
# Protect against decompression bomb attacks
Image.MAX_IMAGE_PIXELS = MAX_IMAGE_PIXELS


def validate_and_open_image(image_bytes: bytes) -> Image.Image:
    """
    Safely load image bytes into Pillow with strict dimension and decompression bomb bounds.
    Raises ValueError on malformed or corrupt images.
    """
    if not image_bytes:
        raise ValueError("Image data is empty.")

    try:
        img = Image.open(io.BytesIO(image_bytes))
        img.verify()  # Verify headers without full decode
    except Exception as e:
        raise ValueError(f"Malformed or unreadable image file: {str(e)}")

    # Re-open after verify() to load image pixels safely
    try:
        img = Image.open(io.BytesIO(image_bytes))
        width, height = img.size
        pixels = width * height
        if pixels > MAX_IMAGE_PIXELS:
            raise ValueError(
                f"Image dimensions ({width}x{height} = {pixels}px) exceed maximum limit of {MAX_IMAGE_PIXELS}px."
            )
        if width > MAX_IMAGE_DIMENSION or height > MAX_IMAGE_DIMENSION:
            raise ValueError(
                f"Image edge ({max(width, height)}px) exceeds maximum dimension {MAX_IMAGE_DIMENSION}px."
            )
        # Ensure image is loaded in memory
        img.load()
        return img
    except ValueError:
        raise
    except Exception as e:
        raise ValueError(f"Failed to decode image data: {str(e)}")


def preprocess_image_for_ocr(img: Image.Image) -> Image.Image:
    """
    Apply lightweight preprocessing to enhance OCR clarity:
    - Grayscale conversion
    - Contrast enhancement
    - Auto-invert if inverted (dark background with light text)
    - Resize if too small (minimum 300px on smallest side)
    """
    # Convert RGBA / P to RGB first, then to Grayscale
    if img.mode in ("RGBA", "LA", "P"):
        background = Image.new("RGB", img.size, (255, 255, 255))
        if img.mode == "P":
            img = img.convert("RGBA")
        background.paste(img, mask=img.split()[-1] if "A" in img.mode else None)
        gray = background.convert("L")
    else:
        gray = img.convert("L")

    # Scale up if very small for better character definition
    w, h = gray.size
    min_dim = min(w, h)
    if min_dim < 300 and min_dim > 0:
        scale_factor = 300 / min_dim
        new_w = min(int(w * scale_factor), MAX_IMAGE_DIMENSION)
        new_h = min(int(h * scale_factor), MAX_IMAGE_DIMENSION)
        gray = gray.resize((new_w, new_h), Image.Resampling.LANCZOS)

    # Moderate contrast enhancement
    enhancer = ImageEnhance.Contrast(gray)
    enhanced = enhancer.enhance(1.5)

    return enhanced


def extract_text_from_image_bytes(
    image_bytes: bytes,
    ocr_engine: OCREngine,
    timeout_seconds: int = 15,
) -> tuple[str, list[str]]:
    """
    Decode, preprocess, and run OCR on image bytes.
    Returns (extracted_text, warnings).
    """
    warnings: list[str] = []
    img = validate_and_open_image(image_bytes)

    # Check for very low resolution warning
    if img.width < 100 or img.height < 100:
        warnings.append("Image resolution is very low; OCR accuracy may be degraded.")

    processed = preprocess_image_for_ocr(img)
    text = ocr_engine.extract_text_from_image(processed, timeout_seconds=timeout_seconds)

    if not text.strip():
        warnings.append("No recognizable text was found in the image.")

    return text.strip(), warnings
