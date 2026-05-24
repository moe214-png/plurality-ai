#!/usr/bin/env python3
"""
Four-model API dialogue runner.

This script rotates a prompt through Claude, ChatGPT, DeepSeek, and Zhipu by
default. API keys are read from environment variables; model names and order are
kept in models_config.json so you can adjust them without editing code.
"""

import argparse
import json
import os
import random
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path


FOLDER = Path(__file__).resolve().parent
CONFIG_FILE = FOLDER / "models_config.json"
LOG_FILE = FOLDER / "api_dialogue_log.json"
MARKDOWN_FILE = FOLDER / "api_dialogue.md"
RETRYABLE_HTTP_STATUS = {408, 409, 425, 429, 500, 502, 503, 504}
RETRYABLE_NETWORK_MARKERS = (
    "UNEXPECTED_EOF_WHILE_READING",
    "EOF occurred in violation of protocol",
    "Remote end closed connection",
    "Connection reset",
    "Connection aborted",
    "timed out",
    "timeout",
)

DEFAULT_CONFIG = {
    "max_rounds": 15,
    "delay_seconds": 0,
    "max_output_tokens": 1200,
    "response_min_chars": 1,
    "response_max_chars": 80,
    "continue_on_error": True,
    "dialogue_mode": "chat",
    "turn_mode": "natural",
    "natural_selector": "all",
    "natural_pick_strategy": "sample",
    "natural_judge_model_id": "deepseek",
    "natural_check_tokens": 80,
    "max_consecutive_turns": 1,
    "natural_balance_enabled": True,
    "natural_balance_window": 8,
    "natural_balance_strength": 1.0,
    "natural_silence_fallback": True,
    "self_memory_turns": 15,
    "conversation_goal": "四个 AI 像朋友一样围绕用户的话题自然接话。不要做报告，不要列清单，优先使用连续的句子和轻松的短段落。",
    "models": [
        {
            "id": "claude",
            "name": "Claude",
            "avatar": "CL",
            "enabled": True,
            "speaker_weight": 1.0,
            "provider": "openai_compatible",
            "base_url": "https://api.tokenfree.shop/v1",
            "model": "claude-sonnet-4-6",
            "api_key_env": "CLAUDE_API_KEY",
            "system_prompt": "你是 Claude。你说话温和、细腻、会认真接住对方的情绪。闲聊模式下不要列条目，不要分析式总结，用自然连续的句子回应，像一个耐心又聪明的朋友。",
        },
        {
            "id": "chatgpt",
            "name": "ChatGPT",
            "avatar": "GPT",
            "enabled": True,
            "speaker_weight": 1.0,
            "provider": "openai_compatible",
            "base_url": "https://api.tokenfree.shop/v1",
            "model": "gpt-5.5",
            "api_key_env": "OPENAI_API_KEY",
            "system_prompt": "你是 ChatGPT。你擅长把话题接得顺、让聊天继续自然流动。闲聊模式下避免标题和列表，用轻松清楚的段落说话，可以适当追问，但不要像在写方案。",
        },
        {
            "id": "deepseek",
            "name": "DeepSeek",
            "avatar": "DS",
            "enabled": True,
            "speaker_weight": 1.5,
            "provider": "openai_compatible",
            "base_url": "https://api.deepseek.com",
            "model": "deepseek-v4-flash",
            "api_key_env": "DEEPSEEK_API_KEY",
            "system_prompt": "你是 DeepSeek。你反应直接，偶尔有一点幽默，会把复杂想法说得接地气。闲聊模式下用口语化连续句子，不要写成分析报告。",
        },
        {
            "id": "zhipu",
            "name": "智谱",
            "avatar": "智",
            "enabled": True,
            "speaker_weight": 1.0,
            "provider": "openai_compatible",
            "base_url": "https://open.bigmodel.cn/api/paas/v4",
            "model": "glm-5.1",
            "api_key_env": "ZHIPU_API_KEY",
            "thinking": {"type": "disabled"},
            "system_prompt": "你是智谱。你联想丰富，喜欢从不同角度补充话题。闲聊模式下用自然段落表达，保持轻快，不要堆概念或列点。",
        },
    ],
}


