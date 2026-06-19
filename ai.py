# ai.py
import os
import re
import json
import time
import logging
from ollama import Client
from setup_wizard import load_profile, build_profile_prompt_context

# ══════════════════════════════════════════════════════════════
# AI ASSISTANT
# ══════════════════════════════════════════════════════════════

class OllamaAssistant:
    def __init__(self, model="gemma4:31b-cloud"):
        self.model = model
        api_key = os.environ.get("OLLAMA_API_KEY")

        # Use cloud host if model ends with -cloud or API key is set
        if api_key or model.endswith("-cloud"):
            self.client = Client(
                host="https://ollama.com",
                headers={"Authorization": f"Bearer {api_key}"}
            )
        else:
            self.client = Client(host="http://localhost:11434")

    def submit_message(self, prompt):
        logging.info("--- AI PROMPT START ---\n%s\n--- AI PROMPT END ---", prompt)
        response = self.client.chat(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            stream=False,
            options={
                "num_predict": 64384,      # ← unlimited
                "num_ctx":     32768,   # ← large context
                "temperature": 0.3,
            },
        )
        content = response["message"]["content"].strip()
        logging.info("--- AI RESPONSE START ---\n%s\n--- AI RESPONSE END ---", content)
        return content

def send_with_retries(assistant, msg: str, tries: int = 3, backoff_sec: float = 2.0):
    """
    Calls the AI assistant with exponential backoff and specific error handling.
    """
    last_err = None
    for attempt in range(1, tries + 1):
        try:
            response = assistant.submit_message(msg)
            if not response:
                raise ValueError("AI returned an empty response")
            return response
        except Exception as e:
            last_err = e
            err_str = str(e).lower()

            # 429 or Rate Limit: Increase backoff
            if "429" in err_str or "rate" in err_str:
                sleep_time = backoff_sec * (2 ** (attempt - 1)) * 2
                logging.warning("Rate limit hit (attempt %d/%d). Sleeping for %.1fs", attempt, tries, sleep_time)
            else:
                sleep_time = backoff_sec * attempt
                logging.warning("Model call failed (attempt %d/%d): %s. Sleeping for %.1fs", attempt, tries, e, sleep_time)

            time.sleep(sleep_time)

    logging.error("All %d attempts failed. Last error: %s", tries, last_err)
    raise last_err

def parse_ai_verdict(text: str) -> dict:
    """
    Robustly extracts a job verdict JSON from AI output.
    Implements multiple fallback strategies to prevent crashes.
    """
    default = {
        "verdict": "maybe", "years_required": "unspecified",
        "role_level": "unspecified", "skills_match_pct": 50,
        "matched_skills": [], "missing_skills": [],
        "reasoning": "Could not parse response."
    }

    if not text or len(text.strip()) < 5:
        return default

    txt = text.strip()

    # Strip markdown fences
    if "```" in txt:
        m = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", txt, re.IGNORECASE)
        if m: txt = m.group(1).strip()

    # Fix trailing commas
    txt = re.sub(r",\s*([}\]])", r"\1", txt)

    # Strategy 1: find complete JSON object anywhere in text
    brace_start = txt.find("{")
    brace_end   = txt.rfind("}")
    if brace_start != -1 and brace_end > brace_start:
        try:
            candidate = txt[brace_start:brace_end+1]
            data = json.loads(candidate)
            if "verdict" in data:
                v = str(data.get("verdict", "maybe")).lower().strip()
                if v not in ("yes", "no", "maybe"): v = "maybe"
                return {
                    "verdict":           v,
                    "years_required":    str(data.get("years_required", "unspecified")),
                    "role_level":        str(data.get("role_level", "unspecified")).lower(),
                    "skills_match_pct":  int(data.get("skills_match_pct", 50)),
                    "matched_skills":    data.get("matched_skills", []),
                    "missing_skills":    data.get("missing_skills", []),
                    "reasoning":         str(data.get("reasoning", "")),
                }
        except Exception:
            pass

    # Strategy 2: regex field extraction
    def extract(pattern, text, default_val):
        m = re.search(pattern, text, re.IGNORECASE)
        return m.group(1) if m else default_val

    verdict = extract(r'"verdict"\s*:\s*"(\w+)"', txt, "maybe").lower()
    if verdict not in ("yes", "no", "maybe"): verdict = "maybe"

    # Keyword fallback
    tl = txt.lower()
    if verdict == "maybe":
        if '"yes"' in tl or 'verdict: yes' in tl: verdict = "yes"
        elif '"no"' in tl or 'verdict: no' in tl: verdict = "no"

    default["verdict"]          = verdict
    default["skills_match_pct"] = int(extract(r'"skills_match_pct"\s*:\s*(\d+)', txt, "50"))
    default["reasoning"]        = extract(r'"reasoning"\s*:\s*"([^"]*)"', txt, "Auto-scored.")

    return default
