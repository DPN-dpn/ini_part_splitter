# 라이브러리 임포트
import bpy
import urllib.request
import json
from bpy.types import Operator, Panel, PropertyGroup, Scene


# 업데이트 체크
class OT_CheckUpdate(Operator):
    bl_idname = "updater.check_update"
    bl_label = "업데이트 체크"
    bl_description = "최신 버전이 있는지 확인합니다"

    def execute(self, context):
        try:
            url = (
                "https://api.github.com/repos/DPN-dpn/ini_part_splitter/releases/latest"
            )
            with urllib.request.urlopen(url, timeout=5) as response:
                data = json.loads(response.read().decode())
                latest_version = data.get("tag_name", "").lstrip("v")
                context.scene["latest_version"] = latest_version
                # 현재 버전 가져오기
                from .. import bl_info

                current_version = ".".join(map(str, bl_info["version"]))
                context.scene["current_version"] = current_version
                if latest_version and latest_version != current_version:
                    context.scene["update_available"] = True
                    self.report(
                        {"INFO"}, f"업데이트 가능: {current_version} → {latest_version}"
                    )
                else:
                    context.scene["update_available"] = False
                    self.report({"INFO"}, "최신 버전입니다.")
        except Exception as e:
            context.scene["update_available"] = False
            self.report({"ERROR"}, f"업데이트 확인 실패: {e}")

        # 패널 강제 새로고침
        for window in context.window_manager.windows:
            for area in window.screen.areas:
                if area.type == "VIEW_3D":
                    for region in area.regions:
                        if region.type == "UI":
                            region.tag_redraw()
        return {"FINISHED"}


# 업데이트 실행
class OT_DoUpdate(Operator):
    bl_idname = "updater.do_update"
    bl_label = "업데이트"
    bl_description = "애드온을 최신 버전으로 업데이트합니다"

    def execute(self, context):
        updater = context.scene.updater_props
        if not bool(context.scene.get("update_available", False)):
            self.report({"INFO"}, "업데이트가 필요하지 않습니다.")
            return {"CANCELLED"}
        self.report({"WARNING"}, "업데이트 기능은 추후 구현 예정입니다.")
        return {"FINISHED"}


# GitHub 이동
class OT_OpenGithub(Operator):
    bl_idname = "updater.open_github"
    bl_label = "GitHub"
    bl_description = "애드온의 GitHub 페이지를 엽니다"

    def execute(self, context):
        import webbrowser

        webbrowser.open("https://github.com/DPN-dpn/ini_part_splitter")
        self.report({"INFO"}, "ini_part_splitter GitHub 페이지를 엽니다.")
        return {"FINISHED"}


# 업데이터 패널 UI
class PT_UpdaterPanel(Panel):
    bl_label = "업데이트"
    bl_idname = "VIEW3D_PT_updater_panel"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "파츠 분리"
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        layout = self.layout
        scene = context.scene
        latest_version = scene.get("latest_version", "")
        current_version = scene.get("current_version", "")
        update_available = scene.get("update_available", False)
        
        # 버튼 라벨 조건 분기
        if not latest_version:
            update_label = "업데이트 체크 필요"
        elif not update_available:
            update_label = "현재 최신 버전입니다"
        else:
            update_label = f"업데이트: {current_version} → {latest_version}"
        
        layout.operator(
            "updater.check_update", text="업데이트 체크", icon="FILE_REFRESH"
        )
        row = layout.row()
        row.enabled = bool(update_available)
        row.operator("updater.do_update", text=update_label, icon="IMPORT")
        layout.operator("updater.open_github", text="GitHub", icon="URL")


# 애드온 등록 함수
def register_updater():
    for cls in classes:
        bpy.utils.register_class(cls)


# 애드온 해제 함수
def unregister_updater():
    del Scene.updater_props
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)


# Blender에 등록할 클래스 목록
classes = (
    PT_UpdaterPanel,
    OT_CheckUpdate,
    OT_DoUpdate,
    OT_OpenGithub,
)
