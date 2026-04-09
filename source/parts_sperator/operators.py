import bpy
from bpy.types import Operator
from bpy_extras.io_utils import ImportHelper
import os
from ..utils.ini_parser import parse_ini_sections
from .functions import defunctionalize, create_resource_enum, build_parts_map


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
    _parts_map = []

    def invoke(self, context, event):
        scene = context.scene

        # 기본 검증 및 초기화
        ini_path = getattr(scene, "inips_ini_path", None)
        resource = getattr(scene, "inips_resource", None)
        if not ini_path or not resource:
            self.report({"ERROR"}, "INI 파일과 Resource를 선택하세요.")
            return {"CANCELLED"}

        self._parts_map = build_parts_map({}, "")
        self._index = 0

        wm = context.window_manager
        self._timer = wm.event_timer_add(0.1, window=context.window)
        wm.modal_handler_add(self)
        return {"RUNNING_MODAL"}

    def modal(self, context, event):
        if event.type == "TIMER":
            if self._index >= len(self._parts_map):
                if getattr(self, "_timer", None):
                    context.window_manager.event_timer_remove(self._timer)
                    self._timer = None
                self._finish(context)
                return {"FINISHED"}

            # TODO: 한 파트 처리 구현(메인 스레드에서 bpy 안전 호출)
            # self._process_part(context, self._parts_map[self._index])
            self._index += 1
            return {"PASS_THROUGH"}

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

    def _process_part(self, context, part):
        # TODO: 실제 분리 로직을 여기에 구현 (bpy 호출 허용)
        pass

    def _finish(self, context):
        # 간단한 정리 및 UI 갱신
        for window in context.window_manager.windows:
            for area in window.screen.areas:
                if area.type == "VIEW_3D":
                    area.tag_redraw()
        self.report({"INFO"}, f"파츠 분리 완료: {self._index}개 처리됨")


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
