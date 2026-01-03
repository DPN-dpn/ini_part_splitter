# 라이브러리 임포트
import bpy
import bmesh
import re
import time
from bpy.types import Operator, Panel, PropertyGroup, Scene
from bpy_extras.io_utils import ImportHelper


# 디버그 로그 함수: 디버그 모드일 때만 출력
def log_debug(context, category, msg=None):
    try:
        # 호환성: 두 번째 인자만 전달된 경우
        if msg is None:
            msg = category
            category = ""
        # 경과시간 계산 (이전 로그 호출과의 차이)
        global _log_prev_time
        try:
            now = time.perf_counter()
        except Exception:
            now = None
        delta = 0.0
        if now is not None:
            if globals().get("_log_prev_time") is None:
                delta = 0.0
            else:
                delta = now - globals().get("_log_prev_time")
            globals()["_log_prev_time"] = now

        prefix = f"({delta:.3f}s) "

        props = getattr(context.scene, "parts_seperator_props", None)
        if props and getattr(props, "debug_mode", False):
            if category:
                print(f"{prefix}[{category}] {msg}")
            else:
                print(f"{prefix}{msg}")
    except Exception:
        pass


# INI 파일 선택 및 파싱 오퍼레이터
class OT_SelectIniFile(Operator, ImportHelper):
    bl_idname = "wm.select_ini_file_panel"
    bl_label = "INI 파일 선택"
    bl_description = "INI 파일을 선택하고 리소스를 불러옵니다"
    filename_ext = ".ini"
    filter_glob: bpy.props.StringProperty(
        default="*.ini",
        options={"HIDDEN"},
    )

    def execute(self, context):
        props = context.scene.parts_seperator_props
        # 1. 선택한 INI 파일 경로 저장
        props.ini_path = self.filepath
        log_debug(context, "select_ini", f"INI 파일 경로 저장: {self.filepath}")

        # 2. INI 파일에서 TextureOverride 섹션 내 ib = 구문을 모두 찾아 Resource 목록 생성
        resource_set = set()
        current_section = None
        with open(self.filepath, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                # 2-1. 섹션명 감지
                if line.startswith("[") and line.endswith("]"):
                    current_section = line[1:-1]
                # 2-2. TextureOverride 섹션 내 ib = 구문 추출
                elif (
                    current_section
                    and current_section.startswith("TextureOverride")
                    and line.lower().startswith("ib")
                ):
                    parts = line.split("=", 1)
                    if len(parts) == 2:
                        ib_name = parts[1].strip()
                        resource_set.add(ib_name)

        log_debug(context, "select_ini", f"TextureOverride에서 발견된 리소스 개수: {len(resource_set)}")

        # 3. Resource 목록이 없으면 에러 리포트
        resource_items = [(r, r, "") for r in sorted(resource_set)]
        if not resource_items:
            self.report({"ERROR"}, "TextureOverride 섹션에 ib = 구문이 없습니다.")
            return {"CANCELLED"}

        # 4. Resource 목록을 프로퍼티에 저장
        PartsSeperatorProperties._resource_items = resource_items
        props.resource = resource_items[0][0]
        log_debug(context, "select_ini", f"리소스 목록 저장 및 선택: {props.resource}")

        # 5. 패널 강제 갱신: 모든 3D 뷰 영역에 대해 tag_redraw
        for window in context.window_manager.windows:
            for area in window.screen.areas:
                if area.type == "VIEW_3D":
                    area.tag_redraw()
        return {"FINISHED"}


# INI와 IB 파일을 기반으로 파츠를 분리하는 메인 오퍼레이터
class OT_SeparatePartsFromIniModal(Operator):
    bl_idname = "object.separate_parts_from_ini_modal"
    bl_label = "파츠 분리"
    bl_description = "선택된 INI와 IB를 기반으로 선택된 오브젝트에서 파츠를 분리합니다"
    bl_options = {"REGISTER", "UNDO"}

    _timer = None
    _index = 0
    _parts_map = []
    _original_obj = None
    _original_collections = []
    _scene_collection = None
    _new_collection = None

    # 특정 리소스를 사용하는 TextureOverride 섹션 구간 찾기
    def find_sections_using_resource(self, section_map, resource_name):
        log_debug(bpy.context, "find_sections_using_resource", f"resource_name={resource_name}")
        result = []
        for sec, lines in section_map.items():
            log_debug(bpy.context, "find_sections_using_resource", f"섹션 처리 시작: {sec} (줄수={len(lines)})")
            if not sec.startswith("TextureOverride"):
                continue
            current_resource = None
            start_idx = None
            commandlist_sections = []  # run = CommandList~ 구문으로 참조되는 섹션들
            
            for idx, line in enumerate(lines):
                l = line.strip()
                # 1. ib= 구문을 만나면 리소스명 추출
                if l.lower().startswith("ib"):
                    parts = l.split("=", 1)
                    if len(parts) == 2:
                        ib_name = parts[1].strip()
                        log_debug(bpy.context, "find_sections_using_resource", f"{sec}: ib 발견: {ib_name} (라인 {idx})")
                        # 2. 이전 리소스가 타겟이면 구간 종료
                        if current_resource == resource_name and start_idx is not None:
                            result.append((sec, start_idx, idx))
                            log_debug(bpy.context, "find_sections_using_resource", f"{sec}: resource 구간 추가: start={start_idx}, end={idx}")
                        # 3. 새 리소스 시작 또는 타겟 아님 처리
                        if ib_name == resource_name:
                            current_resource = ib_name
                            start_idx = idx
                        else:
                            current_resource = ib_name
                            start_idx = None
                # run = CommandList~ 구문 찾기
                elif l.lower().startswith("run") and current_resource == resource_name:
                    parts = l.split("=", 1)
                    if len(parts) == 2:
                        target_section = parts[1].strip()
                        if target_section.startswith("CommandList") and target_section in section_map:
                            commandlist_sections.append(target_section)
                            log_debug(bpy.context, "find_sections_using_resource", f"CommandList 섹션 발견: {target_section}")
            
            # 4. 섹션 끝까지 타겟 리소스면 마지막까지 구간 추가
            if current_resource == resource_name and start_idx is not None:
                result.append((sec, start_idx, len(lines)))
                log_debug(bpy.context, "find_sections_using_resource", f"{sec}: 섹션 끝까지 resource 유지, 구간 추가 start={start_idx}, end={len(lines)}")
            
            # 5. CommandList 섹션들도 결과에 추가
            for cmd_sec in commandlist_sections:
                result.append((cmd_sec, 0, len(section_map[cmd_sec])))
                log_debug(bpy.context, "find_sections_using_resource", f"CommandList 섹션 추가: {cmd_sec} (전체 {len(section_map[cmd_sec])}줄)")
        
        return result

    # INI에서 DrawIndexed 정보 추출
    def extract_drawindexed_all(self, section_map, section):
        log_debug(bpy.context, "extract_drawindexed_all", f"section={section}")

        drawindexed_map = []
        seen = set()
        last_comment = None

        def extract_drawindexed(lines):
            nonlocal seen, last_comment
            results = []

            # 1단계: 모든 DrawIndexed와 해당 주석을 수집
            log_debug(bpy.context, "extract_drawindexed", f"1단계 시작: lines={len(lines)}")
            temp_results = []
            comment_stack = []  # IF문의 중첩 레벨별 주석을 저장
            if_depth = 0

            for i, line in enumerate(lines):
                stripped_line = line.strip()

                if stripped_line.startswith(";"):
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
                    parts = stripped_line.split("=", 1)
                    if len(parts) == 2:
                        value = parts[1].strip()
                        if re.match(r"^\d+,\s*\d+,\s*0$", value) and value not in seen:
                            seen.add(value)
                            numbers = list(map(int, re.findall(r"\d+", value)))
                            if len(numbers) >= 2:
                                # 가장 구체적인 주석 선택 (가장 안쪽 블록의 주석)
                                effective_comment = None
                                for j in range(len(comment_stack) - 1, -1, -1):
                                    if comment_stack[j]:
                                        effective_comment = comment_stack[j]
                                        break

                                temp_results.append(
                                    {
                                        "start_index": numbers[1],
                                        "index_count": numbers[0],
                                        "comment": effective_comment,
                                        "if_depth": if_depth,
                                    }
                                )
                                log_debug(bpy.context, "extract_drawindexed", f"DrawIndexed 발견: start={numbers[1]}, count={numbers[0]}, comment={effective_comment}, if_depth={if_depth}")

                # 다른 구문이 나오면 현재 레벨의 주석 리셋 (IF 블록 외부에서만)
                elif (
                    if_depth == 0
                    and not stripped_line.startswith(";")
                    and stripped_line
                ):
                    comment_stack = []

            log_debug(bpy.context, "extract_drawindexed", f"1단계 완료: 발견된 DrawIndexed 수={len(temp_results)}")
            # 2단계: 같은 주석을 가진 항목들을 그룹화하고 네이밍
            comment_groups = {}
            for item in temp_results:
                comment = item["comment"]
                if comment:
                    if comment not in comment_groups:
                        comment_groups[comment] = []
                    comment_groups[comment].append(item)

            # 3단계: 최종 결과 생성
            for item in temp_results:
                if item["comment"]:
                    comment = item["comment"]
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

                results.append(
                    {
                        "start_index": item["start_index"],
                        "index_count": item["index_count"],
                        "name": part_name,
                    }
                )

            return results

        drawindexed_map.extend(extract_drawindexed(section_map.get(section, [])))

        for line in section_map.get(section, []):
            if line.lower().startswith("run"):
                parts = line.split("=", 1)
                if len(parts) == 2:
                    target = parts[1].strip()
                    if target in section_map:
                        drawindexed_map.extend(extract_drawindexed(section_map[target]))
        return drawindexed_map

    # 분리된 파츠를 제외한 잔여 파츠 생성
    def _create_remaining_part(self, context):
        log_debug(context, "create_remaining_part", "called")

        # 1. 모든 오브젝트 선택 해제 후 원본 오브젝트만 선택
        bpy.ops.object.select_all(action="DESELECT")
        self._original_obj.select_set(True)
        context.view_layer.objects.active = self._original_obj
        log_debug(context, "create_remaining_part", "1. 원본 오브젝트만 선택됨")

        # 2. 원본 오브젝트를 OBJECT 모드로 전환
        bpy.ops.object.mode_set(mode="OBJECT")
        mesh = self._original_obj.data
        log_debug(context, "create_remaining_part", "2. OBJECT 모드 전환 및 mesh 참조 획득")

        # 3. 분리된 파츠의 모든 인덱스를 수집할 집합 준비
        all_separated_indices = set()
        log_debug(context, "create_remaining_part", "3. 분리된 파츠 인덱스 집합 초기화")

        # 4. 인덱스 버퍼(삼각형만) 구성
        index_buffer = []
        for poly in mesh.polygons:
            if len(poly.vertices) == 3:
                index_buffer.extend(poly.vertices)
        log_debug(context, "create_remaining_part", f"4. 인덱스 버퍼 구성 완료 (len={len(index_buffer)})")

        # 5. 각 파츠의 인덱스 범위를 집합에 추가
        for part_info in self._parts_map:
            start_index = part_info["start_index"]
            index_count = part_info["index_count"]
            if start_index + index_count <= len(index_buffer):
                part_indices = set(
                    index_buffer[start_index : start_index + index_count]
                )
                all_separated_indices.update(part_indices)
        log_debug(context, "create_remaining_part", f"5. 분리 파츠 인덱스 합산 완료 (총 분리 버텍스 수={len(all_separated_indices)})")

        # 6. EDIT 모드로 전환 후 분리된 파츠에 해당하는 면 선택
        bpy.ops.object.mode_set(mode="EDIT")
        bm = bmesh.from_edit_mesh(mesh)
        bm.faces.ensure_lookup_table()
        bm.verts.ensure_lookup_table()
        log_debug(context, "create_remaining_part", "6. EDIT 모드 진입 및 BMesh 준비")

        # 7. 분리된 파츠의 버텍스 인덱스를 포함하는 면 선택
        separated_face_count = 0
        for f in bm.faces:
            f.select = any(v.index in all_separated_indices for v in f.verts)
            if f.select:
                separated_face_count += 1
        bmesh.update_edit_mesh(mesh)

        log_debug(bpy.context, "create_remaining_part", f"7. 분리된 파츠에 해당하는 면 선택 완료 (선택된 면 수={separated_face_count})")

        # 8. 분리된 파츠가 있으면 해당 면 삭제
        if separated_face_count > 0:
            bpy.ops.mesh.delete(type="FACE")
            log_debug(bpy.context, "create_remaining_part", "8. 선택된 면 삭제 실행")

        bpy.ops.object.mode_set(mode="OBJECT")

        # 9. 잔여 파츠가 남아 있으면 이름 부여 및 컬렉션 이동
        remaining_face_count = len(mesh.polygons)
        if remaining_face_count > 0:
            self._original_obj.name = "remaining_original"
            self._new_collection.objects.link(self._original_obj)
            self._scene_collection.objects.unlink(self._original_obj)
            log_debug(bpy.context, "create_remaining_part", f"9. 잔여 파츠 보존: {remaining_face_count}개 면")
        else:
            # 10. 잔여 부분이 없으면 원본 삭제
            bpy.ops.object.delete()
            log_debug(bpy.context, "create_remaining_part", "10. 잔여 파츠 없음 - 원본 오브젝트 삭제됨")

    # 모달 오퍼레이터 실행 진입점
    def invoke(self, context, event):
        # 파츠 분리 시작 시점에 로그 타이머 리셋
        try:
            globals()["_log_prev_time"] = time.perf_counter()
        except Exception:
            globals()["_log_prev_time"] = None
       # 분리 전체 시간 측정 시작 시간 저장
        try:
            globals()["_log_start_time"] = time.perf_counter()
        except Exception:
            globals()["_log_start_time"] = None
        log_debug(context, "invoke", "called")
        props = context.scene.parts_seperator_props
        ini_path = props.ini_path
        resource = props.resource

        # 1. INI 파일과 Resource가 선택되었는지 확인
        if not ini_path or not resource:
            self.report({"ERROR"}, "INI 파일과 Resource를 선택해야 합니다.")
            return {"CANCELLED"}
        log_debug(context, "invoke", "1. INI 파일 및 Resource 선택 확인 완료")

        # 2. INI 파일을 파싱하여 섹션별로 저장
        section_map = {}
        log_debug(context, "invoke", f"INI 파일 파싱 시작: {ini_path}")
        bpy.ops.object.mode_set(mode="OBJECT")
        with open(ini_path, encoding="utf-8") as f:
            current_section = None
            for line in f:
                line = line.strip()
                if line.startswith("[") and line.endswith("]"):
                    current_section = line[1:-1]
                    section_map[current_section] = []
                elif current_section:
                    section_map[current_section].append(line)
        log_debug(context, "invoke", f"INI 파싱 완료, 섹션 수: {len(section_map)}")

        # 3. 전역 파츠 카운터 초기화
        self._global_part_counter = 1
        log_debug(context, "invoke", "전역 파츠 카운터 초기화")

        # 4. TextureOverride 섹션 내에서 resource를 사용하는 구간을 모두 찾음
        target_ranges = self.find_sections_using_resource(section_map, resource)
        log_debug(context, "invoke", f"resource 사용 구간 수: {len(target_ranges)}")

        # 5. 각 구간별로 DrawIndexed 파츠 정보만 추출
        ini_parts = []
        for sec, start, end in target_ranges:
            lines = section_map[sec][start:end]
            ini_parts.extend(self.extract_drawindexed_all({sec: lines}, sec))
        log_debug(context, "invoke", f"INI에서 추출된 DrawIndexed 파츠 수: {len(ini_parts)}")

        # 6. INI 파츠 정보만 사용 (merge_parts_info 제거)
        self._parts_map = ini_parts.copy()
        log_debug(context, "invoke", f"_parts_map에 저장된 파츠 수: {len(self._parts_map)}")

        # 8. 분리할 파츠가 없으면 에러 리포트
        if not self._parts_map:
            self.report({"ERROR"}, "분리할 파츠가 없습니다.")
            return {"CANCELLED"}
        log_debug(context, "invoke", "8. 분리할 파츠 존재 확인 완료")

        # 9. 분리할 파츠 정보 로그 출력
        log_debug(context, "invoke", f"총 {len(self._parts_map)}개 파츠를 분리합니다:")
        for i, part in enumerate(self._parts_map):
            log_debug(context, "invoke", f"  {i+1}. {part['name']}: 시작={part['start_index']}, 개수={part['index_count']}")

        # 10. 활성 메시 오브젝트 확인 및 저장
        self._original_obj = context.active_object
        if not self._original_obj or self._original_obj.type != "MESH":
            self.report({"ERROR"}, "메시 오브젝트를 선택하세요.")
            return {"CANCELLED"}
        log_debug(context, "invoke", f"10. 활성 메시 오브젝트: {self._original_obj.name}")

        # 11. 오브젝트의 컬렉션 정보 저장
        self._original_collections = list(self._original_obj.users_collection)
        self._scene_collection = context.scene.collection
        log_debug(context, "invoke", f"11. 오브젝트 컬렉션 저장 (개수={len(self._original_collections)})")

        # 12. 오브젝트가 씬 컬렉션에 없으면 추가
        if self._scene_collection not in self._original_collections:
            for col in self._original_collections:
                col.objects.unlink(self._original_obj)
            self._scene_collection.objects.link(self._original_obj)
        log_debug(context, "invoke", "12. 오브젝트를 씬 컬렉션으로 이동 및 링크 확인")

        # 13. 새 컬렉션 생성 및 씬에 추가
        self._new_collection = bpy.data.collections.new(self._original_obj.name)
        self._scene_collection.children.link(self._new_collection)
        log_debug(context, "invoke", f"13. 새 컬렉션 생성: {self._new_collection.name}")

        # 14. 전체 오브젝트 선택 해제 및 타이머 등록
        bpy.ops.object.select_all(action="DESELECT")
        wm = context.window_manager
        self._timer = wm.event_timer_add(0.1, window=context.window)
        wm.modal_handler_add(self)
        log_debug(context, "invoke", "14. 타이머 등록 및 모달 핸들러 추가 완료")
        return {"RUNNING_MODAL"}

    # 모달 오퍼레이터의 반복 처리 (타이머 기반)
    def modal(self, context, event):
        if event.type == "TIMER":
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
                # 총 소요시간 로깅
                try:
                    start = globals().get("_log_start_time")
                    if start is not None:
                        elapsed = time.perf_counter() - start
                    else:
                        elapsed = 0.0
                except Exception:
                    elapsed = 0.0
                log_debug(context, "modal", f"총 소요시간: {elapsed:.3f}s")
                self.report(
                    {"INFO"},
                    f"{len(self._parts_map)}개의 파츠 분리 완료 + 잔여 파츠 보존",
                )
                return {"FINISHED"}

            # 5. 현재 분리할 파츠 정보 준비
            part_info = self._parts_map[self._index]
            log_debug(context, "modal", f"진행도: {self._index + 1}/{len(self._parts_map)} - {part_info['name']}")

            index_count = part_info["index_count"]
            start_index = part_info["start_index"]
            name = part_info["name"]

            # 6. 원본 오브젝트 복제
            self._original_obj.select_set(True)
            context.view_layer.objects.active = self._original_obj
            # 6-1. OBJECT_OT_duplicate linked=False 옵션으로 메시 데이터는 복제(독립), 머티리얼 슬롯은 그대로 유지됩니다.
            bpy.ops.object.duplicate_move(OBJECT_OT_duplicate={"linked": False})
            dup_obj = context.active_object
            # 6-2. 안전을 위해 머티리얼 슬롯을 원본과 동일하게 보정
            dup_obj.data.materials.clear()
            for m in self._original_obj.data.materials:
                dup_obj.data.materials.append(m)
            mesh = dup_obj.data

            # 7. 인덱스 버퍼 생성 (삼각형만)
            bpy.ops.object.mode_set(mode="OBJECT")
            index_buffer = []
            poly_type_count = {}
            for poly in mesh.polygons:
                poly_type_count[len(poly.vertices)] = (
                    poly_type_count.get(len(poly.vertices), 0) + 1
                )
                if len(poly.vertices) == 3:
                    index_buffer.extend(poly.vertices)

            log_debug(context, "separate", f"파츠: {name}, start_index={start_index}, index_count={index_count}, index_buffer_len={len(index_buffer)}")
            log_debug(context, "separate", f"poly_type_count: {poly_type_count}")
            slice_start = start_index
            slice_end = start_index + index_count
            log_debug(context, "separate", f"index_buffer[{slice_start}:{slice_end}] (len={slice_end-slice_start})")
            log_debug(context, "separate", f"index_buffer slice head: {index_buffer[slice_start:slice_start+10] if slice_end > slice_start else []}")
            log_debug(context, "separate", f"index_buffer slice tail: {index_buffer[max(slice_end-10,slice_start):slice_end] if slice_end > slice_start else []}")

            # 8. 분리할 인덱스 집합 생성
            selected_indices = set(
                index_buffer[start_index : start_index + index_count]
            )
            log_debug(context, "separate", f"selected_indices 샘플: {list(selected_indices)[:10]} ... (총 {len(selected_indices)}개)")

            # 9. EDIT 모드에서 분리할 face 선택
            bpy.ops.object.mode_set(mode="EDIT")
            bm = bmesh.from_edit_mesh(mesh)
            bm.faces.ensure_lookup_table()
            bm.verts.ensure_lookup_table()

            face_select_count = 0
            for f in bm.faces:
                f.select = any(v.index in selected_indices for v in f.verts)
                if f.select:
                    face_select_count += 1
            log_debug(context, "separate", f"선택된 face 개수: {face_select_count} / 전체 {len(bm.faces)}")

            bmesh.update_edit_mesh(mesh)
            selected_face_count = sum(1 for f in bm.faces if f.select)

            # 10. 선택된 face가 없으면 건너뜀
            if selected_face_count == 0:
                log_debug(context, "separate", f"선택된 face 없음, 파츠 건너뜀")
                bpy.ops.object.mode_set(mode="OBJECT")
                # 10-1. 삭제 전에 메쉬와 머티리얼 참조를 보관
                _mesh_to_remove = dup_obj.data
                _mats_to_check = [m for m in _mesh_to_remove.materials if m is not None]
                bpy.data.objects.remove(dup_obj)
                # 10-2. 메쉬 데이터 블록이 더 이상 사용되지 않으면 제거
                try:
                    if _mesh_to_remove.users == 0:
                        bpy.data.meshes.remove(_mesh_to_remove)
                except Exception:
                    pass
                # 10-3. 머티리얼 중 사용자가 0인 항목은 제거
                for _m in _mats_to_check:
                    try:
                        if _m.users == 0:
                            bpy.data.materials.remove(_m)
                    except Exception:
                        pass
                self._index += 1
                return {"PASS_THROUGH"}

            # 11. 선택된 face를 분리
            bpy.ops.mesh.separate(type="SELECTED")
            bpy.ops.object.mode_set(mode="OBJECT")

            # 12. 분리된 오브젝트를 새 컬렉션으로 이동 및 이름 지정
            for obj in context.selected_objects:
                if obj != dup_obj:
                    self._new_collection.objects.link(obj)
                    self._scene_collection.objects.unlink(obj)
                    obj.name = name
                    log_debug(context, "separate", f"분리된 오브젝트: {obj.name}, faces: {len(obj.data.polygons)}")

            # 13. 복제 오브젝트 삭제 및 인덱스 증가 및 사용하지 않는 데이터 정리
            bpy.ops.object.select_all(action="DESELECT")
            dup_obj.select_set(True)
            # 13-1. 삭제 전에 메쉬와 머티리얼 참조를 보관(삭제 후 참조 손실 방지)
            _mesh_to_remove = dup_obj.data
            _mats_to_check = [m for m in _mesh_to_remove.materials if m is not None]
            bpy.ops.object.delete()
            # 13-2. 메쉬 데이터 블록이 더 이상 사용되지 않으면 제거
            try:
                if _mesh_to_remove.users == 0:
                    bpy.data.meshes.remove(_mesh_to_remove)
            except Exception:
                pass
            # 13-3. 머티리얼 중 사용자가 0인 항목은 제거
            for _m in _mats_to_check:
                try:
                    if _m.users == 0:
                        bpy.data.materials.remove(_m)
                except Exception:
                    pass
            self._index += 1
        return {"PASS_THROUGH"}


# INI 파츠 분리 패널 UI
class PT_PartsSeperatorPanel(Panel):
    bl_label = "INI 파츠 분리"
    bl_idname = "VIEW3D_PT_parts_seperator_panel"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "파츠 분리"

    def draw(self, context):
        layout = self.layout
        props = context.scene.parts_seperator_props

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
            obj is not None
            and obj.type == "MESH"
            and bool(props.ini_path.strip())
            and bool(props.resource.strip())
        )

        # 5. 파츠 분리 버튼
        row = layout.row()
        row.enabled = enable_button
        row.operator("object.separate_parts_from_ini_modal", text="파츠 분리")


