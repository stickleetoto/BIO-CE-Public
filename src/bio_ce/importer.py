# Copyright 2026 stickleetoto
# SPDX-License-Identifier: Apache-2.0

"""Import memories from another AI: pasted text or a .md/.txt file in the "[date] - content" format.

Pipeline (fixed order, the same as every other write):

1. Parse: entries, source notes (the AI's explanations around the list), and lines BIO CE couldn't read.
2. Per entry: secrets (blocked) -> instructions to an AI (blocked) -> size (too long) -> local paths -> sensitive
   labels -> duplicates in the batch -> comparison with the destination space (already there / possible conflict).
3. Commit: new entries go to the destination space's inbox in transactions of 100; possible conflicts and
   personal paths go to the review queue. Nothing existing is ever overwritten.
4. Undo: removes what is still in the inbox, closes the batch's pending reviews, keeps what the user already sorted.

Dates written by another AI are not trusted: they are kept as ``claimed_date``. ``said_at`` ("when the user said
it") is filled only when the user confirms a date in the preview. Nothing here calls an AI model.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timezone
from difflib import SequenceMatcher
import json
import os
from pathlib import Path
import re
import secrets as _secrets
import time
from typing import Any, Callable, Iterable, Sequence
import unicodedata

from bio_ce.control_store import ControlStore
from bio_ce.core.models import MemoryScope, SourceProvenance
from bio_ce.inbox import discard_inbox_items
from bio_ce.memory_policy import (
    DUPLICATE_THRESHOLD,
    FILE_CONTENT_LIMIT,
    detect_injection,
    detect_secrets,
    normalize,
    prepare_text,
)
from bio_ce.curation import TOPIC_THRESHOLD, topic_overlap
from bio_ce.spaces import PERSONAL_SPACE_ID, Space
from bio_ce.storage.sqlite_store import INBOX_SUFFIX, KEPT_SUFFIX, SQLiteMemoryStore


IMPORT_HOST = "bio-ce-import"
SOURCE_TYPE = "user-imported"
SOURCES = ("chatgpt", "claude", "other")
MAX_FILE_BYTES = 5 * 1024 * 1024
MAX_ITEMS = 5000
CHUNK_SIZE = 100
CONFLICT_LOW = 0.45  # V8: same topic, different text -> review (never an overwrite)
SAME_DATE_COUNT = 20  # 12.1: one date this often ...
SAME_DATE_SHARE = 0.5  # ... or on half the dated entries is probably the export date, not when it was said
TITLE_LIMIT = 80

# Entry states shown in the preview.
NEW = "new"
EXISTS = "exists"
CONFLICT = "conflict"
BATCH_DUPLICATE = "batch_duplicate"
SECRET = "secret"
INSTRUCTION = "instruction"
TOO_LONG = "too_long"
PATH_REVIEW = "path_review"
EMPTY = "empty"
BLOCKED = (SECRET, INSTRUCTION, TOO_LONG, EMPTY)
# Short: the table must fit about 1,000 px with its date column (GUI check I6, 2026-11-15). The full reason is in
# the line under the table when a row is selected.
STATE_LABELS = {
    NEW: "New", EXISTS: "Already there", CONFLICT: "Review: conflict", BATCH_DUPLICATE: "Repeated",
    SECRET: "Blocked: secret", INSTRUCTION: "Blocked: instruction", TOO_LONG: "Too long",
    PATH_REVIEW: "Review: local path", EMPTY: "Empty",
}

# 12.2: explanations an AI puts around the list. A line that starts with one of these is a source note, not a
# memory, even when it looks like a list entry. Compared after NFKC and case folding.
META_PHRASES = (
    "확인 범위", "참고:", "참고 :", "참고로", "누락", "날짜는", "날짜가 없는", "날짜를", "이 목록은", "위 목록", "아래 목록",
    "다음은", "아래는", "이상입니다", "이상이", "이 외에", "그 외에", "제가 기억", "저장된 기억",
    "complete set", "verbatim", "i don't have", "i do not have", "note:", "notes:", "here are", "here is",
    "this is the", "these are", "this list", "the list above", "i've included", "i have included", "let me know",
    "if you'd like", "if you want", "dates are", "dates were", "where no date", "(no other",
)
UNKNOWN_DATES = {"", "unknown", "n/a", "na", "none", "no date", "date unknown", "undated", "?", "-", "—",
                 "날짜 없음", "날짜없음", "알 수 없음", "알수없음", "미상", "없음", "모름"}
_MONTHS = {name: number for number, names in enumerate((
    ("jan", "january"), ("feb", "february"), ("mar", "march"), ("apr", "april"), ("may",), ("jun", "june"),
    ("jul", "july"), ("aug", "august"), ("sep", "sept", "september"), ("oct", "october"), ("nov", "november"),
    ("dec", "december")), start=1) for name in names}

_FENCE = re.compile(r"^\s*(```|~~~)")
_HEADING = re.compile(r"^\s{0,3}#{1,6}\s+(?P<text>.+?)\s*#*\s*$")
_MARKER = r"(?:[-*•+]\s+|\d{1,4}[.)]\s+)"
_DATED = re.compile(r"^\s*" + _MARKER + r"?\[(?P<date>[^\]\n]{0,40})\]\s*(?:[-–—:]\s*)?(?P<content>.*\S)?\s*$")
_PLAIN = re.compile(r"^\s*" + _MARKER + r"(?P<content>.*\S)\s*$")
_TAIL = re.compile(r"\s*\((?P<kind>claimed|imported)\s+(?P<date>\d{4}-\d{2}(?:-\d{2})?)\)\s*$", re.IGNORECASE)
_WORD = re.compile(r"\w{2,}")

# 12.3: sensitive labels (local patterns only). A label never blocks anything; it only sets the default check.
SENSITIVE_PATTERNS: tuple[tuple[str, str, re.Pattern[str]], ...] = (
    ("health", "Health", re.compile(
        r"질병|진단|처방|복용|투약|약을\s*먹|병원|수술|입원|통원|치료|정신과|상담\s*치료|우울|공황|불안\s*장애|ADHD|장애|당뇨|고혈압|"
        r"알레르기|알러지|천식|암\s*(?:진단|투병|수술)|투병|재활|"
        r"(?i:\bdiagnos\w*|\bmedication\b|\bprescri\w*|\bhospital\w*|\bsurgery\b|\btherapy\b|\btherapist\b|"
        r"\bdepress\w*|\banxiety\b|\bdisorder\b|\bdisease\b|\ballerg\w*|\billness\b|\bclinic\b|\bdiabet\w*|"
        r"\bpsychiatr\w*|\bdisabilit\w*)")),
    ("military", "Military service", re.compile(
        r"군\s*복무|입대|전역|제대|병역|군\s*면제|면제\s*판정|보충역|사회복무|공익\s*근무|카투사|의무경찰|현역\s*(?:판정|복무)|"
        r"(?i:\bmilitary service\b|\benlist\w*|\bconscript\w*|\bdischarged from the (?:army|military)\b|"
        r"\bserved in the (?:army|navy|air force|military)\b)")),
    ("school", "School", re.compile(
        r"[가-힣]{2,}(?:대학교|대학원|고등학교|중학교|초등학교)|[가-힣]{1,6}(?:대|고|중)\s*(?:출신|졸업|재학|입학|다녔|다닌|학생|동문)|"
        r"\d{2}\s*학번|학번|"
        r"(?i:\buniversity\b|\bcollege\b|\bhigh school\b|\balma mater\b|\bgraduated from\b|\bstudent id\b)")),
    ("family", "Family", re.compile(
        r"(?:아버지|어머니|아빠|엄마|부모님?|배우자|아내|남편|와이프|자녀|아들|딸|형|누나|언니|오빠|남동생|여동생|동생|형제|자매|"
        r"할머니|할아버지|장인|장모|시어머니|시아버지)(?:의|가|는|이|께서|도)?\s*\S{0,12}\s*\S{0,12}\s*"
        r"(?:직장|회사|학교|병원|건강|연락처|전화|다니|근무|일하|재직|진단|수술|입원)|"
        r"(?i:\b(?:father|mother|dad|mom|parents?|wife|husband|spouse|son|daughter|brother|sister|children|child)"
        r"(?:'s)?\b[^.\n]{0,40}\b(?:works?|job|employ\w*|school|studies|health|sick|phone|contact|hospital|"
        r"diagnos\w*))")),
    ("other", "Other sensitive", re.compile(
        r"종교|교회|성당|기독교|불교|천주교|이슬람|무교|정치\s*성향|지지\s*정당|지지하는\s*정당|성적\s*지향|동성애|양성애|"
        r"소득|연봉|월급|대출|부채|빚이|계좌|집\s*주소|사는\s*곳|거주지|전화번호|연락처|이메일\s*주소|"
        r"\b0\d{1,2}-\d{3,4}-\d{4}\b|[\w.+-]+@[\w-]+\.[\w.]+|"
        r"(?i:\breligio\w*|\bchurch\b|\batheis\w*|\bpolitical (?:views?|leaning|party)\b|\bvoted? for\b|"
        r"\bsexual orientation\b|\bgay\b|\blesbian\b|\bbisexual\b|\bsalary\b|\bincome\b|\bloan\b|\bdebt\b|"
        r"\bmortgage\b|\bbank account\b|\bhome address\b|\blives (?:at|on)\b|\bphone number\b|\bemail address\b)")),
)
SENSITIVE_LABELS = {key: label for key, label, _pattern in SENSITIVE_PATTERNS}


class ImportRejected(ValueError):
    """The input can't be imported as it is (too large, too many entries, unreadable)."""


