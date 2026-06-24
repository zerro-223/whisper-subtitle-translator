"""
Whisper 字幕识别 + 翻译 GUI 工具
轻量级界面，支持配置API、拖入文件、批量处理
"""

import json
import os
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, scrolledtext, ttk

from whisper_transcribe import (
    build_bilingual_srt,
    format_timestamp,
    parse_srt,
    segments_to_srt,
    translate_srt,
)

# 项目目录
PROJECT_DIR = Path(__file__).parent
CONFIG_FILE = PROJECT_DIR / "config.json"

# 将模型缓存目录设置为项目下的 whisper 文件夹
os.environ["XDG_CACHE_HOME"] = str(PROJECT_DIR)

# 支持的格式
AUDIO_FORMATS = {".mp3", ".wav", ".flac", ".aac", ".ogg", ".m4a", ".wma"}
VIDEO_FORMATS = {".mp4", ".mkv", ".avi", ".mov", ".wmv", ".flv", ".webm", ".m4v"}
SUPPORTED_FORMATS = AUDIO_FORMATS | VIDEO_FORMATS

# 模型信息（显存需求 + 精度参考）
MODEL_INFO = {
    "tiny":     "约 1GB 显存 | 精度：一般",
    "base":     "约 1GB 显存 | 精度：一般",
    "small":    "约 2GB 显存 | 精度：较好",
    "medium":   "约 5GB 显存 | 精度：良好",
    "large-v3": "约 10GB 显存 | 精度：最佳",
}

# 语言显示名称 → 语言代码
LANG_DISPLAY = {
    "自动检测": "auto",
    "中文": "zh",
    "英文": "en",
    "日语": "ja",
    "韩语": "ko",
    "法语": "fr",
    "德语": "de",
    "西班牙语": "es",
}
LANG_CODE = {v: k for k, v in LANG_DISPLAY.items()}  # 代码 → 显示名称

# 常见 LLM 厂商配置
LLM_PROVIDERS = {
    "OpenAI": {
        "base_url": "https://api.openai.com/v1",
        "models": ["gpt-4o", "gpt-4o-mini", "gpt-4-turbo", "gpt-3.5-turbo"],
    },
    "DeepSeek": {
        "base_url": "https://api.deepseek.com/v1",
        "models": ["deepseek-chat", "deepseek-coder"],
    },
    "通义千问": {
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "models": ["qwen-turbo", "qwen-plus", "qwen-max", "qwen-long"],
    },
    "智谱 AI": {
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "models": ["glm-4", "glm-4-flash", "glm-4-air", "glm-4-airx"],
    },
    "文心一言": {
        "base_url": "https://aip.baidubce.com/rpc/2.0/ai_custom/v1/wenxinworkshop",
        "models": ["ernie-4.0-turbo-8k", "ernie-3.5-8k", "ernie-speed-128k"],
    },
    "Moonshot": {
        "base_url": "https://api.moonshot.cn/v1",
        "models": ["moonshot-v1-128k", "moonshot-v1-32k", "moonshot-v1-8k"],
    },
    "百川": {
        "base_url": "https://api.baichuan-ai.com/v1",
        "models": ["Baichuan4", "Baichuan3-Turbo", "Baichuan2-Turbo"],
    },
    "零一万物": {
        "base_url": "https://api.lingyiwanwu.com/v1",
        "models": ["yi-large", "yi-medium", "yi-spark"],
    },
    "自定义": {
        "base_url": "",
        "models": [],
    },
}


class Config:
    """配置管理"""

    def __init__(self):
        self.data = {
            "whisper_model": "large-v3",
            "language": "zh",
            "translator": "google",
            "translate_to": "en",
            "bilingual": False,
            "output_dir": "",
            "llm_api_key": "",
            "llm_base_url": "https://api.openai.com/v1",
            "llm_model": "gpt-4o-mini",
            "deepl_api_key": "",
            "baidu_app_id": "",
            "baidu_secret_key": "",
            "youdao_app_key": "",
            "youdao_app_secret": "",
            "device": "auto",
        }
        self.load()

    def load(self):
        if CONFIG_FILE.exists():
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                saved = json.load(f)
                self.data.update(saved)

    def save(self):
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(self.data, f, ensure_ascii=False, indent=2)

    def get(self, key, default=None):
        return self.data.get(key, default)

    def set(self, key, value):
        self.data[key] = value


