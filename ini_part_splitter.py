
# Blender 애드온 정보
bl_info = {
    "name": "INI 기반 파츠 분리",
    "author": "DPN",
    "version": (1, 6, 1),
    "blender": (2, 93, 0),
    "location": "3D 뷰 > 우측 UI 패널 > 파츠 분리",
    "description": "INI 파일을 기반으로 DrawIndexed 파츠를 오브젝트에서 분리합니다.",
    "category": "Object"
}


# Blender 및 파이썬 표준 라이브러리 임포트
import bpy
import bmesh
import re
import os
import struct
from bpy.types import Operator, Panel, PropertyGroup
from bpy.props import StringProperty, EnumProperty, PointerProperty
from bpy_extras.io_utils import ImportHelper


# 디버그 로그 함수: 디버그 모드일 때만 출력
def log_debug(context, msg):
    try:
        props = getattr(context.scene, 'ini_resource_props', None)
        if props and getattr(props, 'debug_mode', False):
            print(f"[DEBUG] {msg}")
    except Exception:
        pass

# 애드온에서 사용할 커스텀 프로퍼티 그룹
class INIResourceProperties(PropertyGroup):
    _resource_items = []

    def resource_items(self, context):
        return self._resource_items
    # drawindexed_start, drawindexed_count는 register에서 동적으로 할당