class ImportCancelled(RuntimeError):
    """The user cancelled the preview; nothing was written."""


# Parsing ------------------------------------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class ParsedEntry:
    line_no: int
    content: str
    date_text: str | None  # the text inside [ ], None when the entry had no brackets
    claimed_date: str | None  # YYYY-MM-DD, or YYYY-MM for a month
    claimed_precision: str | None  # "day" or "month"
    section: str | None


@dataclass(frozen=True, slots=True)
class ParseResult:
    entries: tuple[ParsedEntry, ...]
    source_notes: tuple[tuple[int, str], ...]  # 12.2: explanations around the list; shown, never stored
    unreadable: tuple[tuple[int, str], ...]  # lines inside the list that BIO CE couldn't read; never stored
    encoding: str = "text"


def read_import_file(path: str | os.PathLike[str]) -> tuple[str, str]:
    """(text, encoding) of a .md or .txt file: UTF-8 (with or without BOM), else CP949. At most 5 MB."""
    file = Path(path)
    if file.suffix.casefold() not in (".md", ".txt", ".markdown"):
        raise ImportRejected("Choose a .md or .txt file.")
    size = file.stat().st_size
    if size > MAX_FILE_BYTES:
        raise ImportRejected("This file is larger than 5 MB. Split it and import the parts one by one.")
    data = file.read_bytes()
    for encoding, label in (("utf-8-sig", "UTF-8"), ("cp949", "CP949")):
        try:
            return data.decode(encoding), label
        except UnicodeDecodeError:
            continue
    raise ImportRejected("BIO CE couldn't read this file's text encoding. Save it as UTF-8 and try again.")


