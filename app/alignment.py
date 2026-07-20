"""Assessment-context extraction and evidence alignment."""
from __future__ import annotations

import io
import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree

from .knowledge import EvidenceStore, expand_concepts, retrieval_tokens
from .assessment_catalog import TOPIC_BY_ID

MAX_FILE_BYTES = 12 * 1024 * 1024
MAX_CONTEXT_CHARS = 120_000
MAX_TARGETS = 48

_TEXT_SUFFIXES = {
    ".txt", ".md", ".csv", ".tsv", ".json", ".yaml", ".yml", ".xml", ".html", ".htm",
}
_BULLET_RE = re.compile(r"^\s*(?:[-*•▪◦]|\d+[.)]|[A-Za-z][.)])\s+")
_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9])")
_MARK_RE = re.compile(r"\b(\d+(?:\.\d+)?)\s*(?:marks?|points?|%)\b", re.I)
_RUBRIC_TOTAL_RE = re.compile(r"^(.*?)(\d+(?:\.\d+)?)/(\d+(?:\.\d+)?)\s*pts?$", re.I)
_RATING_RE = re.compile(r"^(excellent|good|satisfactory|fail|not solved)$", re.I)
_POINT_LINE_RE = re.compile(r"^\d+(?:\.\d+)?\s*pts?$", re.I)


class ContextDocumentError(ValueError):
    pass


def extract_document_text(filename: str, data: bytes) -> str:
    if len(data) > MAX_FILE_BYTES:
        raise ContextDocumentError(f"{filename} exceeds the 12 MB context-file limit.")
    suffix = Path(filename).suffix.lower()
    if suffix in _TEXT_SUFFIXES:
        text = data.decode("utf-8", errors="replace")
    elif suffix == ".pdf":
        text = _pdf_text(filename, data)
    elif suffix in {".docx", ".pptx"}:
        text = _office_text(filename, data, suffix)
    else:
        raise ContextDocumentError(
            f"{filename} is not supported. Upload PDF, DOCX, PPTX, or a text file."
        )
    return _clean_text(text)[:MAX_CONTEXT_CHARS]


def _pdf_text(filename: str, data: bytes) -> str:
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise ContextDocumentError(
            "PDF support requires `pypdf`. Install the updated requirements and restart RepoProof."
        ) from exc
    try:
        return "\n\n".join(page.extract_text() or "" for page in PdfReader(io.BytesIO(data)).pages)
    except Exception as exc:
        raise ContextDocumentError(f"Could not read {filename} as PDF.") from exc


def _office_text(filename: str, data: bytes, suffix: str) -> str:
    prefix = "word/" if suffix == ".docx" else "ppt/slides/"
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            names = sorted(
                name for name in archive.namelist()
                if name.startswith(prefix) and name.endswith(".xml")
            )
            parts = []
            for name in names:
                root = ElementTree.fromstring(archive.read(name))
                parts.append(" ".join(node.text or "" for node in root.iter() if node.tag.endswith("}t")))
            return "\n\n".join(parts)
    except Exception as exc:
        raise ContextDocumentError(f"Could not read {filename}.") from exc


def _clean_text(text: str) -> str:
    text = text.replace("\x00", " ").replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _text_blocks(text: str) -> list[str]:
    blocks = []
    current: list[str] = []

    def flush() -> None:
        if current:
            value = " ".join(current).strip()
            if len(value) >= 12:
                blocks.append(value)
            current.clear()

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            flush()
            continue
        if _BULLET_RE.match(line):
            flush()
            current.append(_BULLET_RE.sub("", line))
            continue
        if len(line) < 100 and line.endswith(":"):
            flush()
            current.append(line)
            continue
        current.append(line)
        if len(" ".join(current)) >= 700:
            flush()
    flush()

    out = []
    for block in blocks:
        if len(block) <= 900:
            out.append(block)
            continue
        sentences = _SENTENCE_RE.split(block)
        part = ""
        for sentence in sentences:
            candidate = f"{part} {sentence}".strip()
            if part and len(candidate) > 900:
                out.append(part)
                part = sentence
            else:
                part = candidate
        if part:
            out.append(part)
    return out


def _rubric_blocks(text: str) -> list[str]:
    lines = [line.strip() for line in text.splitlines()]
    starts = [
        index for index, line in enumerate(lines)
        if line.casefold() == "criteria ratings points"
    ]
    blocks = []
    for position, start in enumerate(starts):
        end = starts[position + 1] if position + 1 < len(starts) else len(lines)
        section = lines[start + 1:end]
        first_rating = next(
            (index for index, line in enumerate(section) if _RATING_RE.match(line)),
            None,
        )
        if first_rating is None:
            continue
        criteria = []
        name_parts = []
        for line in section[:first_rating]:
            match = _RUBRIC_TOTAL_RE.match(line)
            if match:
                if match.group(1).strip():
                    name_parts.append(match.group(1).strip())
                name = " ".join(name_parts).strip()
                if name:
                    criteria.append((name, float(match.group(3))))
                name_parts = []
            elif line:
                name_parts.append(line)

        excellent = []
        body = section[first_rating:]
        index = 0
        while index < len(body):
            if body[index].casefold() != "excellent":
                index += 1
                continue
            index += 1
            description = []
            while index < len(body) and not _POINT_LINE_RE.match(body[index]):
                if body[index] and not _RATING_RE.match(body[index]):
                    description.append(body[index])
                index += 1
            if description:
                excellent.append(" ".join(description))
            index += 1

        for (name, points), description in zip(criteria, excellent):
            blocks.append(
                f"{name} ({points:g} points): {description}"
            )
    return blocks


def _target_label(text: str) -> str:
    label = _SENTENCE_RE.split(text, maxsplit=1)[0]
    label = re.sub(r"\s+", " ", label).strip(" -:;")
    return label if len(label) <= 110 else label[:107].rstrip() + "..."


