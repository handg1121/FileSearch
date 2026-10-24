"""태그 기본 색과 저장 가능한 색 형식을 정의해요."""

import re

DEFAULT_TAG_COLOR = "#ef4444"


def normalize_color(color):
    if not isinstance(color, str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", color):
        raise ValueError("색은 #RRGGBB 형식으로 지정해 주세요.")
    return color.lower()


def badge_palette(color):
    """선택한 색으로 옅은 배경과 읽기 쉬운 글자색을 만들어요."""
    color = normalize_color(color)
    values = [int(color[start:start + 2], 16) for start in (1, 3, 5)]
    background = [round(value * 0.14 + 255 * 0.86) for value in values]
    # 밝은 노랑·흰색도 옅은 배경 위에서 읽히도록 글자색을 어둡게 해요.
    foreground = values[:]
    def luminance(rgb):
        linear = [v / 255 / 12.92 if v / 255 <= 0.04045 else ((v / 255 + 0.055) / 1.055) ** 2.4 for v in rgb]
        return sum(v * weight for v, weight in zip(linear, (0.2126, 0.7152, 0.0722)))
    while (luminance(background) + 0.05) / (luminance(foreground) + 0.05) < 4.5:
        foreground = [int(value * 0.88) for value in foreground]
    return ("#" + "".join(f"{value:02x}" for value in background),
            "#" + "".join(f"{value:02x}" for value in foreground))
