import bpy
from bpy.types import Panel


class INIPS_PT_PartsSeperatorPanel(Panel):
    bl_label = "INI 파츠 분리"
    bl_idname = "INIPS_PT_parts_seperator_panel"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "파츠 분리"

    def draw(self, context):
        layout = self.layout
        ini_path = context.scene.inips_ini_path
        resource = context.scene.inips_resource

        # INI 파일 열기 버튼
        layout.operator("inips.select_ini_file_panel", text="INI 파일 열기")

        # INI 파일 경로와 리소스 선택 표시
        if ini_path:
            layout.label(text=f"INI: {ini_path.split('/')[-1]}")
            layout.prop(context.scene, "inips_resource")

        # 파츠 분리 버튼 활성화 조건
        obj = context.active_object
        enable_button = (
            obj is not None
            and obj.type == "MESH"
            and bool(ini_path.strip())
            and bool(resource.strip())
        )

        # 파츠 분리 버튼
        row = layout.row()
        row.enabled = enable_button
        row.operator("inips.separate_parts_from_ini_modal", text="파츠 분리")


classes = (INIPS_PT_PartsSeperatorPanel,)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
