"""
翻译 API 集成模块
支持 DeepL、百度翻译、有道翻译
"""

import hashlib
import json
import random
import time
import urllib.parse
from abc import ABC, abstractmethod
from pathlib import Path

import requests

CONFIG_PATH = Path(__file__).parent / "translate_config.json"
DEFAULT_TIMEOUT = 30


class TranslatorBase(ABC):
    """翻译器基类"""

    @abstractmethod
    def translate(self, text: str, from_lang: str, to_lang: str) -> str:
        """翻译文本"""
        pass

    @abstractmethod
    def get_name(self) -> str:
        """获取翻译器名称"""
        pass


class DeepLTranslator(TranslatorBase):
    """DeepL 翻译"""

    def __init__(self, api_key: str, is_pro: bool = False):
        self.api_key = api_key
        self.base_url = "https://api.deepl.com/v2" if is_pro else "https://api-free.deepl.com/v2"

    def get_name(self) -> str:
        return "DeepL"

    def translate(self, text: str, from_lang: str, to_lang: str) -> str:
        url = f"{self.base_url}/translate"
        data = {
            "text": [text],
            "source_lang": from_lang.upper(),
            "target_lang": to_lang.upper(),
            "auth_key": self.api_key,
        }
        response = requests.post(url, data=data, timeout=DEFAULT_TIMEOUT)
        response.raise_for_status()
        result = response.json()
        return result["translations"][0]["text"]


class BaiduTranslator(TranslatorBase):
    """百度翻译"""

    def __init__(self, app_id: str, secret_key: str):
        self.app_id = app_id
        self.secret_key = secret_key
        self.url = "https://fanyi-api.baidu.com/api/trans/vip/translate"

    def get_name(self) -> str:
        return "百度翻译"

    def translate(self, text: str, from_lang: str, to_lang: str) -> str:
        salt = str(random.randint(32768, 65536))
        sign_str = self.app_id + text + salt + self.secret_key
        sign = hashlib.md5(sign_str.encode()).hexdigest()

        params = {
            "q": text,
            "from": from_lang,
            "to": to_lang,
            "appid": self.app_id,
            "salt": salt,
            "sign": sign,
        }

        response = requests.get(self.url, params=params, timeout=DEFAULT_TIMEOUT)
        response.raise_for_status()
        result = response.json()

        if "error_code" in result:
            raise Exception(f"百度翻译错误: {result['error_code']} - {result.get('error_msg', '')}")

        return result["trans_result"][0]["dst"]


class YoudaoTranslator(TranslatorBase):
    """有道翻译"""

    def __init__(self, app_key: str, app_secret: str):
        self.app_key = app_key
        self.app_secret = app_secret
        self.url = "https://openapi.youdao.com/api"

    def get_name(self) -> str:
        return "有道翻译"

    def translate(self, text: str, from_lang: str, to_lang: str) -> str:
        salt = str(random.randint(32768, 65536))
        curtime = str(int(time.time()))

        sign_str = self.app_key + text + salt + curtime + self.app_secret
        sign = hashlib.sha256(sign_str.encode()).hexdigest()

        params = {
            "q": text,
            "from": from_lang,
            "to": to_lang,
            "appKey": self.app_key,
            "salt": salt,
            "sign": sign,
            "signType": "v3",
            "curtime": curtime,
        }

        response = requests.get(self.url, params=params, timeout=DEFAULT_TIMEOUT)
        response.raise_for_status()
        result = response.json()

        if result.get("errorCode") != "0":
            raise Exception(f"有道翻译错误: {result.get('errorCode')}")

        return result["translation"][0]


class GoogleTranslator(TranslatorBase):
    """Google 翻译 (免费，无需 API key)"""

    def __init__(self):
        self.url = "https://translate.googleapis.com/translate_a/single"

    def get_name(self) -> str:
        return "Google翻译"

    def translate(self, text: str, from_lang: str, to_lang: str) -> str:
        params = {
            "client": "gtx",
            "sl": from_lang,
            "tl": to_lang,
            "dt": "t",
            "q": text,
        }

        response = requests.get(self.url, params=params, timeout=DEFAULT_TIMEOUT)
        response.raise_for_status()
        result = response.json()

        translated = "".join([item[0] for item in result[0] if item[0]])
        return translated


