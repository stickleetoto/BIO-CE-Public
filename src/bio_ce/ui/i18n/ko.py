# Copyright 2026 stickleetoto
# SPDX-License-Identifier: Apache-2.0

"""Korean text of the desktop app, by key. Every key here is also in ``en.py`` (tests check)."""

STRINGS: dict[str, object] = {
    # Navigation
    "nav.dashboard": "대시보드",
    "nav.memories": "기억",
    "nav.connections": "연결",
    "nav.settings": "설정",
    # Spaces
    "space.general": "일반",
    "space.personal": "개인",
    "space.all": "모든 공간",
    # Common words
    "common.cancel": "취소",
    "common.close": "닫기",
    "common.save": "저장",
    "common.undo": "실행 취소",
    "common.items": {"other": "항목 {count}개"},
    "common.memories": {"other": "기억 {count}개"},
    # Settings: language
    "settings.language.title": "언어",
    "settings.language.auto": "Windows와 같게",
    "settings.language.note": "이 앱의 글자입니다. AI 앱이 BIO CE에서 읽는 내용은 영어로 남습니다.",
    # Settings: automatic backups
    "settings.backups.keep": "자동 백업을 최근 {count}개만 보관",
}
