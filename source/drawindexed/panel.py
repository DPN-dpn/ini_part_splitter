import bpy
import bmesh
from bpy.types import Panel


class INIPS_PT_DrawIndexedPanel(Panel):
    bl_label = "DrawIndexed"
    bl_idname = "INIPS_PT_drawindexed_panel"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "파츠 분리"
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        layout = self.layout

        # drawIndexed 값 입력 박스
        box = layout.box()
        box.label(text="drawIndexed = ")
        row = box.row(align=True)
        # count 입력
        col_count = row.column()
        col_count.scale_x = 2.0
        col_count.prop(context.scene, "inips_drawindexed_count", text="", slider=False)
        # 첫 번째 쉼표
        col_comma1 = row.column()
        col_comma1.scale_x = 0.15
        col_comma1.label(text=",", icon="BLANK1")
        # start 입력
        col_start = row.column()
        col_start.scale_x = 2.0
        col_start.prop(context.scene, "inips_drawindexed_start", text="", slider=False)
        # 두 번째 쉼표
        col_comma2 = row.column()
        col_comma2.scale_x = 0.15
        col_comma2.label(text=",", icon="BLANK1")
        # 0 고정값
        col_zero = row.column()
        col_zero.scale_x = 0.2
        col_zero.label(text="0")

        # 매쉬 선택/추출 버튼
        box.operator("inips.select_drawindexed_mesh", text="매쉬 선택")


def register():
    bpy.utils.register_class(INIPS_PT_DrawIndexedPanel)


def unregister():
    bpy.utils.unregister_class(INIPS_PT_DrawIndexedPanel)
