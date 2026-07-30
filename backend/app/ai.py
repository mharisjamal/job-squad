"""One small OpenAI-compatible chat client plus the resume-tailoring prompt.

Every configured provider (Gemini, Groq, or a custom base URL) speaks the same
OpenAI /chat/completions shape, so a single async httpx call backs both the
settings "test" button and the tailoring endpoint. Errors are turned into an
AIError carrying a user-safe message; the raw provider payload is never leaked
to the client and API keys are never logged.
"""

import json
import logging

import httpx

logger = logging.getLogger(__name__)

AI_TIMEOUT_SECONDS = 60.0


class AIError(Exception):
    """A provider call failed. The message is safe to show to the user."""


async def chat_completion(
    *,
    base_url: str,
    api_key: str,
    model: str,
    messages: list[dict],
    temperature: float = 0.2,
    timeout: float = AI_TIMEOUT_SECONDS,
) -> str:
    """POST to {base_url}/chat/completions and return the assistant text.

    Raises AIError with a clean, user-facing message on any failure.
    """
    if not base_url:
        raise AIError("No AI provider base URL is configured.")
    if not api_key:
        raise AIError("No AI API key is configured.")
    url = base_url.rstrip("/") + "/chat/completions"
    payload = {"model": model, "messages": messages, "temperature": temperature}
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    try:
        async with httpx.AsyncClient(timeout=timeout) as http:
            response = await http.post(url, json=payload, headers=headers)
    except httpx.TimeoutException as exc:
        raise AIError("The AI provider timed out. Try again.") from exc
    except httpx.HTTPError as exc:
        raise AIError("Could not reach the AI provider. Check the base URL.") from exc

    if response.status_code in (401, 403):
        raise AIError("Your API key was rejected.")
    if response.status_code == 404:
        raise AIError("The AI endpoint or model was not found. Check the base URL and model.")
    if response.status_code == 429:
        raise AIError("The AI provider is rate limiting. Try again in a moment.")
    if response.status_code >= 500:
        raise AIError("The AI provider had a server error. Try again.")
    if response.status_code >= 400:
        raise AIError(_provider_error_message(response))

    try:
        data = response.json()
        content = data["choices"][0]["message"]["content"]
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        raise AIError("The AI provider returned an unexpected response.") from exc
    if not isinstance(content, str) or not content.strip():
        raise AIError("The AI provider returned an empty response.")
    return content


def _provider_error_message(response: httpx.Response) -> str:
    """Pull a short, safe message out of a 4xx body without leaking internals."""
    try:
        body = response.json()
        message = body.get("error", {}).get("message") if isinstance(body, dict) else None
    except ValueError:
        message = None
    if isinstance(message, str) and message.strip():
        return f"The AI provider rejected the request: {message.strip()[:200]}"
    return f"The AI provider returned an error (status {response.status_code})."


# ---------------------------------------------------------------------------
# Resume tailoring prompt. The constraints below encode the researched
# best-practice rules (IMPLEMENTATION_PLAN.md 9b) as explicit numbered rules;
# the R3 verifier asserts their presence, so keep them verbatim in intent.
# ---------------------------------------------------------------------------

TAILOR_CONSTRAINTS = (
    "You are a careful resume tailoring assistant. You edit a candidate's EXISTING "
    "resume to align it with a specific job description, without fabricating anything. "
    "Follow every constraint exactly:\n\n"
    "1. NEVER invent or change employers, job titles, dates, degrees, certifications, "
    "skills, tools, or metrics. Every fact in your output must already be present in "
    "the candidate's resume.\n"
    "2. The contact block (name, email, phone, links, address) is FROZEN. Never "
    "change, add, or remove any contact detail.\n"
    "3. Edits are limited to rephrasing, reordering, and re-emphasizing content that "
    "is ALREADY in the resume. You may sharpen wording and surface the most relevant "
    "experience earlier; you may not add experience the candidate does not have.\n"
    "4. Do NOT keyword-stuff. Modern ATS penalizes unnatural keyword density. "
    "Introduce a job-description term at most a few times and only where it reads "
    "naturally; never repeat a term to raise its frequency.\n"
    "5. NEVER produce hidden, white-on-white, zero-opacity, off-page, tiny, or "
    "otherwise invisible text. All text must be visible and honest; hidden keywords "
    "are fraud and cause automatic rejection.\n"
    "6. Mirror the job description's exact terminology ONLY when the candidate "
    "genuinely has that skill (for example, rephrase a synonym the resume already "
    "uses). Never claim a skill the resume does not support.\n"
    "7. Prefer quantified, STAR-style bullets with strong action verbs and measurable "
    "outcomes, but use ONLY numbers already present in the resume. If a bullet has no "
    "metric, keep it qualitative rather than inventing one.\n"
    "8. If the job description requires something the resume does not support, report "
    'it as a GAP suggestion ("consider adding X if you have it"), never silently '
    "write it into the resume.\n"
    "9. Reason through the changes before writing, then return ONLY the JSON described "
    "below: no prose, no explanation, no markdown, no code fences."
)

