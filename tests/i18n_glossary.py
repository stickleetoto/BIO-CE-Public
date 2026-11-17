# Copyright 2026 stickleetoto
# SPDX-License-Identifier: Apache-2.0

"""The Korean glossary as a check (v0.4.4 U5, owner request 2026-11-17).

For every English text that uses a glossary term, the Korean text of the same key must use one of that term's
Korean forms; and no Korean text may use a form the glossary retired (판 for revision, 호스트 for host, 읽기만).
The glossary itself (with the style rules) is BIO_CE_V044_I18N_GLOSSARY.md in the reports folder; this file holds
the parts a program can check. A text that uses a word in another sense goes in EXCEPTIONS with the reason.
"""

from __future__ import annotations

import re

# (English pattern, Korean forms any one of which must appear)
TERMS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (r"\bmemor(?:y|ies)\b", ("기억",)),
    (r"\binbox\b", ("수집함",)),
    (r"\bsuggestions?\b", ("제안",)),
    (r"\breviews?\b", ("검토",)),
    (r"\bretract(?:ion|ed|s)?\b", ("철회", "삭제")),
    (r"\bforget\b|\bforgotten\b|\bforgetting\b", ("잊",)),
    (r"\bdiscard(?:ed|s|ing)?\b", ("버리", "버림", "버렸", "버린", "버릴", "버려", "버립")),
    (r"\bundo(?:ne)?\b", ("실행 취소", "되돌", "취소")),
    (r"\bapprov(?:e|ed|al|es|ing)\b", ("승인",)),
    (r"\breject(?:ed|s|ing)?\b", ("거절",)),
    (r"\bmerg(?:e|ed|es|ing)\b", ("합치", "합친", "합쳐", "합칠", "합쳤")),
    (r"(?<!\{)\bspaces?\b(?!\})", ("공간",)),  # not the {space} placeholder
    (r"\bpersonal\b", ("개인",)),
    (r"\b(?:ai )?hosts?\b", ("AI 도구", "{host}")),
    (r"\bimport(?:ed|s|ing)?\b", ("가져오", "가져온", "가져옴", "가져와", "가져올", "가져왔")),
    (r"\bexport(?:ed|s|ing)?\b", ("내보내", "내보낸", "내보냄", "내보낼", "내보냈")),
    (r"\bbackups?\b|\bbacked up\b|\bback(?:s)? up\b", ("백업",)),
    (r"\brestor(?:e|ed|es|ing)\b", ("복원",)),
    (r"\brevisions?\b", ("버전",)),
    (r"\bhistory\b", ("기록",)),
    (r"\bsensitive\b", ("민감",)),
    (r"\bread only\b", ("읽기 전용",)),
    (r"\bauto memory\b", ("자동 기억",)),
    (r"\bcurated\b", ("바로 저장",)),
)

# Korean forms the glossary retired; none may appear anywhere.
RETIRED: tuple[tuple[str, str], ...] = (
    (r"호스트", "Host is “AI 도구” (owner decision 2026-11-17)"),
    (r"(?<![가-힣])판(?=[ {)·,.]|$|으로|까지|은|을|이|에|의)", "Revision is “버전” (owner decision 2026-11-17)"),
    (r"읽기만", "Read only is “읽기 전용” (owner decision 2026-11-17)"),
)

# key -> why the English word there is not the glossary term (or the Korean says it another accepted way)
EXCEPTIONS: dict[str, str] = {
    "shortcut.tab": "“Space” is the key's name, not a BIO CE space",
    "hub.card.no_text": "a card's own label: “memory text” is the card's 본문",
    "dashboard.stored_detail": "“your personal store” is the local database on this PC, not the Personal space",
    "connections.connect.point_read": "“your personal store” is the local database on this PC, not the Personal space",
    "connections.desktop.point_read": "“your personal store” is the local database on this PC, not the Personal space",
    "connections.saving.collect_point_review": "“curated memories” are saved memories (not the inbox), not the "
                                               "Curated saving mode",
}


def _text(value) -> str:
    return value if isinstance(value, str) else " ".join(str(v) for v in value.values())


def violations(english: dict, korean: dict) -> list[str]:
    found = []
    for key, value in english.items():
        if key in EXCEPTIONS or key not in korean:
            continue
        en_text, ko_text = _text(value).casefold(), _text(korean[key])
        for pattern, forms in TERMS:
            if re.search(pattern, en_text) and not any(form in ko_text for form in forms):
                found.append(f"{key}: “{pattern}” → none of {forms} in: {ko_text[:80]}")
    for key, value in korean.items():
        for pattern, why in RETIRED:
            if re.search(pattern, _text(value)):
                found.append(f"{key}: {why}: {_text(value)[:80]}")
    return found
