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
import logging
import os

log = logging.getLogger("starsage.llm")

# Default model ids per provider/tier — used when the caller hasn't chosen a model.
# The effective model is resolved at call time (model_for) so a per-request override
# via STARSAGE_<PROVIDER>_<TIER> (set from the console's stored settings) takes effect.
MODELS = {
    "claude": {
        "quality": "claude-sonnet-5",
        "fast": "claude-haiku-4-5",
        "key_env": ("ANTHROPIC_API_KEY",),
    },
    "gpt": {
        "quality": "gpt-4o",
        "fast": "gpt-4o-mini",
        "key_env": ("OPENAI_API_KEY",),
    },
    "gemini": {
        # "-latest" aliases track Google's current pro/flash and never 404 on
        # deprecation (unlike pinned "-preview" ids). Pin an exact model per
        # request via the console or STARSAGE_GEMINI_QUALITY / _FAST.
        "quality": "gemini-pro-latest",
        "fast": "gemini-flash-latest",
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
    """Effective model for a tier: a per-request env override
    (STARSAGE_<PROVIDER>_<TIER>, e.g. STARSAGE_CLAUDE_QUALITY) wins, else the default."""
    provider = resolve_provider()
    if provider == "mock":
        return "mock"
    override = os.environ.get(f"STARSAGE_{provider.upper()}_{tier.upper()}")
    return override or MODELS[provider][tier]


def list_models(provider: str, api_key: str) -> list[str]:
    """Live model ids from the provider's official API, using the given key. Raises
    on auth/network errors so the caller can fall back to a curated list."""
    if provider == "claude":
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)
        return [m.id for m in client.models.list(limit=1000).data]
    if provider == "gpt":
        import re
        from openai import OpenAI
        client = OpenAI(api_key=api_key)
        ids = [m.id for m in client.models.list().data]
        # keep chat-capable families; drop embeddings/audio/image/etc.
        keep = [i for i in ids if i.startswith(("gpt", "chatgpt")) or re.match(r"^o\d", i)]
        return sorted(keep)
    if provider == "gemini":
        from google import genai
        client = genai.Client(api_key=api_key)
        out = []
        for m in client.models.list():
            short = (getattr(m, "name", "") or "").split("/")[-1]
            actions = getattr(m, "supported_actions", None) or []
            if short.startswith("gemini") and (not actions or "generateContent" in actions):
                out.append(short)
        return sorted(set(out))
    return []


# ---- provider adapters ----------------------------------------------------
def _call_claude(model, system, messages, temp, max_tokens):
    import anthropic
    client = anthropic.Anthropic(api_key=_key_for("claude"))
    # Claude 5 / Opus 4.7+ reject `temperature` (400) — steer via the prompt.
    # Disable thinking: it is ON by default on Claude 5 and its tokens count against
    # max_tokens, so a heavy prompt can spend the whole budget thinking and return an
    # empty completion (stop_reason=max_tokens, zero text).
    resp = client.messages.create(
        model=model, system=system, messages=messages,
        max_tokens=max_tokens, thinking={"type": "disabled"},
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
    if _key_for(provider) is None:
        # Clear, loggable error instead of the SDK's opaque "could not resolve
        # authentication method" (e.g. a stored key that failed to decrypt).
        raise RuntimeError(f"no usable API key for provider '{provider}' "
                           "(missing, or failed to decrypt — check STARSAGE_SECRET_KEY)")
    model = model_for(tier)
    log.info("LLM call: provider=%s tier=%s model=%s", provider, tier, model)
    try:
        out = _DISPATCH[provider](model, system, messages, temp, max_tokens)
    except Exception as e:
        # Log the true provider error here (the caller may swallow it into a fallback).
        log.error("LLM call failed: provider=%s model=%s -> %s: %s",
                  provider, model, type(e).__name__, e)
        raise
    return out or ""   # normalise a None/empty completion to "" for uniform handling


def call_llm(tier, system, user, temp=0.7, max_tokens=800):
    """Single-shot call. Returns raw text."""
    return _dispatch(tier, system, [{"role": "user", "content": user}], temp, max_tokens)


def call_llm_with_history(tier, system, history, user, temp=0.7, max_tokens=800):
    """Call with prior turns. `history` is a list of {role, content}."""
    messages = list(history) + [{"role": "user", "content": user}]
    return _dispatch(tier, system, messages, temp, max_tokens)


# ---- streaming ------------------------------------------------------------
def _stream_claude(model, system, messages, temp, max_tokens):
    import anthropic
    client = anthropic.Anthropic(api_key=_key_for("claude"))
    # Claude 5 / Opus 4.7+ reject `temperature` (400); disable thinking so its tokens
    # don't consume the whole max_tokens budget and starve the streamed answer.
    with client.messages.stream(model=model, system=system, messages=messages,
                                 max_tokens=max_tokens, thinking={"type": "disabled"}) as stream:
        for text in stream.text_stream:
            yield text


def _stream_gpt(model, system, messages, temp, max_tokens):
    from openai import OpenAI
    client = OpenAI(api_key=_key_for("gpt"))
    msgs = [{"role": "system", "content": system}] + messages
    stream = client.chat.completions.create(
        model=model, messages=msgs, temperature=temp, max_tokens=max_tokens, stream=True)
    for chunk in stream:
        delta = chunk.choices[0].delta.content
        if delta:
            yield delta


def _stream_gemini(model, system, messages, temp, max_tokens):
    from google import genai
    from google.genai import types
    client = genai.Client(api_key=_key_for("gemini"))
    contents = [
        {"role": "model" if m["role"] == "assistant" else "user", "parts": [{"text": m["content"]}]}
        for m in messages
    ]
    # Give headroom so thinking tokens don't starve the streamed answer.
    stream = client.models.generate_content_stream(
        model=model, contents=contents,
        config=types.GenerateContentConfig(
            system_instruction=system, temperature=temp, max_output_tokens=max_tokens + 4096),
    )
    for chunk in stream:
        if chunk.text:
            yield chunk.text


_STREAM = {"claude": _stream_claude, "gpt": _stream_gpt, "gemini": _stream_gemini}


def stream_llm(tier, system, history, user, temp=0.7, max_tokens=800):
    """Yield text deltas from the model. Raises in mock mode (callers handle mock)."""
    provider = resolve_provider()
    if provider == "mock":
        raise RuntimeError("stream_llm called in mock mode — callers should check is_mock() first.")
    if _key_for(provider) is None:
        raise RuntimeError(f"no usable API key for provider '{provider}' "
                           "(missing, or failed to decrypt — check STARSAGE_SECRET_KEY)")
    messages = list(history) + [{"role": "user", "content": user}]
    yield from _STREAM[provider](model_for(tier), system, messages, temp, max_tokens)
