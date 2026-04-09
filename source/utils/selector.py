import bpy, bmesh


def select_indices_from_drawindexed(mesh, start, count):
    """
    drawIndexed 인덱스 버퍼의 [start:start+count) 구간에 포함된 정점 인덱스를 기준으로
    해당 정점을 포함하는 face들을 선택합니다.

    Args:
        mesh (bpy.types.Mesh): 보통 `obj.data`
        start (int), count (int)
        ensure_edit_mode (bool): True면 함수가 편집 모드로 전환/복귀 처리함

    Returns:
        (select_count, selected_vertex_indices_set, selected_face_vertex_indices_set)
    Raises:
        ValueError: 범위가 유효하지 않을 때
    """

    if count <= 0:
        return 0, set(), set()

    # loop triangles 기준으로 삼각형 범위 계산
    mesh.calc_loop_triangles()
    tris = mesh.loop_triangles
    total_indices = len(tris) * 3
    if start < 0 or start + count > total_indices:
        raise ValueError(f"Invalid drawIndexed range (0~{total_indices}).")

    first_tri = start // 3
    last_tri = (start + count - 1) // 3

    # 선택된 삼각형이 소속된 폴리곤 인덱스와, 범위에 등장하는 정점 인덱스 집합
    selected_poly_indices = {
        tris[i].polygon_index for i in range(first_tri, last_tri + 1)
    }
    selected_indices = set()
    for i in range(first_tri, last_tri + 1):
        selected_indices.update(tris[i].vertices)

    # 편집 모드로 전환(요청된 경우)
    obj = bpy.context.active_object
    prev_mode = obj.mode if obj else None
    if prev_mode != "EDIT":
        bpy.ops.object.mode_set(mode="EDIT")

    bm = bmesh.from_edit_mesh(mesh)
    bm.faces.ensure_lookup_table()
    bm.verts.ensure_lookup_table()

    select_count = 0
    face_vertex_indices = set()
    for f in bm.faces:
        if f.index in selected_poly_indices:
            f.select = True
            select_count += 1
            for v in f.verts:
                face_vertex_indices.add(v.index)
        else:
            f.select = False

    bmesh.update_edit_mesh(mesh)

    return select_count, selected_indices, face_vertex_indices
