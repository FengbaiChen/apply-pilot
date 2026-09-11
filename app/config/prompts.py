from pathlib import Path


def load_reference_prompt(path: Path | None) -> str:
    """An absent/empty optional file uses the built-in prompt; no startup failure."""
    if path is None or not path.is_file():
        return ""
    text = path.read_text(encoding="utf-8").strip()
    if len(text) > 8000:
        raise ValueError("The LLM reference prompt must be at most 8,000 characters")
    return text
