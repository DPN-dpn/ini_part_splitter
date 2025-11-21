# 라이브러리 임포트
import bpy
import bmesh
from bpy.types import Operator, PropertyGroup, Panel, Scene


# 선택된 face로부터 DrawIndexed 값 추출 오퍼레이터
class OT_GetDrawIndexedFromSelection(Operator):
    bl_idname = "object.get_drawindexed_from_selection"
    bl_label = "drawIndexed 추출"
    bl_description = "선택된 face로부터 drawIndexed 값을 추출합니다"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        props = context.scene.drawindexed_props
        obj = context.active_object
        # 1. 메시 오브젝트 선택 확인
        if not obj or obj.type != "MESH":
            self.report({"ERROR"}, "메시 오브젝트를 선택하세요.")
            return {"CANCELLED"}

        mesh = obj.data
        # 2. EDIT 모드 전환 및 bmesh 준비
        bpy.ops.object.mode_set(mode="EDIT")
        bm = bmesh.from_edit_mesh(mesh)
        bm.faces.ensure_lookup_table()
        bm.verts.ensure_lookup_table()

        # 3. 인덱스 버퍼 추출 (삼각형만)
        index_buffer = []
        for poly in mesh.polygons:
            if len(poly.vertices) == 3:
                index_buffer.extend(poly.vertices)

        # 4. 선택된 face 확인
        selected_faces = [f for f in bm.faces if f.select]
        if not selected_faces:
            self.report({"ERROR"}, "선택된 face가 없습니다.")
            return {"CANCELLED"}

        # 5. 선택된 face의 버텍스 인덱스 추출
        face_indices_list = []
        for f in selected_faces:
            for v in f.verts:
                face_indices_list.append(v.index)

        # 6. 선택된 face와 일치하는 삼각형 블록 찾기
        face_indices_set = set(face_indices_list)
        tris = [index_buffer[i : i + 3] for i in range(0, len(index_buffer), 3)]
        selected_tri_indices = set(
            tuple(sorted([v.index for v in f.verts])) for f in selected_faces
        )

        tri_blocks = []
        for i, tri in enumerate(tris):
            if tuple(sorted(tri)) in selected_tri_indices:
                tri_blocks.append(i)

        # 7. 연속 구간으로 묶기
        if not tri_blocks:
            self.report(
                {"ERROR"},
                "선택된 face와 일치하는 삼각형을 index_buffer에서 찾지 못했습니다.",
            )
            return {"CANCELLED"}

        block_ranges = []
        block_start = tri_blocks[0]
        prev = tri_blocks[0]
        for idx in tri_blocks[1:]:
            if idx == prev + 1:
                prev = idx
            else:
                block_ranges.append((block_start, prev))
                block_start = idx
                prev = idx
        block_ranges.append((block_start, prev))

        # 8. DrawIndexed 슬라이스 정보로 변환
        block_infos = []
        for start_tri, end_tri in block_ranges:
            start_idx = start_tri * 3
            count = (end_tri - start_tri + 1) * 3
            block_infos.append({"start": start_idx, "count": count})

        # 9. 첫 번째 블록을 UI에 입력, 전체 블록 메시지 안내
        if block_infos:
            props.drawindexed_start = block_infos[0]["start"]
            props.drawindexed_count = block_infos[0]["count"]
            msg_lines = []
            for i, info in enumerate(block_infos):
                msg = f"DrawIndexed 블록 {i+1}: count={info['count']}, start={info['start']}"
                msg_lines.append(msg)
            self.report(
                {"INFO"},
                "선택된 face를 DrawIndexed로 변환 결과:\n" + "\n".join(msg_lines),
            )
        else:
            self.report({"ERROR"}, "선택된 face를 DrawIndexed로 변환할 수 없습니다.")
            return {"CANCELLED"}
        return {"FINISHED"}


