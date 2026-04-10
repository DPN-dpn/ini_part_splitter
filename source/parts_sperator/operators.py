import bpy
from bpy.types import Operator
from bpy_extras.io_utils import ImportHelper
import os
from ..utils.ini_parser import parse_ini_sections
from .functions import (
    defunctionalize,
    create_resource_enum,
    build_parts_map,
    separate_parts,
)


def _force_ui_redraw():
    """모든 윈도우/영역을 강제로 다시 그려 UI(패널)를 갱신합니다."""
    for window in bpy.context.window_manager.windows:
        for area in window.screen.areas:
            area.tag_redraw()
            for region in area.regions:
                region.tag_redraw()


class INIPS_OT_SelectIniFile(Operator, ImportHelper):
    bl_idname = "inips.select_ini_file_panel"
    bl_label = "INI 파일 선택"
    bl_description = "INI 파일을 선택하고 리소스를 불러옵니다"
    filename_ext = ".ini"
    filter_glob: bpy.props.StringProperty(
        default="*.ini",
        options={"HIDDEN"},
    )

    def execute(self, context):
        scene = context.scene

        path = getattr(self, "filepath", None)
        if not path or not os.path.isfile(path):
            self.report({"ERROR"}, "유효한 INI 파일을 선택하세요.")
            return {"CANCELLED"}
        scene.inips_ini_path = path

        text = None
        with open(path, "r", encoding="utf-8") as f:
            text = f.read()
        if text is None:
            self.report({"ERROR"}, f"파일을 읽을 수 없습니다: {os.path.basename(path)}")
            return {"CANCELLED"}

        # ini 파싱
        sections = parse_ini_sections(text)

        # CommandList 함수화 해제
        sections = defunctionalize.defunctionalize_sections(sections)

        # INI 섹션 데이터를 Scene의 CollectionProperty에 저장
        ini_sections = scene.inips_ini_sections
        ini_sections.clear()
        for name, lines in sections.items():
            item = ini_sections.add()
            item.section_name = name
            item.lines = "\n".join(lines)

        self.report({"INFO"}, f"INI 파싱 완료: {len(sections)} 섹션")

        # IB 리소스 Enum 생성
        create_resource_enum.create_resource_enum(self, scene, sections)

        # UI 강제 갱신
        _force_ui_redraw()

        return {"FINISHED"}


