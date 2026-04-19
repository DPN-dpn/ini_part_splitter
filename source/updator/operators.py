import bpy
from bpy.types import Operator
import urllib.request
import json
import os
import urllib.request
import zipfile
import shutil
import tempfile


def _redraw_ui_regions(context):
    # 패널 강제 새로고침
    for window in context.window_manager.windows:
        for area in window.screen.areas:
            if area.type == "VIEW_3D":
                for region in area.regions:
                    if region.type == "UI":
                        region.tag_redraw()


# 업데이트 체크
class INIPS_OT_CheckUpdate(Operator):
    bl_idname = "inips.check_update"
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
                context.scene["inips.latest_version"] = latest_version
                # 현재 버전 가져오기
                from ... import bl_info

                current_version = ".".join(map(str, bl_info["version"]))
                context.scene["inips.current_version"] = current_version
                context.scene["inips.show_restart"] = False
                if latest_version and latest_version != current_version:
                    context.scene["inips.update_available"] = True
                    self.report(
                        {"INFO"}, f"업데이트 가능: {current_version} → {latest_version}"
                    )
                else:
                    context.scene["inips.update_available"] = False
                    self.report({"INFO"}, "최신 버전입니다.")
        except Exception as e:
            context.scene["inips.update_available"] = False
            self.report({"ERROR"}, f"업데이트 확인 실패: {e}")

        _redraw_ui_regions(context)
        return {"FINISHED"}


# 업데이트 실행
class INIPS_OT_DoUpdate(Operator):
    bl_idname = "inips.do_update"
    bl_label = "업데이트"
    bl_description = "애드온을 최신 버전으로 업데이트합니다"

    def execute(self, context):
        temp_dir = None
        try:
            url = "https://api.github.com/repos/DPN-dpn/ini_part_splitter/releases/latest"
            with urllib.request.urlopen(url, timeout=5) as response:
                data = json.loads(response.read().decode())
                assets = data.get("assets", [])
                zip_url = ""
                zip_name = ""
                for asset in assets:
                    name = asset.get("name", "")
                    if name.endswith(".zip"):
                        zip_name = name
                        zip_url = asset.get("browser_download_url", "")
                        break
                if not zip_url:
                    self.report({"ERROR"}, "릴리스 zip 파일을 찾을 수 없습니다.")
                    return {"CANCELLED"}

            addon_name = os.path.splitext(zip_name)[0]
            
            # 애드온 폴더 찾기
            current_dir = os.path.dirname(os.path.abspath(__file__))
            addons_root = None
            cur = current_dir
            while True:
                if os.path.basename(cur).lower() == "addons":
                    addons_root = cur
                    break
                parent = os.path.dirname(cur)
                if parent == cur:
                    break
                cur = parent

            if addons_root:
                addon_dir = os.path.join(addons_root, addon_name)
            else:
                # 찾지 못하면 기존 동작(현재 애드온 폴더)으로 폴백
                addon_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

            temp_dir = tempfile.mkdtemp(prefix="dpn_update_")
            zip_path = os.path.join(temp_dir, zip_name or "update.zip")
            urllib.request.urlretrieve(zip_url, zip_path)

            extract_dir = os.path.join(temp_dir, "extracted")
            os.makedirs(extract_dir, exist_ok=True)
            with zipfile.ZipFile(zip_path, "r") as zip_ref:
                zip_ref.extractall(extract_dir)

            # 압축 내부에서 한 단계 들어가서 addon_name 폴더 찾기
            entries = os.listdir(extract_dir)
            if not entries:
                raise Exception("압축을 풀었으나 내부에 항목이 없습니다.")

            new_addon_src = None
            if len(entries) == 1 and os.path.isdir(os.path.join(extract_dir, entries[0])):
                first_level = os.path.join(extract_dir, entries[0])
                candidate = os.path.join(first_level, addon_name)
                if os.path.isdir(candidate):
                    new_addon_src = candidate
                elif os.path.basename(first_level) == addon_name:
                    new_addon_src = first_level

            if not new_addon_src:
                for root, dirs, _files in os.walk(extract_dir):
                    if addon_name in dirs:
                        new_addon_src = os.path.join(root, addon_name)
                        break

            if not new_addon_src:
                self.report({"ERROR"}, f"새 버전 애드온 폴더({addon_name})를 찾지 못했습니다.")
                shutil.rmtree(temp_dir, ignore_errors=True)
                return {"CANCELLED"}

            # 기존 애드온 폴더 내부를 삭제
            if os.path.exists(addon_dir):
                for name in os.listdir(addon_dir):
                    target = os.path.join(addon_dir, name)
                    try:
                        if os.path.isfile(target) or os.path.islink(target):
                            os.remove(target)
                        elif os.path.isdir(target):
                            shutil.rmtree(target)
                    except Exception as e:
                        self.report({"ERROR"}, f"{target} 삭제 실패: {e}")
                        shutil.rmtree(temp_dir, ignore_errors=True)
                        return {"CANCELLED"}

            # 새 버전의 내부 항목들을 애드온 폴더로 이동
            for name in os.listdir(new_addon_src):
                src = os.path.join(new_addon_src, name)
                dst = os.path.join(addon_dir, name)
                try:
                    shutil.move(src, dst)
                except Exception as e:
                    self.report({"ERROR"}, f"{src} 이동 실패: {e}")
                    shutil.rmtree(temp_dir, ignore_errors=True)
                    return {"CANCELLED"}

            if os.path.exists(zip_path):
                os.remove(zip_path)
            shutil.rmtree(temp_dir, ignore_errors=True)

            self.report({"WARNING"}, "블렌더를 재시작해, 애드온을 새로고침해 주세요.")
            context.scene["inips.show_restart"] = True
            _redraw_ui_regions(context)
            return {"FINISHED"}

        except Exception as e:
            if temp_dir:
                shutil.rmtree(temp_dir, ignore_errors=True)
            self.report({"ERROR"}, f"업데이트 실패: {e}")
            context.scene["inips.show_restart"] = False
            return {"CANCELLED"}


# GitHub 이동
class INIPS_OT_OpenGithub(Operator):
    bl_idname = "inips.open_github"
    bl_label = "GitHub"
    bl_description = "애드온의 GitHub 페이지를 엽니다"

    def execute(self, context):
        import webbrowser

        webbrowser.open("https://github.com/DPN-dpn/ini_part_splitter")
        self.report({"INFO"}, "ini_part_splitter GitHub 페이지를 엽니다.")
        return {"FINISHED"}


classes = (
    INIPS_OT_CheckUpdate,
    INIPS_OT_DoUpdate,
    INIPS_OT_OpenGithub,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
