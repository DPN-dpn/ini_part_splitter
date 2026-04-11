import bpy
from bpy.props import BoolProperty

class XXMI_FILEBROWSER_PT_raw_options(bpy.types.Panel):
    bl_label = "INI 파츠 분리 옵션"
    bl_space_type = 'FILE_BROWSER'
    bl_region_type = 'TOOL_PROPS'
    bl_category = "XXMI"

    @classmethod
    def poll(cls, context):
        space = context.space_data
        if not space:
            return False
        active_op = getattr(space, "active_operator", None)
        if not active_op:
            return False
        # 체크할 수 있도록 기본 bl_idname(문자열)과 RNA 형식을 둘 다 허용
        op_id = getattr(active_op, "bl_idname", "")
        return op_id in (
            "import_mesh.migoto_raw_buffers",
            "IMPORT_MESH_OT_migoto_raw_buffers",
        )

    def draw(self, context):
        layout = self.layout
        wm = context.window_manager
        layout.prop(wm, "xxmi_raw_checkbox")


classes = (XXMI_FILEBROWSER_PT_raw_options,)


def register():
    if not hasattr(bpy.types.WindowManager, "xxmi_raw_checkbox"):
        bpy.types.WindowManager.xxmi_raw_checkbox = BoolProperty(
            name="XXMI 체크박스",
            description="임시 체크박스 — 동작은 나중에 구현합니다",
            default=False,
        )
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
    if hasattr(bpy.types.WindowManager, "xxmi_raw_checkbox"):
        del bpy.types.WindowManager.xxmi_raw_checkbox