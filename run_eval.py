#!/usr/bin/env python3
"""
Эвал «человечности» бота МБК на реальных диалогах живого специалиста (Мирзоян Михаил).

Кладётся в корень репозитория mbk-human-assistant рядом с prompts.py и
mikhail_eval_cases.json.

Режимы:
  python run_eval.py baseline
      Прогоняет эвристики по ОТВЕТАМ САМОГО МИХАИЛА. Это калибровка: эталон должен
      набирать высокий балл. Так вы видите «целевую полосу», к которой тянуть бота. API не нужен.

  OPENROUTER_API_KEY=... python run_eval.py gen --model openai/gpt-4o-mini [--n 40]
      Генерит ответы бота вашим системным промптом через OpenRouter и сравнивает балл
      с эталоном. Прогоните на 2-3 моделях — увидите, какая ближе к Михаилу.
      Полный быстрый прогон: --concurrency 4..8 --retries 1 --timeout 45 --max-tokens 350.
      Каждый кейс пишется в JSONL сразу; повторный запуск продолжит с готовых кейсов.
      По умолчанию eval подавляет reasoning у reasoning-моделей; --allow-reasoning включает A/B контроль.

  ... --judge openai/gpt-4o   (доп. к gen)
      LLM-судья сравнивает кандидата с эталоном вслепую: «кто звучит как живой занятой
      специалист». Возвращает win-rate кандидата.
"""
from __future__ import annotations
import argparse, json, os, re, sys, time, urllib.error, urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from statistics import mean
from threading import Lock

from dotenv import load_dotenv

HERE = Path(__file__).resolve().parent
CASES = json.loads((HERE / "mikhail_eval_cases.json").read_text(encoding="utf-8"))


def load_env_file(path: Path, override: bool = False) -> None:
    """Load simple KEY=VALUE .env files, including UTF-8 BOM files that python-dotenv may skip."""
    if not path.exists():
        return
    text: str | None = None
    for encoding in ("utf-8-sig", "utf-8", "utf-16"):
        try:
            text = path.read_text(encoding=encoding)
            break
        except UnicodeError:
            continue
    if text is None:
        return

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        name = name.strip()
        value = value.strip().strip('"').strip("'")
        if not name or (not override and os.getenv(name) is not None):
            continue
        os.environ[name] = value


load_dotenv(HERE / ".env")
load_env_file(HERE / ".env")

DEFAULT_MODELS = {
    "deepseek-v4-pro": "deepseek/deepseek-v4-pro",
    "qwen3.6-plus": "qwen/qwen3.6-plus",
    "qwen3.7-max": "qwen/qwen3.7-max",
    "opus-4.7": "anthropic/claude-opus-4.7",
    "grok-4.3": "x-ai/grok-4.3",
}

MODEL_ALIASES = {
    "deepseek v4 pro": DEFAULT_MODELS["deepseek-v4-pro"],
    "deepseek-v4-pro": DEFAULT_MODELS["deepseek-v4-pro"],
    "deepseek/deepseek-v4-pro": DEFAULT_MODELS["deepseek-v4-pro"],
    "qwen3.6 plus": DEFAULT_MODELS["qwen3.6-plus"],
    "qwen3.6-plus": DEFAULT_MODELS["qwen3.6-plus"],
    "qwen/qwen3.6-plus": DEFAULT_MODELS["qwen3.6-plus"],
    "qwen3.7 max": DEFAULT_MODELS["qwen3.7-max"],
    "qwen3.7-max": DEFAULT_MODELS["qwen3.7-max"],
    "qwen/qwen3.7-max": DEFAULT_MODELS["qwen3.7-max"],
    "opus 4.7": DEFAULT_MODELS["opus-4.7"],
    "claude opus 4.7": DEFAULT_MODELS["opus-4.7"],
    "opus-4.7": DEFAULT_MODELS["opus-4.7"],
    "anthropic/claude-opus-4.7": DEFAULT_MODELS["opus-4.7"],
    "grok 4.3": DEFAULT_MODELS["grok-4.3"],
    "grok-4.3": DEFAULT_MODELS["grok-4.3"],
    "x-ai/grok-4.3": DEFAULT_MODELS["grok-4.3"],
}