def _target_weight(text: str, kind: str) -> float:
    marks = [float(value) for value in _MARK_RE.findall(text)]
    base = 1.15 if kind == "project_scope" else 1.0
    if not marks:
        return base
    return round(base + min(max(marks) / 3, 3.85), 2)


def _is_assessable_target(text: str) -> bool:
    compact = " ".join(text.split()).strip()
    visible = re.sub(r"^[#>*\s-]+", "", compact).strip()
    plain = re.sub(r"[*_`]", "", visible)
    if not visible or compact.lstrip().startswith("#"):
        return False
    if re.fullmatch(
        r"total(?:\s+(?:marks?|points?))?\s*:?\s*"
        r"\d+(?:\.\d+)?(?:\s*/\s*\d+(?:\.\d+)?)?\s*(?:marks?|points?)?",
        plain,
        re.I,
    ):
        return False
    return bool(re.search(r"[A-Za-z\u3400-\u9fff]", visible))


def build_assessment_targets(
    assumed_knowledge: str,
    project_scope: str,
    prior_documents: list[dict] | None = None,
    scope_documents: list[dict] | None = None,
) -> list[dict]:
    sources = []
    if assumed_knowledge.strip():
        sources.append(("prior_knowledge", "Instructor input", assumed_knowledge))
    if project_scope.strip():
        sources.append(("project_scope", "Instructor input", project_scope))
    sources.extend(
        ("prior_knowledge", item["name"], item["text"])
        for item in (prior_documents or [])
        if item.get("text")
    )
    sources.extend(
        ("project_scope", item["name"], item["text"])
        for item in (scope_documents or [])
        if item.get("text")
    )

    targets = []
    seen = set()
    for kind, source, text in sources:
        blocks = _rubric_blocks(text) or _text_blocks(text)
        for block in blocks:
            if not _is_assessable_target(block):
                continue
            normalized = " ".join(block.casefold().split())
            if normalized in seen:
                continue
            seen.add(normalized)
            targets.append({
                "kind": kind,
                "label": _target_label(block),
                "description": block,
                "source": source,
                "weight": _target_weight(block, kind),
            })
    if len(targets) > MAX_TARGETS:
        explicit = [target for target in targets if target["source"] == "Instructor input"]
        remaining = [target for target in targets if target["source"] != "Instructor input"]
        remaining.sort(key=lambda target: -float(target["weight"]))
        targets = (explicit + remaining)[:MAX_TARGETS]
    return [{"id": f"t{index}", **target} for index, target in enumerate(targets)]


def _tokens(text: str) -> set[str]:
    return {token for token in retrieval_tokens(text) if len(token) > 2}


def _topic_matches(target: dict, selected_topics: list[dict]) -> list[dict]:
    target_text = target["description"]
    target_tokens = _tokens(target_text + " " + " ".join(expand_concepts(target_text)))
    scored = []
    for selected in selected_topics:
        topic = TOPIC_BY_ID.get(str(selected.get("id") or ""))
        if not topic:
            continue
        topic_tokens = _tokens(
            " ".join((topic["name"], topic["description"], topic["query"]))
        )
        overlap = len(target_tokens.intersection(topic_tokens))
        score = overlap + 0.15 * float(selected.get("weight", 1))
        scored.append({"id": topic["id"], "name": topic["name"], "score": round(score, 3)})
    scored.sort(key=lambda item: item["score"], reverse=True)
    if not scored:
        return []
    floor = max(0.15, scored[0]["score"] * 0.55)
    return [item for item in scored[:3] if item["score"] >= floor]


def align_assessment_targets(
    chunks: list[dict],
    targets: list[dict],
    focus_areas: list[dict],
) -> list[dict]:
    if not targets:
        return []
    selected_topics = focus_areas or [
        {"id": topic_id, "weight": 1} for topic_id in TOPIC_BY_ID
    ]
    store = EvidenceStore(chunks)
    aligned = []
    for target in targets:
        topic_matches = _topic_matches(target, selected_topics)
        evidence_types = tuple(dict.fromkeys(
            evidence_type
            for match in topic_matches
            for evidence_type in TOPIC_BY_ID[match["id"]]["evidence_types"]
        ))
        expansion = expand_concepts(target["description"], "curriculum_to_code")
        scored = store.retrieve_scored(
            target["description"],
            k=4,
            evidence_types=evidence_types,
            expansion_terms=expansion,
        )
        query_tokens = _tokens(target["description"] + " " + " ".join(expansion))
        matched_scored = []
        for item in scored:
            chunk = item["chunk"]
            overlap = len(query_tokens.intersection(_tokens(chunk["title"] + " " + chunk["text"])))
            if item["score"] > 0 or overlap:
                matched_scored.append((item, overlap))
        evidence = [
            {
                "chunk_id": item["chunk"]["id"],
                "title": item["chunk"]["title"],
                "score": round(item["score"], 3),
            }
            for item, _ in matched_scored
        ]
        best_score = max((item["score"] for item, _ in matched_scored), default=0.0)
        best_overlap = max((overlap for _, overlap in matched_scored), default=0)
        coverage = (
            "strong"
            if best_score >= 2.0 or best_overlap >= 3
            else "partial"
            if matched_scored
            else "unmatched"
        )
        aligned.append({
            **target,
            "topic_ids": [item["id"] for item in topic_matches],
            "topic_names": [item["name"] for item in topic_matches],
            "evidence": evidence,
            "coverage": coverage,
        })
    return aligned


def context_summary(targets: list[dict], kind: str, limit: int = 8) -> str:
    selected = [target["label"] for target in targets if target["kind"] == kind]
    return "; ".join(selected[:limit])
