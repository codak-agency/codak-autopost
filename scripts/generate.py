from __future__ import annotations

import base64
import json
import os
import re
import sys
import time
from datetime import datetime
from io import BytesIO
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
import arabic_reshaper
from bidi.algorithm import get_display
from PIL import Image, ImageDraw, ImageFont, ImageOps

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "out"
STATE_FILE = ROOT / "state" / "history.json"
TIMEZONE = os.getenv("TIMEZONE", "Africa/Cairo")
GEMINI_API_BASE = os.getenv("GEMINI_API_BASE", "https://generativelanguage.googleapis.com/v1beta")
TEXT_MODEL = os.getenv("GEMINI_TEXT_MODEL", "gemini-3.5-flash")
IMAGE_MODEL = os.getenv("GEMINI_IMAGE_MODEL", "gemini-nano-banana-2.1")
CREAM = (245, 234, 223)
BROWN = (62, 44, 32)
ORANGE = (200, 87, 30)


def local_now() -> datetime:
    return datetime.now(ZoneInfo(TIMEZONE))


def read_history() -> dict:
    if not STATE_FILE.exists():
        return {"published_dates": [], "topics": []}
    try:
        value = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ValueError("history must be a JSON object")
        value.setdefault("published_dates", [])
        value.setdefault("topics", [])
        return value
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        raise RuntimeError(f"Could not read publication history: {exc}") from exc


def gemini_request(model: str, payload: dict, api_key: str, timeout: int = 180) -> dict:
    url = f"{GEMINI_API_BASE}/models/{model}:generateContent"
    headers = {"x-goog-api-key": api_key, "Content-Type": "application/json"}
    last_error = None
    for attempt in range(4):
        try:
            response = requests.post(url, headers=headers, json=payload, timeout=timeout)
            if response.status_code in (429, 500, 502, 503, 504) and attempt < 3:
                time.sleep(min(2 ** (attempt + 1), 12))
                continue
            if not response.ok:
                try:
                    details = response.json().get("error", {}).get("message", response.text[:500])
                except ValueError:
                    details = response.text[:500]
                raise RuntimeError(f"Gemini API returned HTTP {response.status_code}: {details}")
            return response.json()
        except requests.RequestException as exc:
            last_error = exc
            if attempt == 3:
                break
            time.sleep(min(2 ** (attempt + 1), 12))
    raise RuntimeError(f"Gemini API request failed: {last_error}")


def extract_text(response: dict) -> str:
    chunks = []
    for candidate in response.get("candidates", []):
        for part in candidate.get("content", {}).get("parts", []):
            if part.get("text"):
                chunks.append(part["text"])
    return "\n".join(chunks).strip()


def parse_json_response(text: str) -> dict:
    cleaned = text.strip()
    fence = chr(96) * 3
    if cleaned.startswith(fence):
        cleaned = cleaned.strip(fence).strip()
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:].strip()
    try:
        value = json.loads(cleaned)
    except json.JSONDecodeError:
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start < 0 or end <= start:
            raise RuntimeError("Gemini returned text instead of the required JSON object.")
        value = json.loads(cleaned[start : end + 1])
    if not isinstance(value, dict):
        raise RuntimeError("Gemini response must be a JSON object.")
    return value