class DropListbox(tk.Listbox):
    """支持拖放的列表框"""

    def __init__(self, master, on_change=None, **kwargs):
        super().__init__(master, **kwargs)
        self.files = []
        self.on_change = on_change
        self._setup_dnd()

    def _setup_dnd(self):
        try:
            import tkinterdnd2
            self.drop_target_register(tkinterdnd2.DND_FILES)
            self.dnd_bind("<<Drop>>", self._on_drop)
        except ImportError:
            pass

    def _on_drop(self, event):
        files = self.tk.splitlist(event.data)
        self.add_files(files)
        if self.on_change:
            self.on_change()

    def add_files(self, files):
        for f in files:
            p = Path(f)
            if p.is_file() and p.suffix.lower() in SUPPORTED_FORMATS:
                if str(p) not in self.files:
                    self.files.append(str(p))
                    self.insert(tk.END, p.name)
            elif p.is_dir():
                for item in sorted(p.iterdir()):
                    if item.is_file() and item.suffix.lower() in SUPPORTED_FORMATS:
                        if str(item) not in self.files:
                            self.files.append(str(item))
                            self.insert(tk.END, item.name)

    def remove_selected(self):
        indices = list(self.curselection())
        for i in reversed(indices):
            self.files.pop(i)
            self.delete(i)

    def clear(self):
        self.files.clear()
        self.delete(0, tk.END)