class ApiDialogueError(RuntimeError):
    pass


def load_dotenv(path, override=False):
    if not path.exists():
        return
    with open(path, "r", encoding="utf-8") as f:
        for raw_line in f:
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and (override or key not in os.environ):
                os.environ[key] = value


def load_json(path, default):
    if not path.exists():
        return default
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def ensure_config(config_file=None):
    cf = config_file or CONFIG_FILE
    if not cf.exists():
        save_json(cf, DEFAULT_CONFIG)
    return load_json(cf, DEFAULT_CONFIG)


def load_log(log_file=None):
    return load_json(log_file or LOG_FILE, [])


def save_log(log, log_file=None, markdown_file=None):
    lf = log_file or LOG_FILE
    mf = markdown_file or MARKDOWN_FILE
    save_json(lf, log)
    export_markdown(log, markdown_file=mf)


def export_markdown(log, markdown_file=None):
    mf = markdown_file or MARKDOWN_FILE
    with open(mf, "w", encoding="utf-8") as f:
        f.write("# 多 AI API 对话记录\n\n")
        f.write(f"_最后更新: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}_\n\n")
        for index, entry in enumerate(log, 1):
            f.write(f"## [{index}] {entry['model_name']}\n")
            f.write(f"**模型**: `{entry['model']}`  \n")
            f.write(f"**时间**: {entry['timestamp']}\n\n")
            f.write(entry["content"].strip())
            f.write("\n\n---\n\n")


def is_retryable_http_error(status, detail):
    if status not in RETRYABLE_HTTP_STATUS:
        return False
    return "No available accounts" not in detail


def is_retryable_network_error(error):
    text = str(error)
    return any(marker.lower() in text.lower() for marker in RETRYABLE_NETWORK_MARKERS)