# 파츠 분리에서 사용할 프로퍼티 그룹
class PartsSeperatorProperties(PropertyGroup):
    _resource_items = []

    def resource_items(self, context):
        return self._resource_items


# 애드온 등록 함수
def register_parts_seperator():
    for cls in classes:
        bpy.utils.register_class(cls)
    Scene.parts_seperator_props = bpy.props.PointerProperty(
        type=PartsSeperatorProperties
    )
    PartsSeperatorProperties.ini_path = bpy.props.StringProperty(
        name="INI 파일 경로", description="선택된 INI 파일의 경로입니다", default=""
    )
    PartsSeperatorProperties.resource = bpy.props.EnumProperty(
        name="IB",
        description="파츠를 분리할 IB의 리소스 이름입니다",
        items=lambda self, context: self.resource_items(context),
    )
    PartsSeperatorProperties.debug_mode = bpy.props.BoolProperty(
        name="디버그 모드",
        description="작업 단계별 디버그 로그를 콘솔에 출력합니다.\n창-시스템 콘솔에서 확인할 수 있습니다",
        default=False,
    )


# 애드온 해제 함수
def unregister_parts_seperator():
    del Scene.parts_seperator_props
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)


# Blender에 등록할 클래스 목록
classes = (
    PT_PartsSeperatorPanel,
    PartsSeperatorProperties,
    OT_SelectIniFile,
    OT_SeparatePartsFromIniModal,
)
