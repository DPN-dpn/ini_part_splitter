import bpy
import bmesh
from ...utils.selector import select_indices_from_drawindexed


def separate_parts(self, context, obj, part, collection):
    if obj is None or obj.type != "MESH":
        return

    name = part.get("name") if isinstance(part, dict) else getattr(part, "name", None)
    if not name:
        name = "part"

    start_index = (
        int(part.get("start_index", 0))
        if isinstance(part, dict)
        else int(getattr(part, "start_index", 0) or 0)
    )
    index_count = (
        int(part.get("index_count", 0))
        if isinstance(part, dict)
        else int(getattr(part, "index_count", 0) or 0)
    )

    if index_count <= 0:
        return

    # 상태 보존
    old_active = context.view_layer.objects.active
    old_selected = [o for o in context.selected_objects]

    # 오브젝트 복제 (데이터 복사)
    dup_obj = obj.copy()
    dup_obj.data = obj.data.copy()
    dup_obj.matrix_world = obj.matrix_world
    link_col = obj.users_collection[0] if obj.users_collection else context.collection
    link_col.objects.link(dup_obj)

    # 이름/참조는 문자열로 저장(삭제된 RNA에 접근하는 오류 방지)
    dup_name = dup_obj.name
    mesh_name = dup_obj.data.name
    _mesh_to_remove = dup_obj.data
    _mats_to_check = [m.name for m in _mesh_to_remove.materials if m is not None]

    # 선택/활성 설정
    try:
        bpy.ops.object.select_all(action="DESELECT")
    except Exception:
        for o in context.view_layer.objects:
            o.select_set(False)
    dup_obj.select_set(True)
    context.view_layer.objects.active = dup_obj

    try:
        # 인덱스 범위에 해당하는 face 선택
        try:
            select_count, _, _ = select_indices_from_drawindexed(
                dup_obj.data, start_index, index_count
            )
        except Exception as e:
            reporter = getattr(self, "report", None)
            if reporter:
                reporter({"WARNING"}, f"Invalid drawIndexed range for part {name}: {e}")
            bpy.ops.object.mode_set(mode="OBJECT")

            # 안전하게 dup 오브젝트 삭제 (이름으로 조회)
            obj_to_del = bpy.data.objects.get(dup_name)
            if obj_to_del:
                try:
                    bpy.ops.object.select_all(action="DESELECT")
                except Exception:
                    for o in context.view_layer.objects:
                        o.select_set(False)
                obj_to_del.select_set(True)
                context.view_layer.objects.active = obj_to_del
                try:
                    bpy.ops.object.delete()
                except Exception:
                    bpy.data.objects.remove(obj_to_del, do_unlink=True)

            mesh = bpy.data.meshes.get(mesh_name)
            if mesh and mesh.users == 0:
                bpy.data.meshes.remove(mesh)
            for mname in _mats_to_check:
                m = bpy.data.materials.get(mname)
                if m and m.users == 0:
                    bpy.data.materials.remove(m)
            return

        # 선택된 face가 없으면 복제 삭제 후 종료
        if select_count == 0:
            bpy.ops.object.mode_set(mode="OBJECT")
            obj_to_del = bpy.data.objects.get(dup_name)
            if obj_to_del:
                try:
                    bpy.ops.object.select_all(action="DESELECT")
                except Exception:
                    for o in context.view_layer.objects:
                        o.select_set(False)
                obj_to_del.select_set(True)
                context.view_layer.objects.active = obj_to_del
                try:
                    bpy.ops.object.delete()
                except Exception:
                    bpy.data.objects.remove(obj_to_del, do_unlink=True)
            mesh = bpy.data.meshes.get(mesh_name)
            if mesh and mesh.users == 0:
                bpy.data.meshes.remove(mesh)
            for mname in _mats_to_check:
                m = bpy.data.materials.get(mname)
                if m and m.users == 0:
                    bpy.data.materials.remove(m)
            return

        # 선택된 면 분리
        bpy.ops.mesh.separate(type="SELECTED")
        bpy.ops.object.mode_set(mode="OBJECT")

        # 분리된 오브젝트들에 이름 지정 (중복 방지)
        separated = [o for o in context.selected_objects if o != dup_obj]
        if separated:
            if len(separated) == 1:
                base_name = name
                if base_name in bpy.data.objects:
                    i = 1
                    while f"{base_name}_{i}" in bpy.data.objects:
                        i += 1
                    base_name = f"{base_name}_{i}"
                separated[0].name = base_name
            else:
                for i, o in enumerate(separated, start=1):
                    base_name = f"{name}_{i}"
                    if base_name in bpy.data.objects:
                        j = 1
                        while f"{base_name}_{j}" in bpy.data.objects:
                            j += 1
                        base_name = f"{base_name}_{j}"
                    o.name = base_name

            # 컬렉션 이동
            scene_col = getattr(self, "_scene_collection", None)
            if collection:
                for o in separated:
                    # unlink from scene collection (best-effort)
                    for col in list(o.users_collection):
                        if scene_col and col.name == scene_col.name:
                            try:
                                col.objects.unlink(o)
                            except Exception:
                                pass
                    # link to new collection if not already linked
                    if o.name not in [obj.name for obj in collection.objects]:
                        collection.objects.link(o)

    finally:
        # 복제 오브젝트 삭제 및 데이터/머티리얼 정리 (이름으로 안전 조회)
        try:
            bpy.ops.object.select_all(action="DESELECT")
        except Exception:
            for o in context.view_layer.objects:
                o.select_set(False)

        obj_to_del = bpy.data.objects.get(dup_name)
        if obj_to_del:
            obj_to_del.select_set(True)
            context.view_layer.objects.active = obj_to_del
            try:
                bpy.ops.object.delete()
            except Exception:
                bpy.data.objects.remove(obj_to_del, do_unlink=True)

        mesh = bpy.data.meshes.get(mesh_name)
        if mesh and mesh.users == 0:
            bpy.data.meshes.remove(mesh)

        for mname in _mats_to_check:
            m = bpy.data.materials.get(mname)
            if m and m.users == 0:
                bpy.data.materials.remove(m)

        # 이전 선택/활성 상태 복원
        try:
            bpy.ops.object.select_all(action="DESELECT")
        except Exception:
            for o in context.view_layer.objects:
                o.select_set(False)

        if old_active and old_active.name in bpy.data.objects:
            old_active.select_set(True)
            context.view_layer.objects.active = old_active
        else:
            for o in old_selected:
                if o.name in bpy.data.objects:
                    bpy.data.objects[o.name].select_set(True)


