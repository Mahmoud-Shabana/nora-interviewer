from __future__ import annotations

from pathlib import Path

WEB_DIR = Path(__file__).with_name("web")


def render_interview_room() -> str:
    return (WEB_DIR / "index.html").read_text(encoding="utf-8")


def render_review_console() -> str:
    return (WEB_DIR / "review.html").read_text(encoding="utf-8")


def render_job_studio() -> str:
    return (WEB_DIR / "studio.html").read_text(encoding="utf-8")
