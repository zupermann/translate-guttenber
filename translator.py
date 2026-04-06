"""Ollama API client and translation logic."""

import json
import logging
import os
import time
from dataclasses import dataclass
from datetime import datetime
from typing import List, Dict, Optional

import requests


# Setup persistent debug logging
LOG_DIR = os.path.expanduser("~/.local/share/translate-book")
os.makedirs(LOG_DIR, exist_ok=True)
LOG_FILE = os.path.join(LOG_DIR, "translation.log")

# Configure logger
logger = logging.getLogger("translate_book")
logger.setLevel(logging.DEBUG)

# File handler for persistent logging
file_handler = logging.FileHandler(LOG_FILE, mode='a')
file_handler.setLevel(logging.DEBUG)
file_formatter = logging.Formatter(
    '%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
file_handler.setFormatter(file_formatter)
logger.addHandler(file_handler)


# Retry configuration
MAX_RETRIES = 3
RETRY_DELAY = 2.0  # seconds


@dataclass
class TranslationResult:
    """Result of a translation attempt."""
    translated_text: str
    prompt_tokens: int = 0
    output_tokens: int = 0
    duration_seconds: float = 0.0
    retries: int = 0
    success: bool = True  # False if all retries exhausted; translated_text = source text
    error_message: Optional[str] = None  # Error message if success=False


class OllamaTranslator:
    """Client for Ollama translation API."""

    SYSTEM_PROMPT = """You are a professional English (en) to Romanian (ro) translator.
Your goal is to accurately convey the meaning and nuances of the original English text
while adhering to Romanian grammar, vocabulary, and cultural sensitivities.

CRITICAL RULES:
1. Produce ONLY the Romanian translation. No explanations, no commentary.
2. Proper nouns, names, and places must remain in English.
3. When text contains ｜｜｜ delimiters, preserve them in the exact same positions in your output.
4. Do NOT translate these instructions. Do NOT echo the input text.

Output format: Only the translated text."""

    USER_PROMPT_TEMPLATE = "TEXT TO TRANSLATE:\n{text}\n\nROMANIAN TRANSLATION:"

    USER_PROMPT_WITH_DELIMITER = "TEXT TO TRANSLATE (preserve ｜｜｜ delimiters):\n{text}\n\nROMANIAN TRANSLATION:"

    def __init__(
        self,
        base_url: str = "http://localhost:11434",
        model: str = "translategemma:27b",
        temperature: float = 0.3,
        num_ctx: int = 8192,
    ):
        """Initialize the translator."""
        self.base_url = base_url.rstrip('/')
        self.model = model
        self.options = {
            "temperature": temperature,
            "top_k": 64,
            "top_p": 0.95,
            "repeat_penalty": 1.1,
            "num_predict": -1,
            "num_ctx": num_ctx,
        }

    def check_connection(self) -> None:
        """
        Check Ollama connection and verify model exists.
        Raise ConnectionError if unreachable.
        Raise ValueError if model not found.
        """
        try:
            response = requests.get(f"{self.base_url}/api/tags", timeout=10)
            response.raise_for_status()
            data = response.json()

            models = data.get('models', [])
            model_names = [m.get('name', '') for m in models]

            # Check for exact match
            if self.model not in model_names:
                # Check if model exists with different tag
                model_base = self.model.split(':')[0]
                available_models = [m for m in model_names if m.startswith(model_base)]

                if not available_models:
                    raise ValueError(
                        f"Model '{self.model}' not found. "
                        f"Available models: {', '.join(model_names[:10])}"
                    )
                else:
                    # Model exists with different tag - warn but continue
                    import sys
                    print(
                        f"Warning: Model '{self.model}' not found exactly. "
                        f"Found: {available_models[0]}. Continuing with configured model name.",
                        file=sys.stderr
                    )

        except requests.exceptions.ConnectionError as e:
            raise ConnectionError(
                f"Cannot connect to Ollama at {self.base_url}. "
                "Is Ollama running? Start it with 'ollama serve'"
            ) from e
        except requests.exceptions.Timeout as e:
            raise ConnectionError(
                f"Timeout connecting to Ollama at {self.base_url}."
            ) from e

    def translate(self, text: str, has_delimiters: bool = False) -> TranslationResult:
        """
        Translate text using Ollama API.

        Args:
            text: The text to translate
            has_delimiters: Whether the text contains delimiter markers

        Returns:
            TranslationResult with the translation and metadata
        """
        source_text = text
        last_error = None
        start_time = time.time()

        logger.info(f"TRANSLATE START: has_delimiters={has_delimiters}")
        logger.debug(f"TRANSLATE INPUT: {repr(text)}")

        for attempt in range(MAX_RETRIES):

            try:
                messages = self._build_messages(text, has_delimiters)
                logger.debug(f"TRANSLATE MESSAGES: {json.dumps(messages, ensure_ascii=False)}")

                response_data = self._call_api(messages)

                raw_response = response_data['message']['content']
                logger.debug(f"TRANSLATE RAW RESPONSE: {repr(raw_response)}")

                cleaned = self._clean_response(raw_response)
                logger.info(f"TRANSLATE CLEANED: {repr(cleaned[:200])}...")

                duration = time.time() - start_time

                # Check if response is valid
                if not cleaned or not cleaned.strip():
                    raise ValueError("Empty response from model")

                # Note: We no longer reject translations that equal source text.
                # This check was incorrectly failing for texts containing proper nouns
                # and book titles that shouldn't be translated (per the system prompt).
                # The model correctly preserves these, so matching source is valid.

                # Extract token counts if available
                prompt_tokens = response_data.get('prompt_eval_count', 0)
                output_tokens = response_data.get('eval_count', 0)

                return TranslationResult(
                    translated_text=cleaned,
                    prompt_tokens=prompt_tokens,
                    output_tokens=output_tokens,
                    duration_seconds=duration,
                    retries=attempt,
                    success=True,
                )

            except (requests.exceptions.RequestException, ValueError) as e:
                last_error = e
                if attempt < MAX_RETRIES - 1:
                    time.sleep(RETRY_DELAY)
                    continue
                break

        # All retries failed
        error_msg = str(last_error) if last_error else "All retries failed"
        return TranslationResult(
            translated_text=source_text,  # Return source text as fallback
            duration_seconds=time.time() - start_time,
            retries=MAX_RETRIES - 1,
            success=False,
            error_message=error_msg,
        )

    def _build_messages(self, text: str, has_delimiters: bool) -> List[Dict[str, str]]:
        """Build the messages for the API call."""
        if has_delimiters:
            user_prompt = self.USER_PROMPT_WITH_DELIMITER.format(text=text)
        else:
            user_prompt = self.USER_PROMPT_TEMPLATE.format(text=text)

        return [
            {"role": "system", "content": self.SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ]

    def _call_api(self, messages: List[Dict[str, str]]) -> Dict:
        """
        Make API call to Ollama.

        Args:
            messages: List of message dicts with 'role' and 'content'

        Returns:
            Parsed JSON response
        """
        payload = {
            "model": self.model,
            "messages": messages,
            "options": self.options,
            "stream": False,
        }

        response = requests.post(
            f"{self.base_url}/api/chat",
            json=payload,
            timeout=300,  # 5 minute timeout for long translations
        )
        response.raise_for_status()
        return response.json()

    def translate_with_delimiter_retry(
        self, text: str, expected_delimiter_count: int, delimiter: str
    ) -> TranslationResult:
        """
        Translate with delimiter preservation, retrying once if delimiter count is wrong.

        Args:
            text: Text with delimiters to translate
            expected_delimiter_count: Expected number of delimiters in output
            delimiter: The delimiter string to preserve

        Returns:
            TranslationResult with correct delimiter count, or success=False if retry fails
        """
        logger.info(f"DELIMITER_RETRY START: expected={expected_delimiter_count}, text={repr(text[:100])}...")
        start_time = time.time()

        # First attempt
        result = self.translate(text, has_delimiters=True)
        if not result.success:
            logger.warning(f"DELIMITER_RETRY: First attempt failed: {result.error_message}")
            return result

        actual_count = result.translated_text.count(delimiter)
        if actual_count == expected_delimiter_count:
            logger.info(f"DELIMITER_RETRY: Success on first attempt")
            return result

        logger.warning(f"DELIMITER_RETRY: First attempt delimiter mismatch. Expected {expected_delimiter_count}, got {actual_count}")
        logger.debug(f"DELIMITER_RETRY: First attempt result: {repr(result.translated_text)}")

        # Delimiter mismatch - retry with explicit correction instruction
        retry_messages = [
            {"role": "system", "content": self.SYSTEM_PROMPT},
            {"role": "user", "content": self.USER_PROMPT_TEMPLATE.format(text=text)},
            {"role": "assistant", "content": result.translated_text},
            {"role": "user", "content": f"""Your translation did not preserve the {delimiter} delimiters correctly.
The source had {expected_delimiter_count + 1} text segments separated by {delimiter}.
Your response must contain exactly {expected_delimiter_count} {delimiter} delimiters.

Please translate again, keeping {delimiter} delimiters in the exact same positions:"""},
        ]

        logger.debug(f"DELIMITER_RETRY MESSAGES: {json.dumps(retry_messages, ensure_ascii=False)}")

        try:
            retry_api_result = self._call_api(retry_messages)
            cleaned = self._clean_response(retry_api_result['message']['content'])
            logger.debug(f"DELIMITER_RETRY RAW: {repr(retry_api_result['message']['content'])}")
            logger.info(f"DELIMITER_RETRY CLEANED: {repr(cleaned[:200])}...")
        except (requests.exceptions.RequestException, KeyError, ValueError) as e:
            logger.error(f"DELIMITER_RETRY: Retry API call failed: {e}")
            return TranslationResult(
                translated_text=text,
                success=False,
                error_message=f"Delimiter retry API call failed: {e}",
            )

        retry_actual_count = cleaned.count(delimiter)
        if retry_actual_count != expected_delimiter_count:
            # Retry failed to fix delimiters
            logger.error(f"DELIMITER_RETRY FAILED: After retry, expected {expected_delimiter_count}, got {retry_actual_count}")
            return TranslationResult(
                translated_text=text,  # Return original
                success=False,
                error_message=f"Delimiter mismatch after retry: expected {expected_delimiter_count}, got {retry_actual_count}",
            )

        logger.info(f"DELIMITER_RETRY: Success after retry")
        return TranslationResult(
            translated_text=cleaned,
            prompt_tokens=retry_api_result.get('prompt_eval_count', 0),
            output_tokens=retry_api_result.get('eval_count', 0),
            duration_seconds=time.time() - start_time,
            retries=1,
            success=True,
        )

    def _clean_response(self, raw: str) -> str:
        """
        Clean the model response by stripping preamble/meta-commentary.

        Args:
            raw: Raw response text

        Returns:
            Cleaned response text
        """
        cleaned = raw.strip()

        # Remove common preamble phrases
        preamble_patterns = [
            "Here is the translation:",
            "Here is the Romanian translation:",
            "Translation:",
            "Romanian translation:",
            "The translation is:",
            "Here is your translation:",
            "I will translate this for you:",
            "Sure, here is the translation:",
        ]

        for pattern in preamble_patterns:
            if cleaned.lower().startswith(pattern.lower()):
                cleaned = cleaned[len(pattern):].strip()
                # Remove leading colon or newline
                if cleaned.startswith(':'):
                    cleaned = cleaned[1:].strip()
                break

        # Remove quotes if the entire text is wrapped
        if (cleaned.startswith('"') and cleaned.endswith('"')) or \
           (cleaned.startswith("'") and cleaned.endswith("'")):
            cleaned = cleaned[1:-1].strip()

        return cleaned