def generate_copy(api_key: str, now: datetime, history: dict) -> dict:
    pillars = [
        "لماذا يحتاج النشاط التجاري إلى موقع إلكتروني مستقل",
        "تحسين تجربة الزائر وسهولة الوصول للمعلومة",
        "تحويل الزيارات إلى استفسارات أو طلبات",
        "المتاجر الإلكترونية وتنظيم عرض المنتجات",
        "المصداقية والهوية الرقمية للنشاط",
        "سرعة الموقع وتجربة الهاتف",
        "صفحات الخدمات والصفحات التعريفية",
        "أخطاء شائعة في المواقع وكيفية تجنبها",
    ]
    pillar = pillars[now.timetuple().tm_yday % len(pillars)]
    previous = [str(item) for item in history.get("topics", [])[-30:]]
    prompt = f"""
أنت مدير محتوى وتسويق عربي محترف لوكالة CODAK Agency المتخصصة في تصميم وتطوير المواقع الإلكترونية.
أنشئ منشورًا واحدًا جديدًا بالكامل للنشر اليوم على فيسبوك وإنستجرام ولينكدإن وتيك توك.
التاريخ المحلي: {now.date().isoformat()}.
محور المحتوى المقترح اليوم: {pillar}.
موضوعات نُشرت مؤخرًا ويجب عدم تكرارها أو إعادة صياغتها بشكل سطحي:
{json.dumps(previous, ensure_ascii=False)}

الجمهور: أصحاب الشركات والمشروعات والمتاجر والعيادات والمدربون ومقدمو الخدمات والعلامات التجارية.
الأسلوب: مصري مهني وواضح، مقنع وغير متكلف، يقدم فائدة عملية حقيقية ويبتعد عن المبالغة.
المطلوب:
- headline: عنوان عربي قصير قوي من 3 إلى 8 كلمات، بحد أقصى 36 حرفًا، مناسب ليظهر داخل التصميم.
- caption: نص عربي مصري أصلي من 350 إلى 900 حرف تقريبًا، بفكرة واحدة واضحة، وفائدة ملموسة، ودعوة لطيفة للتواصل مع CODAK في النهاية دون اختلاق وسيلة تواصل.
- hashtags: من 3 إلى 6 وسوم مناسبة، كل وسم يبدأ بـ #، دون مسافات داخل الوسم.
- topic: وصف قصير للزاوية التي تناولها المنشور، لا يتجاوز 100 حرف.
- visual_prompt: وصف باللغة الإنجليزية لصورة مفاهيمية راقية تعبر بصريًا عن الفكرة. اترك مساحة فارغة واسعة في الجهة اليمنى لإضافة العنوان لاحقًا. استخدم ألوان الهوية فقط: warm cream #F5EADF, dark brown #3E2C20, burnt orange #C8571E. لا تضف أي كتابة أو حروف أو أرقام أو شعارات.

قواعد صارمة:
- لا تخترع أسعارًا أو عروضًا أو أرقامًا أو إحصاءات أو شهادات عملاء أو نتائج مضمونة.
- لا تكرر منشورًا سابقًا أو عنوانًا قريبًا منه.
- لا تستخدم الإنجليزية في العنوان أو النص.
- لا تضع روابط أو أرقام هواتف أو بيانات اتصال غير معطاة.
- لا تكتب مقدمة أو شرحًا خارج JSON.
- أعد JSON صالحًا فقط بهذه المفاتيح: topic, headline, caption, hashtags, visual_prompt.
"""
    payload = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.85, "responseMimeType": "application/json"},
    }
    parsed = parse_json_response(extract_text(gemini_request(TEXT_MODEL, payload, api_key, timeout=120)))
    for key in ("topic", "headline", "caption", "visual_prompt"):
        if not isinstance(parsed.get(key), str) or not parsed[key].strip():
            raise RuntimeError(f"Gemini response is missing a valid '{key}' value.")
        parsed[key] = parsed[key].strip()

    hashtags = parsed.get("hashtags")
    if not isinstance(hashtags, list):
        raise RuntimeError("Gemini must return hashtags as a JSON array.")
    parsed["hashtags"] = [
        tag.strip() for tag in hashtags
        if isinstance(tag, str) and tag.strip().startswith("#")
    ][:6]
    if len(parsed["hashtags"]) < 3:
        raise RuntimeError("Gemini returned fewer than three valid hashtags.")
    if not re.search(r"[\u0600-\u06ff]", parsed["headline"]):
        raise RuntimeError("The generated headline is not Arabic.")
    if len(parsed["headline"]) > 60:
        raise RuntimeError("The generated headline is too long for the poster.")
    if len(parsed["caption"]) > 1700:
        parsed["caption"] = parsed["caption"][:1690].rsplit(" ", 1)[0].rstrip() + "…"
    parsed["caption"] = parsed["caption"] + "\n\n" + " ".join(parsed["hashtags"])
    if len(parsed["caption"]) > 2000:
        raise RuntimeError("The generated caption exceeds the shared platform limit.")
    return parsed


def generate_background(api_key: str, visual_prompt: str) -> bytes:
    prompt = (
        "Create a premium square 1:1 editorial advertising artwork background for a web design agency. "
        "The visual subject should be on the LEFT half only, with generous clean negative space on the RIGHT half "
        "for Arabic typography to be added later. Warm cream #F5EADF background, dark brown #3E2C20 details, "
        "burnt orange #C8571E accents only. Refined, minimal, high-end, realistic 3D or tasteful editorial illustration, "
        "soft natural shadows, balanced composition. NO text, NO letters, NO numbers, NO logos, NO watermark, "
        "NO UI screenshots containing readable text. Concept: "
        + visual_prompt
    )
    payload = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {
            "responseModalities": ["IMAGE"],
            "imageConfig": {"aspectRatio": "1:1", "imageSize": "1K"},
        },
    }
    response = gemini_request(IMAGE_MODEL, payload, api_key, timeout=240)
    for candidate in response.get("candidates", []):
        for part in candidate.get("content", {}).get("parts", []):
            inline = part.get("inlineData") or part.get("inline_data")
            if inline and inline.get("data"):
                return base64.b64decode(inline["data"], validate=True)
    details = extract_text(response)[:400]
    raise RuntimeError(f"Gemini image model returned no image data. {details}")