def http_json(method, url, headers, payload=None, timeout=120, retries=2):
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    last_error = None
    for attempt in range(retries + 1):
        request = urllib.request.Request(url, data=body, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                raw = response.read().decode("utf-8")
                return json.loads(raw)
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            last_error = ApiDialogueError(f"HTTP {exc.code} from {url}: {detail}")
            if attempt < retries and is_retryable_http_error(exc.code, detail):
                time.sleep(0.8 * (attempt + 1))
                continue
            raise last_error from exc
        except urllib.error.URLError as exc:
            last_error = ApiDialogueError(f"Network error calling {url}: {exc}")
            if attempt < retries and is_retryable_network_error(exc):
                time.sleep(0.8 * (attempt + 1))
                continue
            raise last_error from exc
    raise last_error or ApiDialogueError(f"Request failed calling {url}")


def compact_call_error(error):
    text = str(error)
    text_lower = text.lower()
    if "Missing API key" in text:
        return text
    if "no available accounts" in text_lower:
        return "上游暂无可用账号"
    match = re.search(r"\bHTTP\s+(\d{3})\b", text, re.IGNORECASE)
    if match:
        status = int(match.group(1))
        if status in {401, 403}:
            return f"API 鉴权失败（HTTP {status}）"
        if status == 429:
            return "请求过于频繁（HTTP 429）"
        if status >= 500:
            return f"上游服务暂时不可用（HTTP {status}）"
        return f"接口返回 HTTP {status}"
    code = getattr(error, "code", None)
    if isinstance(code, int):
        return f"HTTP {code}"
    if "WinError 10013" in text:
        return "网络请求被拦截"
    if "NameResolutionError" in text or "getaddrinfo failed" in text:
        return "DNS 解析失败"
    if "UNEXPECTED_EOF_WHILE_READING" in text or "EOF occurred in violation of protocol" in text:
        return "上游连接中断"
    if "Remote end closed connection" in text or "Connection reset" in text:
        return "上游连接中断"
    if "timed out" in text_lower or "timeout" in text_lower:
        return "请求超时"
    if "network error calling" in text_lower or "urlopen error" in text_lower:
        return "网络连接失败"
    return "请求失败"


def format_call_failure(error):
    return f"[调用失败] {compact_call_error(error)}"


def get_api_key(model_config):
    env_names = []
    if model_config.get("api_key_env"):
        env_names.append(model_config["api_key_env"])
    env_names.extend(model_config.get("api_key_env_fallbacks") or [])
    for env_name in env_names:
        api_key = os.environ.get(env_name or "")
        if api_key:
            return api_key
    raise ApiDialogueError(f"Missing API key: set environment variable {' or '.join(env_names)}")


def build_user_prompt(config, log, current_model):
    goal = config.get("conversation_goal", "").strip()
    response_min_chars = int(config.get("response_min_chars", 0) or 0)
    response_max_chars = int(config.get("response_max_chars", 0) or 0)
    legacy_target_chars = int(config.get("response_target_chars", 0) or 0)
    if legacy_target_chars and not response_min_chars and not response_max_chars:
        response_min_chars = max(1, int(legacy_target_chars * 0.75))
        response_max_chars = legacy_target_chars
    if not log:
        raise ApiDialogueError("No user prompt found. Start with --prompt or --prompt-file.")

    first_user_prompt = next((item["content"] for item in log if item["role"] == "user"), "")
    recent_messages = log[-8:]
    transcript_lines = []
    for item in recent_messages:
        speaker = item.get("model_name") or item.get("role", "user")
        transcript_lines.append(f"{speaker}:\n{item['content']}")
    own_memory = model_memory_lines(log, current_model.get("id"), int(config.get("self_memory_turns", 5)))
    own_memory_text = "\n".join(own_memory) if own_memory else "你此前还没有发言。"

    length_rule = ""
    if response_min_chars > 0 and response_max_chars > 0:
        length_rule = (
            f"\n\n发言长度标准：请把这次发言控制在约 {response_min_chars}-{response_max_chars} 个中文字符。"
            "这是可见字数范围，不是 token 范围。"
            "如果需要自然收束，可以略短；不要明显超出上限。"
        )
    elif response_max_chars > 0:
        length_rule = (
            f"\n\n发言长度标准：请把这次发言控制在约 {response_max_chars} 个中文字符以内。"
            "这是可见字数标准，不是 token 标准。优先保持完整句子，不要为了凑长度而重复。"
        )

    progress_rule = (
        "\n\n推进规则：不要只是复述或同意前面的话。每次发言至少做一件事："
        "补充一个尚未充分展开的新角度、提出一个相关但不跑题的问题、修正自己或他人的一个判断、"
        "或者把话题自然推进到相邻的新内容。"
        "如果最近上下文已经反复讨论同一点，请明确换一个相关切面继续。"
    )

    return (
        f"对话目标：{goal}\n\n"
        f"用户原始问题：\n{first_user_prompt}\n\n"
        f"你的身份延续：你是 {current_model['name']}，你要把下面这些内容当作你自己此前说过的话，而不是别人说的观点。"
        "这次发言要自然延续你的立场、语气和已经表达过的判断；如果你改变想法，要说明是修正或补充。\n"
        f"你此前的发言摘要：\n{own_memory_text}\n\n"
        f"最近上下文：\n\n" + "\n\n".join(transcript_lines) + "\n\n"
        f"现在轮到 {current_model['name']} 回应。请直接给出你的回答，不要输出 JSON。"
        f"{progress_rule}"
        f"{length_rule}"
    )


def call_openai(model_config, prompt, max_tokens):
    api_key = get_api_key(model_config)
    payload = {
        "model": model_config["model"],
        "instructions": model_config.get("system_prompt", ""),
        "input": prompt,
        "max_output_tokens": max_tokens,
    }
    data = http_json(
        "POST",
        "https://api.openai.com/v1/responses",
        {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        payload,
    )
    if data.get("output_text"):
        return data["output_text"].strip()

    chunks = []
    for item in data.get("output", []):
        for content in item.get("content", []):
            if content.get("type") in {"output_text", "text"} and content.get("text"):
                chunks.append(content["text"])
    if chunks:
        return "\n".join(chunks).strip()
    raise ApiDialogueError(f"OpenAI response did not contain text: {json.dumps(data, ensure_ascii=False)[:1000]}")


def call_anthropic(model_config, prompt, max_tokens):
    api_key = get_api_key(model_config)
    payload = {
        "model": model_config["model"],
        "max_tokens": max_tokens,
        "system": model_config.get("system_prompt", ""),
        "messages": [{"role": "user", "content": prompt}],
    }
    data = http_json(
        "POST",
        "https://api.anthropic.com/v1/messages",
        {
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        },
        payload,
    )
    chunks = [item.get("text", "") for item in data.get("content", []) if item.get("type") == "text"]
    if chunks:
        return "\n".join(chunks).strip()
    raise ApiDialogueError(f"Anthropic response did not contain text: {json.dumps(data, ensure_ascii=False)[:1000]}")


def call_openai_compatible(model_config, prompt, max_tokens):
    api_key = get_api_key(model_config)
    base_url = model_config.get("base_url", "").rstrip("/")
    payload = {
        "model": model_config["model"],
        "messages": [
            {"role": "system", "content": model_config.get("system_prompt", "")},
            {"role": "user", "content": prompt},
        ],
        "max_tokens": max_tokens,
    }
    for key in ("temperature", "top_p", "thinking"):
        if key in model_config:
            payload[key] = model_config[key]
    data = http_json(
        "POST",
        f"{base_url}/chat/completions",
        {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        payload,
    )
    try:
        return data["choices"][0]["message"]["content"].strip()
    except (KeyError, IndexError) as exc:
        raise ApiDialogueError(f"Compatible response did not contain text: {json.dumps(data, ensure_ascii=False)[:1000]}") from exc


def call_gemini(model_config, prompt, max_tokens):
    api_key = get_api_key(model_config)
    model_name = urllib.parse.quote(model_config["model"], safe="")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent"
    payload = {
        "systemInstruction": {
            "parts": [{"text": model_config.get("system_prompt", "")}]
        },
        "contents": [
            {
                "role": "user",
                "parts": [{"text": prompt}],
            }
        ],
        "generationConfig": {
            "maxOutputTokens": max_tokens,
        },
    }
    data = http_json(
        "POST",
        url,
        {
            "Content-Type": "application/json",
            "x-goog-api-key": api_key,
        },
        payload,
    )
    chunks = []
    for candidate in data.get("candidates", []):
        for part in candidate.get("content", {}).get("parts", []):
            if part.get("text"):
                chunks.append(part["text"])
    if chunks:
        return "\n".join(chunks).strip()
    raise ApiDialogueError(f"Gemini response did not contain text: {json.dumps(data, ensure_ascii=False)[:1000]}")


PROVIDER_CALLERS = {
    "openai": call_openai,
    "anthropic": call_anthropic,
    "openai_compatible": call_openai_compatible,
    "gemini": call_gemini,
}


def enabled_models(config):
    return [model for model in config.get("models", []) if model.get("enabled", True)]


def model_memory_lines(log, model_id, limit=5):
    own_messages = [
        item
        for item in log
        if item.get("role") == "assistant" and item.get("model_id") == model_id
    ]
    lines = []
    for item in own_messages[-limit:]:
        content = item.get("content", "").strip()
        if len(content) > 260:
            content = content[:260].rstrip() + "..."
        lines.append(f"- {content}")
    return lines


def build_natural_check_prompt(config, log, model_config):
    goal = config.get("conversation_goal", "").strip()
    recent_messages = log[-8:]
    transcript_lines = []
    for item in recent_messages:
        speaker = item.get("model_name") or item.get("role", "user")
        transcript_lines.append(f"{speaker}: {item['content']}")
    transcript = "\n".join(transcript_lines)
    last_speaker = next((item.get("model_id") for item in reversed(log) if item.get("role") == "assistant"), "")
    own_memory = model_memory_lines(log, model_config.get("id"), int(config.get("self_memory_turns", 5)))
    own_memory_text = "\n".join(own_memory) if own_memory else "你此前还没有发言。"
    return (
        f"对话目标：{goal}\n\n"
        f"你的历史发言：\n{own_memory_text}\n\n"
        f"最近对话：\n{transcript}\n\n"
        f"你是 {model_config['name']}。请判断你现在是否应该发言。"
        "如果上一位刚好是你，只有在确实需要补充时才继续。"
        f"上一位 AI：{last_speaker or '无'}。\n"
        "只输出 JSON，不要解释，格式为："
        '{"score": 0到5的整数, "reason": "一句话理由"}。'
        "score=0 表示保持沉默，score=5 表示非常想说。"
    )


def parse_speak_score(text):
    try:
        start = text.index("{")
        end = text.rindex("}") + 1
        data = json.loads(text[start:end])
        return int(data.get("score", 0)), str(data.get("reason", ""))
    except Exception:
        digits = [int(ch) for ch in text if ch.isdigit()]
        return (max(0, min(5, digits[0])) if digits else 0), text[:80]


def consecutive_speaker_info(log):
    last_model_id = next((item.get("model_id") for item in reversed(log) if item.get("role") == "assistant"), None)
    consecutive_count = 0
    if last_model_id:
        for item in reversed(log):
            if item.get("role") != "assistant":
                continue
            if item.get("model_id") == last_model_id:
                consecutive_count += 1
            else:
                break
    return last_model_id, consecutive_count


def recent_speaker_counts(log, models, window):
    recent_assistant = [item for item in log if item.get("role") == "assistant"][-window:]
    return {
        model["id"]: sum(1 for item in recent_assistant if item.get("model_id") == model["id"])
        for model in models
    }


def natural_allowed_models(config, log, candidates):
    last_model_id, consecutive_count = consecutive_speaker_info(log)
    max_consecutive = int(config.get("max_consecutive_turns", 1))
    decisions = []
    allowed = []
    for model_config in candidates:
        if (
            last_model_id
            and model_config.get("id") == last_model_id
            and consecutive_count >= max_consecutive
            and len(candidates) > 1
        ):
            decisions.append(
                {
                    "model": model_config,
                    "score": -1,
                    "reason": f"已连续发言 {consecutive_count} 次，达到上限",
                }
            )
            continue
        allowed.append(model_config)

    return allowed, decisions


def balance_bonus(config, log, model_id, allowed):
    if not config.get("natural_balance_enabled", True) or len(allowed) <= 1:
        return 0
    balance_window = int(config.get("natural_balance_window", max(4, len(allowed) * 2)))
    strength = float(config.get("natural_balance_strength", 1.0))
    counts = recent_speaker_counts(log, allowed, balance_window)
    max_count = max(counts.values()) if counts else 0
    return max(0, max_count - counts.get(model_id, 0)) * strength


def speaker_weight(model_config):
    try:
        return max(0.1, float(model_config.get("speaker_weight", 1.0)))
    except (TypeError, ValueError):
        return 1.0


def weighted_score(model_config, score):
    return max(0, float(score)) * speaker_weight(model_config)


def fallback_natural_speaker(config, log, allowed, decisions, reason="无人主动发言，兜底接话"):
    if not allowed or not config.get("natural_silence_fallback", True):
        return None, decisions
    ranked = sorted(
        allowed,
        key=lambda model: (
            balance_bonus(config, log, model["id"], allowed),
            -next(
                (
                    index
                    for index, item in enumerate(reversed(log))
                    if item.get("role") == "assistant" and item.get("model_id") == model["id"]
                ),
                10_000,
            ),
        ),
        reverse=True,
    )
    chosen = ranked[0]
    decisions.append({"model": chosen, "score": 0.1, "reason": reason})
    return chosen, decisions


def weighted_pick(decisions):
    eligible = [item for item in decisions if item.get("score", 0) > 0]
    if not eligible:
        return None
    total = sum(float(item["score"]) for item in eligible)
    if total <= 0:
        return None
    target = random.uniform(0, total)
    upto = 0
    for item in eligible:
        upto += float(item["score"])
        if upto >= target:
            return item
    return eligible[-1]


def pick_decision(config, decisions):
    eligible = [item for item in decisions if item.get("score", 0) > 0]
    if not eligible:
        return None
    if config.get("natural_pick_strategy", "sample") == "max":
        return max(eligible, key=lambda item: item["score"])
    return weighted_pick(eligible)


def choose_natural_speaker(config, log, max_tokens=None):
    candidates = enabled_models(config)
    if not candidates:
        return None, []
    allowed, decisions = natural_allowed_models(config, log, candidates)
    if not allowed:
        return None, decisions
    check_tokens = int(max_tokens or config.get("natural_check_tokens", 80))
    for model_config in allowed:
        caller = PROVIDER_CALLERS.get(model_config.get("provider"))
        if not caller:
            continue
        try:
            check_prompt = build_natural_check_prompt(config, log, model_config)
            raw = caller(model_config, check_prompt, check_tokens)
            score, reason = parse_speak_score(raw)
        except Exception as exc:
            score, reason = 0, f"判断失败: {exc}"
        bonus = balance_bonus(config, log, model_config["id"], allowed)
        decisions.append(
            {
                "model": model_config,
                "score": weighted_score(model_config, score + bonus),
                "reason": (
                    reason
                    if bonus == 0 and speaker_weight(model_config) == 1
                    else f"{reason}；少发言加权 +{bonus:g}；发言权重 x{speaker_weight(model_config):g}"
                ),
            }
        )

    chosen_decision = pick_decision(config, decisions)
    decisions.sort(key=lambda item: item["score"], reverse=True)
    if not chosen_decision:
        return fallback_natural_speaker(config, log, allowed, decisions)
    return chosen_decision["model"], decisions


def choose_natural_speaker_by_judge(config, log, max_tokens=None):
    candidates = enabled_models(config)
    if not candidates:
        return None, []

    allowed, decisions = natural_allowed_models(config, log, candidates)
    if not allowed:
        return None, decisions

    judge_id = config.get("natural_judge_model_id", "deepseek")
    judge = next((model for model in candidates if model.get("id") == judge_id), allowed[0])
    caller = PROVIDER_CALLERS.get(judge.get("provider"))
    if not caller:
        return allowed[0], decisions

    recent_messages = log[-8:]
    recent_assistant_messages = [item for item in recent_messages if item.get("role") == "assistant"]
    recent_counts = {
        model["id"]: sum(1 for item in recent_assistant_messages if item.get("model_id") == model["id"])
        for model in allowed
    }
    balance_window = int(config.get("natural_balance_window", max(4, len(allowed) * 2)))
    full_counts = recent_speaker_counts(log, allowed, balance_window)
    max_count = max(full_counts.values()) if full_counts else 0
    transcript_lines = []
    for item in recent_messages:
        speaker = item.get("model_name") or item.get("role", "user")
        transcript_lines.append(f"{speaker}: {item['content']}")
    candidate_text = "\n".join(
        f"- {model['id']}: {model['name']}（最近8条中已发言 {recent_counts.get(model['id'], 0)} 次；均衡权重 +{max_count - full_counts.get(model['id'], 0)}；发言权重 x{speaker_weight(model):g}）"
        for model in allowed
    )
    prompt = (
        f"对话目标：{config.get('conversation_goal', '')}\n\n"
        f"最近对话：\n{chr(10).join(transcript_lines)}\n\n"
        f"可选发言者：\n{candidate_text}\n\n"
        "请评估哪些 AI 适合接下来发言。"
        "请以语境自然度为主，同时参考均衡权重；权重高表示它最近说得少，但不是强制轮流。"
        "至少给出 2 个可行候选，除非只有 1 个候选。"
        "只输出 JSON，格式为："
        '{"candidates": [{"model_id": "候选 id", "score": 1到5的数字, "reason": "一句话理由"}]}。'
    )

    try:
        raw = caller(judge, prompt, int(max_tokens or config.get("natural_check_tokens", 80)))
        start = raw.index("{")
        end = raw.rindex("}") + 1
        data = json.loads(raw[start:end])
        raw_candidates = data.get("candidates")
        if not raw_candidates:
            raw_candidates = [data]
        allowed_ids = {model["id"] for model in allowed}
        for item in raw_candidates:
            model_id = str(item.get("model_id", "")).strip()
            if model_id not in allowed_ids:
                continue
            score = float(item.get("score", 3))
            reason = str(item.get("reason", ""))
            model = next(model for model in allowed if model["id"] == model_id)
            bonus = balance_bonus(config, log, model_id, allowed)
            decisions.append(
                {
                    "model": model,
                    "score": max(0.1, weighted_score(model, score + bonus)),
                    "reason": (
                        reason
                        if bonus == 0 and speaker_weight(model) == 1
                        else f"{reason}；少发言加权 +{bonus:g}；发言权重 x{speaker_weight(model):g}"
                    ),
                }
            )
    except Exception as exc:
        for model in allowed:
            bonus = balance_bonus(config, log, model["id"], allowed)
            decisions.append(
                {
                    "model": model,
                    "score": max(0.1, weighted_score(model, 1 + bonus)),
                    "reason": f"裁判失败，进入兜底抽样: {exc}；发言权重 x{speaker_weight(model):g}",
                }
            )

    existing_ids = {item["model"]["id"] for item in decisions if item.get("score", 0) > 0}
    for model in allowed:
        if model["id"] in existing_ids:
            continue
        bonus = balance_bonus(config, log, model["id"], allowed)
        decisions.append(
            {
                "model": model,
                "score": max(0.2, weighted_score(model, 0.5 + bonus)),
                "reason": f"裁判未列入，但保留少量自然插话机会；发言权重 x{speaker_weight(model):g}",
            }
        )

    chosen_decision = pick_decision(config, decisions)
    decisions.sort(key=lambda item: item["score"], reverse=True)
    if not chosen_decision:
        return fallback_natural_speaker(config, log, allowed, decisions)
    return chosen_decision["model"], decisions


def choose_next_natural_speaker(config, log, max_tokens=None):
    if config.get("natural_selector", "all") == "all":
        return choose_natural_speaker(config, log, max_tokens)
    return choose_natural_speaker_by_judge(config, log, max_tokens)


def append_entry(log, role, content, model_config=None):
    entry = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "role": role,
        "content": content,
    }
    if model_config:
        entry.update(
            {
                "model_id": model_config["id"],
                "model_name": model_config["name"],
                "avatar": model_config.get("avatar", ""),
                "provider": model_config["provider"],
                "model": model_config["model"],
            }
        )
    else:
        entry.update(
            {
                "model_id": "user",
                "model_name": "User",
                "provider": "local",
                "model": "user",
            }
        )
    log.append(entry)


def ask_human_intervention(log):
    print("\n你的操作：直接回车继续；输入内容插入你的发言；输入 /q 结束。")
    human_text = input("> ").strip()
    if human_text == "/q":
        return False
    if human_text:
        append_entry(log, "user", human_text)
        save_log(log)
        print("已插入你的发言。")
    return True


def run_dialogue(config, prompt=None, prompt_file=None, rounds=None, reset=False, interactive=False):
    log = [] if reset else load_log()
    if prompt_file:
        prompt = Path(prompt_file).read_text(encoding="utf-8").strip()
    if prompt:
        append_entry(log, "user", prompt)

    if not log:
        raise ApiDialogueError("请用 --prompt 或 --prompt-file 提供初始问题，或保留已有 api_dialogue_log.json。")

    models = config.get("models", [])
    if not models:
        raise ApiDialogueError("models_config.json 里没有 models。")

    total_rounds = rounds if rounds is not None else int(config.get("max_rounds", 1))
    max_tokens = int(config.get("max_output_tokens", 1200))
    delay_seconds = float(config.get("delay_seconds", 1))
    continue_on_error = bool(config.get("continue_on_error", False))
    turn_mode = config.get("turn_mode", "fixed")

    if turn_mode == "natural":
        total_steps = total_rounds * len(enabled_models(config))
        for step_index in range(total_steps):
            print(f"\n=== 自然发言 {step_index + 1}/{total_steps} ===")
            model_config, decisions = choose_next_natural_speaker(config, log)
            for decision in decisions:
                print(f"  {decision['model']['name']}: {decision['score']} ({decision['reason']})")
            if not model_config:
                print("没有 AI 想继续发言，已停止。")
                break
            provider = model_config.get("provider")
            caller = PROVIDER_CALLERS.get(provider)
            if not caller:
                raise ApiDialogueError(f"Unsupported provider: {provider}")
            prompt_for_model = build_user_prompt(config, log, model_config)
            print(f"[{datetime.now().strftime('%H:%M:%S')}] Calling {model_config['name']} ({model_config['model']})...")
            try:
                content = caller(model_config, prompt_for_model, max_tokens)
            except Exception as exc:
                if not continue_on_error:
                    raise
                content = format_call_failure(exc)
                print(content)
            append_entry(log, "assistant", content, model_config)
            save_log(log)
            print(f"Saved {model_config['name']} response ({len(content)} chars).")
            if interactive and not ask_human_intervention(log):
                print(f"\n已停止。日志: {LOG_FILE}")
                print(f"Markdown: {MARKDOWN_FILE}")
                return
            if delay_seconds > 0:
                time.sleep(delay_seconds)
    else:
        for round_index in range(total_rounds):
            print(f"\n=== 第 {round_index + 1}/{total_rounds} 轮 ===")
            for model_config in models:
                if not model_config.get("enabled", True):
                    print(f"Skipping {model_config['name']} (disabled).")
                    continue
                provider = model_config.get("provider")
                caller = PROVIDER_CALLERS.get(provider)
                if not caller:
                    raise ApiDialogueError(f"Unsupported provider: {provider}")

                prompt_for_model = build_user_prompt(config, log, model_config)
                print(f"[{datetime.now().strftime('%H:%M:%S')}] Calling {model_config['name']} ({model_config['model']})...")
                try:
                    content = caller(model_config, prompt_for_model, max_tokens)
                except Exception as exc:
                    if not continue_on_error:
                        raise
                    content = format_call_failure(exc)
                    print(content)
                append_entry(log, "assistant", content, model_config)
                save_log(log)
                print(f"Saved {model_config['name']} response ({len(content)} chars).")
                if interactive and not ask_human_intervention(log):
                    print(f"\n已停止。日志: {LOG_FILE}")
                    print(f"Markdown: {MARKDOWN_FILE}")
                    return
                if delay_seconds > 0:
                    time.sleep(delay_seconds)

    print(f"\n完成。日志: {LOG_FILE}")
    print(f"Markdown: {MARKDOWN_FILE}")


def main():
    load_dotenv(FOLDER / ".env")

    parser = argparse.ArgumentParser(description="Run a multi-AI API dialogue.")
    parser.add_argument("--prompt", help="Initial user prompt.")
    parser.add_argument("--prompt-file", help="Read initial prompt from a UTF-8 text file.")
    parser.add_argument("--rounds", type=int, help="How many full rounds across all models.")
    parser.add_argument("--reset", action="store_true", help="Start a new log instead of continuing api_dialogue_log.json.")
    parser.add_argument("--interactive", action="store_true", help="Pause after each model so you can join the dialogue.")
    parser.add_argument("--init-config", action="store_true", help="Create models_config.json and exit.")
    args = parser.parse_args()

    config = ensure_config()
    if args.init_config:
        print(f"Config ready: {CONFIG_FILE}")
        return

    run_dialogue(
        config=config,
        prompt=args.prompt,
        prompt_file=args.prompt_file,
        rounds=args.rounds,
        reset=args.reset,
        interactive=args.interactive,
    )


if __name__ == "__main__":
    try:
        main()
    except ApiDialogueError as exc:
        print(f"错误: {exc}")
        raise SystemExit(1)
