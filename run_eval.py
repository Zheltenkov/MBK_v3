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

  ... --judge openai/gpt-4o   (доп. к gen)
      LLM-судья сравнивает кандидата с эталоном вслепую: «кто звучит как живой занятой
      специалист». Возвращает win-rate кандидата.
"""
from __future__ import annotations
import argparse, json, os, re, sys, time, urllib.error, urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from statistics import mean

from dotenv import load_dotenv

HERE = Path(__file__).resolve().parent
CASES = json.loads((HERE / "mikhail_eval_cases.json").read_text(encoding="utf-8"))
load_dotenv(HERE / ".env")

DEFAULT_MODELS = {
    "deepseek-v4-pro": "deepseek/deepseek-v4-pro",
    "qwen3.6-plus": "qwen/qwen3.6-plus",
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


def openrouter_chat(model: str, messages: list[dict], temperature: float = 0.7,
                    max_tokens: int = 700, retries: int = 3) -> str:
    key = get_openrouter_api_key()
    payload = {
        "model": model, "messages": messages,
        "temperature": temperature,
        "max_tokens": max(max_tokens, 1800) if model.startswith("deepseek/deepseek-v4") else max_tokens,
    }
    if model.startswith("deepseek/deepseek-v4"):
        payload["reasoning"] = {"effort": "none", "exclude": True}
        payload["include_reasoning"] = False
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
            with urllib.request.urlopen(req, timeout=90) as r:
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
            return str(content)
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

def judge(model: str, user_input: str, a: list[str], b: list[str]) -> str:
    prompt = (f"Сообщение клиента: {user_input}\n\n"
              f"Ответ A:\n" + "\n".join(a) + "\n\nОтвет B:\n" + "\n".join(b))
    out = openrouter_chat(model, [{"role": "system", "content": JUDGE_SYS},
                                  {"role": "user", "content": prompt}],
                          temperature=0, max_tokens=16)
    return "A" if "a" in out.lower()[:3] else "B"


def run_generation(model: str, cases: list[dict], args: argparse.Namespace, system_prompt: str) -> dict:
    resolved_model = resolve_model_id(model)
    cand_scores, ref_scores, judge_wins, judged, failures = [], [], 0, 0, []
    consecutive_failures = 0

    print(f"\n=== {model} -> {resolved_model} ===")

    if args.concurrency > 1:
        def run_one(index_case: tuple[int, dict]) -> dict:
            i, c = index_case
            raw = openrouter_chat(
                resolved_model,
                build_messages(system_prompt, c),
                args.temperature,
                retries=args.retries,
            )
            cand = parse_bubbles(raw)
            cs, reasons = heuristic_score(cand)
            rs, _ = heuristic_score(c["reference_bubbles"])
            judge_candidate_win = None
            if args.judge:
                # Детерминированно чередуем порядок, чтобы параллельный прогон был воспроизводимым.
                cand_is_a = i % 2 == 1
                if cand_is_a:
                    w = judge(args.judge, c["user_input"], cand, c["reference_bubbles"])
                else:
                    w = judge(args.judge, c["user_input"], c["reference_bubbles"], cand)
                judge_candidate_win = (w == "A") == cand_is_a
            return {
                "index": i,
                "case": c,
                "candidate": cand,
                "candidate_score": cs,
                "reference_score": rs,
                "reasons": reasons,
                "judge_candidate_win": judge_candidate_win,
            }

        completed = []
        with ThreadPoolExecutor(max_workers=args.concurrency) as executor:
            futures = {
                executor.submit(run_one, (i, c)): (i, c)
                for i, c in enumerate(cases, 1)
            }
            for future in as_completed(futures):
                i, c = futures[future]
                try:
                    item = future.result()
                    completed.append(item)
                except Exception as e:
                    failures.append({"case_id": c.get("id"), "error": str(e)})
                    print(f"  [{i}/{len(cases)}] ошибка генерации: {e}")
                    continue

                cand_scores.append(item["candidate_score"])
                ref_scores.append(item["reference_score"])
                if item["judge_candidate_win"] is not None:
                    judged += 1
                    if item["judge_candidate_win"]:
                        judge_wins += 1
                if i <= 3 or item["candidate_score"] < 60:
                    print(f"  [{i}] {c['id']} score={item['candidate_score']} "
                          f"ref={item['reference_score']} bubbles={len(item['candidate'])} "
                          f"{'| ' + '; '.join(item['reasons']) if item['reasons'] else ''}")

        completed.sort(key=lambda x: x["index"])
    else:
        for i, c in enumerate(cases, 1):
            try:
                raw = openrouter_chat(
                    resolved_model,
                    build_messages(system_prompt, c),
                    args.temperature,
                    retries=args.retries,
                )
                cand = parse_bubbles(raw)
                consecutive_failures = 0
            except Exception as e:
                failures.append({"case_id": c.get("id"), "error": str(e)})
                consecutive_failures += 1
                print(f"  [{i}/{len(cases)}] ошибка генерации: {e}")
                if consecutive_failures >= args.max_consecutive_failures:
                    print(f"  остановка модели после {consecutive_failures} ошибок подряд")
                    break
                continue

            cs, reasons = heuristic_score(cand)
            rs, _ = heuristic_score(c["reference_bubbles"])
            cand_scores.append(cs); ref_scores.append(rs)
            if args.judge:
                # вслепую перемешиваем порядок
                import random
                if random.random() < 0.5:
                    w = judge(args.judge, c["user_input"], cand, c["reference_bubbles"]); cand_is_a = True
                else:
                    w = judge(args.judge, c["user_input"], c["reference_bubbles"], cand); cand_is_a = False
                judged += 1
                if (w == "A") == cand_is_a:
                    judge_wins += 1
            if i <= 3 or cs < 60:
                print(f"  [{i}] {c['id']} score={cs} ref={rs} bubbles={len(cand)} "
                      f"{'| ' + '; '.join(reasons) if reasons else ''}")

    result = {
        "label": model,
        "model": resolved_model,
        "n_requested": len(cases),
        "n_completed": len(cand_scores),
        "failures": failures,
        "candidate_score": mean(cand_scores) if cand_scores else None,
        "reference_score": mean(ref_scores) if ref_scores else None,
        "temperature": args.temperature,
        "concurrency": args.concurrency,
        "judge_model": args.judge,
        "judge_win_rate": (100 * judge_wins / judged) if judged else None,
    }

    if cand_scores:
        print(f"\nМОДЕЛЬ: {resolved_model}  (n={len(cand_scores)}, T={args.temperature})")
        print(f"  Балл кандидата: {result['candidate_score']:.1f}/100   "
              f"Эталон Михаила: {result['reference_score']:.1f}/100")
        if failures:
            print(f"  Ошибок генерации: {len(failures)}")
    else:
        print(f"\nМОДЕЛЬ: {resolved_model}: нет успешных генераций")
    if args.judge and judged:
        print(f"  Судья ({args.judge}): кандидат выигрывает у Михаила в "
              f"{result['judge_win_rate']:.0f}% случаев (50% = неотличимо)")

    return result


def write_results(results: list[dict], args: argparse.Namespace) -> None:
    out_path = Path(args.out) if args.out else HERE / "logs" / f"eval_openrouter_{int(time.time())}.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "models": DEFAULT_MODELS,
        "n": args.n,
        "temperature": args.temperature,
        "results": results,
    }
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nРезультаты сохранены: {out_path}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["baseline", "gen"])
    ap.add_argument("--model", default=None)
    ap.add_argument("--models", nargs="*", default=None)
    ap.add_argument("--judge", default=None)
    ap.add_argument("--n", type=int, default=len(CASES))
    ap.add_argument("--temperature", type=float, default=0.7)
    ap.add_argument("--retries", type=int, default=3)
    ap.add_argument("--concurrency", type=int, default=1)
    ap.add_argument("--max-consecutive-failures", type=int, default=8)
    ap.add_argument("--out", default=None)
    ap.add_argument("--env-file", default=None, help="Optional .env path with OPENROUTER_API_KEY/OPEN_ROUTER_API_KEY")
    args = ap.parse_args()

    if args.env_file:
        load_dotenv(Path(args.env_file), override=True)

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
