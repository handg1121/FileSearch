"""한국어 OCR 검사용 이미지를 테스트 폴더에 만들어요."""

from pathlib import Path
from PIL import Image, ImageDraw, ImageFont


def text_image(text="공사 계약서\n계약금을 지불한다\nInvoice total 12345", *, transparent=False):
    image = Image.new("RGBA" if transparent else "RGB", (1600, 700), (0, 0, 0, 0) if transparent else "white")
    font = ImageFont.truetype("C:/Windows/Fonts/malgun.ttf", 56)
    ImageDraw.Draw(image).multiline_text((80, 80), text, font=font, fill="black", spacing=38)
    return image


def save_image(path, text=None):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    image = text_image() if text is None else text_image(text)
    image.save(path, quality=95)
    return path
