# 라이브러리 임포트
import bpy
import urllib.request
import json
import os
import urllib.request
import zipfile
import shutil
from bpy.types import Operator, Panel


def redraw_ui_regions(context):
    # 패널 강제 새로고침
    for window in context.window_manager.windows:
        for area in window.screen.areas:
            if area.type == "VIEW_3D":
                for region in area.regions:
                    if region.type == "UI":
                        region.tag_redraw()


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
                context.scene["show_restart"] = False
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

        redraw_ui_regions(context)
        return {"FINISHED"}


# 업데이트 실행
class OT_DoUpdate(Operator):
    bl_idname = "updater.do_update"
    bl_label = "업데이트"
    bl_description = "애드온을 최신 버전으로 업데이트합니다"

    def execute(self, context):
        try:
            # 최신 릴리스 정보 가져오기
            url = (
                "https://api.github.com/repos/DPN-dpn/ini_part_splitter/releases/latest"
            )
            with urllib.request.urlopen(url, timeout=5) as response:
                data = json.loads(response.read().decode())
                assets = data.get("assets", [])
                zip_url = ""
                for asset in assets:
                    if asset["name"].endswith(".zip"):
                        zip_url = asset["browser_download_url"]
                        break
                if not zip_url:
                    self.report({"ERROR"}, "릴리스 zip 파일을 찾을 수 없습니다.")
                    return {"CANCELLED"}

            # 다운로드 경로 설정
            addon_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            print(addon_dir)
            addons_dir = os.path.dirname(addon_dir)
            print(addons_dir)
            zip_path = os.path.join(addons_dir, "ini_part_splitter_update.zip")

            # zip 파일 다운로드
            urllib.request.urlretrieve(zip_url, zip_path)

            # 폴더 비우기
            for filename in os.listdir(addon_dir):
                file_path = os.path.join(addon_dir, filename)
                try:
                    if os.path.isfile(file_path) or os.path.islink(file_path):
                        os.remove(file_path)
                    elif os.path.isdir(file_path):
                        shutil.rmtree(file_path)
                except Exception as e:
                    self.report({"ERROR"}, f"{file_path} 폴더를 비우지 못했습니다.")

            # zip 파일 압축 해제 (애드온 폴더에 덮어쓰기)
            with zipfile.ZipFile(zip_path, "r") as zip_ref:
                zip_ref.extractall(addon_dir)

            # zip 파일 삭제
            os.remove(zip_path)

            self.report({"WARNING"}, "블렌더를 재시작해, 애드온을 새로고침해 주세요.")
            context.scene["show_restart"] = True
            redraw_ui_regions(context)
            return {"FINISHED"}

        except Exception as e:
            self.report({"ERROR"}, f"업데이트 실패: {e}")
            context.scene["show_restart"] = False
            return {"CANCELLED"}


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
        show_restart = scene.get("show_restart", False)

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
        if show_restart:
            row.operator("wm.quit_blender", text="블렌더 재시작", icon="CANCEL")
        else:
            row.enabled = bool(update_available)
            row.operator("updater.do_update", text=update_label, icon="IMPORT")
        layout.operator("updater.open_github", text="GitHub", icon="URL")


# 애드온 등록 함수
def register_updater():
    for cls in classes:
        bpy.utils.register_class(cls)


# 애드온 해제 함수
def unregister_updater():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)


# Blender에 등록할 클래스 목록
classes = (
    PT_UpdaterPanel,
    OT_CheckUpdate,
    OT_DoUpdate,
    OT_OpenGithub,
)