class WhisperGUI:
    """主界面"""

    def __init__(self):
        self.config = Config()
        self.is_processing = False
        self.stop_event = threading.Event()
        self.model = None

        self.root = tk.Tk()
        self.root.title("Whisper 字幕识别 + 翻译")
        self.root.geometry("800x700")
        self.root.minsize(700, 600)

        self._setup_style()
        self._create_widgets()
        self._load_config()

    def _setup_style(self):
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("Title.TLabel", font=("", 12, "bold"))
        style.configure("Status.TLabel", font=("", 9))
        style.configure("Start.TButton", font=("", 10, "bold"))

    def _create_widgets(self):
        # 主容器
        main = ttk.Frame(self.root, padding=10)
        main.pack(fill=tk.BOTH, expand=True)

        # 顶部：文件区域
        self._create_file_section(main)

        # 中部：设置区域
        self._create_settings_section(main)

        # 底部：控制和日志
        self._create_control_section(main)

    def _create_file_section(self, parent):
        frame = ttk.LabelFrame(parent, text="文件列表", padding=5)
        frame.pack(fill=tk.BOTH, expand=True, pady=(0, 5))

        # 文件列表
        list_frame = ttk.Frame(frame)
        list_frame.pack(fill=tk.BOTH, expand=True)

        self.file_list = DropListbox(
            list_frame,
            selectmode=tk.EXTENDED,
            height=6,
            font=("Consolas", 9),
            on_change=self._update_file_count,
        )
        scrollbar = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=self.file_list.yview)
        self.file_list.configure(yscrollcommand=scrollbar.set)
        self.file_list.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # 按钮栏
        btn_frame = ttk.Frame(frame)
        btn_frame.pack(fill=tk.X, pady=(5, 0))

        ttk.Button(btn_frame, text="添加文件", command=self._add_files).pack(side=tk.LEFT, padx=2)
        ttk.Button(btn_frame, text="添加文件夹", command=self._add_folder).pack(side=tk.LEFT, padx=2)
        ttk.Button(btn_frame, text="移除选中", command=self._remove_selected).pack(side=tk.LEFT, padx=2)
        ttk.Button(btn_frame, text="清空", command=self._clear_files).pack(side=tk.LEFT, padx=2)

        self.file_count_label = ttk.Label(btn_frame, text="共 0 个文件")
        self.file_count_label.pack(side=tk.RIGHT, padx=5)

    def _create_settings_section(self, parent):
        frame = ttk.LabelFrame(parent, text="设置", padding=5)
        frame.pack(fill=tk.X, pady=(0, 5))

        # 第一行：识别设置
        row1 = ttk.Frame(frame)
        row1.pack(fill=tk.X, pady=2)

        ttk.Label(row1, text="模型:").pack(side=tk.LEFT, padx=(0, 5))
        self.model_var = tk.StringVar()
        model_combo = ttk.Combobox(
            row1, textvariable=self.model_var,
            values=list(MODEL_INFO.keys()),
            state="readonly", width=12,
        )
        model_combo.pack(side=tk.LEFT, padx=(0, 5))

        self.model_info_label = ttk.Label(row1, text="", font=("", 8), foreground="gray")
        self.model_info_label.pack(side=tk.LEFT, padx=(0, 15))

        def on_model_change(*args):
            info = MODEL_INFO.get(self.model_var.get(), "")
            self.model_info_label.config(text=info)

        self.model_var.trace_add("write", on_model_change)

        ttk.Label(row1, text="识别语言:").pack(side=tk.LEFT, padx=(0, 5))
        self.lang_var = tk.StringVar()
        lang_combo = ttk.Combobox(
            row1, textvariable=self.lang_var,
            values=list(LANG_DISPLAY.keys()),
            state="readonly", width=8,
        )
        lang_combo.pack(side=tk.LEFT, padx=(0, 15))

        ttk.Label(row1, text="设备:").pack(side=tk.LEFT, padx=(0, 5))
        self.device_var = tk.StringVar()
        device_combo = ttk.Combobox(
            row1, textvariable=self.device_var,
            values=["auto", "cuda", "cpu"],
            state="readonly", width=8,
        )
        device_combo.pack(side=tk.LEFT)

        # 第二行：翻译设置
        row2 = ttk.Frame(frame)
        row2.pack(fill=tk.X, pady=2)

        self.enable_translate_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(row2, text="启用翻译", variable=self.enable_translate_var).pack(side=tk.LEFT, padx=(0, 15))

        ttk.Label(row2, text="翻译器:").pack(side=tk.LEFT, padx=(0, 5))
        self.translator_var = tk.StringVar()
        translator_combo = ttk.Combobox(
            row2, textvariable=self.translator_var,
            values=["google", "llm", "deepl", "baidu", "youdao"],
            state="readonly", width=10,
        )
        translator_combo.pack(side=tk.LEFT, padx=(0, 15))

        ttk.Label(row2, text="目标语言:").pack(side=tk.LEFT, padx=(0, 5))
        self.target_lang_var = tk.StringVar()
        target_combo = ttk.Combobox(
            row2, textvariable=self.target_lang_var,
            values=[v for k, v in LANG_DISPLAY.items() if k != "自动检测"],
            state="readonly", width=8,
        )
        target_combo.pack(side=tk.LEFT, padx=(0, 15))

        self.bilingual_var = tk.BooleanVar()
        ttk.Checkbutton(row2, text="双语字幕", variable=self.bilingual_var).pack(side=tk.LEFT, padx=(0, 15))

        ttk.Label(row2, text="输出目录:").pack(side=tk.LEFT, padx=(0, 5))
        self.output_dir_var = tk.StringVar()
        ttk.Entry(row2, textvariable=self.output_dir_var, width=20).pack(side=tk.LEFT, padx=(0, 2))
        ttk.Button(row2, text="浏览", command=self._browse_output_dir).pack(side=tk.LEFT)

    def _create_control_section(self, parent):
        # 控制按钮
        ctrl_frame = ttk.Frame(parent)
        ctrl_frame.pack(fill=tk.X, pady=(0, 5))

        self.start_btn = ttk.Button(
            ctrl_frame, text="开始处理", style="Start.TButton",
            command=self._start_processing,
        )
        self.start_btn.pack(side=tk.LEFT, padx=(0, 10))

        self.stop_btn = ttk.Button(
            ctrl_frame, text="停止", command=self._stop_processing,
            state=tk.DISABLED,
        )
        self.stop_btn.pack(side=tk.LEFT, padx=(0, 10))

        ttk.Button(ctrl_frame, text="API 配置", command=self._open_api_config).pack(side=tk.LEFT, padx=(0, 10))

        self.unload_btn = ttk.Button(
            ctrl_frame, text="卸载模型", command=self._unload_model,
            state=tk.DISABLED,
        )
        self.unload_btn.pack(side=tk.LEFT, padx=(0, 10))

        self.status_label = ttk.Label(ctrl_frame, text="就绪", style="Status.TLabel")
        self.status_label.pack(side=tk.RIGHT)

        # 日志区域
        log_frame = ttk.LabelFrame(parent, text="日志", padding=5)
        log_frame.pack(fill=tk.BOTH, expand=True)

        # 进度信息
        progress_frame = ttk.Frame(log_frame)
        progress_frame.pack(fill=tk.X, pady=(0, 5))

        self.progress_label = ttk.Label(progress_frame, text="就绪", style="Status.TLabel")
        self.progress_label.pack(side=tk.LEFT)

        self.progress_bar = ttk.Progressbar(progress_frame, mode="determinate", length=300)
        self.progress_bar.pack(side=tk.RIGHT, fill=tk.X, expand=True)

        self.log_text = scrolledtext.ScrolledText(
            log_frame, height=8, font=("Consolas", 9),
            state=tk.DISABLED, wrap=tk.WORD,
        )
        self.log_text.pack(fill=tk.BOTH, expand=True)

    def _load_config(self):
        self.model_var.set(self.config.get("whisper_model", "large-v3"))
        self.lang_var.set(LANG_CODE.get(self.config.get("language", "zh"), "中文"))
        self.device_var.set(self.config.get("device", "auto"))
        self.translator_var.set(self.config.get("translator", "google"))
        self.target_lang_var.set(LANG_CODE.get(self.config.get("translate_to", "en"), "英文"))
        self.bilingual_var.set(self.config.get("bilingual", False))
        self.output_dir_var.set(self.config.get("output_dir", ""))

    def _save_config(self):
        self.config.set("whisper_model", self.model_var.get())
        self.config.set("language", LANG_DISPLAY.get(self.lang_var.get(), "zh"))
        self.config.set("device", self.device_var.get())
        self.config.set("translator", self.translator_var.get())
        self.config.set("translate_to", LANG_DISPLAY.get(self.target_lang_var.get(), "en"))
        self.config.set("bilingual", self.bilingual_var.get())
        self.config.set("output_dir", self.output_dir_var.get())
        self.config.save()

    def _add_files(self):
        filetypes = [
            ("媒体文件", " ".join(f"*{f}" for f in SUPPORTED_FORMATS)),
            ("音频文件", " ".join(f"*{f}" for f in AUDIO_FORMATS)),
            ("视频文件", " ".join(f"*{f}" for f in VIDEO_FORMATS)),
            ("所有文件", "*.*"),
        ]
        files = filedialog.askopenfilenames(filetypes=filetypes)
        if files:
            self.file_list.add_files(files)
            self._update_file_count()

    def _add_folder(self):
        folder = filedialog.askdirectory()
        if folder:
            self.file_list.add_files([folder])
            self._update_file_count()

    def _remove_selected(self):
        self.file_list.remove_selected()
        self._update_file_count()

    def _clear_files(self):
        self.file_list.clear()
        self._update_file_count()

    def _update_file_count(self):
        count = len(self.file_list.files)
        self.file_count_label.config(text=f"共 {count} 个文件")

    def _browse_output_dir(self):
        folder = filedialog.askdirectory()
        if folder:
            self.output_dir_var.set(folder)


    def _open_api_config(self):
        dialog = tk.Toplevel(self.root)
        dialog.title("API 配置")
        dialog.geometry("550x450")
        dialog.transient(self.root)
        dialog.grab_set()

        notebook = ttk.Notebook(dialog)
        notebook.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        # LLM 配置
        llm_frame = ttk.Frame(notebook, padding=10)
        notebook.add(llm_frame, text="LLM")

        # 厂商选择
        ttk.Label(llm_frame, text="厂商:").grid(row=0, column=0, sticky=tk.W, pady=5)
        provider_var = tk.StringVar(value="OpenAI")
        provider_combo = ttk.Combobox(
            llm_frame, textvariable=provider_var,
            values=list(LLM_PROVIDERS.keys()),
            state="readonly", width=15,
        )
        provider_combo.grid(row=0, column=1, sticky=tk.W, pady=5)

        ttk.Label(llm_frame, text="API Key:").grid(row=1, column=0, sticky=tk.W, pady=5)
        llm_key_var = tk.StringVar(value=self.config.get("llm_api_key", ""))
        ttk.Entry(llm_frame, textvariable=llm_key_var, width=50, show="*").grid(row=1, column=1, pady=5)

        ttk.Label(llm_frame, text="Base URL:").grid(row=2, column=0, sticky=tk.W, pady=5)
        llm_url_var = tk.StringVar(value=self.config.get("llm_base_url", "https://api.openai.com/v1"))
        url_entry = ttk.Entry(llm_frame, textvariable=llm_url_var, width=50)
        url_entry.grid(row=2, column=1, pady=5)

        ttk.Label(llm_frame, text="模型:").grid(row=3, column=0, sticky=tk.W, pady=5)
        llm_model_var = tk.StringVar(value=self.config.get("llm_model", "gpt-4o-mini"))
        model_frame = ttk.Frame(llm_frame)
        model_frame.grid(row=3, column=1, sticky=tk.W, pady=5)
        model_combo = ttk.Combobox(model_frame, textvariable=llm_model_var, width=38)
        model_combo.pack(side=tk.LEFT)

        def fetch_models():
            api_key = llm_key_var.get()
            base_url = llm_url_var.get().rstrip("/")
            if not api_key:
                messagebox.showwarning("警告", "请先输入 API Key")
                return
            try:
                import requests
                headers = {"Authorization": f"Bearer {api_key}"}
                resp = requests.get(f"{base_url}/models", headers=headers, timeout=10)
                resp.raise_for_status()
                models = [m["id"] for m in resp.json().get("data", [])]
                models.sort()
                model_combo["values"] = models
                if models:
                    llm_model_var.set(models[0])
                messagebox.showinfo("成功", f"获取到 {len(models)} 个模型")
            except Exception as e:
                messagebox.showerror("错误", f"获取模型失败: {e}")

        ttk.Button(model_frame, text="获取模型", command=fetch_models).pack(side=tk.LEFT, padx=5)

        def test_llm():
            api_key = llm_key_var.get()
            base_url = llm_url_var.get().rstrip("/")
            model = llm_model_var.get()
            if not api_key:
                messagebox.showwarning("警告", "请先输入 API Key")
                return
            try:
                import requests
                headers = {
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                }
                data = {
                    "model": model,
                    "messages": [{"role": "user", "content": "Hi"}],
                    "max_tokens": 10,
                }
                resp = requests.post(f"{base_url}/chat/completions", headers=headers, json=data, timeout=15)
                resp.raise_for_status()
                reply = resp.json()["choices"][0]["message"]["content"]
                messagebox.showinfo("连接成功", f"模型 {model} 响应正常\n返回: {reply}")
            except Exception as e:
                messagebox.showerror("连接失败", f"LLM 测试失败:\n{e}")

        ttk.Button(model_frame, text="测试连接", command=test_llm).pack(side=tk.LEFT, padx=5)

        def on_provider_change(*args):
            provider = provider_var.get()
            if provider in LLM_PROVIDERS:
                info = LLM_PROVIDERS[provider]
                llm_url_var.set(info["base_url"])
                model_combo["values"] = info["models"]
                if info["models"]:
                    llm_model_var.set(info["models"][0])

        provider_combo.bind("<<ComboboxSelected>>", on_provider_change)

        # DeepL 配置
        deepl_frame = ttk.Frame(notebook, padding=10)
        notebook.add(deepl_frame, text="DeepL")

        ttk.Label(deepl_frame, text="API Key:").grid(row=0, column=0, sticky=tk.W, pady=5)
        deepl_key_var = tk.StringVar(value=self.config.get("deepl_api_key", ""))
        ttk.Entry(deepl_frame, textvariable=deepl_key_var, width=50, show="*").grid(row=0, column=1, pady=5)

        def test_deepl():
            api_key = deepl_key_var.get()
            if not api_key:
                messagebox.showwarning("警告", "请先输入 API Key")
                return
            try:
                from translate_api import DeepLTranslator
                t = DeepLTranslator(api_key)
                result = t.translate("Hello", "EN", "ZH")
                messagebox.showinfo("连接成功", f"DeepL 响应正常\nHello → {result}")
            except Exception as e:
                messagebox.showerror("连接失败", f"DeepL 测试失败:\n{e}")

        ttk.Button(deepl_frame, text="测试连接", command=test_deepl).grid(row=1, column=1, sticky=tk.W, pady=5)

        # 百度配置
        baidu_frame = ttk.Frame(notebook, padding=10)
        notebook.add(baidu_frame, text="百度")

        ttk.Label(baidu_frame, text="App ID:").grid(row=0, column=0, sticky=tk.W, pady=5)
        baidu_id_var = tk.StringVar(value=self.config.get("baidu_app_id", ""))
        ttk.Entry(baidu_frame, textvariable=baidu_id_var, width=50).grid(row=0, column=1, pady=5)

        ttk.Label(baidu_frame, text="Secret Key:").grid(row=1, column=0, sticky=tk.W, pady=5)
        baidu_key_var = tk.StringVar(value=self.config.get("baidu_secret_key", ""))
        ttk.Entry(baidu_frame, textvariable=baidu_key_var, width=50, show="*").grid(row=1, column=1, pady=5)

        def test_baidu():
            app_id = baidu_id_var.get()
            secret_key = baidu_key_var.get()
            if not app_id or not secret_key:
                messagebox.showwarning("警告", "请先输入 App ID 和 Secret Key")
                return
            try:
                from translate_api import BaiduTranslator
                t = BaiduTranslator(app_id, secret_key)
                result = t.translate("Hello", "en", "zh")
                messagebox.showinfo("连接成功", f"百度翻译 响应正常\nHello → {result}")
            except Exception as e:
                messagebox.showerror("连接失败", f"百度翻译测试失败:\n{e}")

        ttk.Button(baidu_frame, text="测试连接", command=test_baidu).grid(row=2, column=1, sticky=tk.W, pady=5)

        # 有道配置
        youdao_frame = ttk.Frame(notebook, padding=10)
        notebook.add(youdao_frame, text="有道")

        ttk.Label(youdao_frame, text="App Key:").grid(row=0, column=0, sticky=tk.W, pady=5)
        youdao_key_var = tk.StringVar(value=self.config.get("youdao_app_key", ""))
        ttk.Entry(youdao_frame, textvariable=youdao_key_var, width=50).grid(row=0, column=1, pady=5)

        ttk.Label(youdao_frame, text="App Secret:").grid(row=1, column=0, sticky=tk.W, pady=5)
        youdao_secret_var = tk.StringVar(value=self.config.get("youdao_app_secret", ""))
        ttk.Entry(youdao_frame, textvariable=youdao_secret_var, width=50, show="*").grid(row=1, column=1, pady=5)

        def test_youdao():
            app_key = youdao_key_var.get()
            app_secret = youdao_secret_var.get()
            if not app_key or not app_secret:
                messagebox.showwarning("警告", "请先输入 App Key 和 App Secret")
                return
            try:
                from translate_api import YoudaoTranslator
                t = YoudaoTranslator(app_key, app_secret)
                result = t.translate("Hello", "en", "zh-CHS")
                messagebox.showinfo("连接成功", f"有道翻译 响应正常\nHello → {result}")
            except Exception as e:
                messagebox.showerror("连接失败", f"有道翻译测试失败:\n{e}")

        ttk.Button(youdao_frame, text="测试连接", command=test_youdao).grid(row=2, column=1, sticky=tk.W, pady=5)

        def save_api_config():
            from translate_api import load_config as load_translate_config, save_config as save_translate_config

            self.config.set("llm_api_key", llm_key_var.get())
            self.config.set("llm_base_url", llm_url_var.get())
            self.config.set("llm_model", llm_model_var.get())
            self.config.set("deepl_api_key", deepl_key_var.get())
            self.config.set("baidu_app_id", baidu_id_var.get())
            self.config.set("baidu_secret_key", baidu_key_var.get())
            self.config.set("youdao_app_key", youdao_key_var.get())
            self.config.set("youdao_app_secret", youdao_secret_var.get())

            config_data = load_translate_config()
            changed = False
            if baidu_id_var.get() and baidu_key_var.get():
                config_data["baidu"] = {
                    "app_id": baidu_id_var.get(),
                    "secret_key": baidu_key_var.get(),
                }
                changed = True
            if youdao_key_var.get() and youdao_secret_var.get():
                config_data["youdao"] = {
                    "app_key": youdao_key_var.get(),
                    "app_secret": youdao_secret_var.get(),
                }
                changed = True
            if changed:
                save_translate_config(config_data)

            self.config.save()
            messagebox.showinfo("成功", "API 配置已保存")
            dialog.destroy()

        btn_frame = ttk.Frame(dialog)
        btn_frame.pack(fill=tk.X, padx=10, pady=10)
        ttk.Button(btn_frame, text="保存", command=save_api_config).pack(side=tk.RIGHT, padx=5)
        ttk.Button(btn_frame, text="取消", command=dialog.destroy).pack(side=tk.RIGHT)

    def _log(self, message):
        self.log_text.config(state=tk.NORMAL)
        self.log_text.insert(tk.END, message + "\n")
        self.log_text.see(tk.END)
        self.log_text.config(state=tk.DISABLED)

    def _update_status(self, text):
        self.status_label.config(text=text)

    def _update_progress(self, value, maximum=100):
        self.progress_bar["mode"] = "determinate"
        self.progress_bar["maximum"] = maximum
        self.progress_bar["value"] = value
        percent = int(value / maximum * 100) if maximum > 0 else 0
        self.progress_label.config(text=f"进度: {value}/{maximum} ({percent}%)")

    def _start_indeterminate(self):
        self.progress_bar["mode"] = "indeterminate"
        self.progress_bar.start(15)

    def _start_processing(self):
        files = self.file_list.files
        if not files:
            messagebox.showwarning("警告", "请先添加文件")
            return

        self._save_config()
        self.is_processing = True
        self.stop_event.clear()
        self.start_btn.config(state=tk.DISABLED)
        self.stop_btn.config(state=tk.NORMAL)

        thread = threading.Thread(target=self._process_files, args=(files,), daemon=True)
        thread.start()

    def _stop_processing(self):
        self.stop_event.set()
        self._log("正在停止...")

    def _process_files(self, files):
        try:
            import whisper
            import torch
            from translate_api import create_translator

            # 加载模型
            model_name = self.model_var.get()
            device = self.device_var.get()
            if device == "auto":
                device = "cuda" if torch.cuda.is_available() else "cpu"

            model_dir = PROJECT_DIR / "whisper"
            self.root.after(0, self._log, f"模型缓存目录: {model_dir}")
            self.root.after(0, self._log, f"正在加载模型 {model_name}...")
            self.root.after(0, self._log, f"使用设备: {device}")

            model = whisper.load_model(model_name, device=device)
            self.model = model
            self.model_name = model_name
            self.root.after(0, self.unload_btn.config, {"state": tk.NORMAL})
            self.root.after(0, self._log, "模型加载完成")

            # 翻译器
            enable_translate = self.enable_translate_var.get()
            translator_type = self.translator_var.get()
            translate_to_raw = self.target_lang_var.get() if enable_translate else None
            translate_to = LANG_DISPLAY.get(translate_to_raw, translate_to_raw) if translate_to_raw else None
            translator = None

            if enable_translate and translate_to:
                translator_kwargs = {}
                if translator_type == "llm":
                    translator_kwargs = {
                        "api_key": self.config.get("llm_api_key", ""),
                        "base_url": self.config.get("llm_base_url", ""),
                        "model": self.config.get("llm_model", "gpt-4o-mini"),
                    }
                elif translator_type == "deepl":
                    translator_kwargs = {"api_key": self.config.get("deepl_api_key", "")}
                elif translator_type == "baidu":
                    translator_kwargs = {
                        "app_id": self.config.get("baidu_app_id", ""),
                        "secret_key": self.config.get("baidu_secret_key", ""),
                    }
                elif translator_type == "youdao":
                    translator_kwargs = {
                        "app_key": self.config.get("youdao_app_key", ""),
                        "app_secret": self.config.get("youdao_app_secret", ""),
                    }

                translator = create_translator(translator_type, **translator_kwargs)
                self.root.after(0, self._log, f"翻译器: {translator.get_name()}")
            else:
                self.root.after(0, self._log, "翻译功能已关闭，仅进行语音识别")

            # 处理文件
            total_files = len(files)
            for i, file_path in enumerate(files):
                if self.stop_event.is_set():
                    self.root.after(0, self._log, "处理已停止")
                    break

                file_name = Path(file_path).name
                self.root.after(0, self._update_status, f"[{i+1}/{total_files}] {file_name}")
                self.root.after(0, self._log, f"\n[{i+1}/{total_files}] 处理: {file_name}")

                try:
                    # 识别阶段 — 进度条不确定
                    self.root.after(0, self._update_progress, i, total_files)
                    self.root.after(0, self.progress_label.config,
                        {"text": f"[{i+1}/{total_files}] 正在识别: {file_name}"})

                    language = LANG_DISPLAY.get(self.lang_var.get(), self.lang_var.get())
                    transcribe_options = {"verbose": False}
                    if language != "auto":
                        transcribe_options["language"] = language

                    result = model.transcribe(file_path, **transcribe_options)
                    detected_lang = result.get("language", "unknown")
                    segments = result["segments"]
                    seg_count = len(segments)

                    # 识别完成后检查是否已按下停止
                    if self.stop_event.is_set():
                        self.root.after(0, self._log, "处理已停止")
                        break

                    self.root.after(0, self._log, f"  识别语言: {detected_lang}, 共 {seg_count} 句")

                    # 生成 SRT
                    srt_content = segments_to_srt(segments)

                    # 输出路径
                    output_dir = self.output_dir_var.get()
                    out_path = Path(output_dir) if output_dir else Path(file_path).parent
                    stem = Path(file_path).stem

                    # 保存原文字幕
                    srt_path = out_path / f"{stem}.srt"
                    srt_path.write_text(srt_content, encoding="utf-8")
                    self.root.after(0, self._log, f"  原文字幕: {srt_path}")

                    # 翻译阶段 — 进度条按句显示
                    if translator and translate_to:
                        self.root.after(0, self._log, f"  翻译中: {detected_lang} -> {translate_to}")
                        self.root.after(0, self._update_progress, 0, seg_count)

                        def progress_callback(current, total, text, result_text):
                            self.root.after(0, self._update_progress, current, total)
                            self.root.after(0, self._log,
                                f"  [{current}/{total}] {text[:30]}... -> {result_text[:30]}...")

                        translated_srt = translate_srt(
                            srt_content,
                            translator_type,
                            detected_lang,
                            translate_to,
                            progress_callback=progress_callback,
                            stop_event=self.stop_event,
                            **translator_kwargs,
                        )

                        if self.bilingual_var.get():
                            original_segments = parse_srt(srt_content)
                            translated_segments = parse_srt(translated_srt)
                            trans_content = build_bilingual_srt(original_segments, translated_segments)
                        else:
                            trans_content = translated_srt

                        trans_path = out_path / f"{stem}.{translate_to}.srt"
                        trans_path.write_text(trans_content, encoding="utf-8")
                        self.root.after(0, self._log, f"  翻译字幕: {trans_path}")

                except Exception as e:
                    self.root.after(0, self._log, f"  错误: {e}")

            self.root.after(0, self._update_progress, total_files, total_files)
            self.root.after(0, self._log, "\n处理完成!")

        except Exception as e:
            self.root.after(0, self._log, f"错误: {e}")
        finally:
            self.root.after(0, self._processing_done)

    def _unload_model(self):
        if self.model is None:
            messagebox.showinfo("提示", "模型尚未加载")
            return
        try:
            import torch
            model_name = self.model_name if hasattr(self, 'model_name') else "unknown"
            del self.model
            self.model = None
            torch.cuda.empty_cache()
            self.unload_btn.config(state=tk.DISABLED)
            self._log(f"模型已从内存中卸载，显存已释放")
        except Exception as e:
            self._log(f"卸载模型失败: {e}")

    def _processing_done(self):
        self.is_processing = False
        self.progress_bar.stop()
        self.start_btn.config(state=tk.NORMAL)
        self.stop_btn.config(state=tk.DISABLED)
        self._update_status("完成")


    def run(self):
        self.root.mainloop()


def main():
    try:
        app = WhisperGUI()
        app.run()
    except Exception as e:
        print(f"启动失败: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