_TEX_OUTPUT_SCHEMA = (
    "The candidate's resume is LaTeX source. Return this exact JSON object and "
    "nothing else:\n"
    '{"tailored_tex": "<the full edited .tex document as one string>", '
    '"changes": ["short summary of each change you made"]}\n'
    "The tailored_tex must be a complete, compilable LaTeX document derived from the "
    "original, obeying every constraint above."
)

_ADVICE_OUTPUT_SCHEMA = (
    "The candidate's resume is a PDF/DOCX you cannot rewrite directly, so return "
    "advice only. Return this exact JSON object and nothing else:\n"
    '{"suggestions": [{"section": "<resume section>", '
    '"original": "<exact text from the resume>", '
    '"suggested": "<the improved rephrasing>", '
    '"reason": "<why this helps for this job>"}], '
    '"keywords_to_add": ["<a job-description term the candidate genuinely has but '
    'has not surfaced>"]}\n'
    'Every "original" must be text that actually appears in the resume. Only list a '
    "keyword the candidate genuinely supports; frame anything they lack as a GAP "
    "suggestion instead."
)

_JSON_RETRY_NUDGE = (
    "Your previous reply was not valid JSON. Return ONLY the JSON object described"
    " earlier, with no prose, no markdown, and no code fences."
)


def build_tailor_system_prompt(kind: str) -> str:
    """The system message: shared constraints plus the per-kind output schema."""
    schema = _TEX_OUTPUT_SCHEMA if kind == "tex" else _ADVICE_OUTPUT_SCHEMA
    return f"{TAILOR_CONSTRAINTS}\n\n{schema}"


def build_tailor_messages(kind: str, resume_text: str, jd_text: str) -> list[dict]:
    """Full message list for a tailoring request."""
    user = (
        "JOB DESCRIPTION:\n"
        f"{jd_text}\n\n"
        f"CANDIDATE RESUME ({'LaTeX source' if kind == 'tex' else kind.upper()}):\n"
        f"{resume_text}"
    )
    return [
        {"role": "system", "content": build_tailor_system_prompt(kind)},
        {"role": "user", "content": user},
    ]


def parse_tailor_json(text: str) -> dict | None:
    """Parse the model's tailoring reply into a dict, tolerating a stray code
    fence. Returns None when the reply is not usable JSON so the caller can
    retry once and then fail cleanly."""
    candidate = text.strip()
    if candidate.startswith("```"):
        # Strip a ```json ... ``` fence if the model added one anyway.
        candidate = candidate.strip("`")
        newline = candidate.find("\n")
        if newline != -1 and candidate[:newline].strip().lower() in ("json", ""):
            candidate = candidate[newline + 1 :]
        candidate = candidate.strip()
    try:
        parsed = json.loads(candidate)
    except (ValueError, TypeError):
        return None
    return parsed if isinstance(parsed, dict) else None


def json_retry_messages(messages: list[dict], previous_reply: str) -> list[dict]:
    """Extend a conversation with the model's bad reply and a JSON-only nudge."""
    return [
        *messages,
        {"role": "assistant", "content": previous_reply},
        {"role": "user", "content": _JSON_RETRY_NUDGE},
    ]
