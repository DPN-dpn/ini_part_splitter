import re
from ...core.properties import INIPS_Resources


def create_resource_enum(op, scene, sections):
    # IB 리소스 수집: "ib = ..." 구문에서 값을 추출
    ib_pattern = re.compile(r"^\s*ib\s*=\s*(.+)$", re.IGNORECASE)
    resources = []
    for lines in sections.values():
        for line in lines:
            m = ib_pattern.match(line)
            if not m:
                continue
            val = m.group(1).strip()
            if val:
                resources.append(val)

    # 순서 유지한 중복 제거 및 Enum 항목 생성 (첫 항목은 NONE)
    seen = set()
    enum_items = []
    for r in resources:
        if r in seen:
            continue
        seen.add(r)
        enum_items.append((r, r, ""))

    # 프로퍼티 클래스의 항목을 업데이트
    INIPS_Resources._resource_items = enum_items

    # 현재 선택된 값이 유효하지 않으면 기본값 설정(가능하면 첫 실 리소스로)
    valid_ids = [it[0] for it in enum_items]
    if scene.inips_resource not in valid_ids:
        scene.inips_resource = enum_items[0][0] if enum_items else ""