def parse_date(text: str | None) -> tuple[str | None, str | None]:
    """(normalized date, precision) for the date formats AI exports use; (None, None) when unknown or unreadable."""
    if text is None:
        return None, None
    value = unicodedata.normalize("NFKC", text).strip().strip(".").strip()
    if value.casefold() in UNKNOWN_DATES:
        return None, None
    value = re.sub(r"^(\d{4}-\d{1,2}-\d{1,2})[T ]\d{1,2}:\d{2}.*$", r"\1", value)
    patterns: tuple[tuple[str, Callable[[re.Match[str]], tuple[int, int, int | None]]], ...] = (
        (r"(\d{4})\s*[-/.]\s*(\d{1,2})\s*[-/.]\s*(\d{1,2})", lambda m: (int(m[1]), int(m[2]), int(m[3]))),
        (r"(\d{4})\s*년\s*(\d{1,2})\s*월\s*(\d{1,2})\s*일", lambda m: (int(m[1]), int(m[2]), int(m[3]))),
        (r"([A-Za-z]{3,9})\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})",
         lambda m: (int(m[3]), _MONTHS.get(m[1].casefold(), 0), int(m[2]))),
        (r"(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]{3,9})\.?,?\s+(\d{4})",
         lambda m: (int(m[3]), _MONTHS.get(m[2].casefold(), 0), int(m[1]))),
        (r"(\d{4})\s*[-/.]\s*(\d{1,2})", lambda m: (int(m[1]), int(m[2]), None)),
        (r"(\d{4})\s*년\s*(\d{1,2})\s*월", lambda m: (int(m[1]), int(m[2]), None)),
        (r"([A-Za-z]{3,9})\.?,?\s+(\d{4})", lambda m: (int(m[2]), _MONTHS.get(m[1].casefold(), 0), None)),
    )
    for pattern, parts in patterns:
        match = re.fullmatch(pattern, value)
        if not match:
            continue
        year, month, day = parts(match)
        try:
            date(year, month, day or 1)
        except ValueError:
            return None, None
        if not 1900 <= year <= 2100:
            return None, None
        if day is None:
            return f"{year:04d}-{month:02d}", "month"
        return f"{year:04d}-{month:02d}-{day:02d}", "day"
    return None, None


def _is_meta(text: str) -> bool:
    folded = unicodedata.normalize("NFKC", text).strip().casefold().lstrip("*_>( ").strip()
    return any(folded.startswith(phrase) for phrase in META_PHRASES)


def parse_text(text: str, *, encoding: str = "text") -> ParseResult:
    """Split pasted or file text into entries, source notes, and unreadable lines (12.2 and REVIEW_R2 item 1)."""
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    fenced = [False] * len(lines)
    has_fence = False
    inside = False
    for index, line in enumerate(lines):
        if _FENCE.match(line):
            has_fence = True
            fenced[index] = None  # type: ignore[call-overload]  # the fence line itself
            inside = not inside
            continue
        fenced[index] = inside
    kinds: list[str] = []
    for index, line in enumerate(lines):
        if fenced[index] is None:
            kinds.append("fence")
        elif not line.strip():
            kinds.append("blank")
        elif has_fence and not fenced[index]:
            kinds.append("note")  # outside the code block the AI was asked to use
        elif _HEADING.match(line):
            kinds.append("heading")
        elif _DATED.match(line) or _PLAIN.match(line):
            kinds.append("note" if _is_meta(_entry_text(line)) else "entry")
        elif line[:1] in (" ", "\t") and kinds and _last_entry_open(kinds):
            kinds.append("continuation")
        elif _is_meta(line):
            kinds.append("note")
        else:
            kinds.append("text")
    entry_rows = [index for index, kind in enumerate(kinds) if kind == "entry"]
    first, last = (entry_rows[0], entry_rows[-1]) if entry_rows else (len(lines), -1)
    entries: list[ParsedEntry] = []
    notes: list[tuple[int, str]] = []
    unreadable: list[tuple[int, str]] = []
    section: str | None = None
    current: dict[str, Any] | None = None

    def close() -> None:
        nonlocal current
        if current is not None:
            entries.append(_entry(current, section_at=current["section"]))
            current = None

    for index, (line, kind) in enumerate(zip(lines, kinds)):
        number = index + 1
        if kind == "entry":
            close()
            current = {"line_no": number, "raw": line, "more": [], "section": section}
        elif kind == "continuation" and current is not None:
            current["more"].append(line.strip())
        elif kind == "heading":
            close()
            section = _HEADING.match(line)["text"].strip()[:120]
        elif kind == "note":
            close()
            notes.append((number, line.strip()))
        elif kind == "text":
            close()
            (unreadable if first < index < last else notes).append((number, line.strip()))
        elif kind == "blank":
            continue
        else:  # a fence line, or a continuation without an entry
            close()
            if kind == "continuation":
                (unreadable if first < index < last else notes).append((number, line.strip()))
    close()
    return ParseResult(tuple(entries), tuple(notes), tuple(unreadable), encoding)