# Маркеры «ботовости» — то, что делает текст похожим на анкету/поддержку.
BOT_PHRASES = [
    "понял", "понятно", "спасибо, это важная", "это важная деталь", "следующий шаг",
    "чтобы двигаться дальше", "для корректного подбора", "зафиксировал", "фиксирую",
    "к этому уже не возвращаюсь", "по вашему профилю логично", "это уже важная развилка",
    "хорошего дня",  # допустимо в конце, но как затычка — признак шаблона
]
# Внутренняя кухня, которой клиент видеть не должен.
JARGON = [
    "route", "scenario", "pipeline", "slot", "сценарий", "маршрут", "пайплайн", "слот",
    "квалификаци", "product_fit", "red flag", "красный флаг", "messages", "dialog_phase",
    "fact_update", "handoff",
]
CONCRETE_HINTS = ["примерно", "в районе", "около", "₽", "тыс", "млн", "%", "псб", "сбер",
                  "втб", "озон", "ставк", "скоринг", "нбки", "окб"]


def heuristic_score(bubbles: list[str]) -> tuple[int, list[str]]:
    """0..100 + причины снятия баллов. Кодирует стиль Михаила."""
    reasons, score = [], 100
    n = len(bubbles)
    text = " ".join(bubbles)
    low = text.lower()

    # 1) Очередь сообщений 1..4
    if n == 0:
        return 0, ["пустой ответ"]
    if n > 4:
        score -= 15; reasons.append(f"слишком много пузырей ({n}>4)")

    # 2) Нет «простыни»: каждый пузырь короткий
    longest = max(len(b) for b in bubbles)
    if longest > 280:
        score -= 25; reasons.append(f"есть пузырь-простыня ({longest} символов)")
    elif longest > 200:
        score -= 10; reasons.append(f"длинноватый пузырь ({longest})")

    # 3) Ботовость
    for p in BOT_PHRASES:
        if p in low:
            score -= 12; reasons.append(f"ботовая фраза: «{p}»")

    # 4) Внутренняя кухня
    for j in JARGON:
        if re.search(rf"(?<![а-яёa-z]){re.escape(j)}", low):
            score -= 20; reasons.append(f"внутренний термин наружу: «{j}»")

    # 5) Кол-во вопросов: 0-3 ок, больше — допрос
    q = text.count("?")
    if q > 3:
        score -= 10; reasons.append(f"слишком много вопросов ({q})")

    # 6) Бонус за конкретику (Михаил всегда конкретен)
    if not any(h in low for h in CONCRETE_HINTS) and len(text) > 40:
        score -= 6; reasons.append("нет конкретики (цифр/ориентиров/названий)")

    return max(0, min(100, score)), reasons


# ---------- OpenRouter ----------
def get_openrouter_api_key() -> str:
    """Read OpenRouter key from common env names without printing secret values."""
    for name in ("OPENROUTER_API_KEY", "OPEN_ROUTER_API_KEY", "OPENAI_API_KEY"):
        key = os.getenv(name) or os.getenv(f"$env:{name}")
        if not key:
            continue
        key = key.strip()
        if name == "OPENAI_API_KEY" and not key.startswith("sk-or-"):
            continue
        if key.startswith("sk-or-"):
            return key
    raise RuntimeError(
        "OpenRouter API key not found. Set OPENROUTER_API_KEY or OPEN_ROUTER_API_KEY in .env "
        "(OpenRouter keys usually start with sk-or-)."
    )


def resolve_model_id(model: str) -> str:
    """Resolve human aliases to OpenRouter model ids."""
    raw = model.strip()
    return MODEL_ALIASES.get(raw.lower(), raw)


