"""Entity-ID helpers without Home Assistant runtime dependencies."""

from __future__ import annotations

def suggested_entity_suffix(suffix: str) -> str:
    """Turn a unique-ID suffix into a friendly object-ID suffix."""
    platform, separator, detail = suffix.partition(":")
    if not separator:
        return suffix
    parts = detail.split(":")
    if platform == "switch" and len(parts) == 2 and parts[1].isdigit():
        architecture, band = parts
        band_prefix = "b" if architecture == "lte" else "n"
        return f"{architecture}_{band_prefix}{band}"
    if platform == "switch" and detail.startswith("enable_"):
        return f"enable_5g_{detail.removeprefix('enable_')}"
    return detail.replace(":", "_")