def _entry_text(line: str) -> str:
    match = _DATED.match(line) or _PLAIN.match(line)
    return (match["content"] or "") if match else line


def _last_entry_open(kinds: list[str]) -> bool:
    for kind in reversed(kinds):
        if kind in ("entry", "continuation"):
            return True
        if kind != "blank":
            return False
    return False


def _entry(raw: dict[str, Any], *, section_at: str | None) -> ParsedEntry:
    line = raw["raw"]
    dated = _DATED.match(line)
    date_text = dated["date"] if dated else None
    content = (dated["content"] if dated else _PLAIN.match(line)["content"]) or ""
    if raw["more"]:
        content = " ".join([content, *raw["more"]]).strip()
    claimed, precision = parse_date(date_text)
    tail = _TAIL.search(content)
    if tail:
        content = content[: tail.start()].rstrip()
        if tail["kind"].casefold() == "claimed":
            claimed, precision = parse_date(tail["date"])
    return ParsedEntry(raw["line_no"], content.strip(), date_text, claimed, precision, section_at)


# Preview ------------------------------------------------------------------------------------------------------

@dataclass(slots=True)
class PreviewItem:
    key: int  # the line number in the input
    content: str
    original: str
    date_text: str | None
    claimed_date: str | None
    claimed_precision: str | None
    section: str | None
    destination: str | None  # space id
    state: str = NEW
    reasons: tuple[str, ...] = ()
    sensitive: tuple[str, ...] = ()
    checked: bool = False
    user_checked: bool | None = None  # the user's own choice wins over the default
    said_at: str | None = None
    said_at_precision: str | None = None
    said_at_confirmed: str | None = None  # 12.1: preview-item, preview-bulk, or edited
    match_id: str | None = None  # the existing memory for "already there" and "may conflict"
    match_revision_id: str | None = None
    match_title: str | None = None
    project_hint: str | None = None
    secret_kinds: tuple[str, ...] = ()

    @property
    def title(self) -> str:
        return make_title(self.content)

    @property
    def blocked(self) -> bool:
        return self.state in BLOCKED or self.state == BATCH_DUPLICATE

    @property
    def display_content(self) -> str:
        """Secrets are never shown again: the preview shows the entry with long tokens masked."""
        if self.state != SECRET:
            return self.content
        return mask_secrets(self.content)


@dataclass(slots=True)
class ImportPreview:
    source: str
    items: list[PreviewItem]
    source_notes: tuple[tuple[int, str], ...]
    unreadable: tuple[tuple[int, str], ...]
    encoding: str
    same_date_warning: tuple[str, ...] = ()  # dates that look like the export date (12.1)
    seconds: float = 0.0

    def by_key(self, key: int) -> PreviewItem:
        return next(item for item in self.items if item.key == key)

    def to_note(self, key: int) -> None:
        """12.2: an entry that is really the AI's explanation moves to the source notes (never stored)."""
        item = self.by_key(key)
        self.items.remove(item)
        self.source_notes = tuple(sorted((*self.source_notes, (item.key, item.original))))

    def from_note(self, line_no: int) -> int:
        """A source note or unreadable line that is really a memory becomes an entry (the caller recomputes it)."""
        for name in ("source_notes", "unreadable"):
            lines = getattr(self, name)
            found = next((text for number, text in lines if number == line_no), None)
            if found is None:
                continue
            setattr(self, name, tuple(line for line in lines if line[0] != line_no))
            entry = parse_text(found).entries
            content = entry[0].content if entry else found.strip().lstrip("-*• ").strip()
            claimed = entry[0] if entry else None
            destination = next((item.destination for item in self.items if item.destination), None)
            self.items.append(PreviewItem(line_no, content, content, claimed.date_text if claimed else None,
                                          claimed.claimed_date if claimed else None,
                                          claimed.claimed_precision if claimed else None, None, destination))
            self.items.sort(key=lambda item: item.key)
            return line_no
        raise KeyError(line_no)

    def summary(self) -> dict[str, int]:
        counts = Counter(item.state for item in self.items)
        return {
            "new": counts[NEW], "exists": counts[EXISTS], "conflict": counts[CONFLICT],
            "sensitive": sum(1 for item in self.items if item.sensitive),
            "blocked": sum(counts[state] for state in BLOCKED) + counts[BATCH_DUPLICATE],
            "path_review": counts[PATH_REVIEW], "source_notes": len(self.source_notes),
            "unreadable": len(self.unreadable),
        }

    def selected(self) -> list[PreviewItem]:
        return [item for item in self.items if item.checked and not item.blocked and item.state != EXISTS]

    def ready(self) -> bool:
        """The import button works only when every selected entry has a destination (no General by default)."""
        chosen = self.selected()
        return bool(chosen) and all(item.destination for item in chosen)

    def counts_by_space(self, names: dict[str, str]) -> dict[str, int]:
        result: Counter[str] = Counter()
        for item in self.selected():
            result[names.get(item.destination or "", item.destination or "?")] += 1
        return dict(result)


