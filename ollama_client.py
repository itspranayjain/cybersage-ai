"""
Ollama integration for the phishing detector.

The Random Forest gives a fast numeric score. The LLM (running locally in
Ollama) reads the URL like a security analyst would, explains *why* it looks
safe or dangerous, and gives its own verdict. If Ollama is not running, the
app keeps working with the ML model alone.

Config (environment variables):
    OLLAMA_HOST     default http://localhost:11434
    OLLAMA_MODEL    default gemma4:e2b
    OLLAMA_TIMEOUT  seconds, default 60
"""
import json
import os

import requests

OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434").rstrip("/")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "gemma4:e2b")
OLLAMA_TIMEOUT = float(os.getenv("OLLAMA_TIMEOUT", "60"))

SYSTEM_PROMPT = """You are a cybersecurity analyst who specialises in phishing URLs.
You will be given a URL and the score from a machine-learning model.
Analyse the URL itself: domain, subdomains, TLD, brand impersonation,
typosquatting (e.g. paypa1, rn instead of m), IP addresses, URL shorteners,
'@' tricks, excessive hyphens, suspicious keywords, unusual paths or query strings.

Do NOT visit the URL. Judge only from the text.

Reply with ONLY a JSON object, no other text, in exactly this shape:
{
  "verdict": "safe" | "suspicious" | "phishing",
  "risk_score": <integer 0-100>,
  "red_flags": [<short strings>],
  "explanation": "<2-3 plain-English sentences for a non-technical user>",
  "advice": "<one sentence on what the user should do>"
}"""

VALID_VERDICTS = {"safe", "suspicious", "phishing"}


def is_available():
    """True if the Ollama server is reachable."""
    try:
        r = requests.get(f"{OLLAMA_HOST}/api/tags", timeout=2)
        return r.ok
    except requests.RequestException:
        return False


def _clean(data):
    """Validate/normalise whatever the model returned."""
    verdict = str(data.get("verdict", "")).lower().strip()
    if verdict not in VALID_VERDICTS:
        verdict = "suspicious"

    try:
        score = int(round(float(data.get("risk_score", 50))))
    except (TypeError, ValueError):
        score = 50
    score = max(0, min(100, score))

    flags = data.get("red_flags") or []
    if not isinstance(flags, list):
        flags = [str(flags)]
    flags = [str(f) for f in flags][:8]

    return {
        "verdict": verdict,
        "risk_score": score,
        "red_flags": flags,
        "explanation": str(data.get("explanation", "")).strip(),
        "advice": str(data.get("advice", "")).strip(),
    }


def analyze_url(url, ml_probability):
    """
    Ask the local LLM to analyse a URL.

    Returns a dict (see SYSTEM_PROMPT shape) or None if Ollama is unavailable
    or returned something unusable.
    """
    user_msg = (
        f"URL: {url}\n"
        f"ML model phishing probability: {ml_probability * 100:.1f}%\n"
        "Give your analysis as JSON."
    )
    payload = {
        "model": OLLAMA_MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_msg},
        ],
        "format": "json",   # forces valid JSON output
        "stream": False,
        "options": {"temperature": 0.1},
    }
    try:
        r = requests.post(f"{OLLAMA_HOST}/api/chat", json=payload, timeout=OLLAMA_TIMEOUT)
        r.raise_for_status()
        content = r.json()["message"]["content"]
        return _clean(json.loads(content))
    except (requests.RequestException, KeyError, ValueError) as e:
        print(f"[ollama] analysis failed: {e}")
        return None