class LLMTranslator(TranslatorBase):
    """LLM 翻译 (OpenAI API 兼容接口)"""

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.openai.com/v1",
        model: str = "gpt-4o-mini",
        system_prompt: str | None = None,
    ):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.system_prompt = system_prompt or (
            "你是一个专业的翻译助手。请将用户提供的文本翻译成目标语言。"
            "只返回翻译结果，不要添加任何解释或额外内容。"
            "保持原文的语气和风格。"
        )

    def get_name(self) -> str:
        return f"LLM ({self.model})"

    def translate(self, text: str, from_lang: str, to_lang: str) -> str:
        lang_names = {
            "zh": "中文", "en": "英文", "ja": "日语", "ko": "韩语",
            "fr": "法语", "de": "德语", "es": "西班牙语", "it": "意大利语",
            "pt": "葡萄牙语", "ru": "俄语",
        }
        from_name = lang_names.get(from_lang, from_lang)
        to_name = lang_names.get(to_lang, to_lang)

        user_prompt = f"将以下{from_name}文本翻译成{to_name}：\n{text}"

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        data = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.3,
        }

        response = requests.post(
            f"{self.base_url}/chat/completions",
            headers=headers,
            json=data,
            timeout=30,
        )
        response.raise_for_status()
        result = response.json()

        return result["choices"][0]["message"]["content"].strip()


def create_translator(translator_type: str, **kwargs) -> TranslatorBase:
    """
    创建翻译器实例

    Args:
        translator_type: 翻译器类型 (llm/deepl/baidu/youdao/google)
        **kwargs: 翻译器参数

    Returns:
        TranslatorBase 实例
    """
    translators = {
        "llm": lambda: LLMTranslator(
            kwargs["api_key"],
            kwargs.get("base_url", "https://api.openai.com/v1"),
            kwargs.get("model", "gpt-4o-mini"),
            kwargs.get("system_prompt"),
        ),
        "deepl": lambda: DeepLTranslator(kwargs["api_key"], kwargs.get("is_pro", False)),
        "baidu": lambda: BaiduTranslator(kwargs["app_id"], kwargs["secret_key"]),
        "youdao": lambda: YoudaoTranslator(kwargs["app_key"], kwargs["app_secret"]),
        "google": lambda: GoogleTranslator(),
    }

    if translator_type not in translators:
        raise ValueError(f"不支持的翻译器: {translator_type}，可选: {', '.join(translators.keys())}")

    return translators[translator_type]()


# 语言代码映射
LANGUAGE_CODES = {
    "deepl": {
        "zh": "ZH", "en": "EN", "ja": "JA", "ko": "KO",
        "fr": "FR", "de": "DE", "es": "ES", "it": "IT",
        "pt": "PT", "ru": "RU",
    },
    "baidu": {
        "zh": "zh", "en": "en", "ja": "jp", "ko": "kor",
        "fr": "fra", "de": "de", "es": "spa", "it": "it",
        "pt": "pt", "ru": "ru",
    },
    "youdao": {
        "zh": "zh-CHS", "en": "en", "ja": "ja", "ko": "ko",
        "fr": "fr", "de": "de", "es": "es", "it": "it",
        "pt": "pt", "ru": "ru",
    },
    "google": {
        "zh": "zh-CN", "en": "en", "ja": "ja", "ko": "ko",
        "fr": "fr", "de": "de", "es": "es", "it": "it",
        "pt": "pt", "ru": "ru",
    },
}


def get_lang_code(translator_type: str, lang: str) -> str:
    """获取翻译器对应的语言代码"""
    codes = LANGUAGE_CODES.get(translator_type, {})
    return codes.get(lang, lang)


def load_config() -> dict:
    """加载翻译配置"""
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_config(config: dict):
    """保存翻译配置"""
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)
