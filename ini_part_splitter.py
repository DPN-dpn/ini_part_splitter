
# Blender 애드온 정보
bl_info = {
    "name": "INI 기반 파츠 분리",
    "author": "DPN",
    "version": (1, 6, 1),
    "blender": (2, 93, 0),
    "location": "3D 뷰 > 우측 UI 패널 > 파츠 분리",
    "description": "INI의 DrawIndexed 값을 기반으로 오브젝트에서 파츠를 분리합니다.",
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
    bl_description = "INI 파일을 선택하고 리소스를 불러옵니다"
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

# INI와 IB 파일을 기반으로 파츠를 분리하는 메인 오퍼레이터
class OT_SeparatePartsFromIniModal(Operator):
    bl_idname = "object.separate_parts_from_ini_modal"
    bl_label = "파츠 분리"
    bl_description = "선택된 INI와 IB를 기반으로 선택된 오브젝트에서 파츠를 분리합니다"
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

    # INI에서 DrawIndexed 정보 추출
    def extract_drawindexed_all(self, section_map, section):
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
        bpy.ops.object.mode_set(mode='OBJECT')
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


        # 5. 각 구간별로 DrawIndexed 파츠 정보만 추출
        ini_parts = []
        for sec, start, end in target_ranges:
            lines = section_map[sec][start:end]
            ini_parts.extend(self.extract_drawindexed_all({sec: lines}, sec))

        # 6. INI 파츠 정보만 사용 (merge_parts_info 제거)
        self._parts_map = ini_parts.copy()

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
    bl_label = "drawIndexed 추출"
    bl_description = "선택된 face로부터 drawIndexed 값을 추출합니다"
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
    bl_label = "매쉬 선택"
    bl_description = "drawIndexed 값에 해당하는 face를 오브젝트에서 선택합니다"
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
    INIResourceProperties.ini_path = bpy.props.StringProperty(
        name="INI 파일 경로",
        description="선택된 INI 파일의 경로입니다",
        default=""
    )
    INIResourceProperties.resource = bpy.props.EnumProperty(
        name="IB",
        description="파츠를 분리할 IB의 리소스 이름입니다",
        items=lambda self, context: self.resource_items(context)
    )
    INIResourceProperties.debug_mode = bpy.props.BoolProperty(
        name="디버그 모드",
        description="작업 단계별 디버그 로그를 콘솔에 출력합니다.\n창-시스템 콘솔에서 확인할 수 있습니다",
        default=False
    )
    INIResourceProperties.drawindexed_start = bpy.props.IntProperty(
        name="DrawIndexed Start",
        description="drawindexed = ???, ???, 0 형식에서 두 번째 값",
        default=0,
        min=0,
        max=1000000000,
        step=1
    )
    INIResourceProperties.drawindexed_count = bpy.props.IntProperty(
        name="DrawIndexed Count",
        description="drawindexed = ???, ???, 0 형식에서 첫 번째 값",
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