def _is_reasoning_model(model: str) -> bool:
    m = (model or "").lower()
    return (
        m.startswith("deepseek/deepseek-v4")
        or m.startswith("qwen/qwen3.7-max")
        or "qwen3.7-max" in m
        or "reason" in m
        or "/o1" in m
        or "/o3" in m
    )


def _should_suppress_reasoning(model: str, allow_reasoning: bool) -> bool:
    return (not allow_reasoning) and _is_reasoning_model(model)


def _maybe_suppress_reasoning(payload: dict, model: str, allow_reasoning: bool) -> bool:
    if not _should_suppress_reasoning(model, allow_reasoning):
        return False
    payload["reasoning"] = {"effort": "none", "exclude": True}
    payload["include_reasoning"] = False
    return True


def _extract_cached_tokens(usage: dict | None) -> int:
    """Extract cached prompt tokens from OpenRouter/OpenAI-compatible usage payloads."""
    if not isinstance(usage, dict):
        return 0
    details = usage.get("prompt_tokens_details")
    if isinstance(details, dict):
        return int(details.get("cached_tokens", 0) or 0)
    return int(usage.get("cached_tokens", 0) or 0)


def _normalize_usage(usage: dict | None) -> dict:
    """Normalize token usage so eval artifacts are comparable across providers."""
    if not isinstance(usage, dict):
        return {
            "prompt_tokens": None,
            "completion_tokens": None,
            "total_tokens": None,
            "cached_tokens": None,
            "cache_hit_ratio": None,
        }
    prompt_tokens = int(usage.get("prompt_tokens", 0) or 0)
    completion_tokens = int(usage.get("completion_tokens", 0) or 0)
    total_tokens = int(usage.get("total_tokens", 0) or (prompt_tokens + completion_tokens))
    cached_tokens = _extract_cached_tokens(usage)
    return {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
        "cached_tokens": cached_tokens,
        "cache_hit_ratio": round(cached_tokens / prompt_tokens, 3) if prompt_tokens else 0.0,
    }


