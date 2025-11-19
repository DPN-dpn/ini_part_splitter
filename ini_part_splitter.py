
bl_info = {
    "name": "INI 기반 파츠 분리",
    "author": "DPN",
    "version": (1, 6, 1),
    "blender": (2, 93, 0),
    "location": "3D 뷰 > 우측 UI 패널 > 파츠 분리",
    "description": "INI 파일을 기반으로 DrawIndexed 파츠를 오브젝트에서 분리합니다.",
    "category": "Object"
}


import bpy
import bmesh
import re
import os
import struct
from bpy.types import Operator, Panel, PropertyGroup
from bpy.props import StringProperty, EnumProperty, PointerProperty
from bpy_extras.io_utils import ImportHelper

# 디버그 로그 함수: 디버그 모드 체크 시 콘솔에 출력
def log_debug(context, msg):
    try:
        props = getattr(context.scene, 'ini_resource_props', None)
        if props and getattr(props, 'debug_mode', False):
            print(f"[DEBUG] {msg}")
    except Exception:
        pass





class INIResourceProperties(PropertyGroup):
    _resource_items = []

    def resource_items(self, context):
        return self._resource_items




class OT_SelectIniFile(Operator, ImportHelper):
    bl_idname = "wm.select_ini_file_panel"
    bl_label = "INI 파일 선택"
    # filter_glob은 execute 바깥에서 등록

    def execute(self, context):
        props = context.scene.ini_resource_props
        props.ini_path = self.filepath

        # INI 파일에서 TextureOverride 섹션 내 ib = 구문을 모두 찾아 Resource 목록 생성
        resource_set = set()
        current_section = None
        with open(self.filepath, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line.startswith('[') and line.endswith(']'):
                    current_section = line[1:-1]
                elif current_section and current_section.startswith("TextureOverride"):
                    if line.lower().startswith("ib"):
                        parts = line.split('=', 1)
                        if len(parts) == 2:
                            ib_name = parts[1].strip()
                            if ib_name:
                                resource_set.add(ib_name)

        resource_items = [(r, r, "") for r in sorted(resource_set)]
        if not resource_items:
            self.report({'ERROR'}, "TextureOverride 섹션에 ib = 구문이 없습니다.")
            return {'CANCELLED'}

        INIResourceProperties._resource_items = resource_items
        props.resource = resource_items[0][0]
        return {'FINISHED'}


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
                if l.lower().startswith("ib"):
                    parts = l.split('=', 1)
                    if len(parts) == 2:
                        ib_name = parts[1].strip()
                        # 이전 리소스가 타겟이면 구간 종료
                        if current_resource == resource_name and start_idx is not None:
                            result.append((sec, start_idx, idx))
                        # 새 리소스 시작
                        if ib_name == resource_name:
                            current_resource = ib_name
                            start_idx = idx
                        else:
                            current_resource = ib_name
                            start_idx = None
            # 섹션 끝까지 타겟 리소스면 마지막까지
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

    def read_ib_file(self, ib_path):
        log_debug(bpy.context, f"[read_ib_file] ib_path={ib_path}")
        """IB 파일을 읽어서 모든 파츠 정보를 추출합니다."""
        parts_info = []
        try:
            with open(ib_path, 'rb') as f:
                f.seek(0, 2)  # 파일 끝으로 이동
                file_size = f.tell()
                f.seek(0)  # 파일 시작으로 이동
                # 16비트 또는 32비트 인덱스 자동 감지
                if file_size % 4 == 0:
                    # 32비트 인덱스
                    index_size = 4
                    format_char = '<I'  # Little-endian 32비트 unsigned int
                elif file_size % 2 == 0:
                    # 16비트 인덱스
                    index_size = 2
                    format_char = '<H'  # Little-endian 16비트 unsigned short
                else:
                    log_debug(bpy.context, "알 수 없는 인덱스 형식입니다.")
                    return parts_info
                index_count = file_size // index_size
                log_debug(bpy.context, f"IB 파일 분석: {index_count}개 인덱스 ({index_size*8}비트)")
                # 인덱스 데이터를 읽습니다
                indices = []
                for i in range(index_count):
                    data = f.read(index_size)
                    if len(data) < index_size:
                        break
                    index = struct.unpack(format_char, data)[0]
                    indices.append(index)
                # 다양한 방법으로 파츠 분리 시도
                parts_info = self._analyze_ib_parts(indices)
        except Exception as e:
            log_debug(bpy.context, f"IB 파일 읽기 오류: {e}")
        return parts_info

    def _analyze_ib_parts(self, indices):
        log_debug(bpy.context, f"[_analyze_ib_parts] indices count={len(indices)}")
        """인덱스 패턴을 분석하여 파츠를 분리합니다."""
        parts_info = []
        if not indices or len(indices) < 3:
            return parts_info
        
        # 파츠 넘버링을 위한 전역 카운터 초기화
        self._part_counter = 1
        
        # 방법 1: 인덱스 불연속성 기반 분리
        parts_by_discontinuity = self._find_parts_by_discontinuity(indices)
        
        # 방법 2: 버텍스 범위 기반 분리  
        self._part_counter = 1  # 리셋
        parts_by_vertex_range = self._find_parts_by_vertex_range(indices)
        
        # 방법 3: 최대값 리셋 패턴 기반 분리
        self._part_counter = 1  # 리셋
        parts_by_reset = self._find_parts_by_reset_pattern(indices)
        
        # 방법 4: 전체를 균등하게 나누기 (폴백)
        self._part_counter = 1  # 리셋
        parts_by_equal_split = self._find_parts_by_equal_split(indices)
        
        # 가장 합리적인 분리 방법 선택
        best_parts = self._select_best_partitioning(
            parts_by_discontinuity, 
            parts_by_vertex_range, 
            parts_by_reset,
            parts_by_equal_split,
            indices
        )
        
        # 전체 인덱스가 커버되는지 확인하고 누락된 부분 추가
        best_parts = self._ensure_complete_coverage(best_parts, indices)
        
        return best_parts

    def _find_parts_by_discontinuity(self, indices):
        """인덱스 불연속성을 기반으로 파츠를 찾습니다."""
        parts = []
        if len(indices) < 3:
            return parts
            
        triangles = [indices[i:i+3] for i in range(0, len(indices), 3)]
        current_start = 0
        
        for i in range(1, len(triangles)):
            # 이전 삼각형의 최대 인덱스와 현재 삼각형의 최소 인덱스 비교
            prev_max = max(triangles[i-1])
            curr_min = min(triangles[i])
            
            # 큰 점프가 있으면 새로운 파츠 시작
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
        
        # 마지막 파츠
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

    def _find_parts_by_vertex_range(self, indices):
        """버텍스 범위 패턴을 기반으로 파츠를 찾습니다."""
        parts = []
        if len(indices) < 3:
            return parts
            
        triangles = [indices[i:i+3] for i in range(0, len(indices), 3)]
        current_start = 0
        current_min = min(triangles[0])
        current_max = max(triangles[0])
        
        for i in range(1, len(triangles)):
            tri_min = min(triangles[i])
            tri_max = max(triangles[i])
            
            # 현재 범위를 벗어나는 정도가 큰 경우 새 파츠
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
                # 범위 업데이트
                current_min = min(current_min, tri_min)
                current_max = max(current_max, tri_max)
        
        # 마지막 파츠
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

    def _find_parts_by_reset_pattern(self, indices):
        """인덱스 리셋 패턴을 기반으로 파츠를 찾습니다."""
        parts = []
        if len(indices) < 3:
            return parts
            
        triangles = [indices[i:i+3] for i in range(0, len(indices), 3)]
        current_start = 0
        
        for i in range(1, len(triangles)):
            # 0에 가까운 값으로 리셋되는 패턴 감지
            if min(triangles[i]) < 10 and max(triangles[i-1]) > 100:
                part_size = (i - current_start) * 3
                if part_size >= 3:
                    parts.append({
                        'start_index': current_start * 3,
                        'index_count': part_size,
                        'name': f'part_{self._part_counter}'
                    })
                    self._part_counter += 1
                current_start = i
        
        # 마지막 파츠
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

    def _find_parts_by_equal_split(self, indices):
        """전체를 균등하게 나누는 폴백 방법입니다."""
        parts = []
        if len(indices) < 3:
            return parts
        
        # 삼각형 수 계산
        triangle_count = len(indices) // 3
        
        # 적절한 파츠 수 결정 (100-1000 삼각형당 하나의 파츠)
        if triangle_count < 100:
            part_count = 1
        elif triangle_count < 1000:
            part_count = triangle_count // 100
        else:
            part_count = min(20, triangle_count // 500)  # 최대 20개 파츠
        
        triangles_per_part = triangle_count // part_count
        remainder = triangle_count % part_count
        
        current_start = 0
        for i in range(part_count):
            # 나머지를 앞쪽 파츠들에 분배
            current_size = triangles_per_part + (1 if i < remainder else 0)
            index_count = current_size * 3
            
            if index_count > 0:
                parts.append({
                    'start_index': current_start * 3,
                    'index_count': index_count,
                    'name': f'part_{self._part_counter}'
                })
                self._part_counter += 1
                current_start += current_size
        
        return parts

    def _select_best_partitioning(self, parts1, parts2, parts3, parts4, indices):
        """가장 적절한 파츠 분리 방법을 선택합니다."""
        candidates = [
            (parts1, "Discontinuity"),
            (parts2, "Range"),
            (parts3, "Reset"),
            (parts4, "Equal Split")
        ]
        
        best_parts = []
        best_score = -1
        best_method = ""
        
        for parts, method in candidates:
            if not parts:
                continue
            # 점수 계산: 적절한 파츠 수, 적절한 크기 분포
            score = self._evaluate_partitioning(parts, indices)
            log_debug(bpy.context, f"{method} 방법: {len(parts)}개 파츠, 점수: {score:.2f}")
            if score > best_score:
                best_score = score
                best_parts = parts
                best_method = method
        # 모든 방법이 실패하면 전체를 하나의 파츠로
        if not best_parts:
            best_parts = [{
                'start_index': 0,
                'index_count': len(indices),
                'name': 'Complete_IB_Part'
            }]
            best_method = "Fallback"
        log_debug(bpy.context, f"선택된 방법: {best_method}")
        return best_parts

    def _evaluate_partitioning(self, parts, indices):
        """파츠 분리의 품질을 평가합니다."""
        if not parts:
            return 0
        
        score = 0
        
        # 파츠 수가 적절한지 (너무 많거나 적으면 감점)
        part_count = len(parts)
        if 2 <= part_count <= 20:
            score += 10
        elif part_count == 1:
            score -= 5
        elif part_count > 20:
            score -= part_count * 0.5
        
        # 파츠 크기의 일관성 (너무 작은 파츠는 감점)
        sizes = [part['index_count'] for part in parts]
        avg_size = sum(sizes) / len(sizes)
        
        for size in sizes:
            if size < 9:  # 3개 미만 삼각형
                score -= 2
            elif size > avg_size * 0.1:  # 평균의 10% 이상
                score += 1
        
        # 전체 인덱스 커버리지 확인
        total_covered = sum(part['index_count'] for part in parts)
        if total_covered == len(indices):
            score += 5
        
        return score

    def _ensure_complete_coverage(self, parts, indices):
        """모든 인덱스가 파츠에 포함되도록 보장합니다."""
        if not parts or not indices:
            # 파츠가 없으면 전체를 하나의 파츠로
            return [{
                'start_index': 0,
                'index_count': len(indices),
                'name': 'part_1'
            }]
        
        # 파츠들을 시작 인덱스 순으로 정렬
        parts = sorted(parts, key=lambda x: x['start_index'])
        
        # 커버리지 확인 및 누락된 부분 찾기
        covered_ranges = []
        for part in parts:
            start = part['start_index']
            end = start + part['index_count']
            covered_ranges.append((start, end))
        
        # 누락된 구간 찾기
        missing_parts = []
        total_indices = len(indices)
        
        # 남은 파츠 카운터 초기화
        remaining_counter = 1
        
        # 첫 번째 파츠 이전의 누락 부분
        if parts[0]['start_index'] > 0:
            missing_parts.append({
                'start_index': 0,
                'index_count': parts[0]['start_index'],
                'name': f'remaining_part_{remaining_counter}'
            })
            remaining_counter += 1
        
        # 파츠 사이의 누락 부분
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
        
        # 마지막 파츠 이후의 누락 부분
        last_end = parts[-1]['start_index'] + parts[-1]['index_count']
        if last_end < total_indices:
            missing_parts.append({
                'start_index': last_end,
                'index_count': total_indices - last_end,
                'name': f'remaining_part_{remaining_counter}'
            })
        
        # 원본 파츠와 누락된 파츠 병합
        complete_parts = parts + missing_parts
        complete_parts = sorted(complete_parts, key=lambda x: x['start_index'])
        
        if missing_parts:
            log_debug(bpy.context, f"누락된 {len(missing_parts)}개 구간을 추가로 감지했습니다:")
            for part in missing_parts:
                log_debug(bpy.context, f"  {part['name']}: 시작={part['start_index']}, 개수={part['index_count']}")
        return complete_parts

    def extract_drawindexed_all(self, ini_path, section_map, section):
        log_debug(bpy.context, f"[extract_drawindexed_all] section={section}")
        """INI 파일에서 DrawIndexed 정보를 추출합니다."""
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

    def find_ib_file(self, ini_path, section_map, section):
        log_debug(bpy.context, f"[find_ib_file] section={section}")
        """INI 파일에서 IB 파일 경로를 찾습니다."""
        ib_path = None
        
        # 선택된 섹션에서 IB 파일 경로 찾기
        for line in section_map.get(section, []):
            if line.lower().startswith("ib"):
                parts = line.split('=', 1)
                if len(parts) == 2:
                    ib_filename = parts[1].strip()
                    # INI 파일과 같은 디렉토리에서 IB 파일 찾기
                    ini_dir = os.path.dirname(ini_path)
                    ib_path = os.path.join(ini_dir, ib_filename)
                    if os.path.exists(ib_path):
                        return ib_path
                    
        return None

    def merge_parts_info(self, ini_parts, ib_parts):
        log_debug(bpy.context, f"[merge_parts_info] ini_parts={len(ini_parts)}, ib_parts={len(ib_parts)}")
        """INI 파일의 파츠와 IB 파일의 파츠를 병합합니다."""
        merged_parts = []
        
        # INI 파일의 파츠를 먼저 추가 (우선순위)
        for part in ini_parts:
            merged_parts.append(part)
        
        log_debug(bpy.context, f"INI에서 {len(ini_parts)}개 파츠 추가됨")
        
        # IB 파일의 파츠 중 INI와 겹치지 않는 것들을 찾아 추가
        added_ib_parts = 0
        for ib_part in ib_parts:
            ib_start = ib_part['start_index']
            ib_end = ib_start + ib_part['index_count']
            
            # INI 파츠와 상당한 겹침이 있는지 확인
            has_significant_overlap = False
            for ini_part in ini_parts:
                ini_start = ini_part['start_index']
                ini_end = ini_start + ini_part['index_count']
                
                # 겹치는 범위 계산
                overlap_start = max(ib_start, ini_start)
                overlap_end = min(ib_end, ini_end)
                overlap_size = max(0, overlap_end - overlap_start)
                
                # 겹치는 부분이 IB 파츠의 50% 이상이면 중복으로 간주
                if overlap_size > ib_part['index_count'] * 0.5:
                    has_significant_overlap = True
                    break
            
            # 중복이 없으면 IB 파츠를 추가
            if not has_significant_overlap:
                # IB 파일에서 감지된 파츠는 part_ 넘버링 유지
                merged_parts.append(ib_part)
                added_ib_parts += 1
        
        log_debug(bpy.context, f"IB에서 추가로 {added_ib_parts}개 파츠 추가됨")
        
        # 파츠를 시작 인덱스 순으로 정렬
        merged_parts.sort(key=lambda x: x['start_index'])
        
        # 겹치는 파츠 제거 및 정리
        cleaned_parts = self._clean_overlapping_parts(merged_parts)
        
        log_debug(bpy.context, f"최종 {len(cleaned_parts)}개 파츠")
        return cleaned_parts

    def _clean_overlapping_parts(self, parts):
        """겹치는 파츠들을 정리합니다."""
        if not parts:
            return parts
        
        cleaned = []
        current_part = parts[0].copy()
        
        for next_part in parts[1:]:
            current_end = current_part['start_index'] + current_part['index_count']
            next_start = next_part['start_index']
            
            # 겹치지 않으면 현재 파츠를 추가하고 다음으로
            if current_end <= next_start:
                cleaned.append(current_part)
                current_part = next_part.copy()
            else:
                # 겹치는 경우 병합 또는 조정
                # INI 파츠(Additional_로 시작하지 않는)를 우선
                if not current_part['name'].startswith('Additional_'):
                    # 현재 파츠가 INI 파츠면 유지
                    continue
                elif not next_part['name'].startswith('Additional_'):
                    # 다음 파츠가 INI 파츠면 교체
                    cleaned.append(current_part)
                    current_part = next_part.copy()
                else:
                    # 둘 다 IB 파츠면 더 큰 것 유지
                    if next_part['index_count'] > current_part['index_count']:
                        current_part = next_part.copy()
        
        # 마지막 파츠 추가
        cleaned.append(current_part)
        
        return cleaned

    def _create_remaining_part(self, context):
        log_debug(context, "[_create_remaining_part] called")
        """분리된 파츠들을 제외한 나머지 부분을 잔여 파츠로 만듭니다."""
        bpy.ops.object.select_all(action='DESELECT')
        self._original_obj.select_set(True)
        context.view_layer.objects.active = self._original_obj
        
        # 원본 오브젝트를 편집 모드로 전환
        bpy.ops.object.mode_set(mode='OBJECT')
        mesh = self._original_obj.data
        
        # 모든 분리된 파츠의 인덱스를 수집
        all_separated_indices = set()
        
        # 인덱스 버퍼 구성
        index_buffer = []
        for poly in mesh.polygons:
            if len(poly.vertices) == 3:
                index_buffer.extend(poly.vertices)
        
        # 분리된 모든 파츠의 인덱스 범위 수집
        for part_info in self._parts_map:
            start_index = part_info['start_index']
            index_count = part_info['index_count']
            if start_index + index_count <= len(index_buffer):
                part_indices = set(index_buffer[start_index:start_index + index_count])
                all_separated_indices.update(part_indices)
        
        # 편집 모드로 전환하여 분리된 파츠들을 선택
        bpy.ops.object.mode_set(mode='EDIT')
        bm = bmesh.from_edit_mesh(mesh)
        bm.faces.ensure_lookup_table()
        bm.verts.ensure_lookup_table()
        
        # 분리된 파츠에 해당하는 면들을 선택
        separated_face_count = 0
        for f in bm.faces:
            f.select = any(v.index in all_separated_indices for v in f.verts)
            if f.select:
                separated_face_count += 1
        
        bmesh.update_edit_mesh(mesh)
        
        log_debug(bpy.context, f"원본에서 {separated_face_count}개 면을 제거하여 잔여 파츠 생성")
        
        if separated_face_count > 0:
            # 선택된 면들(분리된 파츠들)을 삭제
            bpy.ops.mesh.delete(type='FACE')
            
        bpy.ops.object.mode_set(mode='OBJECT')
        
        # 잔여 파츠에 이름 부여 및 컬렉션에 추가
        remaining_face_count = len(mesh.polygons)
        if remaining_face_count > 0:
            # 다른 remaining_part들과 구분하기 위해 별도 이름
            self._original_obj.name = "remaining_original"
            self._new_collection.objects.link(self._original_obj)
            self._scene_collection.objects.unlink(self._original_obj)
            log_debug(bpy.context, f"잔여 파츠: {remaining_face_count}개 면 보존됨")
        else:
            # 잔여 부분이 없으면 원본 삭제
            bpy.ops.object.delete()
            log_debug(bpy.context, "모든 파츠가 분리되어 잔여 부분 없음")

    def invoke(self, context, event):
        log_debug(context, "[invoke] called")
        props = context.scene.ini_resource_props
        ini_path = props.ini_path
        resource = props.resource

        if not ini_path or not resource:
            self.report({'ERROR'}, "INI 파일과 Resource를 선택해야 합니다.")
            return {'CANCELLED'}

        # INI 파일 파싱
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

        # 전역 파츠 카운터 초기화
        self._global_part_counter = 1

        # TextureOverride 섹션 내에서 resource를 사용하는 구간(ib=~ 이후 ~)을 모두 찾음
        target_ranges = self.find_sections_using_resource(section_map, resource)

        ini_parts = []
        ib_path = None
        for sec, start, end in target_ranges:
            # 해당 구간만 추출하여 DrawIndexed 파싱
            lines = section_map[sec][start:end]
            ini_parts.extend(self.extract_drawindexed_all(ini_path, {sec: lines}, sec))
            # IB 파일 경로는 첫 구간에서만 사용
            if ib_path is None:
                ib_path = self.find_ib_file(ini_path, {sec: lines}, sec)

        ib_parts = []
        if ib_path and os.path.exists(ib_path):
            log_debug(context, f"IB 파일 발견: {ib_path}")
            ib_parts = self.read_ib_file(ib_path)
            log_debug(context, f"IB 파일에서 {len(ib_parts)}개 파츠 발견")
        else:
            log_debug(context, "IB 파일을 찾을 수 없습니다. INI 파일의 정보만 사용합니다.")

        # INI와 IB 파일의 파츠 정보 병합
        self._parts_map = self.merge_parts_info(ini_parts, ib_parts)
        
        if not self._parts_map:
            self.report({'ERROR'}, "분리할 파츠가 없습니다.")
            return {'CANCELLED'}
        
        log_debug(context, f"총 {len(self._parts_map)}개 파츠를 분리합니다:")
        for i, part in enumerate(self._parts_map):
            log_debug(context, f"  {i+1}. {part['name']}: 시작={part['start_index']}, 개수={part['index_count']}")

        self._original_obj = context.active_object
        if not self._original_obj or self._original_obj.type != 'MESH':
            self.report({'ERROR'}, "메시 오브젝트를 선택하세요.")
            return {'CANCELLED'}

        self._original_collections = list(self._original_obj.users_collection)
        self._scene_collection = context.scene.collection

        if self._scene_collection not in self._original_collections:
            for col in self._original_collections:
                col.objects.unlink(self._original_obj)
            self._scene_collection.objects.link(self._original_obj)

        self._new_collection = bpy.data.collections.new(self._original_obj.name)
        self._scene_collection.children.link(self._new_collection)

        bpy.ops.object.select_all(action='DESELECT')
        wm = context.window_manager
        self._timer = wm.event_timer_add(0.1, window=context.window)
        wm.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        if event.type == 'TIMER':
            if self._index >= len(self._parts_map):
                # 원본 오브젝트에서 분리된 파츠들을 제거하여 잔여 부분만 남김
                self._create_remaining_part(context)

                for col in self._original_collections:
                    if col == self._scene_collection:
                        continue
                    if self._new_collection.name not in col.children:
                        col.children.link(self._new_collection)
                    if self._new_collection.name in self._scene_collection.children:
                        self._scene_collection.children.unlink(self._new_collection)

                context.window_manager.event_timer_remove(self._timer)
                self.report({'INFO'}, f"{len(self._parts_map)}개의 파츠 분리 완료 + 잔여 파츠 보존")
                return {'FINISHED'}

            part_info = self._parts_map[self._index]
            log_debug(context, f"진행도: {self._index + 1}/{len(self._parts_map)} - {part_info['name']}")

            index_count = part_info['index_count']
            start_index = part_info['start_index']
            name = part_info['name']

            self._original_obj.select_set(True)
            context.view_layer.objects.active = self._original_obj
            bpy.ops.object.duplicate()
            dup_obj = context.active_object
            mesh = dup_obj.data

            bpy.ops.object.mode_set(mode='OBJECT')
            index_buffer = []
            for poly in mesh.polygons:
                if len(poly.vertices) == 3:
                    index_buffer.extend(poly.vertices)

            selected_indices = set(index_buffer[start_index:start_index + index_count])

            bpy.ops.object.mode_set(mode='EDIT')
            bm = bmesh.from_edit_mesh(mesh)
            bm.faces.ensure_lookup_table()
            bm.verts.ensure_lookup_table()

            for f in bm.faces:
                f.select = any(v.index in selected_indices for v in f.verts)

            bmesh.update_edit_mesh(mesh)
            selected_face_count = sum(1 for f in bm.faces if f.select)

            if selected_face_count == 0:
                bpy.ops.object.mode_set(mode='OBJECT')
                bpy.data.objects.remove(dup_obj)
                self._index += 1
                return {'PASS_THROUGH'}

            bpy.ops.mesh.separate(type='SELECTED')
            bpy.ops.object.mode_set(mode='OBJECT')

            for obj in context.selected_objects:
                if obj != dup_obj:
                    self._new_collection.objects.link(obj)
                    self._scene_collection.objects.unlink(obj)
                    obj.name = name

            bpy.ops.object.select_all(action='DESELECT')
            dup_obj.select_set(True)
            bpy.ops.object.delete()
            self._index += 1
        return {'PASS_THROUGH'}




class PT_IBResourceSelector(Panel):
    bl_label = "INI 파츠 분리"
    bl_idname = "VIEW3D_PT_ib_resource_selector"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = '파츠 분리'


    def draw(self, context):
        layout = self.layout
        props = context.scene.ini_resource_props

        layout.operator("wm.select_ini_file_panel", text="INI 파일 열기")

        if props.ini_path:
            layout.label(text=f"INI: {props.ini_path.split('/')[-1]}")
            layout.prop(props, "resource")

        # 디버그 모드 체크박스 추가
        layout.prop(props, "debug_mode")

        obj = context.active_object
        enable_button = (
            obj is not None and obj.type == 'MESH'
            and bool(props.ini_path.strip())
            and bool(props.resource.strip())
        )

        row = layout.row()
        row.enabled = enable_button
        row.operator("object.separate_parts_from_ini_modal", text="파츠 분리")




classes = (
    INIResourceProperties,
    OT_SelectIniFile,
    OT_SeparatePartsFromIniModal,
    PT_IBResourceSelector,
)





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
    OT_SelectIniFile.filter_glob = bpy.props.StringProperty(default="*.ini", options={'HIDDEN'})




def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
    del bpy.types.Scene.ini_resource_props


if __name__ == "__main__":
    register()
