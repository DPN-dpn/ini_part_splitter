import bpy
import bmesh
from bpy.types import Operator
from ..utils.selector import select_indices_from_drawindexed


class INIPS_OT_SelectDrawIndexedMesh(Operator):
    bl_idname = "inips.select_drawindexed_mesh"
    bl_label = "매쉬 선택"
    bl_description = "drawIndexed 값에 해당하는 face를 오브젝트에서 선택합니다"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        obj = context.active_object
        start = context.scene.inips_drawindexed_start
        count = context.scene.inips_drawindexed_count

        # 오브젝트 선택 확인
        if not obj or obj.type != "MESH":
            self.report({"ERROR"}, "메시 오브젝트를 선택하세요.")
            return {"CANCELLED"}
        mesh = obj.data

        # 페이스 선택
        select_count, selected_indices, face_indices_set = (
            select_indices_from_drawindexed(mesh, start, count)
        )

        if select_count == 0:
            self.report({"WARNING"}, "선택된 face가 없습니다.")
            return {"CANCELLED"}
        else:
            self.report({"INFO"}, f"{select_count}개 face 선택 완료")
        return {"FINISHED"}


classes = (INIPS_OT_SelectDrawIndexedMesh,)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
