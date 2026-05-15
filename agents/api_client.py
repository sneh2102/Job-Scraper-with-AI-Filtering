# agents/api_client.py
import logging
import time
from ollama import Client

logger = logging.getLogger(__name__)


class RotatingOllamaClient:
    def __init__(self, api_keys: list[str], model: str = "gemma3:e4b"):
        if not api_keys:
            raise ValueError("Provide at least one Ollama API key.")
        self.api_keys      = api_keys
        self.model         = model
        self.current_index = 0
        self._build_client()

    def _build_client(self):
        key = self.api_keys[self.current_index]
        self.client = Client(
            host="https://ollama.com",
            headers={"Authorization": f"Bearer {key}"}
        )
        logger.info("Using Ollama API key index %d", self.current_index)

    def _rotate(self):
        next_index = (self.current_index + 1) % len(self.api_keys)
        if next_index == self.current_index:
            raise RuntimeError("All Ollama API keys exhausted or rate limited.")
        self.current_index = next_index
        self._build_client()
        logger.warning("Rotated to Ollama API key index %d", self.current_index)

    @staticmethod
    def _looks_like_content(err_str: str) -> bool:
        """
        Check if an exception message is actually a partial response
        from the model (not a real error).
        Ollama sometimes raises partial JSON/text as an exception.
        """
        stripped = err_str.strip()
        content_signals = (
            '"score"', '"verdict"', '"keyword', '"section',
            '"skills"', '"pass"', '"experience"',
            '\\section', '\\resumeItem', '\\textbf',
            '\\begin{', '\\end{',
        )
        return (
            stripped.startswith("{") or
            stripped.startswith('"') or
            any(signal in stripped for signal in content_signals)
        )

    def complete(
        self,
        system: str,
        user: str,
        max_tokens: int = 16384,
        retries: int = 3,
        backoff: float = 2.0,
    ) -> str:
        last_error = None

        for attempt in range(retries * len(self.api_keys)):
            try:
                logger.info("Ollama request — model: %s | system: %d chars | user: %d chars",
                self.model, len(system), len(user))
                response = self.client.chat(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": system},
                        {"role": "user",   "content": user},
                    ],
                    stream=False,
                    options={
                        "num_predict": 16384,
                        "num_ctx":     32768,
                        "temperature": 0.3,
                    },
                )
                return response["message"]["content"].strip()

            except Exception as e:
                err_str = str(e)
                err_lower = err_str.lower()

                # ── Partial response returned as exception ────
                # Ollama occasionally raises the model's partial output
                # as an exception instead of returning it normally.
                if self._looks_like_content(err_str):
                    logger.warning(
                        "Partial model response returned as exception "
                        "(attempt %d) — returning content directly | preview: %s",
                        attempt + 1, err_str[:60]
                    )
                    return err_str  # caller (_parse) handles partial content

                # ── Rate limit / auth — rotate key ────────────
                if any(x in err_lower for x in
                       ["rate limit", "429", "401", "403", "quota", "limit exceeded"]):
                    logger.warning("Key %d hit limit: %s — rotating.",
                                   self.current_index, err_str[:60])
                    self._rotate()
                    continue

                # ── Other error — retry with backoff ──────────
                last_error = e
                wait = backoff * (attempt + 1)
                logger.error(
                    "Ollama call failed (attempt %d/%d): %s — retrying in %.1fs",
                    attempt + 1, retries * len(self.api_keys), err_str[:80], wait
                )
                time.sleep(wait)

        result = response["message"]["content"].strip()
        logger.info("Ollama response [%d chars]: %s...", len(result), result[:120])
        return result