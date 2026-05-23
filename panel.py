#!/usr/bin/env python3
"""
Web control panel for the multi-AI dialogue runner.

The panel uses only the Python standard library. It lets you edit dialogue
frequency, model enable switches, model names, and each model's persona prompt,
then starts the API dialogue in a background thread.
"""

import base64
import io
import json
import os
import re
import secrets
import socket
import threading
import time
import zipfile
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote, urlparse

from api_dialogue import (
    CONFIG_FILE,
    LOG_FILE,
    PROVIDER_CALLERS,
    append_entry,
    build_user_prompt,
    choose_next_natural_speaker,
    enabled_models,
    ensure_config,
    export_markdown,
    compact_call_error,
    format_call_failure,
    load_dotenv,
    load_log,
    save_json,
    save_log,
)


FOLDER = Path(__file__).resolve().parent
HOST = os.environ.get("PANEL_HOST", "0.0.0.0")
PORT = int(os.environ.get("PORT") or os.environ.get("PANEL_PORT", "5000"))
EXPORT_INDEX_FILE = FOLDER / "export_index.json"

MODE_PRESETS = {
    "chat": {
        "label": "闲聊",
        "goal": "四个 AI 像朋友一样围绕用户的话题自然接话。不要做报告，不要列清单，优先使用连续的句子和轻松的短段落。",
        "prompts": {
            "claude": "你是 Claude。你说话温和、细腻、会认真接住对方的情绪。闲聊模式下不要列条目，不要分析式总结，用自然连续的句子回应，像一个耐心又聪明的朋友。",
            "chatgpt": "你是 ChatGPT。你擅长把话题接得顺、让聊天继续自然流动。闲聊模式下避免标题和列表，用轻松清楚的段落说话，可以适当追问，但不要像在写方案。",
            "deepseek": "你是 DeepSeek。你反应直接，偶尔有一点幽默，会把复杂想法说得接地气。闲聊模式下用口语化连续句子，不要写成分析报告。",
            "gemini": "你是 Gemini。你联想丰富，喜欢从不同角度补充话题。闲聊模式下用自然段落表达，保持轻快，不要堆概念或列点。",
        },
    },
    "work": {
        "label": "工作",
        "goal": "四个 AI 围绕用户任务协作，快速给出清晰、可执行、可检查的建议。可以使用简洁列表，但避免空泛长篇。",
        "prompts": {
            "claude": "你是 Claude。你负责审慎判断、发现风险、补齐遗漏。工作模式下说话清晰克制，先给结论，再给必要理由和下一步。",
            "chatgpt": "你是 ChatGPT。你负责整合信息、拆解任务、形成可执行方案。工作模式下结构清楚，少废话，必要时使用短列表。",
            "deepseek": "你是 DeepSeek。你负责技术细节、实现路径、成本和效率。工作模式下直接指出可操作步骤、边界条件和可能踩坑的地方。",
            "gemini": "你是 Gemini。你负责补充视角、替代方案和长上下文关联。工作模式下给出有用的扩展，不要发散到任务之外。",
        },
    },
    "study": {
        "label": "钻研",
        "goal": "四个 AI 围绕问题深入推敲，追问前提、拆解机制、比较路径，并把讨论推进到更扎实的理解。",
        "prompts": {
            "claude": "你是 Claude。你负责严谨推理和概念澄清。钻研模式下可以分层分析，但每一层都要推进问题，不要只罗列名词。",
            "chatgpt": "你是 ChatGPT。你负责搭建学习路径和解释框架。钻研模式下可以使用结构化表达，重点是让问题变得更可理解、更可验证。",
            "deepseek": "你是 DeepSeek。你负责底层原理、技术机制和反例测试。钻研模式下多问为什么，指出假设和可能的反例。",
            "gemini": "你是 Gemini。你负责跨领域类比和综合视角。钻研模式下可以展开，但要回到主问题，不要只做漂亮比喻。",
        },
    },
    "abstract": {
        "label": "抽象",
        "goal": "四个 AI 以网络用语里的“抽象”风格围绕用户话题接梗、造梗和整活。可以离谱、怪、好笑，但要能接住原话题，不要变成哲学论文或空洞谜语。",
        "prompts": {
            "claude": "你是 Claude。抽象模式下你要像一个温和但会接梗的网友：认真听懂话题，再用一点离谱比喻、反差表达和轻微怪话把气氛带起来。不要写成哲学分析，不要端着。",
            "chatgpt": "你是 ChatGPT。抽象模式下你负责让怪话仍然好懂：可以玩梗、调侃、用网络语气接话，但别硬堆热词。回答要像聊天里的抽象段子，不要列清单，不要写方案。",
            "deepseek": "你是 DeepSeek。抽象模式下你可以更直接、更损一点，用接地气的怪比喻、反差吐槽和短句推进话题。要好笑但不恶意，不要把抽象变成骂人或阴阳怪气。",
            "gemini": "你是 Gemini。抽象模式下你负责发散梗感和画面感：把用户话题拐成有点离谱但能看懂的场景、梗图感描述或网络怪话。保持轻快，不要故弄玄虚。",
        },
    },
}

STATE_LOCK = threading.Lock()
RUNNER_THREAD = None
RUNNER_STATE = {
    "running": False,
    "stop_requested": False,
    "current_model": None,
    "started_at": None,
    "finished_at": None,
    "last_error": None,
    "completed_calls": 0,
    "total_calls": 0,
}


def read_json_body(handler):
    length = int(handler.headers.get("Content-Length", "0") or "0")
    if length <= 0:
        return {}
    raw = handler.rfile.read(length).decode("utf-8")
    return json.loads(raw or "{}")


def response_json(handler, data, status=200):
    body = json.dumps(data, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def response_html(handler, html):
    body = html.encode("utf-8")
    handler.send_response(200)
    handler.send_header("Content-Type", "text/html; charset=utf-8")
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def response_text(handler, text, status=200):
    body = text.encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "text/plain; charset=utf-8")
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def panel_credentials():
    password = os.environ.get("PANEL_PASSWORD", "").strip()
    if not password:
        return None, None
    return os.environ.get("PANEL_USER", "panel").strip() or "panel", password


def authorized(handler):
    _user, password = panel_credentials()
    if not password:
        return True

    header = handler.headers.get("Authorization", "")
    if not header.startswith("Basic "):
        return False
    try:
        raw = base64.b64decode(header[6:], validate=True).decode("utf-8")
    except (ValueError, UnicodeDecodeError):
        return False
    _provided_user, sep, provided_password = raw.partition(":")
    return bool(sep) and secrets.compare_digest(provided_password, password)


