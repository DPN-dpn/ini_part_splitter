from typing import List, Dict, Iterable, Optional
from dataclasses import dataclass, asdict


@dataclass
class PartInfo:
    name: str
    start_index: int
    index_count: int
    meta: Optional[Dict] = None


def _build_parts_map_dataclass(
    sections: Dict[str, Iterable[str]], resource: str
) -> List[PartInfo]:
    # TODO: 실제 파츠 생성 로직 구현
    return []


def build_parts_map(sections: Dict[str, Iterable[str]], resource: str) -> List[Dict]:
    parts = _build_parts_map_dataclass(sections, resource)
    return [asdict(p) for p in parts]