def shaped(text: str) -> str:
    return get_display(arabic_reshaper.reshape(text), base_dir="R")


def find_font() -> str:
    candidates = [
        "/usr/share/fonts/truetype/noto/NotoNaskhArabic-Bold.ttf",
        "/usr/share/fonts/truetype/noto/NotoNaskhArabic-Regular.ttf",
        "/usr/share/fonts/truetype/noto/NotoSansArabic-Bold.ttf",
        "/usr/share/fonts/truetype/noto/NotoSansArabic-Regular.ttf",
    ]
    for candidate in candidates:
        if Path(candidate).exists():
            return candidate
    raise RuntimeError("Arabic font not found. Install the fonts-noto-core package in the workflow.")


def wrap_arabic(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, max_width: int) -> list[str]:
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        box = draw.textbbox((0, 0), shaped(candidate), font=font)
        if current and (box[2] - box[0]) > max_width:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines[:4]


def render_poster(background: bytes, headline: str, output_path: Path) -> None:
    source = Image.open(BytesIO(background)).convert("RGB")
    canvas = ImageOps.fit(source, (1080, 1080), method=Image.Resampling.LANCZOS).convert("RGBA")

    panel = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    panel_draw = ImageDraw.Draw(panel)
    panel_draw.rounded_rectangle((390, -70, 1160, 1150), radius=72, fill=(*CREAM, 246))
    canvas = Image.alpha_composite(canvas, panel)
    draw = ImageDraw.Draw(canvas)

    font_path = find_font()
    eyebrow_font = ImageFont.truetype(font_path, 31)
    small_font = ImageFont.truetype(font_path, 35)
    title_font = ImageFont.truetype(font_path, 86)

    draw.rounded_rectangle((910, 108, 982, 120), radius=6, fill=ORANGE)
    draw.text((980, 165), shaped("CODAK AGENCY"), font=eyebrow_font, fill=BROWN, anchor="rt")
    draw.text((980, 235), shaped("حلول رقمية تصنع حضورك"), font=small_font, fill=ORANGE, anchor="rt")

    lines = wrap_arabic(draw, headline, title_font, 535)
    if len(lines) > 3:
        title_font = ImageFont.truetype(font_path, 70)
        lines = wrap_arabic(draw, headline, title_font, 535)

    y = 365
    for index, line in enumerate(lines):
        draw.text(
            (985, y), shaped(line), font=title_font,
            fill=ORANGE if index == len(lines) - 1 else BROWN, anchor="rt",
        )
        y += 124

    draw.rounded_rectangle((740, 870, 982, 878), radius=4, fill=ORANGE)
    draw.text((980, 925), shaped("تصميم وتطوير المواقع الإلكترونية"), font=small_font, fill=BROWN, anchor="rt")
    draw.text((980, 1000), "CODAK AGENCY", font=ImageFont.truetype(font_path, 25), fill=(100, 78, 62), anchor="rt")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.convert("RGB").save(output_path, "PNG", optimize=True)


def main() -> None:
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("Missing GEMINI_API_KEY repository secret.")

    OUT.mkdir(parents=True, exist_ok=True)
    now = local_now()
    history = read_history()
    date_key = now.date().isoformat()
    if date_key in history.get("published_dates", []):
        (OUT / "post.json").write_text(
            json.dumps({"already_published": True, "date": date_key}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"CODAK already published for {date_key}; generation skipped.")
        return

    copy = generate_copy(api_key, now, history)
    background = generate_background(api_key, copy["visual_prompt"])
    (OUT / "ai_background.png").write_bytes(background)
    render_poster(background, copy["headline"], OUT / "post.png")

    result = {"date": date_key, "timezone": TIMEZONE, "generated_at": now.isoformat(), **copy}
    (OUT / "post.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Generated CODAK post preview: {copy['topic']}")
    print(f"Headline: {copy['headline']}")
    print(f"Caption characters: {len(copy['caption'])}")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"GENERATION_FAILED: {exc}", file=sys.stderr)
        sys.exit(1)