def require_auth(handler):
    handler.send_response(401)
    handler.send_header("WWW-Authenticate", 'Basic realm="AI Panel"')
    handler.send_header("Cache-Control", "no-store")
    handler.end_headers()


def response_download(handler, path, filename, content_type):
    if not path.exists():
        body = "".encode("utf-8")
    else:
        body = path.read_bytes()
    handler.send_response(200)
    handler.send_header("Content-Type", content_type)
    encoded_name = quote(filename)
    fallback_name = "dialogue_export." + filename.rsplit(".", 1)[-1]
    handler.send_header(
        "Content-Disposition",
        f'attachment; filename="{fallback_name}"; filename*=UTF-8\'\'{encoded_name}',
    )
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def response_export_bundle(handler):
    markdown_path = FOLDER / "api_dialogue.md"
    json_path = LOG_FILE
    base_name = export_filename("zip").rsplit(".", 1)[0]
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(f"{base_name}.md", markdown_path.read_text(encoding="utf-8") if markdown_path.exists() else "")
        archive.writestr(f"{base_name}.json", json_path.read_text(encoding="utf-8") if json_path.exists() else "[]")
    body = buffer.getvalue()
    encoded_name = quote(f"{base_name}.zip")
    handler.send_response(200)
    handler.send_header("Content-Type", "application/zip")
    handler.send_header(
        "Content-Disposition",
        f'attachment; filename="dialogue_export.zip"; filename*=UTF-8\'\'{encoded_name}',
    )
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def access_urls(host, port):
    if host not in ("", "0.0.0.0", "::"):
        return [f"http://{host}:{port}"]

    ips = {"127.0.0.1"}
    try:
        ips.update(socket.gethostbyname_ex(socket.gethostname())[2])
    except OSError:
        pass
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("8.8.8.8", 80))
            ips.add(sock.getsockname()[0])
    except OSError:
        pass

    def sort_key(ip):
        return (ip.startswith("127."), ip)

    return [f"http://{ip}:{port}" for ip in sorted(ips, key=sort_key) if not ip.startswith("169.254.")]


def safe_filename_part(text, fallback="对话记录", max_length=36):
    text = (text or "").strip()
    if not text:
        text = fallback
    text = re.sub(r"\s+", "_", text)
    text = re.sub(r'[\\/:*?"<>|]+', "", text)
    text = re.sub(r"_+", "_", text).strip("._ ")
    return (text or fallback)[:max_length]


