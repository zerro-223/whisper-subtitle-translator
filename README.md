# Whisper 字幕识别 + 翻译

基于 OpenAI Whisper 的本地音视频字幕识别工具，支持多种翻译引擎将字幕翻译为目标语言。

## 功能

- **离线语音识别** — 使用本地 Whisper 模型（支持 tiny / base / small / medium / large-v3），无需联网
- **SRT 字幕输出** — 自动生成标准 SRT 格式字幕文件
- **多引擎翻译** — 支持 Google 翻译（免费）、LLM（兼容 OpenAI API）、DeepL、百度翻译、有道翻译
- **双语字幕** — 可生成原文+译文双语字幕
- **批量处理** — 支持拖放添加多个音视频文件
- **GUI + CLI** — 图形界面和命令行两种使用方式
- **GPU 加速** — 自动检测 CUDA，支持 CPU/CUDA 切换

## 环境要求

- Python 3.10+
- [PyTorch](https://pytorch.org/)（建议 CUDA 12.x 版本以获得 GPU 加速）
- [openai-whisper](https://github.com/openai/whisper)

## 安装

```bash
# 克隆仓库
git clone <repo-url>
cd translate-workflow

# 安装依赖
pip install -r requirements.txt
```

首次运行时，Whisper 模型会自动下载到项目目录下的 `whisper/` 文件夹。也可以手动下载模型文件（`.pt`）放入该目录。

## 快速开始

### GUI 方式

```bash
python gui.py
```

或双击 `start.bat`（Windows）。

操作步骤：
1. 点击「添加文件」选择音视频文件，或直接拖入
2. 选择识别模型和语言（推荐 large-v3 + auto）
3. 勾选「启用翻译」，选择翻译器和目标语言
4. 点击「开始处理」

### 命令行方式

```bash
# 仅识别，输出 SRT 字幕
python whisper_transcribe.py input.mp3

# 识别并翻译为中文
python whisper_transcribe.py input.mp3 -t zh

# 使用 LLM 翻译
python whisper_transcribe.py input.mp3 -t zh -T llm --api-key sk-xxx --base-url https://api.deepseek.com/v1

# 生成双语字幕
python whisper_transcribe.py input.mp3 -t zh --bilingual

# 完整参数
python whisper_transcribe.py input.mp3 \
  -m large-v3 \        # 模型
  -l auto \             # 识别语言
  -d cuda \             # 设备
  -t zh \               # 目标语言
  -T google \           # 翻译器
  --bilingual \         # 双语字幕
  -o ./subtitles        # 输出目录
```

## 支持的格式

| 类型 | 格式 |
|------|------|
| 音频 | `.mp3` `.wav` `.flac` `.aac` `.ogg` `.m4a` `.wma` |
| 视频 | `.mp4` `.mkv` `.avi` `.mov` `.wmv` `.flv` `.webm` `.m4v` |

## 翻译引擎

| 翻译器 | 类型 | 需要配置 |
|--------|------|----------|
| Google 翻译 | 免费 | 无 |
| LLM（OpenAI 兼容） | API | API Key + Base URL + 模型名 |
| DeepL | API | API Key |
| 百度翻译 | API | App ID + Secret Key |
| 有道翻译 | API | App Key + App Secret |

### LLM 厂商预设

内置以下厂商的 API 地址和模型列表，在 GUI 中切换厂商即可自动填充：

- OpenAI — `api.openai.com`
- DeepSeek — `api.deepseek.com`
- 通义千问 — `dashscope.aliyuncs.com`
- 智谱 AI — `open.bigmodel.cn`
- 文心一言 — `aip.baidubce.com`
- Moonshot — `api.moonshot.cn`
- 百川 — `api.baichuan-ai.com`
- 零一万物 — `api.lingyiwanwu.com`
- 自定义 — 手动输入

其他兼容 OpenAI API 格式的服务同样支持，选择「自定义」并填入对应地址即可。

## 配置

GUI 中的设置会自动保存到 `config.json`。

首次使用前请复制配置模板：
```bash
cp config.example.json config.json
```

API 密钥保存在本地 `config.json` 中，**请勿将此文件提交到版本控制**。

## 输出说明

- 原文字幕：`{文件名}.srt`
- 翻译字幕：`{文件名}.{目标语言}.srt`（如 `video.zh.srt`）
- 双语字幕前缀同上，内容包含原文和译文

## 项目结构

```
translate-workflow/
├── gui.py                  # GUI 主界面
├── whisper_transcribe.py   # 命令行入口 + 核心识别逻辑
├── translate_api.py        # 翻译 API 集成（Google/LLM/DeepL/百度/有道）
├── config.example.json     # 配置模板
├── config.json             # 用户配置（已 gitignore）
├── requirements.txt        # Python 依赖
├── start.bat               # Windows 一键启动
├── input/                  # 输入文件目录（已 gitignore）
├── output/                 # 输出文件目录（已 gitignore）
└── whisper/                # Whisper 模型缓存（已 gitignore）
```

## License

MIT
