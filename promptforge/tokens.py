"""
Token estimation module for PromptForge.
Provides accurate token counting using tiktoken when available,
with fallback to heuristic estimation.
"""

import re
from functools import lru_cache

# Try to import tiktoken for accurate counting
_tiktoken_available = False
_tiktoken_encoding = None

try:
    import tiktoken

    _tiktoken_available = True
except ImportError:
    pass


@lru_cache(maxsize=1)
def _get_tiktoken_encoding():
    """Get tiktoken encoding (cached for performance)."""
    global _tiktoken_encoding
    if _tiktoken_encoding is None and _tiktoken_available:
        try:
            # Use cl100k_base encoding (used by GPT-4, Claude, etc.)
            _tiktoken_encoding = tiktoken.get_encoding("cl100k_base")
        except Exception:
            pass
    return _tiktoken_encoding


def estimate_tokens_tiktoken(text: str) -> int:
    """
    Estimate tokens using tiktoken (accurate).

    Args:
        text: Text to tokenize

    Returns:
        Exact token count
    """
    encoding = _get_tiktoken_encoding()
    if encoding is None:
        raise RuntimeError("tiktoken not available")
    return len(encoding.encode(text))


def estimate_tokens_heuristic(text: str) -> int:
    """
    Estimate tokens using heuristics (fallback).

    This uses multiple heuristics for better accuracy:
    1. Word-based estimation (~1.3 tokens per word for English)
    2. Character-based estimation (~4 chars per token)
    3. Special handling for code, punctuation, numbers

    Args:
        text: Text to estimate

    Returns:
        Estimated token count
    """
    if not text:
        return 0

    # Count different text elements
    words = len(text.split())
    chars = len(text)

    # Count special elements that typically become separate tokens
    numbers = len(re.findall(r"\d+", text))
    punctuation = len(re.findall(r'[.,!?;:()[\]{}"\']', text))
    newlines = text.count("\n")

    # Code-specific tokens (if text appears to be code)
    code_indicators = ["def ", "function ", "class ", "import ", "const ", "let ", "var ", "```"]
    is_code = any(indicator in text for indicator in code_indicators)

    if is_code:
        # Code has more tokens per character due to operators, brackets, etc.
        # Approximately 1 token per 3.5 characters for code
        base_estimate = chars / 3.5
        # Add extra for operators and special characters
        operators = len(re.findall(r"[+\-*/=<>!&|^~%]", text))
        base_estimate += operators * 0.5
    else:
        # For natural language text
        # Use weighted average of word-based and char-based estimates
        word_based = words * 1.3  # ~1.3 tokens per word
        char_based = chars / 4.0  # ~4 chars per token
        base_estimate = word_based * 0.6 + char_based * 0.4

    # Add tokens for special elements
    special_tokens = (
        numbers * 0.5  # Numbers often split into multiple tokens
        + punctuation * 0.3  # Some punctuation is merged, some separate
        + newlines * 0.2  # Newlines sometimes count
    )

    return max(1, int(base_estimate + special_tokens))


def estimate_tokens(text: str, use_tiktoken: bool = True) -> int:
    """
    Estimate the number of tokens in a text.

    Uses tiktoken if available and requested, otherwise falls back
    to heuristic estimation.

    Args:
        text: Text to estimate tokens for
        use_tiktoken: Whether to use tiktoken if available

    Returns:
        Estimated or exact token count
    """
    if not text:
        return 0

    if use_tiktoken and _tiktoken_available:
        try:
            return estimate_tokens_tiktoken(text)
        except Exception:
            pass

    return estimate_tokens_heuristic(text)


def estimate_tokens_by_model(text: str, model: str) -> int:
    """
    Estimate tokens for a specific model.

    Different models may use different tokenizers:
    - GPT-4/Claude: cl100k_base (~similar)
    - Older models: p50k_base, r50k_base
    - Gemini: Different tokenizer

    Args:
        text: Text to tokenize
        model: Model name (e.g., "gpt-4", "claude-3", "gemini")

    Returns:
        Estimated token count for that model
    """
    if not _tiktoken_available:
        return estimate_tokens_heuristic(text)

    try:
        # Map model names to encodings
        model_lower = model.lower()

        if any(x in model_lower for x in ["gpt-4", "gpt-5", "claude", "opus", "sonnet", "haiku"]):
            encoding = tiktoken.get_encoding("cl100k_base")
        elif any(x in model_lower for x in ["gpt-3.5", "text-davinci"]):
            encoding = tiktoken.get_encoding("p50k_base")
        elif "gemini" in model_lower:
            # Gemini uses a different tokenizer, estimate ~15% more tokens
            base_count = estimate_tokens_tiktoken(text)
            return int(base_count * 1.15)
        else:
            encoding = tiktoken.get_encoding("cl100k_base")

        return len(encoding.encode(text))
    except Exception:
        return estimate_tokens_heuristic(text)


def get_token_info() -> dict:
    """
    Get information about the token estimation system.

    Returns:
        Dict with availability info and estimation method
    """
    return {
        "tiktoken_available": _tiktoken_available,
        "method": "tiktoken (accurate)" if _tiktoken_available else "heuristic (estimated)",
        "encoding": "cl100k_base" if _tiktoken_available else "n/a",
    }


def count_tokens_detailed(text: str) -> dict:
    """
    Get detailed token breakdown for a text.

    Args:
        text: Text to analyze

    Returns:
        Dict with token count and breakdown
    """
    if not text:
        return {"total": 0, "method": "empty", "breakdown": {}}

    result = {
        "total": estimate_tokens(text),
        "method": "tiktoken" if _tiktoken_available else "heuristic",
        "characters": len(text),
        "words": len(text.split()),
        "lines": text.count("\n") + 1,
    }

    # Add ratio information
    if result["characters"] > 0:
        result["chars_per_token"] = round(result["characters"] / result["total"], 2)
    if result["words"] > 0:
        result["tokens_per_word"] = round(result["total"] / result["words"], 2)

    return result
