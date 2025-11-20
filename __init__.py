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

# 라이브러리 임포트
import bpy
from .source.parts_seperator import INIResourceProperties,PT_IBResourceSelector, OT_SelectIniFile, OT_SeparatePartsFromIniModal
from .source.drawindexed import PT_DrawIndexedPanel, OT_SelectDrawIndexedMesh, OT_GetDrawIndexedFromSelection
from .source.updater import PT_UpdaterPanel, OT_CheckUpdate, OT_DoUpdate, OT_OpenGithub

# Blender에 등록할 클래스 목록
classes = (
    INIResourceProperties,
    OT_SelectIniFile,
    OT_SeparatePartsFromIniModal,
    PT_IBResourceSelector,
    PT_DrawIndexedPanel,
    OT_SelectDrawIndexedMesh,
    OT_GetDrawIndexedFromSelection,
    PT_UpdaterPanel,
    OT_CheckUpdate,
    OT_DoUpdate,
    OT_OpenGithub,
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