def export_filename(extension):
    log = load_log()
    topic = next((item.get("content", "") for item in log if item.get("role") == "user"), "对话记录")
    topic = safe_filename_part(topic)
    date_part = datetime.now().strftime("%Y%m%d")
    key = f"{topic}_{date_part}"
    try:
        index = json.loads(EXPORT_INDEX_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        index = {}
    next_index = int(index.get(key, 0)) + 1
    index[key] = next_index
    save_json(EXPORT_INDEX_FILE, index)
    return f"{topic}_{date_part}_{next_index:03d}.{extension}"


def public_config():
    config = ensure_config()
    config["mode_presets"] = MODE_PRESETS
    return config


def apply_mode_preset(config, mode):
    preset = MODE_PRESETS.get(mode)
    if not preset:
        return config
    config["dialogue_mode"] = mode
    config["conversation_goal"] = preset["goal"]
    for model in config.get("models", []):
        prompt = preset["prompts"].get(model.get("id"))
        if prompt:
            model["system_prompt"] = prompt
    return config


def save_config_from_payload(payload):
    config = ensure_config()
    if payload.get("apply_mode_preset"):
        apply_mode_preset(config, payload.get("dialogue_mode"))
    for key in ["max_rounds", "delay_seconds", "max_output_tokens", "response_min_chars", "response_max_chars", "response_target_chars", "continue_on_error", "conversation_goal", "dialogue_mode", "turn_mode", "natural_pick_strategy", "max_consecutive_turns", "natural_balance_enabled", "natural_balance_window", "natural_balance_strength", "natural_silence_fallback", "self_memory_turns"]:
        if key in payload:
            config[key] = payload[key]
    config["natural_selector"] = "all"

    incoming_models = {model["id"]: model for model in payload.get("models", []) if model.get("id")}
    for model in config.get("models", []):
        update = incoming_models.get(model.get("id"))
        if not update:
            continue
        for field in ["enabled", "name", "avatar", "model", "base_url", "speaker_weight", "system_prompt"]:
            if field in update:
                model[field] = update[field]

    save_json(CONFIG_FILE, config)
    return config


def current_status():
    with STATE_LOCK:
        return dict(RUNNER_STATE)


def set_status(**kwargs):
    with STATE_LOCK:
        RUNNER_STATE.update(kwargs)


def count_enabled_calls(config, rounds):
    return rounds * len(enabled_models(config))


def sleep_with_stop(delay_seconds):
    end_at = time.time() + max(0, delay_seconds)
    while time.time() < end_at:
        if current_status().get("stop_requested"):
            return False
        time.sleep(min(0.25, end_at - time.time()))
    return True


def dialogue_worker(config, prompt, reset, rounds):
    load_dotenv(FOLDER / ".env")
    log = [] if reset else load_log()
    if prompt:
        append_entry(log, "user", prompt)
        save_log(log)

    delay_seconds = float(config.get("delay_seconds", 1))
    max_tokens = int(config.get("max_output_tokens", 1200))
    continue_on_error = bool(config.get("continue_on_error", True))
    turn_mode = config.get("turn_mode", "fixed")

    set_status(
        running=True,
        stop_requested=False,
        current_model=None,
        started_at=datetime.now().isoformat(timespec="seconds"),
        finished_at=None,
        last_error=None,
        completed_calls=0,
        total_calls=count_enabled_calls(config, rounds),
    )

    try:
        if turn_mode == "natural":
            total_steps = rounds * len(enabled_models(config))
            for _step in range(total_steps):
                if current_status().get("stop_requested"):
                    return
                log = load_log()
                set_status(current_model="选择发言者")
                model_config, _decisions = choose_next_natural_speaker(config, log)
                if not model_config:
                    set_status(last_error="没有 AI 想继续发言")
                    return

                set_status(current_model=model_config.get("name"))
                caller = PROVIDER_CALLERS.get(model_config.get("provider"))
                if not caller:
                    raise RuntimeError(f"Unsupported provider: {model_config.get('provider')}")

                log = load_log()
                prompt_for_model = build_user_prompt(config, log, model_config)
                try:
                    content = caller(model_config, prompt_for_model, max_tokens)
                except Exception as exc:
                    if not continue_on_error:
                        raise
                    content = format_call_failure(exc)
                    set_status(last_error=compact_call_error(exc))

                log = load_log()
                append_entry(log, "assistant", content, model_config)
                save_log(log)
                with STATE_LOCK:
                    RUNNER_STATE["completed_calls"] += 1

                if not sleep_with_stop(delay_seconds):
                    return
        else:
            for _round in range(rounds):
                for model_config in config.get("models", []):
                    if current_status().get("stop_requested"):
                        return
                    if not model_config.get("enabled", True):
                        continue

                    log = load_log()
                    set_status(current_model=model_config.get("name"))
                    caller = PROVIDER_CALLERS.get(model_config.get("provider"))
                    if not caller:
                        raise RuntimeError(f"Unsupported provider: {model_config.get('provider')}")

                    prompt_for_model = build_user_prompt(config, log, model_config)
                    try:
                        content = caller(model_config, prompt_for_model, max_tokens)
                    except Exception as exc:
                        if not continue_on_error:
                            raise
                        content = format_call_failure(exc)
                        set_status(last_error=compact_call_error(exc))

                    log = load_log()
                    append_entry(log, "assistant", content, model_config)
                    save_log(log)
                    with STATE_LOCK:
                        RUNNER_STATE["completed_calls"] += 1

                    if not sleep_with_stop(delay_seconds):
                        return
    except Exception as exc:
        set_status(last_error=compact_call_error(exc))
    finally:
        set_status(
            running=False,
            current_model=None,
            finished_at=datetime.now().isoformat(timespec="seconds"),
        )


def start_dialogue(payload):
    global RUNNER_THREAD
    if current_status().get("running"):
        return {"ok": False, "error": "对话正在运行中"}, 409

    config = save_config_from_payload(payload.get("config", {}))
    prompt = (payload.get("prompt") or "").strip()
    reset = bool(payload.get("reset", True))
    rounds = int(payload.get("rounds") or config.get("max_rounds", 1))

    if reset and not prompt:
        return {"ok": False, "error": "新对话需要输入提示词"}, 400
    if not reset and not prompt and not LOG_FILE.exists():
        return {"ok": False, "error": "没有历史日志，请输入提示词开始"}, 400

    RUNNER_THREAD = threading.Thread(
        target=dialogue_worker,
        args=(config, prompt, reset, rounds),
        daemon=True,
    )
    RUNNER_THREAD.start()
    return {"ok": True, "status": current_status()}, 200


def stop_dialogue():
    if current_status().get("running"):
        set_status(stop_requested=True)
        return {"ok": True, "message": "已请求停止，会在当前 API 调用结束后停下。"}, 200
    return {"ok": True, "message": "当前没有运行中的对话。"}, 200


def clear_dialogue():
    if current_status().get("running"):
        return {"ok": False, "error": "运行中不能清空日志"}, 409
    save_json(LOG_FILE, [])
    export_markdown([])
    return {"ok": True}, 200


class PanelHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        return

    def do_HEAD(self):
        if not authorized(self):
            require_auth(self)
            return
        path = urlparse(self.path).path
        if path == "/":
            body = HTML_TEMPLATE.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
        elif path in {"/api/config", "/api/dialogue", "/api/status"}:
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
        elif path in {"/health", "/debug"}:
            body = b"ok"
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
        else:
            self.send_response(404)
            self.send_header("Cache-Control", "no-store")
            self.end_headers()

    def do_GET(self):
        if not authorized(self):
            require_auth(self)
            return
        path = urlparse(self.path).path
        if path == "/":
            response_html(self, HTML_TEMPLATE)
        elif path == "/lite":
            response_html(self, LITE_TEMPLATE)
        elif path in {"/health", "/debug"}:
            response_text(
                self,
                "ok\n"
                "panel server is running\n"
                f"time: {datetime.now().isoformat(timespec='seconds')}\n"
                "try: http://127.0.0.1:5000/lite\n",
            )
        elif path == "/api/config":
            response_json(self, public_config())
        elif path == "/api/dialogue":
            messages = load_log()
            response_json(
                self,
                {
                    "messages": messages,
                    "total": len(messages),
                    "last_update": datetime.now().isoformat(timespec="seconds"),
                },
            )
        elif path == "/api/status":
            response_json(self, current_status())
        elif path == "/export/markdown":
            response_download(self, FOLDER / "api_dialogue.md", export_filename("md"), "text/markdown; charset=utf-8")
        elif path == "/export/json":
            response_download(self, LOG_FILE, export_filename("json"), "application/json; charset=utf-8")
        elif path == "/export/all":
            response_export_bundle(self)
        else:
            response_json(self, {"error": "Not found"}, 404)

    def do_POST(self):
        if not authorized(self):
            require_auth(self)
            return
        path = urlparse(self.path).path
        try:
            payload = read_json_body(self)
            if path == "/api/config":
                response_json(self, save_config_from_payload(payload))
            elif path == "/api/start":
                data, status = start_dialogue(payload)
                response_json(self, data, status)
            elif path == "/api/stop":
                data, status = stop_dialogue()
                response_json(self, data, status)
            elif path == "/api/clear":
                data, status = clear_dialogue()
                response_json(self, data, status)
            elif path == "/api/interject":
                text = (payload.get("content") or "").strip()
                if not text:
                    response_json(self, {"ok": False, "error": "插话内容不能为空"}, 400)
                    return
                log = load_log()
                append_entry(log, "user", text)
                save_log(log)
                response_json(self, {"ok": True})
            else:
                response_json(self, {"error": "Not found"}, 404)
        except Exception as exc:
            response_json(self, {"ok": False, "error": str(exc)}, 500)


HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>多 AI 对话控制台</title>
  <style>
    :root {
      color-scheme: light;
      --bg: #f4f6f8;
      --panel: #ffffff;
      --text: #1d232a;
      --muted: #6b7480;
      --line: #d9e0e7;
      --accent: #2563eb;
      --accent-dark: #1d4ed8;
      --danger: #b42318;
      --ok: #138a43;
      --soft: #eef4ff;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      min-height: 100vh;
      font-family: "Segoe UI", "Microsoft YaHei", Arial, sans-serif;
      background: var(--bg);
      color: var(--text);
    }
    header {
      border-bottom: 1px solid var(--line);
      background: var(--panel);
      padding: 14px 20px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
      position: sticky;
      top: 0;
      z-index: 5;
    }
    h1 { font-size: 20px; margin: 0; font-weight: 700; }
    .status {
      display: flex;
      gap: 10px;
      align-items: center;
      color: var(--muted);
      font-size: 14px;
      flex-wrap: wrap;
    }
    .dot {
      width: 9px;
      height: 9px;
      border-radius: 50%;
      background: #a0a8b2;
      display: inline-block;
    }
    .dot.running { background: var(--ok); }
    main {
      display: grid;
      grid-template-columns: minmax(0, 1fr) minmax(340px, 420px);
      gap: 18px;
      padding: 18px;
      max-width: 1500px;
      margin: 0 auto;
      align-items: start;
    }
    @media (max-width: 980px) {
      main { grid-template-columns: 1fr; }
      header { align-items: flex-start; flex-direction: column; }
    }
    @media (max-width: 700px) {
      header { padding: 12px; gap: 10px; }
      h1 { font-size: 18px; }
      main { padding: 10px; gap: 10px; }
      section { border-radius: 0; }
      .controls {
        max-height: none;
        overflow: visible;
        padding: 12px;
      }
      .row { grid-template-columns: 1fr; }
      .buttons {
        display: grid;
        grid-template-columns: 1fr 1fr;
        order: -1;
        position: sticky;
        top: 0;
        z-index: 8;
        margin: -4px -4px 0;
        padding: 8px;
        border: 1px solid var(--line);
        border-radius: 8px;
        background: var(--panel);
        box-shadow: 0 8px 18px rgba(15, 23, 42, .1);
      }
      .settings-grid { grid-template-columns: 1fr; }
      .mode-row { grid-template-columns: 1fr; }
      button { min-height: 42px; }
      .chat {
        order: 0;
        height: calc(100vh - 118px);
        min-height: 480px;
        max-height: none;
      }
      .chat-toolbar {
        align-items: flex-start;
        flex-direction: column;
      }
      .interject { grid-template-columns: 1fr; }
      .interject button { width: 100%; }
    }
    section {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
    }
    .controls {
      padding: 16px;
      display: grid;
      gap: 14px;
      align-content: start;
      max-height: calc(100vh - 92px);
      overflow: auto;
    }
    .section-title { font-size: 14px; font-weight: 700; color: var(--muted); margin-bottom: 8px; }
    label { display: grid; gap: 6px; font-size: 13px; color: var(--muted); }
    input, textarea, select {
      width: 100%;
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 10px 11px;
      font: inherit;
      color: var(--text);
      background: #fff;
    }
    textarea { resize: vertical; min-height: 92px; line-height: 1.5; }
    .row { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
    .settings-grid {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 10px;
      align-items: end;
    }
    .mode-row {
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto;
      gap: 10px;
      align-items: end;
    }
    body.fixed-turn label:has(#maxConsecutive) { display: none; }
    body.fixed-turn .row:has(#maxConsecutive) { grid-template-columns: 1fr; }
    .range-inputs {
      display: grid;
      grid-template-columns: minmax(58px, 1fr) auto minmax(58px, 1fr);
      gap: 8px;
      align-items: center;
    }
    .range-inputs input { text-align: center; }
    .range-inputs span { color: var(--muted); font-weight: 700; }
    .buttons {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 8px;
    }
    .tool-button,
    .link-button {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      gap: 7px;
      white-space: nowrap;
    }
    .icon {
      width: 18px;
      height: 18px;
      border-radius: 50%;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      font-size: 11px;
      font-weight: 900;
      line-height: 1;
      background: rgba(255,255,255,.22);
    }
    .secondary .icon,
    .link-button .icon {
      background: rgba(15,23,42,.09);
      color: var(--text);
    }
    .danger .icon { background: rgba(255,255,255,.24); }
    button {
      border: 0;
      border-radius: 6px;
      padding: 10px 14px;
      font: inherit;
      font-weight: 700;
      cursor: pointer;
      background: var(--accent);
      color: #fff;
    }
    button:hover { background: var(--accent-dark); }
    button.secondary { background: #e8edf3; color: var(--text); }
    button.secondary:hover { background: #dce4ed; }
    button.danger { background: var(--danger); }
    button:disabled { opacity: .55; cursor: not-allowed; }
    .models { display: grid; gap: 10px; }
    .model {
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 12px;
      display: grid;
      gap: 10px;
      background: #fbfcfd;
    }
    .model-head {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 10px;
    }
    .model-profile {
      display: grid;
      grid-template-columns: 86px 1fr;
      gap: 10px;
      align-items: end;
    }
    .model-title {
      display: inline-flex;
      align-items: center;
      gap: 9px;
      min-width: 0;
    }
    .model-avatar {
      width: 28px;
      height: 28px;
      border-radius: 50%;
      background: var(--model-color, var(--accent));
      color: #fff;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      font-size: 11px;
      font-weight: 800;
      overflow: hidden;
      object-fit: cover;
    }
    .avatar-input { min-width: 0; }
    .display-name-input { min-width: 0; }
    .model-avatar img,
    .avatar img {
      width: 100%;
      height: 100%;
      border-radius: inherit;
      object-fit: cover;
      display: block;
    }
    .toggle {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      color: var(--text);
      font-weight: 700;
    }
    .toggle input { width: auto; }
    .chat {
      order: -1;
      height: calc(100vh - 92px);
      min-height: 540px;
      max-height: 780px;
      display: grid;
      grid-template-rows: auto minmax(0, 1fr) auto;
    }
    .chat-toolbar {
      border-bottom: 1px solid var(--line);
      padding: 9px 12px;
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 12px;
      flex-wrap: wrap;
    }
    .messages {
      overflow: auto;
      padding: 16px 14px;
      display: grid;
      align-content: start;
      gap: 12px;
      background: #edf2f7;
      min-height: 0;
    }
    .msg {
      --speaker-color: var(--accent);
      --speaker-soft: #ffffff;
      display: flex;
      align-items: flex-start;
      gap: 9px;
      font-size: 13px;
      min-width: 0;
    }
    .msg.user {
      --speaker-color: #334155;
      --speaker-soft: #334155;
      flex-direction: row-reverse;
    }
    .avatar {
      width: 34px;
      height: 34px;
      border-radius: 50%;
      background: var(--speaker-color);
      color: #fff;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      font-weight: 800;
      font-size: 12px;
      flex: 0 0 auto;
      box-shadow: inset 0 -10px 18px rgba(0,0,0,.14);
      overflow: hidden;
    }
    .msg-body {
      min-width: 0;
      max-width: min(78%, 760px);
      display: grid;
      gap: 4px;
    }
    .msg.user .msg-body { justify-items: end; }
    .meta {
      display: flex;
      align-items: center;
      justify-content: flex-start;
      gap: 6px;
      color: var(--muted);
      font-size: 11px;
      flex-wrap: wrap;
    }
    .meta strong { color: var(--text); }
    .msg.user .meta { justify-content: flex-end; }
    .message-text {
      display: block;
      border: 1px solid rgba(15, 23, 42, .08);
      border-radius: 17px 17px 17px 5px;
      background: var(--speaker-soft);
      color: var(--text);
      padding: 9px 12px;
      white-space: pre-wrap;
      line-height: 1.45;
      box-shadow: 0 1px 2px rgba(15, 23, 42, .06);
    }
    .msg.user .message-text {
      border-color: transparent;
      border-radius: 17px 17px 5px 17px;
      color: #fff;
    }
    @media (max-width: 700px) {
      .model-profile { grid-template-columns: 1fr; }
      .messages { padding: 12px 10px; }
      .msg-body { max-width: calc(100% - 46px); }
    }
    .empty {
      color: var(--muted);
      text-align: center;
      padding: 60px 20px;
    }
    .typing {
      display: none;
      align-items: flex-start;
      gap: 9px;
      padding: 0 14px 12px;
      background: #edf2f7;
      max-width: 100%;
    }
    .typing.show { display: flex; }
    .typing .avatar {
      --speaker-color: #64748b;
      background: var(--speaker-color);
    }
    .typing-bubble {
      display: flex;
      align-items: center;
      gap: 8px;
      min-height: 34px;
      max-width: min(78%, 760px);
      border: 1px solid rgba(15, 23, 42, .08);
      border-radius: 17px 17px 17px 5px;
      background: #fff;
      color: var(--muted);
      padding: 8px 12px;
      font-size: 13px;
      line-height: 1.35;
      box-shadow: 0 1px 2px rgba(15, 23, 42, .06);
    }
    .typing-dots {
      display: inline-flex;
      gap: 3px;
      align-items: center;
    }
    .typing.waiting .typing-dots { display: none; }
    .typing-dots span {
      width: 4px;
      height: 4px;
      border-radius: 50%;
      background: var(--muted);
      animation: typingPulse 1s infinite ease-in-out;
    }
    .typing-dots span:nth-child(2) { animation-delay: .15s; }
    .typing-dots span:nth-child(3) { animation-delay: .3s; }
    @keyframes typingPulse {
      0%, 80%, 100% { opacity: .35; transform: translateY(0); }
      40% { opacity: 1; transform: translateY(-2px); }
    }
    .interject {
      border-top: 1px solid var(--line);
      padding: 10px 12px;
      display: grid;
      grid-template-columns: 1fr auto;
      gap: 10px;
      background: var(--panel);
    }
    .interject textarea { min-height: 42px; max-height: 82px; }
    .notice {
      color: var(--muted);
      font-size: 13px;
      line-height: 1.5;
    }
    .link-button {
      border-radius: 6px;
      padding: 8px 10px;
      background: #e8edf3;
      color: var(--text);
      text-decoration: none;
      font-weight: 700;
      font-size: 13px;
    }
    .link-button:hover { background: #dce4ed; }
    .export-menu { position: relative; }
    .export-options {
      position: absolute;
      right: 0;
      top: calc(100% + 6px);
      min-width: 168px;
      padding: 6px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: #fff;
      box-shadow: 0 12px 28px rgba(15, 23, 42, .14);
      display: none;
      z-index: 10;
    }
    .export-menu.open .export-options { display: grid; gap: 4px; }
    .export-options a {
      display: flex;
      align-items: center;
      gap: 8px;
      border-radius: 6px;
      padding: 8px 9px;
      color: var(--text);
      text-decoration: none;
      font-size: 13px;
      font-weight: 700;
    }
    .export-options a:hover { background: #eef2f6; }
  </style>
</head>
<body>
  <header>
    <h1>多 AI 对话控制台</h1>
    <div class="status">
      <span><i id="runDot" class="dot"></i> <span id="runText">待机</span></span>
      <span id="currentModel">当前模型：-</span>
      <span id="progressText">进度：0/0</span>
    </div>
  </header>
  <main>
    <section class="controls">
      <div>
        <div class="section-title">开始对话</div>
        <div class="mode-row">
          <label>
            对话模式
            <select id="dialogueMode" onchange="applyModePreset()">
              <option value="chat">闲聊</option>
              <option value="work">工作</option>
              <option value="study">钻研</option>
              <option value="abstract">抽象</option>
            </select>
          </label>
          <button class="secondary tool-button" type="button" onclick="applyModePreset()"><span class="icon">+</span><span>套用人格</span></button>
        </div>
        <label>
          对话目标
          <textarea id="goal"></textarea>
        </label>
        <label>
          初始提示词
          <textarea id="prompt" placeholder="输入你想让四个 AI 讨论的问题"></textarea>
        </label>
      </div>
      <div class="settings-grid">
        <label>
          轮数
          <input id="rounds" type="number" min="1" max="20" value="1" />
        </label>
        <label>
          发言方式
          <select id="turnMode">
            <option value="fixed">固定顺序</option>
            <option value="natural">自然抢话</option>
          </select>
        </label>
        <label>
          对话频率
          <select id="delay">
            <option value="0">连续</option>
            <option value="1">每 1 秒</option>
            <option value="3">每 3 秒</option>
            <option value="5">每 5 秒</option>
            <option value="10">每 10 秒</option>
          </select>
        </label>
        <label>
          连续发言上限
          <input id="maxConsecutive" type="number" min="1" max="5" value="1" />
        </label>
        <label>
          自我记忆
          <input id="selfMemoryTurns" type="number" min="0" max="20" value="5" />
        </label>
        <label>
          发言字数
          <span class="range-inputs">
            <input id="minChars" type="number" min="0" max="2000" step="20" />
            <span>-</span>
            <input id="maxChars" type="number" min="40" max="3000" step="20" />
          </span>
        </label>
        <label>
          API token
          <input id="maxTokens" type="number" min="100" max="8000" step="100" />
        </label>
        <label>
          出错处理
          <select id="continueOnError">
            <option value="true">失败后继续</option>
            <option value="false">失败后停止</option>
          </select>
        </label>
      </div>
      <div class="buttons">
        <button class="tool-button" id="startBtn" onclick="startDialogue()"><span class="icon">▶</span><span>开始</span></button>
        <button class="secondary tool-button" id="continueBtn" onclick="continueDialogue()"><span class="icon">↻</span><span>继续</span></button>
        <button class="secondary tool-button" id="stopBtn" onclick="stopDialogue()"><span class="icon">■</span><span id="stopLabel">停止</span></button>
        <button class="danger tool-button" onclick="clearDialogue()"><span class="icon">×</span><span>清空</span></button>
      </div>
      <div>
        <div class="section-title">AI 人格设置</div>
        <div id="models" class="models"></div>
      </div>
      <p class="notice">API key 只从本地 .env 读取，不会显示在网页里。修改人格后点开始会自动保存配置。</p>
    </section>
    <section class="chat">
      <div class="chat-toolbar">
        <strong>对话记录</strong>
        <div class="status">
          <div class="export-menu" id="exportMenu">
            <button class="secondary tool-button" type="button" onclick="toggleExportMenu(event)"><span class="icon">⇩</span><span>导出聊天记录</span></button>
            <div class="export-options">
              <a href="/export/markdown" onclick="closeExportMenu()"><span class="icon">MD</span><span>Markdown</span></a>
              <a href="/export/json" onclick="closeExportMenu()"><span class="icon">{}</span><span>JSON</span></a>
            </div>
          </div>
          <span class="notice" id="lastUpdate">最后更新：-</span>
        </div>
      </div>
      <div id="messages" class="messages">
        <div class="empty">还没有对话。输入提示词后点击开始。</div>
      </div>
      <div id="typingIndicator" class="typing">
        <span class="avatar" id="typingAvatar">AI</span>
        <span class="typing-bubble">
          <span id="typingText">正在输入</span>
          <span class="typing-dots"><span></span><span></span><span></span></span>
        </span>
      </div>
      <div class="interject">
        <textarea id="interjectText" placeholder="运行中也可以在这里插话，下一位 AI 会看到"></textarea>
        <button class="secondary tool-button" onclick="interject()"><span class="icon">+</span><span>插话</span></button>
      </div>
    </section>
  </main>
  <script>
    let config = null;
    let hasMessages = false;
    let stopRequestedByUser = false;
    let stoppedNoticeUntil = 0;

    async function api(path, options = {}) {
      const response = await fetch(path, {
        headers: { 'Content-Type': 'application/json' },
        ...options
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || '请求失败');
      return data;
    }

    function escapeHtml(text) {
      const div = document.createElement('div');
      div.textContent = text ?? '';
      return div.innerHTML;
    }

    const speakerStyles = {
      user: { avatar: '我', color: '#334155', soft: '#334155' },
      claude: { avatar: 'CL', color: '#b45f36', soft: '#fff7ed' },
      chatgpt: { avatar: 'GPT', color: '#16856b', soft: '#ecfdf5' },
      deepseek: { avatar: 'DS', color: '#2563eb', soft: '#eff6ff' },
      gemini: { avatar: 'GM', color: '#7c3aed', soft: '#f5f3ff' },
    };

    function getConfiguredModel(id) {
      return config?.models?.find(model => String(model.id).toLowerCase() === String(id).toLowerCase());
    }

    function getSpeakerStyle(message) {
      const id = (message.model_id || message.role || '').toLowerCase();
      const base = speakerStyles[id] || {
        avatar: (message.model_name || '?').slice(0, 2).toUpperCase(),
        color: '#64748b',
        soft: '#ffffff',
      };
      const configured = getConfiguredModel(id);
      return {
        ...base,
        avatar: message.avatar || configured?.avatar || base.avatar,
        name: configured?.name || message.model_name || message.role || id || 'AI',
      };
    }

    function isImageAvatar(value) {
      return /^(https?:\/\/|data:image\/|\/)/i.test((value || '').trim());
    }

    function renderAvatar(value, className = 'avatar') {
      const avatar = (value || '?').trim();
      if (isImageAvatar(avatar)) {
        return `<span class="${className}"><img src="${escapeHtml(avatar)}" alt="" /></span>`;
      }
      return `<span class="${className}">${escapeHtml(avatar.slice(0, 4))}</span>`;
    }

    async function loadConfig() {
      config = await api('/api/config');
      document.getElementById('rounds').value = config.max_rounds || 1;
      document.getElementById('turnMode').value = config.turn_mode || 'fixed';
      document.getElementById('delay').value = String(config.delay_seconds ?? 1);
      document.getElementById('maxConsecutive').value = config.max_consecutive_turns || 1;
      document.getElementById('selfMemoryTurns').value = config.self_memory_turns ?? 5;
      document.getElementById('dialogueMode').value = config.dialogue_mode || 'work';
      document.getElementById('goal').value = config.conversation_goal || '';
      document.getElementById('maxTokens').value = config.max_output_tokens || 1200;
      const legacyTarget = config.response_target_chars || 220;
      document.getElementById('minChars').value = config.response_min_chars || Math.round(legacyTarget * 0.75);
      document.getElementById('maxChars').value = config.response_max_chars || legacyTarget;
      document.getElementById('continueOnError').value = String(config.continue_on_error !== false);
      syncTurnModeUi();
      renderModels();
    }

    function renderModels() {
      const root = document.getElementById('models');
      root.innerHTML = config.models.map((model, index) => `
        <div class="model" data-index="${index}" style="--model-color: ${getSpeakerStyle({ model_id: model.id, model_name: model.name }).color};">
          <div class="model-head">
            <label class="toggle">
              <input type="checkbox" class="model-enabled" ${model.enabled !== false ? 'checked' : ''} />
              <span class="model-title">
                ${renderAvatar(model.avatar || getSpeakerStyle({ model_id: model.id, model_name: model.name }).avatar, 'model-avatar')}
                ${escapeHtml(model.name)}
              </span>
            </label>
            <span class="notice">${escapeHtml(model.provider)}</span>
          </div>
          <div class="model-profile">
            <label class="avatar-input">
              头像
              <input class="model-avatar-value" value="${escapeHtml(model.avatar || getSpeakerStyle({ model_id: model.id, model_name: model.name }).avatar)}" placeholder="文字或图片 URL" />
            </label>
            <label class="display-name-input">
              昵称
              <input class="model-display-name" value="${escapeHtml(model.name || '')}" />
            </label>
          </div>
          <label>
            模型名
            <input class="model-name" value="${escapeHtml(model.model)}" />
          </label>
          <label>
            发言权重
            <input class="model-weight" type="number" min="0.1" max="5" step="0.1" value="${escapeHtml(model.speaker_weight ?? 1)}" />
          </label>
          <label>
            人格设定
            <textarea class="model-prompt">${escapeHtml(model.system_prompt || '')}</textarea>
          </label>
        </div>
      `).join('');
    }

    function applyModePreset() {
      const mode = document.getElementById('dialogueMode').value;
      const preset = config.mode_presets?.[mode];
      if (!preset) return;
      config.dialogue_mode = mode;
      config.conversation_goal = preset.goal;
      config.models = config.models.map(model => ({
        ...model,
        system_prompt: preset.prompts?.[model.id] || model.system_prompt,
      }));
      document.getElementById('goal').value = config.conversation_goal;
      renderModels();
    }

    function syncTurnModeUi() {
      document.body.classList.toggle('fixed-turn', document.getElementById('turnMode').value !== 'natural');
    }

    function collectConfig() {
      const models = [...document.querySelectorAll('.model')].map(node => {
        const model = config.models[Number(node.dataset.index)];
        return {
          id: model.id,
          enabled: node.querySelector('.model-enabled').checked,
          name: node.querySelector('.model-display-name').value.trim() || model.name,
          avatar: node.querySelector('.model-avatar-value').value.trim(),
          model: node.querySelector('.model-name').value.trim(),
          speaker_weight: Number(node.querySelector('.model-weight').value || 1),
          system_prompt: node.querySelector('.model-prompt').value.trim(),
        };
      });
      return {
        max_rounds: Number(document.getElementById('rounds').value || 1),
        turn_mode: document.getElementById('turnMode').value,
        natural_selector: 'all',
        delay_seconds: Number(document.getElementById('delay').value || 0),
        max_consecutive_turns: Number(document.getElementById('maxConsecutive').value || 1),
        self_memory_turns: Number(document.getElementById('selfMemoryTurns').value || 0),
        max_output_tokens: Number(document.getElementById('maxTokens').value || 1200),
        response_min_chars: Number(document.getElementById('minChars').value || 0),
        response_max_chars: Number(document.getElementById('maxChars').value || 220),
        continue_on_error: document.getElementById('continueOnError').value === 'true',
        dialogue_mode: document.getElementById('dialogueMode').value,
        conversation_goal: document.getElementById('goal').value.trim(),
        models,
      };
    }

    async function runDialogue(reset) {
      try {
        const payload = {
          prompt: document.getElementById('prompt').value.trim(),
          rounds: Number(document.getElementById('rounds').value || 1),
          reset,
          config: collectConfig(),
        };
        await api('/api/start', { method: 'POST', body: JSON.stringify(payload) });
        document.getElementById('prompt').value = '';
        await loadConfig();
        await refreshAll();
      } catch (error) {
        alert(error.message);
      }
    }

    async function startDialogue() {
      await runDialogue(true);
    }

    async function continueDialogue() {
      await runDialogue(false);
    }

    async function stopDialogue() {
      const stopBtn = document.getElementById('stopBtn');
      const stopLabel = document.getElementById('stopLabel');
      stopRequestedByUser = true;
      stoppedNoticeUntil = 0;
      stopBtn.disabled = true;
      stopLabel.textContent = '停止中';
      document.getElementById('runText').textContent = '停止中';
      try {
        await api('/api/stop', { method: 'POST', body: '{}' });
      } finally {
        await refreshStatus();
      }
    }

    async function clearDialogue() {
      if (!confirm('确定清空当前对话记录吗？')) return;
      try {
        await api('/api/clear', { method: 'POST', body: '{}' });
        await refreshAll();
      } catch (error) {
        alert(error.message);
      }
    }

    async function interject() {
      const box = document.getElementById('interjectText');
      const content = box.value.trim();
      if (!content) return;
      try {
        await api('/api/interject', { method: 'POST', body: JSON.stringify({ content }) });
        box.value = '';
        await refreshDialogue();
      } catch (error) {
        alert(error.message);
      }
    }

    function toggleExportMenu(event) {
      event.stopPropagation();
      document.getElementById('exportMenu').classList.toggle('open');
    }

    function closeExportMenu() {
      document.getElementById('exportMenu').classList.remove('open');
    }

    function bindKeyboardShortcuts() {
      document.addEventListener('click', closeExportMenu);
      document.addEventListener('keydown', event => {
        if (event.key === 'Escape') closeExportMenu();
      });
      document.getElementById('turnMode').addEventListener('change', syncTurnModeUi);

      const interjectBox = document.getElementById('interjectText');
      interjectBox.addEventListener('keydown', event => {
        if (event.key === 'Enter' && !event.shiftKey) {
          event.preventDefault();
          interject();
        }
      });

      const promptBox = document.getElementById('prompt');
      promptBox.addEventListener('keydown', event => {
        if (event.key === 'Enter' && (event.ctrlKey || event.metaKey)) {
          event.preventDefault();
          if (hasMessages) {
            continueDialogue();
          } else {
            startDialogue();
          }
        }
      });
    }

    async function refreshStatus() {
      const status = await api('/api/status');
      const dot = document.getElementById('runDot');
      if (stopRequestedByUser && !status.running && !status.stop_requested) {
        stopRequestedByUser = false;
        stoppedNoticeUntil = Date.now() + 3500;
      }
      const showStopped = !status.running && Date.now() < stoppedNoticeUntil;
      dot.classList.toggle('running', status.running);
      document.getElementById('runText').textContent = showStopped ? '已停止' : (status.stop_requested ? '停止中' : (status.running ? '运行' : '待机'));
      document.getElementById('currentModel').textContent = status.running ? '' : '当前模型：-';
      document.getElementById('progressText').textContent = `进度：${status.completed_calls || 0}/${status.total_calls || 0}`;
      document.getElementById('startBtn').disabled = status.running;
      document.getElementById('continueBtn').disabled = status.running;
      document.getElementById('stopBtn').disabled = !status.running || status.stop_requested;
      document.getElementById('stopLabel').textContent = showStopped ? '已停止' : (status.stop_requested ? '停止中' : '停止');

      const typing = document.getElementById('typingIndicator');
      const typingText = document.getElementById('typingText');
      const typingAvatar = document.getElementById('typingAvatar');
      if (status.running) {
        const model = status.current_model || 'AI';
        const waiting = model === '选择发言者';
        const style = waiting ? { avatar: 'AI', color: '#64748b' } : getSpeakerStyle({
          model_id: config?.models?.find(item => item.name === model)?.id,
          model_name: model,
        });
        typing.style.setProperty('--speaker-color', style.color || '#64748b');
        typingAvatar.innerHTML = isImageAvatar(style.avatar)
          ? `<img src="${escapeHtml(style.avatar)}" alt="" />`
          : escapeHtml((style.avatar || 'AI').slice(0, 4));
        typingText.textContent = waiting ? '发言等待中' : `${model} 正在输入`;
        typing.classList.toggle('waiting', waiting);
        typing.classList.add('show');
      } else {
        typing.classList.remove('waiting');
        typing.classList.remove('show');
      }
    }

    async function refreshDialogue() {
      const data = await api('/api/dialogue');
      hasMessages = data.messages.length > 0;
      document.getElementById('lastUpdate').textContent = `最后更新：${new Date(data.last_update).toLocaleTimeString('zh-CN')}`;
      const root = document.getElementById('messages');
      if (!data.messages.length) {
        root.innerHTML = '<div class="empty">还没有对话。输入提示词后点击开始。</div>';
        return;
      }
      root.innerHTML = data.messages.map(message => `
        <article class="msg ${message.role === 'user' ? 'user' : ''}" style="--speaker-color: ${getSpeakerStyle(message).color}; --speaker-soft: ${getSpeakerStyle(message).soft};">
          ${renderAvatar(getSpeakerStyle(message).avatar, 'avatar')}
          <div class="msg-body">
            <div class="meta">
              <strong>${escapeHtml(getSpeakerStyle(message).name)}</strong>
              <span>${escapeHtml(message.model || '')} · ${escapeHtml(message.timestamp || '')}</span>
            </div>
            <span class="message-text">${escapeHtml(message.content)}</span>
          </div>
        </article>
      `).join('');
      root.scrollTop = root.scrollHeight;
    }

    async function refreshAll() {
      await Promise.all([refreshStatus(), refreshDialogue()]);
    }

    bindKeyboardShortcuts();
    loadConfig().then(refreshAll);
    setInterval(refreshAll, 2000);
  </script>
</body>
</html>
"""


LITE_TEMPLATE = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>AI Panel Lite</title>
  <style>
    body {
      margin: 0;
      font-family: "Segoe UI", "Microsoft YaHei", Arial, sans-serif;
      background: #f6f7f9;
      color: #1f2937;
    }
    header {
      padding: 14px;
      background: #fff;
      border-bottom: 1px solid #d8dee6;
      position: sticky;
      top: 0;
    }
    h1 { margin: 0; font-size: 18px; }
    main { padding: 12px; display: grid; gap: 12px; }
    textarea, input {
      width: 100%;
      box-sizing: border-box;
      border: 1px solid #cfd6df;
      border-radius: 6px;
      padding: 10px;
      font: inherit;
    }
    textarea { min-height: 88px; }
    button {
      border: 0;
      border-radius: 6px;
      padding: 10px 12px;
      font: inherit;
      font-weight: 700;
      color: #fff;
      background: #2563eb;
    }
    .bar { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
    .card {
      background: #fff;
      border: 1px solid #d8dee6;
      border-radius: 8px;
      padding: 10px;
    }
    .meta { color: #64748b; font-size: 12px; margin-bottom: 5px; }
    .msg { white-space: pre-wrap; line-height: 1.45; }
    .muted { color: #64748b; font-size: 13px; }
  </style>
</head>
<body>
  <header>
    <h1>AI Panel Lite</h1>
    <div class="muted" id="status">连接中...</div>
  </header>
  <main>
    <textarea id="prompt" placeholder="输入提示词"></textarea>
    <div class="bar">
      <input id="rounds" type="number" min="1" max="20" value="1" />
      <button onclick="startDialogue()">开始</button>
    </div>
    <button onclick="refreshAll()">刷新</button>
    <div id="messages" class="muted">载入中...</div>
  </main>
  <script>
    async function api(path, options = {}) {
      const response = await fetch(path, {
        headers: { 'Content-Type': 'application/json' },
        ...options
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || '请求失败');
      return data;
    }

    function escapeHtml(text) {
      const div = document.createElement('div');
      div.textContent = text ?? '';
      return div.innerHTML;
    }

    async function refreshAll() {
      const [status, dialogue] = await Promise.all([api('/api/status'), api('/api/dialogue')]);
      document.getElementById('status').textContent =
        `${status.running ? '运行中' : '待机'} · ${status.completed_calls || 0}/${status.total_calls || 0}`;
      const root = document.getElementById('messages');
      if (!dialogue.messages.length) {
        root.textContent = '还没有对话。';
        return;
      }
      root.innerHTML = dialogue.messages.map(message => `
        <article class="card">
          <div class="meta">${escapeHtml(message.model_name || message.role)} · ${escapeHtml(message.timestamp || '')}</div>
          <div class="msg">${escapeHtml(message.content)}</div>
        </article>
      `).join('');
    }

    async function startDialogue() {
      const config = await api('/api/config');
      const payload = {
        prompt: document.getElementById('prompt').value.trim(),
        rounds: Number(document.getElementById('rounds').value || 1),
        reset: true,
        config
      };
      await api('/api/start', { method: 'POST', body: JSON.stringify(payload) });
      document.getElementById('prompt').value = '';
      await refreshAll();
    }

    refreshAll().catch(error => {
      document.getElementById('status').textContent = error.message;
    });
    setInterval(refreshAll, 3000);
  </script>
</body>
</html>
"""


def main():
    load_dotenv(FOLDER / ".env")
    ensure_config()
    server = ThreadingHTTPServer((HOST, PORT), PanelHandler)
    print("=" * 50)
    print("多 AI 对话控制台")
    print("=" * 50)
    print("打开浏览器访问:")
    for url in access_urls(HOST, PORT):
        label = "本机" if "127.0.0.1" in url else "手机/局域网"
        print(f"  {label}: {url}")
    print("手机需要和这台电脑连接同一个 Wi-Fi；如果打不开，请允许 Windows 防火墙放行 Python。")
    print("按 Ctrl+C 停止服务")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n正在停止服务...")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