def openrouter_chat_response(
    model: str,
    messages: list[dict],
    temperature: float = 0.7,
    max_tokens: int = 700,
    retries: int = 3,
    timeout: int = 90,
    allow_reasoning: bool = False,
) -> dict:
    key = get_openrouter_api_key()
    payload = {
        "model": model, "messages": messages,
        "temperature": temperature,
        "max_tokens": max(max_tokens, 1800) if model.startswith("deepseek/deepseek-v4") else max_tokens,
    }
    reasoning_suppressed = _maybe_suppress_reasoning(payload, model, allow_reasoning)
    body = json.dumps(payload).encode("utf-8")
    last_error: Exception | None = None

    for attempt in range(1, retries + 1):
        req = urllib.request.Request(
            "https://openrouter.ai/api/v1/chat/completions", data=body,
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://local.mbk-human-assistant",
                "X-Title": "MBK Human Assistant Eval",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                data = json.loads(r.read())
            choice = data["choices"][0]
            message = choice.get("message") or {}
            content = message.get("content")
            if not content:
                finish_reason = choice.get("finish_reason")
                reasoning_len = len(message.get("reasoning") or "")
                raise ValueError(
                    f"empty model content; finish_reason={finish_reason}; reasoning_len={reasoning_len}"
                )
            return {
                "content": str(content),
                "usage": _normalize_usage(data.get("usage")),
                "reasoning_suppressed": reasoning_suppressed,
            }
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", errors="replace")[:800]
            last_error = RuntimeError(f"HTTP {e.code}: {detail}")
            if e.code not in {408, 409, 425, 429, 500, 502, 503, 504}:
                break
        except (TimeoutError, urllib.error.URLError, json.JSONDecodeError, KeyError) as e:
            last_error = e

        if attempt < retries:
            time.sleep(1.5 * attempt)

    raise RuntimeError(str(last_error))


def openrouter_chat(model: str, messages: list[dict], temperature: float = 0.7,
                    max_tokens: int = 700, retries: int = 3, timeout: int = 90,
                    allow_reasoning: bool = False) -> str:
    return openrouter_chat_response(
        model=model,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
        retries=retries,
        timeout=timeout,
        allow_reasoning=allow_reasoning,
    )["content"]


def strip_code_fence(raw: str) -> str:
    s = raw.strip()
    if s.startswith("```"):
        s = re.sub(r"^```(?:json)?\s*", "", s, flags=re.IGNORECASE)
        s = re.sub(r"\s*```$", "", s)
    return s.strip()


def parse_bubbles(raw: str) -> list[str]:
    """Как в проде: пузыри разделяются пустой строкой (двойным переносом)."""
    if raw is None:
        return []
    chunks = [c.strip() for c in str(raw).replace("\r\n", "\n").split("\n\n")]
    bubbles = [c for c in chunks if c]
    if bubbles:
        return bubbles[:4]
    flat = str(raw).strip()
    return [flat] if flat else []


def build_messages(system_prompt: str, case: dict) -> list[dict]:
    # Тот же формат, что в проде: свободный текст, пузыри через пустую строку (без JSON).
    convo = [{"role": "system", "content": system_prompt}]
    for turn in case["context"]:
        role = "assistant" if turn["role"] == "operator" else "user"
        convo.append({"role": role, "content": turn["text"]})
    convo.append({"role": "user", "content": case["user_input"]})
    return convo


JUDGE_SYS = ("Ты оцениваешь два ответа поддержки кредитного брокера в чате. Какой звучит как "
             "ЖИВОЙ занятой специалист (коротко, прямо, по делу, с мнением), а не как бот/анкета? "
             "Ответь одним словом: A или B.")

def judge(
    model: str,
    user_input: str,
    a: list[str],
    b: list[str],
    retries: int = 3,
    timeout: int = 90,
    allow_reasoning: bool = False,
) -> str:
    prompt = (f"Сообщение клиента: {user_input}\n\n"
              f"Ответ A:\n" + "\n".join(a) + "\n\nОтвет B:\n" + "\n".join(b))
    out = openrouter_chat(model, [{"role": "system", "content": JUDGE_SYS},
                                  {"role": "user", "content": prompt}],
                          temperature=0, max_tokens=16, retries=retries, timeout=timeout,
                          allow_reasoning=allow_reasoning)
    return "A" if "a" in out.lower()[:3] else "B"


def _case_id(index: int, case: dict) -> str:
    return str(case.get("id") or index)


def _load_resume_records(jsonl_path: Path | None, model: str, cases: list[dict]) -> dict[str, dict]:
    """Load successful case records for the current model so interrupted evals can resume."""
    if jsonl_path is None or not jsonl_path.exists():
        return {}

    wanted = {_case_id(i, c) for i, c in enumerate(cases, 1)}
    records: dict[str, dict] = {}
    for line in jsonl_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        case_id = str(record.get("case_id") or "")
        if (
            record.get("status") == "ok"
            and record.get("model") == model
            and case_id in wanted
        ):
            records[case_id] = record
    return records


def _append_jsonl(jsonl_path: Path | None, record: dict, lock: Lock) -> None:
    if jsonl_path is None:
        return
    jsonl_path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(record, ensure_ascii=False, separators=(",", ":"))
    with lock:
        with jsonl_path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")


def _make_success_record(
    *,
    label: str,
    model: str,
    index: int,
    case: dict,
    candidate: list[str],
    candidate_score: int,
    reference_score: int,
    reasons: list[str],
    judge_candidate_win: bool | None,
    latency_sec: float,
    usage: dict,
    reasoning_suppressed: bool,
    args: argparse.Namespace,
) -> dict:
    return {
        "status": "ok",
        "label": label,
        "model": model,
        "case_id": _case_id(index, case),
        "index": index,
        "candidate_bubbles": candidate,
        "candidate_score": candidate_score,
        "reference_score": reference_score,
        "reasons": reasons,
        "judge_candidate_win": judge_candidate_win,
        "latency_sec": round(latency_sec, 3),
        "usage": usage,
        "reasoning_suppressed": reasoning_suppressed,
        "allow_reasoning": args.allow_reasoning,
        "temperature": args.temperature,
        "max_tokens": args.max_tokens,
        "timeout": args.timeout,
        "created_at": int(time.time()),
    }


def _make_failure_record(
    *,
    label: str,
    model: str,
    index: int,
    case: dict,
    error: Exception,
    latency_sec: float,
    args: argparse.Namespace,
) -> dict:
    return {
        "status": "error",
        "label": label,
        "model": model,
        "case_id": _case_id(index, case),
        "index": index,
        "error": str(error),
        "latency_sec": round(latency_sec, 3),
        "temperature": args.temperature,
        "max_tokens": args.max_tokens,
        "timeout": args.timeout,
        "allow_reasoning": args.allow_reasoning,
        "created_at": int(time.time()),
    }


def _has_token_usage(usage: dict | None) -> bool:
    return isinstance(usage, dict) and usage.get("prompt_tokens") is not None


def _mean_usage(usages: list[dict], key: str) -> float | None:
    values = [int(u.get(key) or 0) for u in usages if _has_token_usage(u)]
    return mean(values) if values else None


def _total_usage(usages: list[dict], key: str) -> int | None:
    values = [int(u.get(key) or 0) for u in usages if _has_token_usage(u)]
    return sum(values) if values else None


def run_generation(model: str, cases: list[dict], args: argparse.Namespace, system_prompt: str) -> dict:
    resolved_model = resolve_model_id(model)
    cand_scores, ref_scores, judge_wins, judged, failures, latencies, token_usages = [], [], 0, 0, [], [], []
    consecutive_failures = 0
    jsonl_path = getattr(args, "jsonl_path", None)
    jsonl_lock = Lock()

    print(f"\n=== {model} -> {resolved_model} ===")

    resume_records = {} if args.no_resume else _load_resume_records(jsonl_path, resolved_model, cases)
    if resume_records:
        for i, c in enumerate(cases, 1):
            record = resume_records.get(_case_id(i, c))
            if not record:
                continue
            cand_scores.append(record["candidate_score"])
            ref_scores.append(record["reference_score"])
            if record.get("latency_sec") is not None:
                latencies.append(float(record["latency_sec"]))
            if _has_token_usage(record.get("usage")):
                token_usages.append(record["usage"])
            if record.get("judge_candidate_win") is not None:
                judged += 1
                if record["judge_candidate_win"]:
                    judge_wins += 1
        print(f"  resume: найдено готовых кейсов {len(resume_records)}/{len(cases)}")

    pending_cases = [
        (i, c)
        for i, c in enumerate(cases, 1)
        if _case_id(i, c) not in resume_records
    ]
    if not pending_cases:
        print("  все кейсы уже есть в JSONL, генерация не нужна")

    def run_one(index_case: tuple[int, dict]) -> dict:
        i, c = index_case
        started = time.perf_counter()
        try:
            response = openrouter_chat_response(
                model=resolved_model,
                messages=build_messages(system_prompt, c),
                temperature=args.temperature,
                max_tokens=args.max_tokens,
                retries=args.retries,
                timeout=args.timeout,
                allow_reasoning=args.allow_reasoning,
            )
            raw = response["content"]
            cand = parse_bubbles(raw)
            cs, reasons = heuristic_score(cand)
            rs, _ = heuristic_score(c["reference_bubbles"])
            judge_candidate_win = None
            if args.judge:
                # Детерминированно чередуем порядок, чтобы параллельный прогон был воспроизводимым.
                cand_is_a = i % 2 == 1
                if cand_is_a:
                    w = judge(
                        args.judge,
                        c["user_input"],
                        cand,
                        c["reference_bubbles"],
                        retries=args.retries,
                        timeout=args.timeout,
                        allow_reasoning=args.allow_reasoning,
                    )
                else:
                    w = judge(
                        args.judge,
                        c["user_input"],
                        c["reference_bubbles"],
                        cand,
                        retries=args.retries,
                        timeout=args.timeout,
                        allow_reasoning=args.allow_reasoning,
                    )
                judge_candidate_win = (w == "A") == cand_is_a
            latency_sec = time.perf_counter() - started
            return _make_success_record(
                label=model,
                model=resolved_model,
                index=i,
                case=c,
                candidate=cand,
                candidate_score=cs,
                reference_score=rs,
                reasons=reasons,
                judge_candidate_win=judge_candidate_win,
                latency_sec=latency_sec,
                usage=response["usage"],
                reasoning_suppressed=bool(response.get("reasoning_suppressed")),
                args=args,
            )
        except Exception as e:
            latency_sec = time.perf_counter() - started
            return _make_failure_record(
                label=model,
                model=resolved_model,
                index=i,
                case=c,
                error=e,
                latency_sec=latency_sec,
                args=args,
            )

    if args.concurrency > 1:
        with ThreadPoolExecutor(max_workers=args.concurrency) as executor:
            futures = {
                executor.submit(run_one, (i, c)): (i, c)
                for i, c in pending_cases
            }
            for future in as_completed(futures):
                i, c = futures[future]
                item = future.result()
                _append_jsonl(jsonl_path, item, jsonl_lock)

                if item["status"] == "error":
                    failures.append({"case_id": item["case_id"], "error": item["error"], "latency_sec": item["latency_sec"]})
                    print(f"  [{i}/{len(cases)}] ошибка генерации за {item['latency_sec']:.1f}s: {item['error']}")
                    continue

                cand_scores.append(item["candidate_score"])
                ref_scores.append(item["reference_score"])
                latencies.append(item["latency_sec"])
                if _has_token_usage(item.get("usage")):
                    token_usages.append(item["usage"])
                if item["judge_candidate_win"] is not None:
                    judged += 1
                    if item["judge_candidate_win"]:
                        judge_wins += 1
                if i <= 3 or item["candidate_score"] < 60:
                    print(f"  [{i}] {c['id']} score={item['candidate_score']} "
                          f"ref={item['reference_score']} bubbles={len(item['candidate_bubbles'])} "
                          f"latency={item['latency_sec']:.1f}s "
                          f"{'| ' + '; '.join(item['reasons']) if item['reasons'] else ''}")
    else:
        for i, c in pending_cases:
            item = run_one((i, c))
            _append_jsonl(jsonl_path, item, jsonl_lock)

            if item["status"] == "error":
                failures.append({"case_id": item["case_id"], "error": item["error"], "latency_sec": item["latency_sec"]})
                consecutive_failures += 1
                print(f"  [{i}/{len(cases)}] ошибка генерации за {item['latency_sec']:.1f}s: {item['error']}")
                if consecutive_failures >= args.max_consecutive_failures:
                    print(f"  остановка модели после {consecutive_failures} ошибок подряд")
                    break
                continue

            consecutive_failures = 0
            cand_scores.append(item["candidate_score"])
            ref_scores.append(item["reference_score"])
            latencies.append(item["latency_sec"])
            if _has_token_usage(item.get("usage")):
                token_usages.append(item["usage"])
            if item["judge_candidate_win"] is not None:
                judged += 1
                if item["judge_candidate_win"]:
                    judge_wins += 1
            if i <= 3 or item["candidate_score"] < 60:
                print(f"  [{i}] {c['id']} score={item['candidate_score']} "
                      f"ref={item['reference_score']} bubbles={len(item['candidate_bubbles'])} "
                      f"latency={item['latency_sec']:.1f}s "
                      f"{'| ' + '; '.join(item['reasons']) if item['reasons'] else ''}")

    total_prompt_tokens = _total_usage(token_usages, "prompt_tokens")
    total_cached_tokens = _total_usage(token_usages, "cached_tokens")
    result = {
        "label": model,
        "model": resolved_model,
        "n_requested": len(cases),
        "n_completed": len(cand_scores),
        "n_resumed": len(resume_records),
        "failures": failures,
        "candidate_score": mean(cand_scores) if cand_scores else None,
        "reference_score": mean(ref_scores) if ref_scores else None,
        "temperature": args.temperature,
        "concurrency": args.concurrency,
        "max_tokens": args.max_tokens,
        "timeout": args.timeout,
        "allow_reasoning": args.allow_reasoning,
        "reasoning_suppressed": _should_suppress_reasoning(resolved_model, args.allow_reasoning),
        "avg_latency_sec": mean(latencies) if latencies else None,
        "usage_n": len(token_usages),
        "avg_prompt_tokens_per_dialog": _mean_usage(token_usages, "prompt_tokens"),
        "avg_completion_tokens_per_dialog": _mean_usage(token_usages, "completion_tokens"),
        "avg_total_tokens_per_dialog": _mean_usage(token_usages, "total_tokens"),
        "avg_cached_tokens_per_dialog": _mean_usage(token_usages, "cached_tokens"),
        "total_prompt_tokens": total_prompt_tokens,
        "total_completion_tokens": _total_usage(token_usages, "completion_tokens"),
        "total_tokens": _total_usage(token_usages, "total_tokens"),
        "total_cached_tokens": total_cached_tokens,
        "cache_hit_ratio": (
            round(total_cached_tokens / total_prompt_tokens, 3)
            if total_prompt_tokens
            else None
        ),
        "judge_model": args.judge,
        "judge_win_rate": (100 * judge_wins / judged) if judged else None,
    }

    if cand_scores:
        print(f"\nМОДЕЛЬ: {resolved_model}  (n={len(cand_scores)}, T={args.temperature})")
        print(f"  Балл кандидата: {result['candidate_score']:.1f}/100   "
              f"Эталон Михаила: {result['reference_score']:.1f}/100")
        if result["avg_latency_sec"] is not None:
            print(f"  Средняя latency по успешным кейсам: {result['avg_latency_sec']:.1f}s")
        if result["avg_total_tokens_per_dialog"] is not None:
            print(
                "  Средние токены на диалог: "
                f"input={result['avg_prompt_tokens_per_dialog']:.0f}, "
                f"output={result['avg_completion_tokens_per_dialog']:.0f}, "
                f"total={result['avg_total_tokens_per_dialog']:.0f}, "
                f"cached={result['avg_cached_tokens_per_dialog']:.0f}, "
                f"cache_hit_ratio={result['cache_hit_ratio']}"
            )
        if failures:
            print(f"  Ошибок генерации: {len(failures)}")
    else:
        print(f"\nМОДЕЛЬ: {resolved_model}: нет успешных генераций")
    if args.judge and judged:
        print(f"  Судья ({args.judge}): кандидат выигрывает у Михаила в "
              f"{result['judge_win_rate']:.0f}% случаев (50% = неотличимо)")

    return result


def prepare_output_paths(args: argparse.Namespace) -> None:
    """Set stable JSON/JSONL paths before generation so partial progress is recoverable."""
    out_path = Path(args.out) if args.out else HERE / "logs" / f"eval_openrouter_{int(time.time())}.json"
    jsonl_path = Path(args.jsonl_out) if args.jsonl_out else out_path.with_suffix(".jsonl")
    args.out_path = out_path
    args.jsonl_path = jsonl_path


def write_results(results: list[dict], args: argparse.Namespace) -> None:
    out_path = args.out_path
    out_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "models": DEFAULT_MODELS,
        "n": args.n,
        "temperature": args.temperature,
        "concurrency": args.concurrency,
        "max_tokens": args.max_tokens,
        "timeout": args.timeout,
        "retries": args.retries,
        "allow_reasoning": args.allow_reasoning,
        "jsonl_path": str(args.jsonl_path),
        "results": results,
    }
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nРезультаты сохранены: {out_path}")
    print(f"JSONL по кейсам: {args.jsonl_path}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["baseline", "gen"])
    ap.add_argument("--model", default=None)
    ap.add_argument("--models", nargs="*", default=None)
    ap.add_argument("--judge", default=None)
    ap.add_argument("--n", type=int, default=len(CASES))
    ap.add_argument("--temperature", type=float, default=0.7)
    ap.add_argument("--retries", type=int, default=1)
    ap.add_argument("--concurrency", type=int, default=4)
    ap.add_argument("--max-tokens", type=int, default=350)
    ap.add_argument("--timeout", type=int, default=45)
    ap.add_argument("--allow-reasoning", action="store_true")
    ap.add_argument("--max-consecutive-failures", type=int, default=8)
    ap.add_argument("--out", default=None)
    ap.add_argument("--jsonl-out", default=None)
    ap.add_argument("--no-resume", action="store_true")
    ap.add_argument("--env-file", default=None, help="Optional .env path with OPENROUTER_API_KEY/OPEN_ROUTER_API_KEY")
    args = ap.parse_args()

    if args.env_file:
        load_dotenv(Path(args.env_file), override=True)
        load_env_file(Path(args.env_file), override=True)

    cases = CASES[: args.n]

    if args.mode == "baseline":
        scores = []
        for c in cases:
            s, _ = heuristic_score(c["reference_bubbles"])
            scores.append(s)
        print(f"BASELINE (ответы самого Михаила), n={len(scores)}")
        print(f"  Средний балл эталона: {mean(scores):.1f}/100  <- целевая полоса для бота")
        print(f"  Доля кейсов с очередью >=2: "
              f"{100*sum(1 for c in cases if c['reference_bubble_count']>=2)/len(cases):.0f}%")
        return

    # gen
    try:
        get_openrouter_api_key()
    except RuntimeError as e:
        print(f"!! {e}")
        sys.exit(2)

    try:
        from prompts import get_full_system_prompt
        system_prompt = get_full_system_prompt()
    except Exception as e:
        print(f"!! не смог импортировать prompts.get_full_system_prompt ({e}); запусти из корня репо")
        sys.exit(1)
    if args.models:
        models = args.models
    elif args.model == "all":
        models = list(DEFAULT_MODELS)
    elif args.model:
        models = [args.model]
    else:
        print("укажи --model, напр. --model deepseek-v4-pro или --model all")
        print("доступные алиасы:", ", ".join(DEFAULT_MODELS))
        sys.exit(1)

    prepare_output_paths(args)
    args.out_path.parent.mkdir(parents=True, exist_ok=True)
    args.jsonl_path.parent.mkdir(parents=True, exist_ok=True)
    if not args.no_resume:
        print(f"resume включён: успешные кейсы будут подхвачены из {args.jsonl_path}")

    results = [run_generation(model, cases, args, system_prompt) for model in models]
    if len(results) > 1:
        print("\nИТОГОВАЯ ТАБЛИЦА")
        for r in sorted(results, key=lambda x: x["candidate_score"] or -1, reverse=True):
            score = "n/a" if r["candidate_score"] is None else f"{r['candidate_score']:.1f}"
            print(f"  {r['label']:18s} {score:>5s}/100  "
                  f"ok={r['n_completed']}/{r['n_requested']}  id={r['model']}")
    write_results(results, args)


if __name__ == "__main__":
    main()
