"""
modules/media/image_gen.py — генерация превью-изображений через Gemini API
с наложением текста через PIL (тема поста / цитата).
"""
import os
import base64
import logging
import random
import uuid
from pathlib import Path

logger = logging.getLogger(__name__)

AUTHOR_PHOTOS_DIR = Path(__file__).parent.parent.parent / "data" / "media" / "author"
PREVIEW_OUTPUT_DIR = Path(__file__).parent.parent.parent / "data" / "media" / "previews"

# Ракурс фото по категории
FACE_REF_BY_CATEGORY = {
    "personal":     ["front.png", "close_up.png"],
    "opinion":      ["three_quarter_left.png", "three_quarter_right.png"],
    "motivational": ["three_quarter_right.png", "front.png"],
    "story":        ["front.png", "three_quarter_left.png"],
    "expert":       ["three_quarter_left.png", "three_quarter_right.png"],
    "engaging":     ["front.png", "close_up.png"],
    "entertaining": ["close_up.png", "front.png"],
}

FACE_CATEGORIES = {"personal", "motivational", "story", "engaging", "entertaining", "opinion", "expert"}
ASPECT_RATIOS = ["1:1", "4:5", "16:9"]

# ── Сцены: разная одежда, эмоции, обстановка ─────────────────────────────────
# Главное: тёплое освещение, разнообразие образов, НЕ всегда костюм

SCENE_PROMPTS = {
    "personal": [
        "cozy home setting, warm golden lamp light, casual light grey hoodie, relaxed genuine smile, sitting on sofa, warm bokeh background, candid authentic moment",
        "home office desk, warm morning light from window, simple white t-shirt, thoughtful relaxed expression, coffee mug nearby, soft natural warm tones",
        "casual kitchen or living room, warm evening light, navy blue casual sweater, laughing natural expression, very human and relatable",
    ],
    "opinion": [
        "dark minimal background, strong warm side light, dark blue unstructured blazer over white tee, arms crossed slight smirk, confident opinionated expression",
        "home office bookshelves background, warm desk lamp, charcoal crewneck sweater, direct camera gaze, leaning slightly forward, strong point of view energy",
        "simple dark background, warm spotlight, black zip-up hoodie, one eyebrow raised, intellectual skeptical expression, editorial style",
    ],
    "motivational": [
        "bright modern workspace, warm morning sun through window, fresh white shirt, big genuine smile, energetic optimistic expression, success energy",
        "city view window background soft bokeh, warm afternoon light, navy polo shirt, confident forward lean, hands together gesture, breakthrough moment",
        "clean light background, warm studio light, olive green casual jacket, thumbs up or open palm gesture, encouraging authentic expression",
    ],
    "story": [
        "cozy cafe background blur, warm indoor light, grey casual hoodie, thoughtful nostalgic expression, slight smile, storytelling intimate moment",
        "evening home setting, warm lamp light, burgundy henley shirt, leaning back relaxed, reminiscing expression, genuine personal story mood",
        "warm home office, golden hour light, casual dark denim shirt, resting chin on hand, reflective honest expression",
    ],
    "expert": [
        "clean home office, warm directional light, dark green merino sweater, pointing to side gesture, explaining expression, YouTube Studio on screen behind",
        "simple background, warm studio light, black polo shirt, both hands open explaining gesture, authoritative but approachable expert energy",
        "minimal bright background, warm light, dark unstructured blazer, one hand raised making a point, clear confident teaching expression",
    ],
    "engaging": [
        "warm bright background, natural light, casual light blue shirt, wide open smile, hands spread open inviting gesture, direct eye contact, fun energy",
        "simple background, warm light, orange or yellow casual tee, playful curious expression, head slightly tilted, conversational and friendly",
        "cozy setting, warm lamp light, casual stripe shirt, leaning forward elbows on knees, genuinely curious engaged expression",
    ],
    "entertaining": [
        "warm colorful background bokeh, bright light, fun casual bright colored hoodie, laughing or grinning widely, very animated expression, great energy",
        "simple warm background, playful light, casual graphic tee, comedic exaggerated surprised expression, hands up gesture",
        "warm studio light, casual colorful shirt, ironic knowing smirk, one eyebrow up, arms crossed amusedly, clever humorous vibe",
    ],
    # Без лица — тёмный бренд стиль
    "trend": [
        "dark premium background #0d0d0d, YouTube red #FF0000 glowing accent lines, abstract upward growth chart, bold modern business design, 4K",
        "deep black background, red and white geometric shapes, dynamic diagonal composition, YouTube brand aesthetic, premium quality",
        "dark gradient background, glowing red data visualization, minimalist infographic style, high contrast professional",
    ],
    "report": [
        "dark charcoal background, clean white text layout space, subtle red accent bar top, editorial news dark style, professional",
        "almost black background, minimal white geometric frame, YouTube red highlight strip, serious credible dark magazine aesthetic",
        "dark premium background, bold typographic space, red and white accents, clean dark editorial design",
    ],
}


def _load_ref_image(filename: str) -> bytes | None:
    path = AUTHOR_PHOTOS_DIR / filename
    if not path.exists():
        logger.warning(f"Эталонное фото не найдено: {path}")
        return None
    with open(path, "rb") as f:
        return f.read()


