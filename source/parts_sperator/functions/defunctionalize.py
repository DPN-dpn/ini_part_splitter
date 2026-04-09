from collections import OrderedDict
import re


def _strip_inline_comments(value: str) -> str:
    # ';' 또는 '#' 이후는 주석으로 취급
    for sep in (";", "#"):
        idx = value.find(sep)
        if idx != -1:
            value = value[:idx]
    return value.strip()


def _expand_section(
    name: str,
    stack: set,
    ini_sections: dict,
    memo: dict = {},
    recursion_marker_fmt="; [defunctionalize_sections] recursion skipped: {}",
) -> list:
    if name in memo:
        # 캐시 복사 반환 (외부에서 수정될 수 있으므로 복사)
        return list(memo[name])
    if name not in ini_sections:
        return []
    if name in stack:
        # 순환 발견: 무한 재귀 방지용 주석을 삽입하고 확장 중단
        return [recursion_marker_fmt.format(name)]

    stack.add(name)
    out_lines = []
    for line in ini_sections[name]:
        # run = ... 형식 검사 (대소문자 무시)
        if re.match(r"^\s*run\s*=", line, re.IGNORECASE):
            parts = line.split("=", 1)
            if len(parts) == 2:
                target = _strip_inline_comments(parts[1])
                if (
                    target
                    and target.startswith("CommandList")
                    and target in ini_sections
                ):
                    expanded = _expand_section(
                        target, stack, ini_sections, memo, recursion_marker_fmt
                    )
                    out_lines.extend(expanded)
                    continue  # run 라인은 확장된 내용으로 대체됨
        out_lines.append(line)
    stack.remove(name)
    memo[name] = list(out_lines)
    return list(out_lines)


def defunctionalize_sections(ini_sections):
    """
    INI 섹션 맵을 전처리해 `CommandList...` 섹션을 함수처럼 취급하고
    `run = CommandList...` 구문을 호출 지점에 인라인으로 확장합니다.

    입력:
      ini_sections: mapping(section_name -> list_of_lines) (OrderedDict 권장)
    출력:
      OrderedDict로 반환되며, 원본과 동일한 섹션 순서를 유지하되
      - 이름이 'CommandList'로 시작하는 섹션들은 함수로 간주되어 호출 지점에서 인라인 확장됨
      - 확장 후에는 `CommandList...` 섹션 자체는 결과에서 제외됩니다

    동작:
      - `run = <target>` 문은 좌변/우변을 '='로 분리 후 오른쪽에서 ';' 또는 '#'로 시작하는 인라인 주석을 제거해 타겟을 결정합니다.
      - 타겟이 존재하고 'CommandList'로 시작하면 해당 섹션의 내용으로 교체(재귀적으로 확장).
      - 순환 호출이 발견되면 해당 호출은 주석 행으로 대체하여 무한 루프를 방지합니다.
    """
    if not ini_sections:
        return OrderedDict()

    memo = {}  # 섹션별 확장 결과 캐시
    recursion_marker_fmt = "; [defunctionalize_sections] recursion skipped: {}"

    result = OrderedDict()
    for sec_name in ini_sections:
        # CommandList로 시작하는 섹션은 함수 정의이므로 결과에는 포함하지 않음
        if sec_name.startswith("CommandList"):
            continue
        result[sec_name] = _expand_section(
            sec_name, set(), ini_sections, memo, recursion_marker_fmt
        )

    return result
