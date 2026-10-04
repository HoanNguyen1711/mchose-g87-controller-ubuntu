"""UI strings (English / Vietnamese) and the persisted language setting."""
import json
import locale
import os

LANGUAGES = {"en": "English", "vi": "Tiếng Việt"}

STRINGS = {
    "en": {
        "effects": "Effects",
        "brightness": "Brightness",
        "speed": "Speed",
        "color": "Color",
        "palette": "Cycle 7 colors",
        "language": "Language",
        "battery": "Battery: {level}%",
        "battery_unknown": "Battery: —",
        "battery_unavailable": "Battery: not connected",
        "charging": " (charging)",
        "applying": "Applying…",
        "applied": "Applied",
        "error": "Error: {err}",
        "open_settings": "Open settings",
        "quit": "Quit",
        "low_battery_title": "MCHOSE keyboard battery low",
        "low_battery_body": "{level}% left, please plug in the charger.",
        "effect.static": "Static",
        "effect.breathing": "Breathing",
        "effect.rainbow": "Rainbow",
        "effect.reactive": "Reactive",
        "effect.rain": "Raindrops",
        "effect.ripple": "Ripple",
        "effect.stars": "Starlight",
        "effect.stream": "Stream",
        "effect.flow": "Flow",
        "effect.shadow": "Shadow",
        "effect.sine": "Sine wave",
        "effect.pinwheel": "Pinwheel",
        "effect.waterfall": "Waterfall",
        "effect.flowers": "Blossom",
        "effect.off": "Lights off",
    },
    "vi": {
        "effects": "Hiệu ứng",
        "brightness": "Độ sáng",
        "speed": "Tốc độ",
        "color": "Màu",
        "palette": "Xoay vòng 7 màu",
        "language": "Ngôn ngữ",
        "battery": "Pin: {level}%",
        "battery_unknown": "Pin: —",
        "battery_unavailable": "Pin: không kết nối được",
        "charging": " (đang sạc)",
        "applying": "Đang áp dụng…",
        "applied": "Đã áp dụng",
        "error": "Lỗi: {err}",
        "open_settings": "Mở cài đặt",
        "quit": "Thoát",
        "low_battery_title": "Bàn phím MCHOSE sắp hết pin",
        "low_battery_body": "Còn {level}%, hãy cắm sạc.",
        "effect.static": "Tĩnh",
        "effect.breathing": "Thở",
        "effect.rainbow": "Cầu vồng",
        "effect.reactive": "Phản hồi phím",
        "effect.rain": "Mưa rơi",
        "effect.ripple": "Gợn sóng",
        "effect.stars": "Sao trời",
        "effect.stream": "Dòng chảy",
        "effect.flow": "Trôi theo sóng",
        "effect.shadow": "Bóng đuổi",
        "effect.sine": "Sóng sin",
        "effect.pinwheel": "Chong chóng",
        "effect.waterfall": "Thác bảy màu",
        "effect.flowers": "Hoa nở",
        "effect.off": "Tắt đèn",
    },
}

CONFIG_PATH = os.path.join(os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config")),
                           "mchose", "config.json")

_lang = "en"


def _load_config():
    try:
        with open(CONFIG_PATH) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def system_language():
    for var in ("LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG"):
        value = os.environ.get(var)
        if value:
            return "vi" if value.startswith("vi") else "en"
    code = locale.getlocale()[0] or ""
    return "vi" if code.startswith("vi") else "en"


def init(override=None):
    """Pick the language: explicit override, then saved setting, then system locale."""
    global _lang
    lang = override or _load_config().get("language") or system_language()
    _lang = lang if lang in STRINGS else "en"


def current():
    return _lang


def set_language(lang, save=True):
    global _lang
    if lang not in STRINGS:
        raise ValueError(f"unsupported language {lang!r}")
    _lang = lang
    if save:
        config = _load_config()
        config["language"] = lang
        os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
        with open(CONFIG_PATH, "w") as f:
            json.dump(config, f, indent=2)


def t(key, **kwargs):
    text = STRINGS[_lang].get(key) or STRINGS["en"][key]
    return text.format(**kwargs) if kwargs else text


def effect_label(effect, lang=None):
    return STRINGS[lang or _lang].get(f"effect.{effect.name}", effect.name)


def all_texts():
    """Every UI string in every language, for sizing and font-coverage checks."""
    return [text for strings in STRINGS.values() for text in strings.values()]