# DrawIndexed 값으로 face 선택 오퍼레이터
class OT_SelectDrawIndexedMesh(Operator):
    bl_idname = "object.select_drawindexed_mesh"
    bl_label = "매쉬 선택"
    bl_description = "drawIndexed 값에 해당하는 face를 오브젝트에서 선택합니다"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        props = context.scene.drawindexed_props
        start = props.drawindexed_start
        count = props.drawindexed_count
        obj = context.active_object
        # 1. 메시 오브젝트가 선택되었는지 확인
        if not obj or obj.type != "MESH":
            self.report({"ERROR"}, "메시 오브젝트를 선택하세요.")
            return {"CANCELLED"}

        # 2. 메시 데이터 접근
        mesh = obj.data

        # 3. 인덱스 버퍼 추출 (삼각형만)
        index_buffer = []
        for poly in mesh.polygons:
            if len(poly.vertices) == 3:
                index_buffer.extend(poly.vertices)

        # 4. 입력 범위가 유효한지 확인
        if start < 0 or start + count > len(index_buffer):
            self.report({"ERROR"}, f"범위가 잘못되었습니다. (0~{len(index_buffer)})")
            return {"CANCELLED"}

        # 5. 선택할 인덱스 집합 생성
        selected_indices = set(index_buffer[start : start + count])

        # 6. EDIT 모드로 전환 및 bmesh 준비
        bpy.ops.object.mode_set(mode="EDIT")
        bm = bmesh.from_edit_mesh(mesh)
        bm.faces.ensure_lookup_table()
        bm.verts.ensure_lookup_table()

        # 7. face 순회하며 선택 인덱스 포함 여부로 선택 처리
        select_count = 0
        face_indices = []
        for f in bm.faces:
            if any(v.index in selected_indices for v in f.verts):
                f.select = True
                select_count += 1
                face_indices.extend([v.index for v in f.verts])
            else:
                f.select = False
        bmesh.update_edit_mesh(mesh)

        # 8. 디버그: index_buffer 슬라이스와 실제 선택된 face의 인덱스 집합 비교
        face_indices_set = set(face_indices)
        only_selected = selected_indices.issubset(
            face_indices_set
        ) and face_indices_set.issubset(selected_indices)
        if not only_selected:
            self.report(
                {"WARNING"},
                f"[디버그] index_buffer[{start}:{start+count}]의 인덱스와 실제 선택된 face의 인덱스가 완전히 일치하지 않습니다.\nindex_buffer 슬라이스 인덱스 수: {len(selected_indices)}, 선택된 face의 인덱스 수: {len(face_indices_set)}",
            )

        # 9. 최종 선택 결과 리포트
        self.report({"INFO"}, f"{select_count}개 face 선택 완료")
        return {"FINISHED"}


# DrawIndexed 패널 UI
class PT_DrawIndexedPanel(Panel):
    bl_label = "DrawIndexed"
    bl_idname = "VIEW3D_PT_drawindexed_panel"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "파츠 분리"
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        layout = self.layout
        props = context.scene.drawindexed_props
        # 1. drawIndexed 값 입력 박스
        box = layout.box()
        box.label(text="drawIndexed = ")
        row = box.row(align=True)
        # 2. count 입력
        col_count = row.column()
        col_count.scale_x = 2.0
        col_count.prop(props, "drawindexed_count", text="", slider=False)
        # 3. 첫 번째 쉼표
        col_comma1 = row.column()
        col_comma1.scale_x = 0.15
        col_comma1.label(text=",", icon="BLANK1")
        # 4. start 입력
        col_start = row.column()
        col_start.scale_x = 2.0
        col_start.prop(props, "drawindexed_start", text="", slider=False)
        # 5. 두 번째 쉼표
        col_comma2 = row.column()
        col_comma2.scale_x = 0.15
        col_comma2.label(text=",", icon="BLANK1")
        # 6. 0 고정값
        col_zero = row.column()
        col_zero.scale_x = 0.2
        col_zero.label(text="0")
        # 7. 매쉬 선택/추출 버튼
        box.operator("object.select_drawindexed_mesh", text="매쉬 선택")
        box.operator("object.get_drawindexed_from_selection", text="drawIndexed 추출")


# drawindexed에서 사용할 프로퍼티 그룹
class DrawindexedProperties(PropertyGroup):
    _temp = None


# 애드온 등록 함수
def register_drawindexed():
    for cls in classes:
        bpy.utils.register_class(cls)
    Scene.drawindexed_props = bpy.props.PointerProperty(type=DrawindexedProperties)
    DrawindexedProperties.drawindexed_start = bpy.props.IntProperty(
        name="DrawIndexed Start",
        description="drawindexed = ???, ???, 0 형식에서 두 번째 값",
        default=0,
        min=0,
        max=1000000000,
        step=1,
    )
    DrawindexedProperties.drawindexed_count = bpy.props.IntProperty(
        name="DrawIndexed Count",
        description="drawindexed = ???, ???, 0 형식에서 첫 번째 값",
        default=0,
        min=0,
        max=1000000000,
        step=1,
    )


# 애드온 해제 함수
def unregister_drawindexed():
    del Scene.drawindexed_props
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)


# Blender에 등록할 클래스 목록
classes = (
    PT_DrawIndexedPanel,
    DrawindexedProperties,
    OT_SelectDrawIndexedMesh,
    OT_GetDrawIndexedFromSelection,
)
