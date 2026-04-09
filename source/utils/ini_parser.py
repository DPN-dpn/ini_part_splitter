from collections import OrderedDict
import re

_SECTION_RE = re.compile(r"^\s*\[([^\]]+)\]\s*(?:[;#].*)?$")


def parse_ini_sections(text: str) -> OrderedDict:
    """
    INI-like 문자열을 섹션 단위로 파싱해 OrderedDict(section_name -> list_of_lines)을 반환.
    - 섹션 헤더 '[name]' 자체는 각 섹션의 라인 리스트에 포함되지 않습니다.
    - 첫 섹션 이전의 라인(파일 상단의 주석 등)은 빈 문자열 키 '' 에 저장됩니다.
    - 각 라인은 원본 그대로(들여쓰기, 주석, 공백 유지) 리스트 항목으로 저장됩니다.
    - 같은 이름의 섹션이 여러 번 나오면 기존 섹션에 라인을 이어 붙입니다.
    """
    if text is None:
        return OrderedDict()
    # BOM 제거(있을 수 있음)
    if text.startswith("\ufeff"):
        text = text.lstrip("\ufeff")

    lines = text.splitlines()
    sections = OrderedDict()
    current = ""
    sections[current] = []

    for line in lines:
        m = _SECTION_RE.match(line)
        if m:
            name = m.group(1).strip()
            if name not in sections:
                sections[name] = []
            current = name
        else:
            sections[current].append(line)

    return sections
