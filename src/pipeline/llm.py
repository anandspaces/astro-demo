"""LLM abstraction with a 3-way provider switch: Claude / GPT / Gemini.

Select the provider with the STARSAGE_PROVIDER env var (claude | gpt | gemini | mock).
If unset, auto-detects from whichever API key is present; falls back to `mock`
(deterministic, no network) so the whole pipeline runs and is testable with no keys.

Each provider reads its own key:
  claude  -> ANTHROPIC_API_KEY
  gpt     -> OPENAI_API_KEY
  gemini  -> GEMINI_API_KEY  (or GOOGLE_API_KEY)

Two model tiers are used by the pipeline:
  "quality" -> Generator / Synthesis
  "fast"    -> Planner / Critic
Override any model id via env, e.g. STARSAGE_CLAUDE_QUALITY=claude-opus-4-8.
"""
import os

# Default model ids per provider/tier. The spec's `claude-sonnet-4-6` was invalid;
# these are current, and each is overridable via env.
MODELS = {
    "claude": {
        "quality": os.environ.get("STARSAGE_CLAUDE_QUALITY", "claude-sonnet-5"),
        "fast": os.environ.get("STARSAGE_CLAUDE_FAST", "claude-haiku-4-5"),
        "key_env": ("ANTHROPIC_API_KEY",),
    },
    "gpt": {
        "quality": os.environ.get("STARSAGE_GPT_QUALITY", "gpt-4o"),
        "fast": os.environ.get("STARSAGE_GPT_FAST", "gpt-4o-mini"),
        "key_env": ("OPENAI_API_KEY",),
    },
    "gemini": {
        "quality": os.environ.get("STARSAGE_GEMINI_QUALITY", "gemini-2.5-pro"),
        "fast": os.environ.get("STARSAGE_GEMINI_FAST", "gemini-2.5-flash"),
        "key_env": ("GEMINI_API_KEY", "GOOGLE_API_KEY"),
    },
}


def _key_for(provider):
    for env in MODELS[provider]["key_env"]:
        if os.environ.get(env):
            return os.environ[env]
    return None


def resolve_provider() -> str:
    """Explicit STARSAGE_PROVIDER wins; else first provider with a key; else mock."""
    p = os.environ.get("STARSAGE_PROVIDER", "").strip().lower()
    if p in MODELS or p == "mock":
        return p
    for provider in ("claude", "gpt", "gemini"):
        if _key_for(provider):
            return provider
    return "mock"


def is_mock() -> bool:
    return resolve_provider() == "mock"


def model_for(tier: str) -> str:
    provider = resolve_provider()
    if provider == "mock":
        return "mock"
    return MODELS[provider][tier]


# ---- provider adapters ----------------------------------------------------
def _call_claude(model, system, messages, temp, max_tokens):
    import anthropic
    client = anthropic.Anthropic(api_key=_key_for("claude"))
    resp = client.messages.create(
        model=model, system=system, messages=messages,
        temperature=temp, max_tokens=max_tokens,
    )
    return "".join(b.text for b in resp.content if b.type == "text")


def _call_gpt(model, system, messages, temp, max_tokens):
    from openai import OpenAI
    client = OpenAI(api_key=_key_for("gpt"))
    msgs = [{"role": "system", "content": system}] + messages
    resp = client.chat.completions.create(
        model=model, messages=msgs, temperature=temp, max_tokens=max_tokens,
    )
    return resp.choices[0].message.content


def _call_gemini(model, system, messages, temp, max_tokens):
    from google import genai
    from google.genai import types
    client = genai.Client(api_key=_key_for("gemini"))
    # Gemini uses 'user'/'model' roles; system prompt goes in config.
    contents = [
        {"role": "model" if m["role"] == "assistant" else "user",
         "parts": [{"text": m["content"]}]}
        for m in messages
    ]
    # Gemini 3 "thinks" by default, and thinking tokens count against
    # max_output_tokens — starving the answer. Two-pass strategy:
    #  1) try with thinking disabled (flash honours this; full budget -> answer),
    #  2) else give generous headroom so thinking + the full reading both fit
    #     (pro-preview requires thinking). The Critic caps answer length anyway.
    attempts = [
        dict(max_output_tokens=max_tokens, thinking_config=types.ThinkingConfig(thinking_budget=0)),
        dict(max_output_tokens=max_tokens + 4096),
    ]
    last_err = None
    for cfg in attempts:
        try:
            resp = client.models.generate_content(
                model=model, contents=contents,
                config=types.GenerateContentConfig(system_instruction=system, temperature=temp, **cfg),
            )
            if resp.text:
                return resp.text
        except Exception as e:
            last_err = e
            continue
    if last_err:
        raise last_err
    return ""


_DISPATCH = {"claude": _call_claude, "gpt": _call_gpt, "gemini": _call_gemini}


def _dispatch(tier, system, messages, temp, max_tokens):
    provider = resolve_provider()
    if provider == "mock":
        raise RuntimeError("LLM called in mock mode — callers should check is_mock() first.")
    model = MODELS[provider][tier]
    return _DISPATCH[provider](model, system, messages, temp, max_tokens)


def call_llm(tier, system, user, temp=0.7, max_tokens=800):
    """Single-shot call. Returns raw text."""
    return _dispatch(tier, system, [{"role": "user", "content": user}], temp, max_tokens)


def call_llm_with_history(tier, system, history, user, temp=0.7, max_tokens=800):
    """Call with prior turns. `history` is a list of {role, content}."""
    messages = list(history) + [{"role": "user", "content": user}]
    return _dispatch(tier, system, messages, temp, max_tokens)
