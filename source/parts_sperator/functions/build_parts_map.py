import re
from typing import List, Dict, Iterable, Optional, Tuple
from dataclasses import dataclass, asdict


@dataclass
class PartInfo:
    name: str
    start_index: int
    index_count: int
    meta: Optional[Dict] = None


def _extract_drawindexed_from_lines(
    lines: Iterable[str], counter: int
) -> Tuple[List[PartInfo], int]:
    # 섹션 내용에서 주석과 drawindexed만 필터링 (원본 순서 유지)
    filtered = []
    for raw in lines:
        s = raw.strip()
        if not s:
            continue
        low = s.lower()
        if s.startswith(";") or s.startswith("#") or low.startswith("drawindexed"):
            filtered.append(s)

    temp_results = []
    seen_values = set()
    last_comment = None

    for item in filtered:
        if item.startswith(";") or item.startswith("#"):
            m = re.match(r"[;#]\s*([^\(]+)", item)
            if m:
                last_comment = m.group(1).strip()
            else:
                last_comment = item.lstrip(";#").strip()
            continue

        # drawindexed 처리
        if item.lower().startswith("drawindexed"):
            parts_eq = item.split("=", 1)
            if len(parts_eq) != 2:
                continue
            val = parts_eq[1].strip()
            if not re.match(r"^\s*\d+\s*,\s*\d+\s*,\s*0\s*$", val):
                continue
            if val in seen_values:
                continue
            seen_values.add(val)
            numbers = list(map(int, re.findall(r"\d+", val)))
            if len(numbers) >= 2:
                temp_results.append(
                    {
                        "start_index": numbers[1],
                        "index_count": numbers[0],
                        "comment": last_comment,
                    }
                )

    # 같은 주석 그룹별로 네이밍(같은 주석이면 _1, _2 ...), 주석 없으면 part_N
    comment_groups = {}
    for item in temp_results:
        c = item["comment"]
        if c:
            comment_groups.setdefault(c, []).append(item)

    out: List[PartInfo] = []
    for item in temp_results:
        c = item["comment"]
        if c:
            group = comment_groups[c]
            if len(group) == 1:
                name = c
            else:
                name = f"{c}_{group.index(item) + 1}"
        else:
            name = f"part_{counter}"
            counter += 1

        out.append(
            PartInfo(
                name=name,
                start_index=item["start_index"],
                index_count=item["index_count"],
                meta={"comment": c},
            )
        )

    return out, counter


def _build_parts_map_dataclass(
    sections: Dict[str, Iterable[str]], resource: str
) -> List[PartInfo]:
    if not sections or not resource:
        return []

    def _strip_inline_comment(s: str) -> str:
        for sep in (";", "#"):
            idx = s.find(sep)
            if idx != -1:
                s = s[:idx]
        return s.strip()

    # TextureOverride 섹션에서 ib = {resource} 구간만 수집
    ranges = []
    for sec, lines in sections.items():
        if not sec.startswith("TextureOverride"):
            continue
        current_resource = None
        start_idx = None
        for idx, raw_line in enumerate(lines):
            l = raw_line.strip()
            if not l:
                continue
            if l.lower().startswith("ib"):
                parts = l.split("=", 1)
                if len(parts) == 2:
                    ib_val = _strip_inline_comment(parts[1])
                    if current_resource == resource and start_idx is not None:
                        ranges.append((sec, start_idx, idx))
                    if ib_val == resource:
                        current_resource = ib_val
                        start_idx = idx
                    else:
                        current_resource = ib_val
                        start_idx = None
        if current_resource == resource and start_idx is not None:
            ranges.append((sec, start_idx, len(lines)))

    # 중복 제거(순서 유지)
    seen_ranges = set()
    ordered_ranges = []
    for r in ranges:
        if r not in seen_ranges:
            seen_ranges.add(r)
            ordered_ranges.append(r)

    # 각 범위에서 주석+drawindexed만 남겨 파츠 추출
    counter = 1
    parts: List[PartInfo] = []
    for sec, start, end in ordered_ranges:
        sec_lines = list(sections.get(sec, []))[start:end]
        new_parts, counter = _extract_drawindexed_from_lines(sec_lines, counter)
        parts.extend(new_parts)

    return parts


def build_parts_map(sections: Dict[str, Iterable[str]], resource: str) -> List[Dict]:
    parts = _build_parts_map_dataclass(sections, resource)
    return [asdict(p) for p in parts]