# INI 파일 선택 및 파싱 오퍼레이터
class OT_SelectIniFile(Operator, ImportHelper):
    bl_idname = "wm.select_ini_file_panel"
    bl_label = "INI 파일 선택"
    # filter_glob은 execute 바깥에서 등록

    def execute(self, context):
        props = context.scene.ini_resource_props
        # 1. 선택한 INI 파일 경로 저장
        props.ini_path = self.filepath

        # 2. INI 파일에서 TextureOverride 섹션 내 ib = 구문을 모두 찾아 Resource 목록 생성
        resource_set = set()
        current_section = None
        with open(self.filepath, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                # 2-1. 섹션명 감지
                if line.startswith('[') and line.endswith(']'):
                    current_section = line[1:-1]
                # 2-2. TextureOverride 섹션 내 ib = 구문 추출
                elif current_section and current_section.startswith('TextureOverride') and line.lower().startswith('ib'):
                    parts = line.split('=', 1)
                    if len(parts) == 2:
                        ib_name = parts[1].strip()
                        resource_set.add(ib_name)

        # 3. Resource 목록이 없으면 에러 리포트
        resource_items = [(r, r, "") for r in sorted(resource_set)]
        if not resource_items:
            self.report({'ERROR'}, "TextureOverride 섹션에 ib = 구문이 없습니다.")
            return {'CANCELLED'}

        # 4. Resource 목록을 프로퍼티에 저장
        INIResourceProperties._resource_items = resource_items
        props.resource = resource_items[0][0]

        # 5. 패널 강제 갱신: 모든 3D 뷰 영역에 대해 tag_redraw
        for window in context.window_manager.windows:
            for area in window.screen.areas:
                if area.type == 'VIEW_3D':
                    area.tag_redraw()
        return {'FINISHED'}

# INI와 IB 파일을 기반으로 파츠를 분리하는 메인 오퍼레이터 (모달)
class OT_SeparatePartsFromIniModal(Operator):
    bl_idname = "object.separate_parts_from_ini_modal"
    bl_label = "INI로 파츠 분리 (모달)"
    bl_options = {'REGISTER', 'UNDO'}

    _timer = None
    _index = 0
    _parts_map = []
    _original_obj = None
    _original_collections = []
    _scene_collection = None
    _new_collection = None

    # 특정 리소스를 사용하는 TextureOverride 섹션 구간 찾기
    def find_sections_using_resource(self, section_map, resource_name):
        log_debug(bpy.context, f"[find_sections_using_resource] resource_name={resource_name}")
        """
        TextureOverride 섹션 내 ib = 구문을 모두 파싱하여,
        각 ib = 이후 다음 ib = 또는 섹션 끝까지 해당 Resource를 사용하는 구간을 반환
        반환값: [(섹션명, start_line, end_line)]
        """
        result = []
        for sec, lines in section_map.items():
            if not sec.startswith("TextureOverride"):
                continue
            current_resource = None
            start_idx = None
            for idx, line in enumerate(lines):
                l = line.strip()
                # 1. ib= 구문을 만나면 리소스명 추출
                if l.lower().startswith("ib"):
                    parts = l.split('=', 1)
                    if len(parts) == 2:
                        ib_name = parts[1].strip()
                        # 2. 이전 리소스가 타겟이면 구간 종료
                        if current_resource == resource_name and start_idx is not None:
                            result.append((sec, start_idx, idx))
                        # 3. 새 리소스 시작 또는 타겟 아님 처리
                        if ib_name == resource_name:
                            current_resource = ib_name
                            start_idx = idx
                        else:
                            current_resource = ib_name
                            start_idx = None
            # 4. 섹션 끝까지 타겟 리소스면 마지막까지 구간 추가
            if current_resource == resource_name and start_idx is not None:
                result.append((sec, start_idx, len(lines)))
        return result

    bl_idname = "object.separate_parts_from_ini_modal"
    bl_label = "INI로 파츠 분리 (모달)"
    bl_options = {'REGISTER', 'UNDO'}

    _timer = None
    _index = 0
    _parts_map = []
    _original_obj = None
    _original_collections = []
    _scene_collection = None
    _new_collection = None

    # IB 파일을 읽어 파츠 정보 추출
    def read_ib_file(self, ib_path):
        log_debug(bpy.context, f"[read_ib_file] ib_path={ib_path}")

        parts_info = []
        try:
            with open(ib_path, 'rb') as f:
                f.seek(0, 2)  # 1. 파일 끝으로 이동하여 크기 확인
                file_size = f.tell()
                f.seek(0)  # 2. 파일 시작으로 이동
                # 3. 인덱스 크기(16/32비트) 자동 감지
                if file_size % 4 == 0:
                    index_size = 4
                    format_char = '<I'
                elif file_size % 2 == 0:
                    index_size = 2
                    format_char = '<H'
                else:
                    log_debug(bpy.context, "알 수 없는 인덱스 형식입니다.")
                    return parts_info
                index_count = file_size // index_size
                log_debug(bpy.context, f"IB 파일 분석: {index_count}개 인덱스 ({index_size*8}비트)")
                # 4. 인덱스 데이터 읽기
                indices = []
                for i in range(index_count):
                    data = f.read(index_size)
                    if len(data) < index_size:
                        break
                    index = struct.unpack(format_char, data)[0]
                    indices.append(index)
                # 5. 인덱스 배열로 파츠 분리 시도
                parts_info = self._analyze_ib_parts(indices)
        except Exception as e:
            log_debug(bpy.context, f"IB 파일 읽기 오류: {e}")
        return parts_info

    # 인덱스 배열을 분석해 파츠 분리
    def _analyze_ib_parts(self, indices):
        log_debug(bpy.context, f"[_analyze_ib_parts] indices count={len(indices)}")

        parts_info = []
        if not indices or len(indices) < 3:
            return parts_info
        # 1. 파츠 넘버링 초기화
        self._part_counter = 1
        # 2. 다양한 분리 방법 시도
        parts_by_discontinuity = self._find_parts_by_discontinuity(indices)
        self._part_counter = 1
        parts_by_vertex_range = self._find_parts_by_vertex_range(indices)
        self._part_counter = 1
        parts_by_reset = self._find_parts_by_reset_pattern(indices)
        self._part_counter = 1
        parts_by_equal_split = self._find_parts_by_equal_split(indices)
        # 3. 최적의 분리 방법 선택
        best_parts = self._select_best_partitioning(
            parts_by_discontinuity, 
            parts_by_vertex_range, 
            parts_by_reset,
            parts_by_equal_split,
            indices
        )
        # 4. 전체 인덱스가 커버되는지 확인
        best_parts = self._ensure_complete_coverage(best_parts, indices)
        return best_parts

    # 인덱스 불연속성 기반 파츠 분리
    def _find_parts_by_discontinuity(self, indices):
        parts = []
        if len(indices) < 3:
            return parts
        # 1. 인덱스를 삼각형 단위로 분할
        triangles = [indices[i:i+3] for i in range(0, len(indices), 3)]
        current_start = 0
        # 2. 삼각형 순회하며 불연속성(큰 점프) 탐지
        for i in range(1, len(triangles)):
            prev_max = max(triangles[i-1])
            curr_min = min(triangles[i])
            # 2-1. 큰 점프가 있으면 파츠 분리
            if curr_min > prev_max + 50:  # 임계값 조정 가능
                part_size = (i - current_start) * 3
                if part_size >= 3:  # 최소 1개 삼각형
                    parts.append({
                        'start_index': current_start * 3,
                        'index_count': part_size,
                        'name': f'part_{self._part_counter}'
                    })
                    self._part_counter += 1
                current_start = i
        # 3. 마지막 파츠 처리
        if current_start < len(triangles):
            part_size = (len(triangles) - current_start) * 3
            if part_size >= 3:
                parts.append({
                    'start_index': current_start * 3,
                    'index_count': part_size,
                    'name': f'part_{self._part_counter}'
                })
                self._part_counter += 1
        return parts

    # 버텍스 범위 기반 파츠 분리
    def _find_parts_by_vertex_range(self, indices):
        parts = []
        if len(indices) < 3:
            return parts
        # 1. 인덱스를 삼각형 단위로 분할
        triangles = [indices[i:i+3] for i in range(0, len(indices), 3)]
        current_start = 0
        current_min = min(triangles[0])
        current_max = max(triangles[0])
        # 2. 삼각형 순회하며 버텍스 범위 변화 탐지
        for i in range(1, len(triangles)):
            tri_min = min(triangles[i])
            tri_max = max(triangles[i])
            # 2-1. 범위를 크게 벗어나면 새 파츠 시작
            if (tri_min < current_min - 20 or tri_max > current_max + 100):
                part_size = (i - current_start) * 3
                if part_size >= 3:
                    parts.append({
                        'start_index': current_start * 3,
                        'index_count': part_size,
                        'name': f'part_{self._part_counter}'
                    })
                    self._part_counter += 1
                current_start = i
                current_min = tri_min
                current_max = tri_max
            else:
                # 2-2. 범위 내면 현재 범위 갱신
                current_min = min(current_min, tri_min)
                current_max = max(current_max, tri_max)
        # 3. 마지막 파츠 처리
        if current_start < len(triangles):
            part_size = (len(triangles) - current_start) * 3
            if part_size >= 3:
                parts.append({
                    'start_index': current_start * 3,
                    'index_count': part_size,
                    'name': f'part_{self._part_counter}'
                })
                self._part_counter += 1
        return parts

    # 인덱스 리셋 패턴 기반 파츠 분리
    def _find_parts_by_reset_pattern(self, indices):
        # 1. 결과 저장 리스트 초기화
        parts = []
        # 2. 인덱스가 3개 미만이면 바로 반환
        if len(indices) < 3:
            return parts
        # 3. 인덱스를 삼각형 단위로 분할
        triangles = [indices[i:i+3] for i in range(0, len(indices), 3)]
        current_start = 0
        # 4. 삼각형 순회하며 리셋 패턴(0에 가까운 값) 감지
        for i in range(1, len(triangles)):
            # 4-1. 이전 삼각형의 최대값이 크고, 현재 삼각형의 최소값이 10 이하이면 리셋으로 간주
            if min(triangles[i]) < 10 and max(triangles[i-1]) > 100:
                part_size = (i - current_start) * 3
                # 4-2. 최소 1개 삼각형 이상일 때만 파츠로 추가
                if part_size >= 3:
                    parts.append({
                        'start_index': current_start * 3,
                        'index_count': part_size,
                        'name': f'part_{self._part_counter}'
                    })
                    self._part_counter += 1
                # 4-3. 새 파츠 시작점 갱신
                current_start = i
        # 5. 마지막 파츠 처리
        if current_start < len(triangles):
            part_size = (len(triangles) - current_start) * 3
            if part_size >= 3:
                parts.append({
                    'start_index': current_start * 3,
                    'index_count': part_size,
                    'name': f'part_{self._part_counter}'
                })
                self._part_counter += 1
        # 6. 결과 반환
        return parts

    # 균등 분할(폴백) 파츠 분리
    def _find_parts_by_equal_split(self, indices):
        # 1. 결과 저장 리스트 초기화
        parts = []
        # 2. 인덱스가 3개 미만이면 바로 반환
        if len(indices) < 3:
            return parts
        # 3. 삼각형 개수 계산
        triangle_count = len(indices) // 3
        # 4. 삼각형 개수에 따라 파츠 개수 결정 (100~1000개당 1개, 최대 20개)
        if triangle_count < 100:
            part_count = 1
        elif triangle_count < 1000:
            part_count = triangle_count // 100
        else:
            part_count = min(20, triangle_count // 500)
        # 5. 파츠별 삼각형 개수와 나머지 계산
        triangles_per_part = triangle_count // part_count
        remainder = triangle_count % part_count
        current_start = 0
        # 6. 파츠 개수만큼 반복하며 파츠 생성
        for i in range(part_count):
            # 6-1. 나머지 삼각형을 앞쪽 파츠에 분배
            current_size = triangles_per_part + (1 if i < remainder else 0)
            index_count = current_size * 3
            # 6-2. 인덱스 개수가 0보다 크면 파츠로 추가
            if index_count > 0:
                parts.append({
                    'start_index': current_start * 3,
                    'index_count': index_count,
                    'name': f'part_{self._part_counter}'
                })
                self._part_counter += 1
                current_start += current_size
        # 7. 결과 반환
        return parts

    # 여러 분리 방법 중 최적의 파츠 분리 선택
    def _select_best_partitioning(self, parts1, parts2, parts3, parts4, indices):
        # 1. 각 분리 방법과 이름을 후보 리스트로 준비
        candidates = [
            (parts1, "Discontinuity"),
            (parts2, "Range"),
            (parts3, "Reset"),
            (parts4, "Equal Split")
        ]
        # 2. 최적의 파츠와 점수, 방법명 초기화
        best_parts = []
        best_score = -1
        best_method = ""
        # 3. 각 분리 방법별로 평가
        for parts, method in candidates:
            if not parts:
                continue
            # 3-1. 파츠 분리 품질 점수 계산
            score = self._evaluate_partitioning(parts, indices)
            log_debug(bpy.context, f"{method} 방법: {len(parts)}개 파츠, 점수: {score:.2f}")
            # 3-2. 점수가 더 높으면 최적 후보로 갱신
            if score > best_score:
                best_score = score
                best_parts = parts
                best_method = method
        # 4. 모든 방법이 실패하면 전체를 하나의 파츠로 처리
        if not best_parts:
            best_parts = [{
                'start_index': 0,
                'index_count': len(indices),
                'name': 'Complete_IB_Part'
            }]
            best_method = "Fallback"
        # 5. 최종 선택된 방법 로그 출력
        log_debug(bpy.context, f"선택된 방법: {best_method}")
        # 6. 최적의 파츠 리스트 반환
        return best_parts

    # 파츠 분리 품질 평가
    def _evaluate_partitioning(self, parts, indices):
        # 1. 파츠가 없으면 0점 반환
        if not parts:
            return 0
        # 2. 점수 변수 초기화
        score = 0
        # 3. 파츠 수가 적절한지 평가 (2~20개면 가산점, 1개면 감점, 20개 초과면 감점)
        part_count = len(parts)
        if 2 <= part_count <= 20:
            score += 10
        elif part_count == 1:
            score -= 5
        elif part_count > 20:
            score -= part_count * 0.5
        # 4. 파츠 크기 일관성 평가 (너무 작은 파츠 감점, 평균의 10% 이상이면 가산점)
        sizes = [part['index_count'] for part in parts]
        avg_size = sum(sizes) / len(sizes)
        for size in sizes:
            if size < 9:  # 3개 미만 삼각형
                score -= 2
            elif size > avg_size * 0.1:
                score += 1
        # 5. 전체 인덱스가 모두 커버되는지 확인 (완전 커버면 가산점)
        total_covered = sum(part['index_count'] for part in parts)
        if total_covered == len(indices):
            score += 5
        # 6. 최종 점수 반환
        return score

    # 모든 인덱스가 파츠에 포함되도록 보장
    def _ensure_complete_coverage(self, parts, indices):
        # 1. 파츠나 인덱스가 없으면 전체를 하나의 파츠로 반환
        if not parts or not indices:
            return [{
                'start_index': 0,
                'index_count': len(indices),
                'name': 'part_1'
            }]
        # 2. 파츠를 시작 인덱스 순으로 정렬
        parts = sorted(parts, key=lambda x: x['start_index'])
        # 3. 각 파츠의 커버리지 범위 계산
        covered_ranges = []
        for part in parts:
            start = part['start_index']
            end = start + part['index_count']
            covered_ranges.append((start, end))
        # 4. 누락된 구간을 담을 리스트와 전체 인덱스 수 준비
        missing_parts = []
        total_indices = len(indices)
        # 5. 남은 파츠 카운터 초기화
        remaining_counter = 1
        # 6. 첫 번째 파츠 이전에 누락된 부분이 있으면 추가
        if parts[0]['start_index'] > 0:
            missing_parts.append({
                'start_index': 0,
                'index_count': parts[0]['start_index'],
                'name': f'remaining_part_{remaining_counter}'
            })
            remaining_counter += 1
        # 7. 파츠 사이의 누락 구간 탐지 및 추가
        for i in range(len(parts) - 1):
            current_end = parts[i]['start_index'] + parts[i]['index_count']
            next_start = parts[i + 1]['start_index']
            if current_end < next_start:
                gap_size = next_start - current_end
                if gap_size >= 3:  # 최소 1개 삼각형
                    missing_parts.append({
                        'start_index': current_end,
                        'index_count': gap_size,
                        'name': f'remaining_part_{remaining_counter}'
                    })
                    remaining_counter += 1
        # 8. 마지막 파츠 이후에 누락된 부분이 있으면 추가
        last_end = parts[-1]['start_index'] + parts[-1]['index_count']
        if last_end < total_indices:
            missing_parts.append({
                'start_index': last_end,
                'index_count': total_indices - last_end,
                'name': f'remaining_part_{remaining_counter}'
            })
        # 9. 원본 파츠와 누락된 파츠 병합 및 정렬
        complete_parts = parts + missing_parts
        complete_parts = sorted(complete_parts, key=lambda x: x['start_index'])
        # 10. 누락된 구간이 있으면 디버그 로그 출력
        if missing_parts:
            log_debug(bpy.context, f"누락된 {len(missing_parts)}개 구간을 추가로 감지했습니다:")
            for part in missing_parts:
                log_debug(bpy.context, f"  {part['name']}: 시작={part['start_index']}, 개수={part['index_count']}")
        # 11. 최종 파츠 리스트 반환
        return complete_parts

    # INI에서 DrawIndexed 정보 추출
    def extract_drawindexed_all(self, ini_path, section_map, section):
        log_debug(bpy.context, f"[extract_drawindexed_all] section={section}")

        drawindexed_map = []
        seen = set()
        last_comment = None

        def extract_drawindexed(lines):
            nonlocal seen, last_comment
            results = []
            
            # 1단계: 모든 DrawIndexed와 해당 주석을 수집
            temp_results = []
            comment_stack = []  # IF문의 중첩 레벨별 주석을 저장
            if_depth = 0
            
            for i, line in enumerate(lines):
                stripped_line = line.strip()
                
                if stripped_line.startswith(';'):
                    comment_match = re.match(r";\s*([^\(]+)", stripped_line)
                    if comment_match:
                        new_comment = comment_match.group(1).strip()
                        # 현재 IF 블록 레벨의 주석 업데이트
                        if if_depth > 0:
                            # IF 블록 내부의 주석
                            if len(comment_stack) > if_depth - 1:
                                comment_stack[if_depth - 1] = new_comment
                            else:
                                comment_stack.append(new_comment)
                        else:
                            # IF 블록 외부의 주석 - 다음 IF 블록을 위해 저장
                            comment_stack = [new_comment]
                
                elif stripped_line.lower().startswith("if"):
                    if_depth += 1
                    # 새로운 IF 블록 시작 - 주석 스택 확장
                    if len(comment_stack) < if_depth:
                        comment_stack.append(None)
                    
                elif stripped_line.lower().startswith("endif"):
                    if_depth -= 1
                    # IF 블록 종료 - 해당 레벨의 주석 제거
                    if len(comment_stack) > if_depth:
                        comment_stack = comment_stack[:if_depth] if if_depth > 0 else []
                
                elif stripped_line.lower().startswith("drawindexed"):
                    parts = stripped_line.split('=', 1)
                    if len(parts) == 2:
                        value = parts[1].strip()
                        if re.match(r"^\d+,\s*\d+,\s*0$", value) and value not in seen:
                            seen.add(value)
                            numbers = list(map(int, re.findall(r'\d+', value)))
                            if len(numbers) >= 2:
                                # 가장 구체적인 주석 선택 (가장 안쪽 블록의 주석)
                                effective_comment = None
                                for j in range(len(comment_stack) - 1, -1, -1):
                                    if comment_stack[j]:
                                        effective_comment = comment_stack[j]
                                        break
                                
                                temp_results.append({
                                    'start_index': numbers[1],
                                    'index_count': numbers[0],
                                    'comment': effective_comment,
                                    'if_depth': if_depth
                                })
                
                # 다른 구문이 나오면 현재 레벨의 주석 리셋 (IF 블록 외부에서만)
                elif if_depth == 0 and not stripped_line.startswith(';') and stripped_line:
                    comment_stack = []
            
            # 2단계: 같은 주석을 가진 항목들을 그룹화하고 네이밍
            comment_groups = {}
            for item in temp_results:
                comment = item['comment']
                if comment:
                    if comment not in comment_groups:
                        comment_groups[comment] = []
                    comment_groups[comment].append(item)
            
            # 3단계: 최종 결과 생성
            for item in temp_results:
                if item['comment']:
                    comment = item['comment']
                    group = comment_groups[comment]
                    if len(group) == 1:
                        # 단일 DrawIndexed면 넘버링 없이
                        part_name = comment
                    else:
                        # 여러 DrawIndexed면 넘버링 추가
                        index = group.index(item) + 1
                        part_name = f"{comment}_{index}"
                else:
                    # 주석이 없는 경우
                    part_name = f"part_{self._global_part_counter}"
                    self._global_part_counter += 1
                
                results.append({
                    'start_index': item['start_index'],
                    'index_count': item['index_count'],
                    'name': part_name
                })
            
            return results

        drawindexed_map.extend(extract_drawindexed(section_map.get(section, [])))

        for line in section_map.get(section, []):
            if line.lower().startswith("run"):
                parts = line.split('=', 1)
                if len(parts) == 2:
                    target = parts[1].strip()
                    if target in section_map:
                        drawindexed_map.extend(extract_drawindexed(section_map[target]))
        return drawindexed_map

    # INI에서 IB 파일 경로 찾기
    def find_ib_file(self, ini_path, section_map, section):
        log_debug(bpy.context, f"[find_ib_file] section={section}")

        # 1. 반환할 IB 파일 경로 변수 초기화
        ib_path = None

        # 2. 선택된 섹션의 각 줄을 순회하며 IB 파일 경로 탐색
        for line in section_map.get(section, []):
            # 2-1. ib=로 시작하는 줄을 찾음
            if line.lower().startswith("ib"):
                parts = line.split('=', 1)
                # 2-2. = 기준으로 분리하여 파일명 추출
                if len(parts) == 2:
                    ib_filename = parts[1].strip()
                    # 2-3. INI 파일과 같은 폴더에서 IB 파일 경로 생성
                    ini_dir = os.path.dirname(ini_path)
                    ib_path = os.path.join(ini_dir, ib_filename)
                    # 2-4. 해당 경로에 파일이 존재하면 바로 반환
                    if os.path.exists(ib_path):
                        return ib_path

        # 3. 찾지 못하면 None 반환
        return None

    # INI와 IB 파츠 정보 병합
    def merge_parts_info(self, ini_parts, ib_parts):
        log_debug(bpy.context, f"[merge_parts_info] ini_parts={len(ini_parts)}, ib_parts={len(ib_parts)}")

        # 1. 병합 결과를 저장할 리스트 초기화
        merged_parts = []

        # 2. INI 파일의 파츠를 먼저 추가 (우선순위)
        for part in ini_parts:
            merged_parts.append(part)

        log_debug(bpy.context, f"INI에서 {len(ini_parts)}개 파츠 추가됨")

        # 3. IB 파일의 파츠 중 INI와 겹치지 않는 것만 추가
        added_ib_parts = 0
        for ib_part in ib_parts:
            ib_start = ib_part['start_index']
            ib_end = ib_start + ib_part['index_count']

            # 3-1. INI 파츠와 50% 이상 겹치는지 확인
            has_significant_overlap = False
            for ini_part in ini_parts:
                ini_start = ini_part['start_index']
                ini_end = ini_start + ini_part['index_count']

                # 3-2. 겹치는 범위 계산
                overlap_start = max(ib_start, ini_start)
                overlap_end = min(ib_end, ini_end)
                overlap_size = max(0, overlap_end - overlap_start)

                # 3-3. 겹치는 부분이 IB 파츠의 50% 이상이면 중복으로 간주
                if overlap_size > ib_part['index_count'] * 0.5:
                    has_significant_overlap = True
                    break

            # 3-4. 중복이 없으면 IB 파츠를 추가
            if not has_significant_overlap:
                # IB 파일에서 감지된 파츠는 part_ 넘버링 유지
                merged_parts.append(ib_part)
                added_ib_parts += 1

        log_debug(bpy.context, f"IB에서 추가로 {added_ib_parts}개 파츠 추가됨")

        # 4. 파츠를 시작 인덱스 순으로 정렬
        merged_parts.sort(key=lambda x: x['start_index'])

        # 5. 겹치는 파츠를 정리하여 최종 결과 생성
        cleaned_parts = self._clean_overlapping_parts(merged_parts)

        log_debug(bpy.context, f"최종 {len(cleaned_parts)}개 파츠")
        # 6. 최종 병합된 파츠 리스트 반환
        return cleaned_parts

    # 겹치는 파츠 정리
    def _clean_overlapping_parts(self, parts):
        # 1. 입력 파츠가 없으면 그대로 반환
        if not parts:
            return parts

        # 2. 정리된 파츠를 저장할 리스트와 현재 파츠 초기화
        cleaned = []
        current_part = parts[0].copy()

        # 3. 파츠를 순서대로 비교하며 겹침 처리
        for next_part in parts[1:]:
            current_end = current_part['start_index'] + current_part['index_count']
            next_start = next_part['start_index']

            # 3-1. 겹치지 않으면 현재 파츠를 추가하고 다음 파츠로 이동
            if current_end <= next_start:
                cleaned.append(current_part)
                current_part = next_part.copy()
            else:
                # 3-2. 겹치는 경우 병합 또는 조정
                # INI 파츠(Additional_로 시작하지 않는)를 우선
                if not current_part['name'].startswith('Additional_'):
                    # 3-2-1. 현재 파츠가 INI 파츠면 그대로 유지
                    continue
                elif not next_part['name'].startswith('Additional_'):
                    # 3-2-2. 다음 파츠가 INI 파츠면 교체
                    cleaned.append(current_part)
                    current_part = next_part.copy()
                else:
                    # 3-2-3. 둘 다 IB 파츠면 더 큰 파츠로 교체
                    if next_part['index_count'] > current_part['index_count']:
                        current_part = next_part.copy()

        # 4. 마지막 파츠 추가
        cleaned.append(current_part)

        # 5. 정리된 파츠 리스트 반환
        return cleaned

    # 분리된 파츠를 제외한 잔여 파츠 생성
    def _create_remaining_part(self, context):
        log_debug(context, "[_create_remaining_part] called")

        # 1. 모든 오브젝트 선택 해제 후 원본 오브젝트만 선택
        bpy.ops.object.select_all(action='DESELECT')
        self._original_obj.select_set(True)
        context.view_layer.objects.active = self._original_obj

        # 2. 원본 오브젝트를 OBJECT 모드로 전환
        bpy.ops.object.mode_set(mode='OBJECT')
        mesh = self._original_obj.data

        # 3. 분리된 파츠의 모든 인덱스를 수집할 집합 준비
        all_separated_indices = set()

        # 4. 인덱스 버퍼(삼각형만) 구성
        index_buffer = []
        for poly in mesh.polygons:
            if len(poly.vertices) == 3:
                index_buffer.extend(poly.vertices)

        # 5. 각 파츠의 인덱스 범위를 집합에 추가
        for part_info in self._parts_map:
            start_index = part_info['start_index']
            index_count = part_info['index_count']
            if start_index + index_count <= len(index_buffer):
                part_indices = set(index_buffer[start_index:start_index + index_count])
                all_separated_indices.update(part_indices)

        # 6. EDIT 모드로 전환 후 분리된 파츠에 해당하는 면 선택
        bpy.ops.object.mode_set(mode='EDIT')
        bm = bmesh.from_edit_mesh(mesh)
        bm.faces.ensure_lookup_table()
        bm.verts.ensure_lookup_table()

        # 7. 분리된 파츠의 버텍스 인덱스를 포함하는 면 선택
        separated_face_count = 0
        for f in bm.faces:
            f.select = any(v.index in all_separated_indices for v in f.verts)
            if f.select:
                separated_face_count += 1

        bmesh.update_edit_mesh(mesh)

        log_debug(bpy.context, f"원본에서 {separated_face_count}개 면을 제거하여 잔여 파츠 생성")

        # 8. 분리된 파츠가 있으면 해당 면 삭제
        if separated_face_count > 0:
            bpy.ops.mesh.delete(type='FACE')

        bpy.ops.object.mode_set(mode='OBJECT')

        # 9. 잔여 파츠가 남아 있으면 이름 부여 및 컬렉션 이동
        remaining_face_count = len(mesh.polygons)
        if remaining_face_count > 0:
            self._original_obj.name = "remaining_original"
            self._new_collection.objects.link(self._original_obj)
            self._scene_collection.objects.unlink(self._original_obj)
            log_debug(bpy.context, f"잔여 파츠: {remaining_face_count}개 면 보존됨")
        else:
            # 10. 잔여 부분이 없으면 원본 삭제
            bpy.ops.object.delete()
            log_debug(bpy.context, "모든 파츠가 분리되어 잔여 부분 없음")

    # 모달 오퍼레이터 실행 진입점
    def invoke(self, context, event):
        log_debug(context, "[invoke] called")
        props = context.scene.ini_resource_props
        ini_path = props.ini_path
        resource = props.resource

        # 1. INI 파일과 Resource가 선택되었는지 확인
        if not ini_path or not resource:
            self.report({'ERROR'}, "INI 파일과 Resource를 선택해야 합니다.")
            return {'CANCELLED'}

        # 2. INI 파일을 파싱하여 섹션별로 저장
        section_map = {}
        log_debug(context, f"[invoke] INI 파일 파싱 시작: {ini_path}")
        with open(ini_path, encoding='utf-8') as f:
            current_section = None
            for line in f:
                line = line.strip()
                if line.startswith('[') and line.endswith(']'):
                    current_section = line[1:-1]
                    section_map[current_section] = []
                elif current_section:
                    section_map[current_section].append(line)
        log_debug(context, f"[invoke] INI 파싱 완료, 섹션 수: {len(section_map)}")

        # 3. 전역 파츠 카운터 초기화
        self._global_part_counter = 1

        # 4. TextureOverride 섹션 내에서 resource를 사용하는 구간을 모두 찾음
        target_ranges = self.find_sections_using_resource(section_map, resource)

        # 5. 각 구간별로 DrawIndexed 파츠 정보와 IB 파일 경로 추출
        ini_parts = []
        ib_path = None
        for sec, start, end in target_ranges:
            lines = section_map[sec][start:end]
            ini_parts.extend(self.extract_drawindexed_all(ini_path, {sec: lines}, sec))
            if ib_path is None:
                ib_path = self.find_ib_file(ini_path, {sec: lines}, sec)

        # 6. IB 파일이 있으면 파츠 정보 추출
        ib_parts = []
        if ib_path and os.path.exists(ib_path):
            log_debug(context, f"IB 파일 발견: {ib_path}")
            ib_parts = self.read_ib_file(ib_path)
            log_debug(context, f"IB 파일에서 {len(ib_parts)}개 파츠 발견")
        else:
            log_debug(context, "IB 파일을 찾을 수 없습니다. INI 파일의 정보만 사용합니다.")

        # 7. INI와 IB 파츠 정보를 병합
        self._parts_map = self.merge_parts_info(ini_parts, ib_parts)

        # 8. 분리할 파츠가 없으면 에러 리포트
        if not self._parts_map:
            self.report({'ERROR'}, "분리할 파츠가 없습니다.")
            return {'CANCELLED'}

        # 9. 분리할 파츠 정보 로그 출력
        log_debug(context, f"총 {len(self._parts_map)}개 파츠를 분리합니다:")
        for i, part in enumerate(self._parts_map):
            log_debug(context, f"  {i+1}. {part['name']}: 시작={part['start_index']}, 개수={part['index_count']}")

        # 10. 활성 메시 오브젝트 확인 및 저장
        self._original_obj = context.active_object
        if not self._original_obj or self._original_obj.type != 'MESH':
            self.report({'ERROR'}, "메시 오브젝트를 선택하세요.")
            return {'CANCELLED'}

        # 11. 오브젝트의 컬렉션 정보 저장
        self._original_collections = list(self._original_obj.users_collection)
        self._scene_collection = context.scene.collection

        # 12. 오브젝트가 씬 컬렉션에 없으면 추가
        if self._scene_collection not in self._original_collections:
            for col in self._original_collections:
                col.objects.unlink(self._original_obj)
            self._scene_collection.objects.link(self._original_obj)

        # 13. 새 컬렉션 생성 및 씬에 추가
        self._new_collection = bpy.data.collections.new(self._original_obj.name)
        self._scene_collection.children.link(self._new_collection)

        # 14. 전체 오브젝트 선택 해제 및 타이머 등록
        bpy.ops.object.select_all(action='DESELECT')
        wm = context.window_manager
        self._timer = wm.event_timer_add(0.1, window=context.window)
        wm.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    # 모달 오퍼레이터의 반복 처리 (타이머 기반)
    def modal(self, context, event):
        if event.type == 'TIMER':
            # 1. 모든 파츠 분리가 끝났는지 확인
            if self._index >= len(self._parts_map):
                # 2. 잔여 파츠 생성
                self._create_remaining_part(context)

                # 3. 새 컬렉션을 원래 컬렉션에 연결/해제
                for col in self._original_collections:
                    if col == self._scene_collection:
                        continue
                    if self._new_collection.name not in col.children:
                        col.children.link(self._new_collection)
                    if self._new_collection.name in self._scene_collection.children:
                        self._scene_collection.children.unlink(self._new_collection)

                # 4. 타이머 해제 및 완료 메시지
                context.window_manager.event_timer_remove(self._timer)
                self.report({'INFO'}, f"{len(self._parts_map)}개의 파츠 분리 완료 + 잔여 파츠 보존")
                return {'FINISHED'}

            # 5. 현재 분리할 파츠 정보 준비
            part_info = self._parts_map[self._index]
            log_debug(context, f"진행도: {self._index + 1}/{len(self._parts_map)} - {part_info['name']}")

            index_count = part_info['index_count']
            start_index = part_info['start_index']
            name = part_info['name']

            # 6. 원본 오브젝트 복제
            self._original_obj.select_set(True)
            context.view_layer.objects.active = self._original_obj
            bpy.ops.object.duplicate()
            dup_obj = context.active_object
            mesh = dup_obj.data

            # 7. 인덱스 버퍼 생성 (삼각형만)
            bpy.ops.object.mode_set(mode='OBJECT')
            index_buffer = []
            poly_type_count = {}
            for poly in mesh.polygons:
                poly_type_count[len(poly.vertices)] = poly_type_count.get(len(poly.vertices), 0) + 1
                if len(poly.vertices) == 3:
                    index_buffer.extend(poly.vertices)

            log_debug(context, f"[분리] 파츠: {name}, start_index={start_index}, index_count={index_count}, index_buffer_len={len(index_buffer)}")
            log_debug(context, f"[분리] poly_type_count: {poly_type_count}")
            slice_start = start_index
            slice_end = start_index + index_count
            log_debug(context, f"[분리] index_buffer[{slice_start}:{slice_end}] (len={slice_end-slice_start})")
            log_debug(context, f"[분리] index_buffer slice head: {index_buffer[slice_start:slice_start+10] if slice_end > slice_start else []}")
            log_debug(context, f"[분리] index_buffer slice tail: {index_buffer[max(slice_end-10,slice_start):slice_end] if slice_end > slice_start else []}")

            # 8. 분리할 인덱스 집합 생성
            selected_indices = set(index_buffer[start_index:start_index + index_count])
            log_debug(context, f"[분리] selected_indices 샘플: {list(selected_indices)[:10]} ... (총 {len(selected_indices)}개)")

            # 9. EDIT 모드에서 분리할 face 선택
            bpy.ops.object.mode_set(mode='EDIT')
            bm = bmesh.from_edit_mesh(mesh)
            bm.faces.ensure_lookup_table()
            bm.verts.ensure_lookup_table()

            face_select_count = 0
            for f in bm.faces:
                f.select = any(v.index in selected_indices for v in f.verts)
                if f.select:
                    face_select_count += 1
            log_debug(context, f"[분리] 선택된 face 개수: {face_select_count} / 전체 {len(bm.faces)}")

            bmesh.update_edit_mesh(mesh)
            selected_face_count = sum(1 for f in bm.faces if f.select)

            # 10. 선택된 face가 없으면 건너뜀
            if selected_face_count == 0:
                log_debug(context, f"[분리] 선택된 face 없음, 파츠 건너뜀")
                bpy.ops.object.mode_set(mode='OBJECT')
                bpy.data.objects.remove(dup_obj)
                self._index += 1
                return {'PASS_THROUGH'}

            # 11. 선택된 face를 분리
            bpy.ops.mesh.separate(type='SELECTED')
            bpy.ops.object.mode_set(mode='OBJECT')

            # 12. 분리된 오브젝트를 새 컬렉션으로 이동 및 이름 지정
            for obj in context.selected_objects:
                if obj != dup_obj:
                    self._new_collection.objects.link(obj)
                    self._scene_collection.objects.unlink(obj)
                    obj.name = name
                    log_debug(context, f"[분리] 분리된 오브젝트: {obj.name}, faces: {len(obj.data.polygons)}")

            # 13. 복제 오브젝트 삭제 및 인덱스 증가
            bpy.ops.object.select_all(action='DESELECT')
            dup_obj.select_set(True)
            bpy.ops.object.delete()
            self._index += 1
        return {'PASS_THROUGH'}

# INI 파츠 분리 패널 UI
class PT_IBResourceSelector(Panel):
    bl_label = "INI 파츠 분리"
    bl_idname = "VIEW3D_PT_ib_resource_selector"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = '파츠 분리'


    def draw(self, context):
        layout = self.layout
        props = context.scene.ini_resource_props

        # 1. INI 파일 열기 버튼
        layout.operator("wm.select_ini_file_panel", text="INI 파일 열기")

        # 2. INI 파일 경로와 리소스 선택 표시
        if props.ini_path:
            layout.label(text=f"INI: {props.ini_path.split('/')[-1]}")
            layout.prop(props, "resource")

        # 3. 디버그 모드 체크박스
        layout.prop(props, "debug_mode")

        # 4. 파츠 분리 버튼 활성화 조건
        obj = context.active_object
        enable_button = (
            obj is not None and obj.type == 'MESH'
            and bool(props.ini_path.strip())
            and bool(props.resource.strip())
        )

        # 5. 파츠 분리 버튼
        row = layout.row()
        row.enabled = enable_button
        row.operator("object.separate_parts_from_ini_modal", text="파츠 분리")

# DrawIndexed 디버그 패널 UI
class PT_DrawIndexedDebugPanel(Panel):
    bl_label = "DrawIndexed"
    bl_idname = "VIEW3D_PT_drawindexed_panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = '파츠 분리'
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout
        props = context.scene.ini_resource_props
        # 1. drawIndexed 값 입력 박스
        box = layout.box()
        box.label(text="drawIndexed = ")
        row = box.row(align=True)
        # 2. count 입력
        col_count = row.column()
        col_count.scale_x = 2.0
        col_count.prop(props, "drawindexed_count", text="", slider=False)
        # 3. 첫 번째 쉼표
        col_comma1 = row.column()
        col_comma1.scale_x = 0.15
        col_comma1.label(text=",", icon='BLANK1')
        # 4. start 입력
        col_start = row.column()
        col_start.scale_x = 2.0
        col_start.prop(props, "drawindexed_start", text="", slider=False)
        # 5. 두 번째 쉼표
        col_comma2 = row.column()
        col_comma2.scale_x = 0.15
        col_comma2.label(text=",", icon='BLANK1')
        # 6. 0 고정값
        col_zero = row.column()
        col_zero.scale_x = 0.2
        col_zero.label(text="0")
        # 7. 매쉬 선택/추출 버튼
        box.operator("object.select_drawindexed_mesh", text="매쉬 선택")
        box.operator("object.get_drawindexed_from_selection", text="drawIndexed 추출")
    
# 선택된 face로부터 DrawIndexed 값 추출 오퍼레이터
class OT_GetDrawIndexedFromSelection(Operator):
    bl_idname = "object.get_drawindexed_from_selection"
    bl_label = "선택된 매쉬로 DrawIndexed 값 추출"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        props = context.scene.ini_resource_props
        obj = context.active_object
        # 1. 메시 오브젝트 선택 확인
        if not obj or obj.type != 'MESH':
            self.report({'ERROR'}, "메시 오브젝트를 선택하세요.")
            return {'CANCELLED'}

        mesh = obj.data
        # 2. EDIT 모드 전환 및 bmesh 준비
        bpy.ops.object.mode_set(mode='EDIT')
        bm = bmesh.from_edit_mesh(mesh)
        bm.faces.ensure_lookup_table()
        bm.verts.ensure_lookup_table()

        # 3. 인덱스 버퍼 추출 (삼각형만)
        index_buffer = []
        for poly in mesh.polygons:
            if len(poly.vertices) == 3:
                index_buffer.extend(poly.vertices)

        # 4. 선택된 face 확인
        selected_faces = [f for f in bm.faces if f.select]
        if not selected_faces:
            self.report({'ERROR'}, "선택된 face가 없습니다.")
            return {'CANCELLED'}

        # 5. 선택된 face의 버텍스 인덱스 추출
        face_indices_list = []
        for f in selected_faces:
            for v in f.verts:
                face_indices_list.append(v.index)

        # 6. 선택된 face와 일치하는 삼각형 블록 찾기
        face_indices_set = set(face_indices_list)
        tris = [index_buffer[i:i+3] for i in range(0, len(index_buffer), 3)]
        selected_tri_indices = set(tuple(sorted([v.index for v in f.verts])) for f in selected_faces)

        tri_blocks = []
        for i, tri in enumerate(tris):
            if tuple(sorted(tri)) in selected_tri_indices:
                tri_blocks.append(i)

        # 7. 연속 구간으로 묶기
        if not tri_blocks:
            self.report({'ERROR'}, "선택된 face와 일치하는 삼각형을 index_buffer에서 찾지 못했습니다.")
            return {'CANCELLED'}

        block_ranges = []
        block_start = tri_blocks[0]
        prev = tri_blocks[0]
        for idx in tri_blocks[1:]:
            if idx == prev + 1:
                prev = idx
            else:
                block_ranges.append((block_start, prev))
                block_start = idx
                prev = idx
        block_ranges.append((block_start, prev))

        # 8. DrawIndexed 슬라이스 정보로 변환
        block_infos = []
        for start_tri, end_tri in block_ranges:
            start_idx = start_tri * 3
            count = (end_tri - start_tri + 1) * 3
            block_infos.append({'start': start_idx, 'count': count})

        # 9. 첫 번째 블록을 UI에 입력, 전체 블록 메시지 안내
        if block_infos:
            props.drawindexed_start = block_infos[0]['start']
            props.drawindexed_count = block_infos[0]['count']
            msg_lines = []
            for i, info in enumerate(block_infos):
                msg = f"DrawIndexed 블록 {i+1}: count={info['count']}, start={info['start']}"
                msg_lines.append(msg)
            self.report({'INFO'}, "선택된 face를 DrawIndexed로 변환 결과:\n" + "\n".join(msg_lines))
        else:
            self.report({'ERROR'}, "선택된 face를 DrawIndexed로 변환할 수 없습니다.")
            return {'CANCELLED'}
        return {'FINISHED'}

# DrawIndexed 값으로 face 선택 오퍼레이터
class OT_SelectDrawIndexedMesh(Operator):
    bl_idname = "object.select_drawindexed_mesh"
    bl_label = "DrawIndexed 매쉬 선택"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        props = context.scene.ini_resource_props
        start = props.drawindexed_start
        count = props.drawindexed_count
        obj = context.active_object
        # 1. 메시 오브젝트가 선택되었는지 확인
        if not obj or obj.type != 'MESH':
            self.report({'ERROR'}, "메시 오브젝트를 선택하세요.")
            return {'CANCELLED'}

        # 2. 메시 데이터 접근
        mesh = obj.data

        # 3. 인덱스 버퍼 추출 (삼각형만)
        index_buffer = []
        for poly in mesh.polygons:
            if len(poly.vertices) == 3:
                index_buffer.extend(poly.vertices)

        # 4. 입력 범위가 유효한지 확인
        if start < 0 or start + count > len(index_buffer):
            self.report({'ERROR'}, f"범위가 잘못되었습니다. (0~{len(index_buffer)})")
            return {'CANCELLED'}

        # 5. 선택할 인덱스 집합 생성
        selected_indices = set(index_buffer[start:start+count])

        # 6. EDIT 모드로 전환 및 bmesh 준비
        bpy.ops.object.mode_set(mode='EDIT')
        bm = bmesh.from_edit_mesh(mesh)
        bm.faces.ensure_lookup_table()
        bm.verts.ensure_lookup_table()

        # 7. face 순회하며 선택 인덱스 포함 여부로 선택 처리
        select_count = 0
        face_indices = []
        for f in bm.faces:
            if any(v.index in selected_indices for v in f.verts):
                f.select = True
                select_count += 1
                face_indices.extend([v.index for v in f.verts])
            else:
                f.select = False
        bmesh.update_edit_mesh(mesh)

        # 8. 디버그: index_buffer 슬라이스와 실제 선택된 face의 인덱스 집합 비교
        face_indices_set = set(face_indices)
        only_selected = selected_indices.issubset(face_indices_set) and face_indices_set.issubset(selected_indices)
        if not only_selected:
            self.report({'WARNING'}, f"[디버그] index_buffer[{start}:{start+count}]의 인덱스와 실제 선택된 face의 인덱스가 완전히 일치하지 않습니다.\nindex_buffer 슬라이스 인덱스 수: {len(selected_indices)}, 선택된 face의 인덱스 수: {len(face_indices_set)}")

        # 9. 최종 선택 결과 리포트
        self.report({'INFO'}, f"{select_count}개 face 선택 완료")
        return {'FINISHED'}


# Blender에 등록할 클래스 목록
classes = (
    INIResourceProperties,
    OT_SelectIniFile,
    OT_SeparatePartsFromIniModal,
    PT_IBResourceSelector,
    PT_DrawIndexedDebugPanel,
    OT_SelectDrawIndexedMesh,
    OT_GetDrawIndexedFromSelection,
)


# 애드온 등록 함수
def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.ini_resource_props = bpy.props.PointerProperty(type=INIResourceProperties)
    INIResourceProperties.ini_path = bpy.props.StringProperty(name="INI 파일 경로", default="")
    INIResourceProperties.resource = bpy.props.EnumProperty(
        name="IB",
        items=lambda self, context: self.resource_items(context)
    )
    INIResourceProperties.debug_mode = bpy.props.BoolProperty(
        name="디버그 모드",
        description="작업 단계별 디버그 로그를 출력합니다.",
        default=False
    )
    INIResourceProperties.drawindexed_start = bpy.props.IntProperty(
        name="DrawIndexed Start",
        description="DrawIndexed의 start_index",
        default=0,
        min=0,
        max=1000000000,
        step=1
    )
    INIResourceProperties.drawindexed_count = bpy.props.IntProperty(
        name="DrawIndexed Count",
        description="DrawIndexed의 index_count",
        default=0,
        min=0,
        max=1000000000,
        step=1
    )
    OT_SelectIniFile.filter_glob = bpy.props.StringProperty(default="*.ini", options={'HIDDEN'})

# 애드온 해제 함수
def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
    del bpy.types.Scene.ini_resource_props

# 스크립트 직접 실행 시 등록
if __name__ == "__main__":
    register()