def create_remaining_part(self, context, obj, parts_map, collection):
    if not obj or not parts_map:
        return 0

    # 상태 보존
    old_active = context.view_layer.objects.active
    old_selected = [o for o in context.selected_objects]

    # 오브젝트 복제 (데이터 복사)
    dup_obj = obj.copy()
    dup_obj.data = obj.data.copy()
    dup_obj.matrix_world = obj.matrix_world
    link_col = obj.users_collection[0] if obj.users_collection else context.collection
    link_col.objects.link(dup_obj)

    dup_name = dup_obj.name
    mesh_name = dup_obj.data.name
    _mesh_to_remove = dup_obj.data
    _mats_to_check = [m.name for m in _mesh_to_remove.materials if m is not None]

    created_count = 0

    try:
        try:
            bpy.ops.object.select_all(action="DESELECT")
        except Exception:
            for o in context.view_layer.objects:
                o.select_set(False)
        dup_obj.select_set(True)
        context.view_layer.objects.active = dup_obj

        # parts_map 전체의 폴리곤 인덱스 합집합 계산
        mesh = dup_obj.data
        mesh.calc_loop_triangles()
        tris = mesh.loop_triangles
        total_indices = len(tris) * 3

        selected_poly_indices = set()
        for part in parts_map:
            if isinstance(part, dict):
                start = int(part.get("start_index", 0))
                count = int(part.get("index_count", 0))
            else:
                start = int(getattr(part, "start_index", 0) or 0)
                count = int(getattr(part, "index_count", 0) or 0)
            if count <= 0:
                continue
            if start < 0 or start + count > total_indices:
                reporter = getattr(self, "report", None)
                pname = (
                    part.get("name")
                    if isinstance(part, dict)
                    else getattr(part, "name", None)
                )
                if reporter:
                    reporter(
                        {"WARNING"},
                        f"Invalid drawIndexed range for part {pname}: {start},{count}",
                    )
                continue
            first_tri = start // 3
            last_tri = (start + count - 1) // 3
            for i in range(first_tri, last_tri + 1):
                selected_poly_indices.add(tris[i].polygon_index)

        if not selected_poly_indices:
            # 선택된 폴리곤이 없다면 복제 삭제 후 종료
            bpy.ops.object.mode_set(mode="OBJECT")
            obj_to_del = bpy.data.objects.get(dup_name)
            if obj_to_del:
                try:
                    bpy.ops.object.select_all(action="DESELECT")
                except Exception:
                    for o in context.view_layer.objects:
                        o.select_set(False)
                obj_to_del.select_set(True)
                context.view_layer.objects.active = obj_to_del
                try:
                    bpy.ops.object.delete()
                except Exception:
                    bpy.data.objects.remove(obj_to_del, do_unlink=True)
            mesh_ref = bpy.data.meshes.get(mesh_name)
            if mesh_ref and mesh_ref.users == 0:
                bpy.data.meshes.remove(mesh_ref)
            for mname in _mats_to_check:
                m = bpy.data.materials.get(mname)
                if m and m.users == 0:
                    bpy.data.materials.remove(m)
            return 0

        # 편집모드로 전환하여 폴리곤 선택
        bpy.ops.object.mode_set(mode="EDIT")
        bm = bmesh.from_edit_mesh(mesh)
        bm.faces.ensure_lookup_table()
        for f in bm.faces:
            f.select = f.index in selected_poly_indices
        bmesh.update_edit_mesh(mesh)

        # 선택된 면 분리 -> 선택된 오브젝트(부분)들을 삭제하고 남은 오브젝트를 남김
        bpy.ops.mesh.separate(type="SELECTED")
        bpy.ops.object.mode_set(mode="OBJECT")

        separated = [o for o in context.selected_objects if o != dup_obj]
        # 분리된 오브젝트들 삭제(파츠로 이미 처리된 것들이므로 제거)
        for so in separated:
            try:
                bpy.ops.object.select_all(action="DESELECT")
            except Exception:
                for o in context.view_layer.objects:
                    o.select_set(False)
            if so.name in bpy.data.objects:
                so.select_set(True)
                context.view_layer.objects.active = so
                try:
                    bpy.ops.object.delete()
                except Exception:
                    bpy.data.objects.remove(so, do_unlink=True)

        remaining = bpy.data.objects.get(dup_name)
        if remaining:
            # 남은 오브젝트에 지오메트리가 있는지 확인
            has_geo = False
            try:
                if getattr(remaining, "data", None):
                    remaining.data.calc_loop_triangles()
                    if len(remaining.data.polygons) > 0:
                        has_geo = True
            except Exception:
                if getattr(remaining, "data", None) and len(remaining.data.vertices) > 0:
                    has_geo = True

            if not has_geo:
                # 지오메트리가 없는 경우 오브젝트 삭제
                try:
                    bpy.ops.object.select_all(action="DESELECT")
                except Exception:
                    for o in context.view_layer.objects:
                        o.select_set(False)
                if remaining.name in bpy.data.objects:
                    remaining.select_set(True)
                    context.view_layer.objects.active = remaining
                    try:
                        bpy.ops.object.delete()
                    except Exception:
                        bpy.data.objects.remove(remaining, do_unlink=True)
                mesh_ref = bpy.data.meshes.get(mesh_name)
                if mesh_ref and mesh_ref.users == 0:
                    bpy.data.meshes.remove(mesh_ref)
                for mname in _mats_to_check:
                    m = bpy.data.materials.get(mname)
                    if m and m.users == 0:
                        bpy.data.materials.remove(m)
                created_count = 0
            else:
                # 남은 오브젝트 이름 중복 방지 및 컬렉션 이동
                base_name = "part_remaining"
                if base_name in bpy.data.objects and remaining.name != base_name:
                    i = 1
                    while f"{base_name}_{i}" in bpy.data.objects:
                        i += 1
                    base_name = f"{base_name}_{i}"
                remaining.name = base_name

                scene_col = getattr(self, "_scene_collection", None)
                if collection:
                    for col in list(remaining.users_collection):
                        if scene_col and col.name == scene_col.name:
                            col.objects.unlink(remaining)
                    if remaining.name not in [obj.name for obj in collection.objects]:
                        collection.objects.link(remaining)
                created_count = 1

    finally:
        # 데이터/머티리얼 정리
        mesh_ref = bpy.data.meshes.get(mesh_name)
        if mesh_ref and mesh_ref.users == 0:
            bpy.data.meshes.remove(mesh_ref)
        for mname in _mats_to_check:
            m = bpy.data.materials.get(mname)
            if m and m.users == 0:
                bpy.data.materials.remove(m)

        # 이전 선택/활성 상태 복원
        try:
            bpy.ops.object.select_all(action="DESELECT")
        except Exception:
            for o in context.view_layer.objects:
                o.select_set(False)

        if old_active and old_active.name in bpy.data.objects:
            old_active.select_set(True)
            context.view_layer.objects.active = old_active
        else:
            for o in old_selected:
                if o.name in bpy.data.objects:
                    bpy.data.objects[o.name].select_set(True)
                    
    return created_count