class INIPS_OT_SeparatePartsFromIniModal(Operator):
    bl_idname = "inips.separate_parts_from_ini_modal"
    bl_label = "파츠 분리"
    bl_description = "선택된 INI와 IB를 기반으로 선택된 오브젝트에서 파츠를 분리합니다"
    bl_options = {"REGISTER", "UNDO"}

    _timer = None
    _index = 0
    _target_obj = None
    _parts_map = []

    _original_collections = []
    _scene_collection = None
    _new_collection = None

    _success_count = 0
    _skipped_count = 0

    def invoke(self, context, event):
        scene = context.scene

        # 기본 검증 및 초기화
        ini_path = getattr(scene, "inips_ini_path", None)
        resource = getattr(scene, "inips_resource", None)
        if not ini_path or not resource:
            self.report({"ERROR"}, "INI 파일과 Resource를 선택하세요.")
            return {"CANCELLED"}

        # 선택된 오브젝트 캡처
        target_obj = context.active_object
        if not target_obj:
            self.report({"ERROR"}, "분리 대상 오브젝트를 선택하세요.")
            return {"CANCELLED"}
        self._target_obj = target_obj

        # INI 섹션 데이터 가져오기
        ini_sections = getattr(scene, "inips_ini_sections", None)
        sections = {}
        if ini_sections:
            for item in ini_sections:
                sections[item.section_name] = item.lines.splitlines()

        # 파츠 맵 생성
        self._parts_map = build_parts_map.build_parts_map(sections, resource)

        # 초기화
        self._index = 0
        self._success_count = 0
        self._skipped_count = 0
        self._remaining_created = False

        # 원본/컬렉션 정보 보관 및 새 컬렉션 생성
        self._original_collections = list(target_obj.users_collection)
        self._scene_collection = context.scene.collection

        if self._scene_collection not in self._original_collections:
            for col in self._original_collections:
                col.objects.unlink(target_obj)
            self._scene_collection.objects.link(target_obj)

        # 새 컬렉션 생성 및 씬에 링크(여기에 분리된 파츠들을 모음)
        base_name = target_obj.name
        new_col_name = base_name
        if bpy.data.collections.get(new_col_name):
            i = 1
            while bpy.data.collections.get(f"{new_col_name}_{i}"):
                i += 1
            new_col_name = f"{new_col_name}_{i}"
        self._new_collection = bpy.data.collections.new(new_col_name)
        # 원본 컬렉션이 있으면 그 밑에 링크, 없으면 씬에 링크
        if self._original_collections:
            for col in self._original_collections:
                if self._new_collection.name not in [c.name for c in col.children]:
                    col.children.link(self._new_collection)
        else:
            self._scene_collection.children.link(self._new_collection)

        # 타이머 설정 및 모달 시작
        wm = context.window_manager
        self._timer = wm.event_timer_add(0.1, window=context.window)
        wm.modal_handler_add(self)
        return {"RUNNING_MODAL"}

    def modal(self, context, event):
        if event.type == "TIMER":
            if self._index >= len(self._parts_map):
                # 잔여 파츠 생성 및 컬렉션 정리
                before_count = (
                    len(self._new_collection.objects) if self._new_collection else 0
                )
                created_from_remaining = separate_parts.create_remaining_part(
                    self,
                    context,
                    getattr(self, "_target_obj", None),
                    self._parts_map,
                    self._new_collection,
                )
                # create_remaining_part는 int 반환(생성된 오브젝트 수)입니다.
                after_count = 0
                if isinstance(created_from_remaining, int):
                    created = created_from_remaining
                else:
                    after_count = (
                        len(self._new_collection.objects) if self._new_collection else 0
                    )
                    created = max(0, after_count - before_count)

                if created:
                    self._success_count += created
                self._remaining_created = bool(created)

                # 원본 오브젝트 삭제
                orig = getattr(self, "_target_obj", None)
                if orig:
                    orig_name = orig.name
                    mesh_name = None
                    mats_to_check = []

                    if getattr(orig, "data", None):
                        mesh_name = orig.data.name
                        mats_to_check = [
                            m.name for m in orig.data.materials if m is not None
                        ]

                    # 선택 해제 후 대상 활성화 -> 삭제 시도
                    try:
                        bpy.ops.object.select_all(action="DESELECT")
                    except Exception:
                        for o in context.view_layer.objects:
                            o.select_set(False)

                    obj_to_del = bpy.data.objects.get(orig_name)
                    if obj_to_del:
                        obj_to_del.select_set(True)
                        context.view_layer.objects.active = obj_to_del
                        try:
                            bpy.ops.object.delete()
                        except Exception:
                            bpy.data.objects.remove(obj_to_del, do_unlink=True)

                    # 메쉬/머티리얼 정리(다른 곳에서 사용중이지 않을 때만 제거)
                    if mesh_name:
                        mesh = bpy.data.meshes.get(mesh_name)
                        if mesh and mesh.users == 0:
                            bpy.data.meshes.remove(mesh)
                    for mname in mats_to_check:
                        m = bpy.data.materials.get(mname)
                        if m and m.users == 0:
                            bpy.data.materials.remove(m)

                    # 참조 해제
                    self._target_obj = None

                # 타이머 제거 및 종료
                if getattr(self, "_timer", None):
                    context.window_manager.event_timer_remove(self._timer)
                    self._timer = None
                self._finish(context)
                return {"FINISHED"}

            # 파츠 당 분리 로직 실행
            before_count = (
                len(self._new_collection.objects) if self._new_collection else 0
            )
            separate_parts.separate_parts(
                self,
                context,
                getattr(self, "_target_obj", None),
                self._parts_map[self._index],
                self._new_collection,
            )
            after_count = (
                len(self._new_collection.objects) if self._new_collection else 0
            )
            created = max(0, after_count - before_count)
            if created:
                self._success_count += created
            else:
                self._skipped_count += 1
            self._index += 1
            return {"PASS_THROUGH"}

        # ESC 키로 모달 취소
        if event.type in {"ESC"}:
            if getattr(self, "_timer", None):
                context.window_manager.event_timer_remove(self._timer)
                self._timer = None
            self.report({"INFO"}, "파츠 분리 취소됨")
            return {"CANCELLED"}

        return {"RUNNING_MODAL"}

    def cancel(self, context):
        if getattr(self, "_timer", None):
            context.window_manager.event_timer_remove(self._timer)
            self._timer = None

    def _finish(self, context):
        # 간단한 정리 및 UI 갱신
        _force_ui_redraw()
        attempts = self._index + (
            1 if getattr(self, "_remaining_created", False) else 0
        )
        self.report(
            {"INFO"},
            f"파츠 분리 완료: 시도 {attempts}개, 생성 {self._success_count}개, 건너뜀 {self._skipped_count}개",
        )


classes = (
    INIPS_OT_SelectIniFile,
    INIPS_OT_SeparatePartsFromIniModal,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