def _pick_aspect_ratio() -> str:
    return random.choice(ASPECT_RATIOS)


def _should_use_face(category: str, post_format: str, force) -> bool:
    if force is not None:
        return force
    if post_format in ("trend", "report"):
        return False
    return category in FACE_CATEGORIES



def generate_preview(
    theme: str,
    post_text: str,
    category: str = "expert",
    post_format: str = "opinion",
    config: dict = None,
    use_face=None,
    aspect_ratio: str = None,
    show_text: bool = True,
) -> dict:
    try:
        from google import genai as genai_new
        from google.genai import types as genai_types
    except ImportError:
        return {"success": False, "error": "Установи SDK: pip install google-genai"}

    if not config:
        return {"success": False, "error": "Конфиг не передан"}

    api_key = config.get("gemini", {}).get("api_key") or os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return {"success": False, "error": "GEMINI_API_KEY не задан в config.yaml"}

    client = genai_new.Client(api_key=api_key)

    used_face = _should_use_face(category, post_format, use_face)
    chosen_ratio = aspect_ratio or _pick_aspect_ratio()

    PREVIEW_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Выбираем сцену
    scene_key = category if category in SCENE_PROMPTS else "expert"
    if post_format in ("trend", "report") and not used_face:
        scene_key = post_format
    scene = random.choice(SCENE_PROMPTS[scene_key])

    theme_short = theme[:80]

    # Выбираем ракурс фото
    ref_bytes = None
    if used_face:
        refs = FACE_REF_BY_CATEGORY.get(category, ["front.png"])
        ref_file = random.choice(refs)
        ref_bytes = _load_ref_image(ref_file)
        if not ref_bytes:
            used_face = False

    # Короткая цитата из поста для текста на картинке (первые ~100 символов)
    quote = post_text.strip().replace("\n", " ")
    quote = (quote[:97] + "…") if len(quote) > 100 else quote

    # Строим промпт
    if used_face:
        text_instruction = (
            f"TEXT ON IMAGE: place in bottom area of image — "
            f"bold white uppercase title: \"{theme_short}\" "
            f"and below it smaller grey italic quote: \"{quote}\" "
            f"Use clean modern sans-serif font. Dark semi-transparent background behind text for readability. "
            if show_text else
            "NO text, NO captions, NO watermarks, NO labels on the image. Clean photo only. "
        )
        prompt = (
            f"Photorealistic portrait photo for Telegram post preview image. "
            f"PERSON: bald head, round thin-frame glasses, short beard, BROAD WIDE shoulders, athletic build — use reference photo exactly. "
            f"OUTFIT AND SCENE: {scene}. "
            f"LIGHTING: warm, natural, cinematic — NOT studio podcast lighting, NOT formal suit. "
            f"EMOTION: authentic, varied, matching topic mood. "
            f"FRAMING: upper body shot showing wide broad shoulders clearly, {chosen_ratio} composition. "
            f"{text_instruction}"
            f"Warm color grading, shallow depth of field. Ultra high quality photo."
        )
    else:
        text_instruction = (
            f"TEXT ON IMAGE — bold white uppercase title in center or lower area: \"{theme_short}\" "
            f"and smaller quote below: \"{quote}\" "
            f"Clean modern typography, dark semi-transparent text background. "
            if show_text else
            "NO text, NO captions, NO watermarks on the image. Clean visual only. "
        )
        prompt = (
            f"Premium dark Telegram post preview image. "
            f"Brand style: 'YouTube как бизнес' — dark background #0d0d0d, YouTube red #FF0000 accents, white typography. "
            f"Style: {scene}. "
            f"{text_instruction}"
            f"Composition: {chosen_ratio}. 4K premium quality."
        )

    # Формируем parts
    parts = []
    if used_face and ref_bytes:
        parts.append(genai_types.Part.from_bytes(data=ref_bytes, mime_type="image/png"))
    parts.append(genai_types.Part.from_text(text=prompt))

    try:
        response = client.models.generate_content(
            model="gemini-3.1-flash-image-preview",
            contents=parts,
            config=genai_types.GenerateContentConfig(
                response_modalities=["IMAGE", "TEXT"],
            ),
        )
    except Exception as e:
        return {"success": False, "error": f"Ошибка Gemini API: {e}"}

    # Извлекаем изображение
    image_raw = None
    for candidate in response.candidates:
        for part in candidate.content.parts:
            if hasattr(part, "inline_data") and part.inline_data and part.inline_data.data:
                data = part.inline_data.data
                image_raw = bytes(data) if isinstance(data, (bytes, bytearray)) else base64.b64decode(data)
                break
        if image_raw:
            break

    if not image_raw:
        return {"success": False, "error": "Gemini не вернул изображение"}

    # Сохраняем
    final_filename = f"preview_{uuid.uuid4().hex[:8]}.png"
    final_path = PREVIEW_OUTPUT_DIR / final_filename
    with open(final_path, "wb") as f:
        f.write(image_raw)

    logger.info(f"Превью готово: {final_filename} ({chosen_ratio}, face={used_face})")

    return {
        "success": True,
        "path": f"data/media/previews/{final_filename}",
        "filename": final_filename,
        "aspect_ratio": chosen_ratio,
        "used_face": used_face,
        "error": None,
    }
