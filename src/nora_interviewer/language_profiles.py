from __future__ import annotations

import re
from dataclasses import dataclass

_ARABIC_RE = re.compile(r"[\u0600-\u06ff]")
_LATIN_RE = re.compile(r"[A-Za-z]")


@dataclass(frozen=True)
class TechnicalVocabularyPack:
    id: str
    domain: str
    terms: tuple[str, ...]


TECHNICAL_VOCABULARY_PACKS: dict[str, TechnicalVocabularyPack] = {
    "ar-software-engineering-v1": TechnicalVocabularyPack(
        id="ar-software-engineering-v1",
        domain="software_engineering",
        terms=(
            "API",
            "database",
            "PostgreSQL",
            "cache",
            "Docker",
            "Kubernetes",
            "latency",
            "timeout",
            "deployment",
            "rollback",
            "incident",
            "queue",
            "circuit breaker",
            "واجهة برمجة التطبيقات",
            "قاعدة بيانات",
            "ذاكرة مؤقتة",
            "زمن الاستجابة",
            "مهلة",
            "نشر",
            "تراجع",
            "حادثة",
            "طابور",
            "قاطع الدائرة",
        ),
    ),
    "ar-ai-ml-v1": TechnicalVocabularyPack(
        id="ar-ai-ml-v1",
        domain="ai_ml",
        terms=(
            "machine learning",
            "model",
            "inference",
            "embedding",
            "vector",
            "RAG",
            "token",
            "prompt",
            "fine-tuning",
            "evaluation",
            "latency",
            "تعلم آلي",
            "نموذج",
            "استدلال",
            "تضمين",
            "متجه",
            "رمز",
            "موجه",
            "ضبط دقيق",
            "تقييم",
            "زمن الاستجابة",
        ),
    ),
    "ar-data-engineering-v1": TechnicalVocabularyPack(
        id="ar-data-engineering-v1",
        domain="data_engineering",
        terms=(
            "SQL",
            "ETL",
            "dataframe",
            "schema",
            "join",
            "aggregation",
            "percentile",
            "median",
            "anomaly",
            "pipeline",
            "مخطط",
            "ربط",
            "تجميع",
            "وسيط",
            "شذوذ",
            "خط بيانات",
        ),
    ),
}


def _script_counts(text: str) -> tuple[int, int]:
    arabic = sum(
        1
        for character in text
        if _ARABIC_RE.match(character)
    )
    latin = sum(
        1
        for character in text
        if _LATIN_RE.match(character)
    )
    return arabic, latin


def _contains_term(
    text: str,
    term: str,
) -> bool:
    if _ARABIC_RE.search(term):
        return term in text
    return term.casefold() in text.casefold()


def detect_technical_terms(
    text: str,
    pack_ids: list[str],
) -> list[str]:
    detected: list[str] = []
    seen: set[str] = set()

    for pack_id in pack_ids:
        pack = TECHNICAL_VOCABULARY_PACKS.get(
            pack_id
        )
        if pack is None:
            continue
        for term in pack.terms:
            key = term.casefold()
            if (
                key not in seen
                and _contains_term(
                    text,
                    term,
                )
            ):
                detected.append(term)
                seen.add(key)
    return detected


def build_language_metadata(
    text: str,
    *,
    locale: str,
    dialect: str | None = None,
    pack_ids: list[str] | None = None,
    reference_text: str | None = None,
    critical_terms: list[str] | None = None,
) -> dict:
    packs = list(
        dict.fromkeys(
            pack_ids or []
        )
    )
    unknown = [
        pack_id
        for pack_id in packs
        if pack_id
        not in TECHNICAL_VOCABULARY_PACKS
    ]
    if unknown:
        raise ValueError(
            "Unknown technical vocabulary pack(s): "
            + ", ".join(unknown)
        )

    arabic_chars, latin_chars = (
        _script_counts(text)
    )
    detected_terms = detect_technical_terms(
        text,
        packs,
    )

    metadata: dict = {
        "asr_locale": locale,
        "code_switch_detected": (
            arabic_chars > 0
            and latin_chars > 0
        ),
        "script_profile": {
            "arabic_chars": arabic_chars,
            "latin_chars": latin_chars,
        },
        "technical_vocabulary_packs": (
            packs
        ),
        "technical_terms_detected": (
            detected_terms
        ),
    }

    if dialect:
        metadata["asr_dialect"] = (
            dialect
        )

    if reference_text is not None:
        metadata[
            "asr_reference_text"
        ] = reference_text
        ref_arabic, ref_latin = (
            _script_counts(
                reference_text
            )
        )
        metadata[
            "code_switch_expected"
        ] = (
            ref_arabic > 0
            and ref_latin > 0
        )

    cleaned_critical = list(
        dict.fromkeys(
            term.strip()
            for term in (
                critical_terms or []
            )
            if term.strip()
        )
    )
    if cleaned_critical:
        metadata[
            "asr_critical_terms"
        ] = cleaned_critical

    return metadata