def make_title(content: str) -> str:
    """A short title from the entry: its first sentence, at most 80 characters, cut at a word."""
    text = " ".join(content.split())
    sentence = re.split(r"(?<=[.!?。])\s", text, maxsplit=1)[0]
    if len(sentence) <= TITLE_LIMIT:
        return sentence or "Imported memory"
    cut = sentence[: TITLE_LIMIT - 1].rsplit(" ", 1)[0]
    return (cut if len(cut) > TITLE_LIMIT // 2 else sentence[: TITLE_LIMIT - 1]) + "…"


def mask_secrets(text: str) -> str:
    """Hide anything that looks like a credential before it is shown on screen."""
    masked = re.sub(r"[A-Za-z0-9+/_=-]{12,}", "•••", text)
    return re.sub(r"(?i)((?:password|passwd|pwd|token|secret|api[_ -]?key|비밀번호|패스워드|토큰)\s*(?:[:=]|is|는|은)?\s*)\S+",
                  r"\1•••", masked)


def sensitive_labels(text: str) -> tuple[str, ...]:
    return tuple(key for key, _label, pattern in SENSITIVE_PATTERNS if pattern.search(text))


def same_date_warning(items: Sequence[PreviewItem]) -> tuple[str, ...]:
    """Dates used by 20 or more entries, or by half or more of the dated entries (12.1)."""
    dated = [item.claimed_date for item in items if item.claimed_date]
    if not dated:
        return ()
    counts = Counter(dated)
    return tuple(sorted(day for day, count in counts.items()
                        if count >= 2 and (count >= SAME_DATE_COUNT or count >= SAME_DATE_SHARE * len(dated))))


class ImportPlanner:
    """Builds and recomputes the preview. Reads the store; never writes."""

    def __init__(self, store: SQLiteMemoryStore, spaces: Iterable[Space], *, size_limit: int = FILE_CONTENT_LIMIT,
                 folder_labels: Iterable[str] = (), profile: str | None = None) -> None:
        self.store = store
        self.spaces = {space.space_id: space for space in spaces}
        self.size_limit = size_limit
        self.profile = profile if profile is not None else os.environ.get("USERPROFILE")
        self.hints = [(space.display_name, space) for space in self.spaces.values()
                      if not space.is_general and not space.is_personal]
        self.folder_labels = [label for label in folder_labels if len(label) >= 3]

    def preview(self, parsed: ParseResult, *, source: str, destination: str | None,
                progress: Callable[[int, int], bool] | None = None) -> ImportPreview:
        """Every entry starts with the batch destination; ``None`` means the user hasn't chosen one yet.

        ``progress(done, total)`` is called while entries are compared; returning False cancels the preview.
        """
        if source not in SOURCES:
            raise ValueError("source must be chatgpt, claude, or other")
        if len(parsed.entries) > MAX_ITEMS:
            raise ImportRejected(f"This has {len(parsed.entries):,} entries; BIO CE imports at most {MAX_ITEMS:,} at "
                               "once. Split it and import the parts one by one.")
        if destination is not None and destination not in self.spaces:
            raise ValueError("unknown destination space")
        started = time.perf_counter()
        items = [PreviewItem(entry.line_no, entry.content, entry.content, entry.date_text, entry.claimed_date,
                             entry.claimed_precision, entry.section, destination) for entry in parsed.entries]
        result = ImportPreview(source, items, parsed.source_notes, parsed.unreadable, parsed.encoding)
        self.recompute(result, progress=progress)
        result.same_date_warning = same_date_warning(items)
        result.seconds = time.perf_counter() - started
        return result

    # Changes in the preview ----------------------------------------------------------------------------

    def set_destination(self, preview: ImportPreview, keys: Iterable[int], space_id: str) -> None:
        if space_id not in self.spaces:
            raise ValueError("unknown destination space")
        wanted = set(keys)
        for item in preview.items:
            if item.key in wanted:
                item.destination = space_id
        self.recompute(preview, wanted)

    def set_checked(self, preview: ImportPreview, keys: Iterable[int], checked: bool) -> None:
        wanted = set(keys)
        for item in preview.items:
            if item.key in wanted and not item.blocked and item.state != EXISTS:
                item.user_checked = checked
                item.checked = checked

    def edit(self, preview: ImportPreview, key: int, content: str) -> PreviewItem:
        """Change an entry's text. A changed text (not only spacing) loses its source date: that date was a claim
        about the original text (owner rule, 2026-11-16), and so does a "said" date taken from it. A date the user
        typed (``edited``) stays."""
        item = preview.by_key(key)
        new = " ".join(content.split())
        if normalize(new) != normalize(item.content):
            item.claimed_date = item.claimed_precision = item.date_text = None
            if item.said_at_confirmed != "edited":
                item.said_at = item.said_at_precision = item.said_at_confirmed = None
        item.content = new
        self.recompute(preview, {key})
        return item

    def confirm_dates(self, preview: ImportPreview, keys: Iterable[int], *, how: str = "preview-bulk") -> int:
        """12.1: the user says these dates are when they said it. Only then is ``said_at`` filled."""
        count = 0
        wanted = set(keys)
        for item in preview.items:
            if item.key in wanted and item.claimed_date:
                item.said_at, item.said_at_precision, item.said_at_confirmed = (
                    item.claimed_date, item.claimed_precision, how)
                count += 1
        return count

    def set_date(self, preview: ImportPreview, key: int, text: str) -> PreviewItem:
        """The user typed a date: that counts as confirmed (``edited``). An empty value clears it."""
        item = preview.by_key(key)
        parsed, precision = parse_date(text)
        if text.strip() and parsed is None:
            raise ValueError("Use a date such as 2025-03-14 or 2025-03.")
        item.said_at, item.said_at_precision = parsed, precision
        item.said_at_confirmed = "edited" if parsed else None
        return item

    def bulk_confirmable(self, preview: ImportPreview) -> list[int]:
        """Entries offered for "confirm all dates": dated, and not on a date that looks like the export date."""
        suspicious = set(preview.same_date_warning)
        return [item.key for item in preview.items if item.claimed_date and item.claimed_date not in suspicious]

    # Classification ----------------------------------------------------------------------------------------

    def recompute(self, preview: ImportPreview, keys: set[int] | None = None,
                  progress: Callable[[int, int], bool] | None = None) -> None:
        self._has_rows: dict[MemoryScope, bool] = {}
        seen: dict[tuple[str | None, str], int] = {}
        total = len(preview.items)
        for done, item in enumerate(preview.items):
            if progress is not None and done % 25 == 0 and progress(done, total) is False:
                raise ImportCancelled("The preview was cancelled.")
            if keys is None or item.key in keys:
                self._classify(item)
            if item.state in BLOCKED:
                continue
            marker = (item.destination, normalize(item.content))
            if marker in seen and seen[marker] != item.key:
                item.state, item.reasons = BATCH_DUPLICATE, ("the same entry appears earlier in this import",)
                item.checked = False
            else:
                if item.state == BATCH_DUPLICATE:
                    self._classify(item)
                seen.setdefault(marker, item.key)

    def _classify(self, item: PreviewItem) -> None:
        item.match_id = item.match_revision_id = item.match_title = item.project_hint = None
        item.secret_kinds = ()
        item.sensitive = sensitive_labels(item.content)
        content = item.content.strip()
        if not content:
            self._set(item, EMPTY, ("the entry has no text",))
            return
        found = detect_secrets(content)
        if found:
            item.secret_kinds = found
            self._set(item, SECRET, ("secrets are never stored (" + ", ".join(found) + ")",))
            return
        if detect_injection(content):
            self._set(item, INSTRUCTION, ("this reads like an instruction to an AI; rewrite it as your preference",))
            return
        title = make_title(content)
        if len(title) + len(content) > self.size_limit:
            self._set(item, TOO_LONG, (f"at most {self.size_limit:,} characters (title and text together); "
                                       "shorten it in the preview",))
            return
        prepared = prepare_text(title, content, profile=self.profile)
        personal = item.destination == PERSONAL_SPACE_ID
        if item.destination is None:
            self._set(item, NEW, ())
            return
        space = self.spaces[item.destination]
        if prepared.absolute_paths and not personal:
            self._set(item, PATH_REVIEW, ("contains a local path, which can identify you or your PC",))
            return
        if personal:
            item.project_hint = self._project_hint(content)
        match, score = self._closest(space, f"{title}\n{prepared.content}")
        if match is not None and (score >= DUPLICATE_THRESHOLD or _contained(content, match)):
            item.match_id, item.match_revision_id, item.match_title = match.memory_id, match.revision_id, match.title
            self._set(item, EXISTS, ("BIO CE already has this in the destination space",))
            return
        # A review protects a curated memory from being replaced, so only a memory, and only for the same topic:
        # sharing an opening and an ending ("사용자는 … 한다") made three reviews that would replace one fact
        # with another (GUI check, 2026-11-16). A near inbox item is New; a merge suggestion handles that.
        if match is not None and match.scope == space.curated and score >= CONFLICT_LOW \
                and _shares_keyword(content, match) \
                and topic_overlap(content, f"{match.title}\n{match.content or ''}") >= TOPIC_THRESHOLD:
            item.match_id, item.match_revision_id, item.match_title = match.memory_id, match.revision_id, match.title
            self._set(item, CONFLICT, ("imported text may differ from an existing memory; you review it, nothing "
                                       "is overwritten",))
            return
        self._set(item, NEW, ())

    def _set(self, item: PreviewItem, state: str, reasons: tuple[str, ...]) -> None:
        item.state, item.reasons = state, reasons
        if state in BLOCKED or state in (EXISTS, BATCH_DUPLICATE):
            item.checked = False
            return
        if item.user_checked is not None:
            item.checked = item.user_checked
            return
        # 12.3: a sensitive entry stays checked for Personal and starts unchecked anywhere else.
        item.checked = not item.sensitive or item.destination == PERSONAL_SPACE_ID

    def _closest(self, space: Space, text: str):
        """The most similar memory among the top FTS candidates (curated and inbox), searched by key words only."""
        best, best_score = None, 0.0
        query = _keywords(text)
        if not query:
            return best, best_score
        mine = _word_set(text)
        for scope in (space.curated, space.inbox):
            if not self._rows(scope):
                continue
            for hit in self.store.search(scope, query, limit=5):
                try:
                    revision = self.store.read(scope, hit.memory_id)
                except Exception:  # noqa: BLE001 - a vanished candidate is no match
                    continue
                other = f"{revision.title}\n{revision.content or ''}"
                theirs = _word_set(other)
                overlap = len(mine & theirs) / max(1, min(len(mine), len(theirs)))
                score = _score(text, other) if overlap >= 0.2 else 0.0
                if _contained(text.split("\n", 1)[-1], revision):
                    score = max(score, DUPLICATE_THRESHOLD)
                if score > best_score:
                    best, best_score = revision, score
        return best, best_score

    def _rows(self, scope: MemoryScope) -> bool:
        cache = getattr(self, "_has_rows", None)
        if cache is None:
            cache = self._has_rows = {}
        if scope not in cache:
            cache[scope] = self.store.count_current(scope) > 0
        return cache[scope]

    def _project_hint(self, content: str) -> str | None:
        folded = content.casefold()
        for name, space in self.hints:
            if len(name) >= 3 and name.casefold() in folded:
                return space.display_name
        for label in self.folder_labels:
            if label.casefold() in folded:
                return label
        return None


def _score(left: str, right: str) -> float:
    """The same value as memory_policy.similarity at or above CONFLICT_LOW; 0.0 below it (cheap upper bounds first)."""
    a, b = normalize(left), normalize(right)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    matcher = SequenceMatcher(None, a, b, autojunk=False)
    if matcher.real_quick_ratio() < CONFLICT_LOW or matcher.quick_ratio() < CONFLICT_LOW:
        return 0.0
    return matcher.ratio()


def _contained(content: str, revision) -> bool:
    left, right = normalize(content), normalize(f"{revision.title}\n{revision.content or ''}")
    return bool(left) and len(left) >= 12 and (left in right or (len(right) >= 12 and right in left))


def _word_set(text: str) -> set[str]:
    return {word for word in _WORD.findall(normalize(text)) if word not in _STOP}


def _keywords(text: str, limit: int = 8) -> str:
    """The longest distinct words: a short FTS query that finds the same topic without matching every row."""
    words = sorted(_word_set(text), key=lambda word: (-len(word), word))
    return " ".join(words[:limit])


_STOP = {"the", "and", "for", "with", "that", "this", "user", "users", "uses", "use", "about", "from", "has",
         "have", "are", "was", "were", "they", "their", "every", "사용자", "사용자는", "사용자의", "있다", "한다", "했다"}


def _shares_keyword(content: str, revision) -> bool:
    mine = {word for word in _WORD.findall(normalize(content)) if word not in _STOP}
    theirs = {word for word in _WORD.findall(normalize(f"{revision.title} {revision.content or ''}"))
              if word not in _STOP}
    return bool(mine & theirs)


# Commit and undo ----------------------------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class ImportResult:
    batch_id: str
    status: str  # complete or partial
    to_inbox: int
    to_review: int
    by_space: dict[str, int]
    error: str | None = None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def entry_source(item: PreviewItem, *, source: str, batch_id: str, imported_at: str) -> SourceProvenance:
    metadata = {
        "import_source": source, "batch_id": batch_id, "imported_at": imported_at, "stage": "inbox",
        "claimed_date": item.claimed_date, "claimed_date_precision": item.claimed_precision,
        "claimed_date_text": (item.date_text or None) if item.date_text and not item.claimed_date else None,
        "said_at": item.said_at, "said_at_precision": item.said_at_precision,
        "said_at_confirmed": item.said_at_confirmed, "section": item.section, "line_no": item.key,
        "sensitive": list(item.sensitive) or None,
    }
    return SourceProvenance(SOURCE_TYPE, f"import:{source}", {k: v for k, v in metadata.items() if v is not None})


class ImportService:
    """Writes a previewed import and undoes it. Only the desktop app uses this (one writer, like other app writes)."""

    def __init__(self, store: SQLiteMemoryStore, control: ControlStore, spaces: Iterable[Space]) -> None:
        self.store = store
        self.control = control
        self.spaces = {space.space_id: space for space in spaces}

    def commit(self, preview: ImportPreview, *, batch_id: str | None = None,
               fail_after_chunks: int | None = None) -> ImportResult:
        """Save the selected entries. ``batch_id`` retries a partial batch (entries already saved are skipped).

        ``fail_after_chunks`` exists for the interruption test only.
        """
        chosen = preview.selected()
        if not chosen:
            raise ImportRejected("Nothing is selected to import.")
        if not all(item.destination in self.spaces for item in chosen):
            raise ImportRejected("Choose a destination space for every selected entry first.")
        if batch_id is None:
            batch_id = "imp_" + _secrets.token_hex(8)
            imported_at = _now()
            self.control.create_import_batch(batch_id, source=preview.source,
                                             default_space_id=chosen[0].destination or "",
                                             created_at=imported_at)
        batch = self.control.import_batch(batch_id)
        imported_at = batch["created_at"]
        saved: dict[int, str] = {int(k): v for k, v in batch["memory_ids"]}
        reviewed: dict[int, int] = {int(k): int(v) for k, v in batch["review_ids"]}
        inbox_items = [item for item in chosen if item.state == NEW and item.key not in saved]
        review_items = [item for item in chosen if item.state in (CONFLICT, PATH_REVIEW) and item.key not in reviewed]
        error = None
        try:
            for number, start in enumerate(range(0, len(inbox_items), CHUNK_SIZE)):
                if fail_after_chunks is not None and number >= fail_after_chunks:
                    raise RuntimeError("interrupted for the test")
                chunk = inbox_items[start:start + CHUNK_SIZE]
                revisions = self.store.add_many([
                    (self.spaces[item.destination].inbox, item.title, item.content,
                     entry_source(item, source=preview.source, batch_id=batch_id, imported_at=imported_at))
                    for item in chunk])
                for item, revision in zip(chunk, revisions):
                    saved[item.key] = revision.memory_id
                self.control.inbox_seen_many([revision.memory_id for revision in revisions], first_seen=imported_at)
                self.control.update_import_batch(batch_id, memory_ids=sorted(saved.items()))
            for item in review_items:
                space = self.spaces[item.destination]
                metadata = {**entry_source(item, source=preview.source, batch_id=batch_id,
                                           imported_at=imported_at).metadata}
                if item.state == CONFLICT:
                    review_id = self.control.enqueue_review(
                        host=IMPORT_HOST, connection_id=None, kind="update", title=item.match_title or item.title,
                        content=item.content, memory_id=item.match_id, expected_revision_id=item.match_revision_id,
                        review_reason="Imported text may differ from this memory. Nothing was overwritten.",
                        metadata={**metadata, "project": space.curated.project, "namespace": space.curated.namespace})
                else:
                    review_id = self.control.enqueue_review(
                        host=IMPORT_HOST, connection_id=None, kind="create", title=item.title, content=item.content,
                        review_reason="Contains a local path, which can identify you or your PC.",
                        metadata={**metadata, "project": space.inbox.project, "namespace": space.inbox.namespace})
                reviewed[item.key] = review_id
                self.control.update_import_batch(batch_id, review_ids=sorted(reviewed.items()))
        except Exception as exc:  # noqa: BLE001 - the batch stays "partial": retry or undo
            error = str(exc) or exc.__class__.__name__
        names = {space_id: space.display_name for space_id, space in self.spaces.items()}
        by_space: Counter[str] = Counter()
        for item in chosen:
            if item.key in saved or item.key in reviewed:
                by_space[names[item.destination]] += 1
        status = "partial" if error else "complete"
        counts = {"inbox": len(saved), "review": len(reviewed), "by_space": dict(by_space),
                  "source_notes": len(preview.source_notes), "unreadable": len(preview.unreadable),
                  "skipped": len(preview.items) - len(saved) - len(reviewed)}
        self.control.update_import_batch(batch_id, status=status, counts=counts)
        self.control.record(host=IMPORT_HOST, connection_id=None, action="import", outcome=status,
                            detail={"batch_id": batch_id, "source": preview.source, "inbox": len(saved),
                                    "review": len(reviewed)})
        return ImportResult(batch_id, status, len(saved), len(reviewed), dict(by_space), error)

    def undo(self, batch_id: str) -> dict[str, int]:
        """Remove what is still in the inbox from this batch, close its pending reviews, keep everything sorted."""
        batch = self.control.import_batch(batch_id)
        if batch["status"] == "undone":
            raise ImportRejected("This import was already undone.")
        ids = [memory_id for _key, memory_id in batch["memory_ids"]]
        # Also its items a suggestion or a move kept aside: undoing the import deletes what it brought in.
        where = {memory_id: MemoryScope(project, namespace)
                 for memory_id, project, namespace in self.store.inventory()
                 if namespace.endswith(INBOX_SUFFIX) or namespace.endswith(INBOX_SUFFIX + KEPT_SUFFIX)}
        by_scope: dict[MemoryScope, list[str]] = {}
        for memory_id in ids:
            if memory_id in where:
                by_scope.setdefault(where[memory_id], []).append(memory_id)
        removed = 0
        for scope, scope_ids in by_scope.items():
            deleted = discard_inbox_items(self.store, self.control, scope, scope_ids, host=IMPORT_HOST).deleted
            removed += deleted if scope.namespace.endswith(INBOX_SUFFIX) else 0
        closed = 0
        for _key, review_id in batch["review_ids"]:
            try:
                self.control.resolve_review(int(review_id), "rejected", "import undone")
                closed += 1
            except Exception:  # noqa: BLE001 - already decided by the user: it stays as decided
                continue
        kept = len(ids) - removed
        self.control.update_import_batch(batch_id, status="undone", undone_at=_now())
        self.control.record(host=IMPORT_HOST, connection_id=None, action="import-undo", outcome="undone",
                            detail={"batch_id": batch_id, "removed": removed, "kept": kept,
                                    "reviews_closed": closed})
        return {"removed": removed, "kept": kept, "reviews_closed": closed}


__all__ = [
    "BATCH_DUPLICATE", "CONFLICT", "EXISTS", "INSTRUCTION", "ImportCancelled", "ImportRejected", "ImportPlanner",
    "ImportPreview",
    "ImportResult", "ImportService", "MAX_FILE_BYTES", "MAX_ITEMS", "NEW", "PATH_REVIEW", "ParseResult",
    "ParsedEntry", "PreviewItem", "SECRET", "SENSITIVE_LABELS", "SOURCES", "STATE_LABELS", "TOO_LONG",
    "make_title", "mask_secrets", "parse_date", "parse_text", "read_import_file", "same_date_warning",
    "sensitive_labels",
]
