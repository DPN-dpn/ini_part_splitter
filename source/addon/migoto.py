import bpy
from bpy.props import BoolProperty
import importlib
import collections


class INIPS_PT_Addon_Migoto(bpy.types.Panel):
    bl_label = "INI 파츠 분리 옵션"
    bl_space_type = "FILE_BROWSER"
    bl_region_type = "TOOL_PROPS"
    bl_category = "Migoto"

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
        layout.prop(wm, "inips_addon_migoto")


classes = (INIPS_PT_Addon_Migoto,)


def _apply_xxmi_adapter():
    try:
        mi = importlib.import_module("XXMITools.migoto.import_ops")
    except Exception:
        return
    if hasattr(mi, "_xxmi_orig_import_3dmigoto_vb_ib"):
        return

    mi._xxmi_orig_import_3dmigoto_vb_ib = mi.import_3dmigoto_vb_ib

    def _xxmi_import_3dmigoto_vb_ib(
        operator,
        context,
        paths,
        flip_texcoord_v: bool = True,
        flip_winding: bool = False,
        flip_mesh: bool = False,
        flip_normal: bool = False,
        axis_forward="-Z",
        axis_up="Y",
        pose_cb_off=[0, 0],
        pose_cb_step=1,
        merge_verts: bool = False,
        tris_to_quads: bool = False,
        clean_loose: bool = False,
    ):
        # 체크박스가 꺼져있으면 원본 동작 호출
        wm = bpy.context.window_manager
        if not getattr(wm, "inips_addon_migoto", False):
            return mi._xxmi_orig_import_3dmigoto_vb_ib(
                operator,
                context,
                paths,
                flip_texcoord_v=flip_texcoord_v,
                flip_winding=flip_winding,
                flip_mesh=flip_mesh,
                flip_normal=flip_normal,
                axis_forward=axis_forward,
                axis_up=axis_up,
                pose_cb_off=pose_cb_off,
                pose_cb_step=pose_cb_step,
                merge_verts=merge_verts,
                tris_to_quads=tris_to_quads,
                clean_loose=clean_loose,
            )

        # 체크박스가 켜져있으면 패치된 동작 적용 (원본 함수를 복제한 형태)
        vb, ib, name, pose_path = mi.load_3dmigoto_mesh(operator, paths)

        mesh = bpy.data.meshes.new(name)
        obj = bpy.data.objects.new(mesh.name, mesh)

        global_matrix = mi.axis_conversion(
            from_forward=axis_forward, from_up=axis_up
        ).to_4x4()
        obj.matrix_world = global_matrix

        if hasattr(operator.properties, "semantic_remap"):
            semantic_translations = vb.layout.apply_semantic_remap(operator)
        else:
            semantic_translations = vb.layout.get_semantic_remap()

        obj["3DMigoto:VBLayout"] = vb.layout.serialise()
        obj["3DMigoto:Topology"] = vb.topology
        for raw_vb in vb.vbs:
            obj["3DMigoto:VB%iStride" % raw_vb.idx] = raw_vb.stride
        obj["3DMigoto:FirstVertex"] = vb.first
        obj["3DMigoto:FlipWinding"] = flip_winding
        obj["3DMigoto:FlipNormal"] = flip_normal
        obj["3DMigoto:FlipMesh"] = flip_mesh
        if flip_mesh:
            flip_winding = not flip_winding

        if ib is not None:
            if ib.topology in ("trianglelist", "trianglestrip"):
                try:
                    mi.import_faces_from_ib(
                        mesh, ib, flip_winding, index_offset=vb.first
                    )
                except TypeError:
                    try:
                        mi.import_faces_from_ib(mesh, ib, flip_winding, vb.first)
                    except TypeError:
                        mi.import_faces_from_ib(mesh, ib, flip_winding)
            elif ib.topology == "pointlist":
                mi.assert_pointlist_ib_is_pointless(ib, vb)
            else:
                raise mi.Fatal("Unsupported topology (IB): {}".format(ib.topology))
            obj["3DMigoto:IBFormat"] = ib.format
            obj["3DMigoto:FirstIndex"] = ib.first
        elif vb.topology == "trianglelist":
            mi.import_faces_from_vb_trianglelist(mesh, vb, flip_winding)
        elif vb.topology == "trianglestrip":
            mi.import_faces_from_vb_trianglestrip(mesh, vb, flip_winding)
        elif vb.topology != "pointlist":
            raise mi.Fatal("Unsupported topology (VB): {}".format(vb.topology))
        if vb.topology == "pointlist":
            operator.report(
                {"WARNING"},
                "{}: uses point list topology, which is highly experimental and may have issues with normals/tangents/lighting. This may not be the mesh you are looking for.".format(
                    mesh.name
                ),
            )

        (
            blend_indices,
            blend_weights,
            texcoords,
            vertex_layers,
            use_normals,
            normals,
        ) = mi.import_vertices(
            mesh, obj, vb, operator, semantic_translations, flip_normal, flip_mesh
        )

        mi.import_uv_layers(mesh, obj, texcoords, flip_texcoord_v)
        if not texcoords:
            operator.report(
                {"WARNING"},
                "{}: No TEXCOORDs / UV layers imported. This may cause issues with normals/tangents/lighting on export.".format(
                    mesh.name
                ),
            )

        mi.import_vertex_layers(mesh, obj, vertex_layers)
        mi.import_vertex_groups(mesh, obj, blend_indices, blend_weights)

        # 변경된 부분: mesh.validate() 실행 여부 결정
        skip_validate = False
        try:
            # raw-buffers 연동으로 호출된 경우 우선 스킵
            if getattr(operator, "bl_idname", "") == "import_mesh.migoto_raw_buffers":
                skip_validate = True
                warn_msg = (
                    "[3DMigoto Import] Raw buffers import: preserving original face list; "
                    "skipping mesh.validate() to keep duplicate faces"
                )
                print(warn_msg)
                try:
                    operator.report({"INFO"}, warn_msg)
                except Exception:
                    pass

            # 인덱스 버퍼 내 중복 face가 있으면 스킵
            if ib is not None and not skip_validate:
                index_offset = getattr(
                    ib, "original_first", getattr(ib, "first", vb.first)
                )
                orig_keys = [
                    tuple(sorted((i - index_offset) for i in face)) for face in ib.faces
                ]
                orig_counter = collections.Counter(orig_keys)
                duplicates_in_ib = sum(c - 1 for c in orig_counter.values() if c > 1)
                if duplicates_in_ib > 0:
                    skip_validate = True
                    warn_msg = (
                        f"[3DMigoto Import] Skipping mesh.validate() due to {duplicates_in_ib} duplicate faces in IB; "
                        "preserving original face list"
                    )
                    print(warn_msg)
                    try:
                        operator.report({"WARNING"}, warn_msg)
                    except Exception:
                        pass
        except Exception:
            skip_validate = False

        if not skip_validate:
            mesh.validate(verbose=False, clean_customdata=False)
        mesh.update()

        if use_normals:
            if bpy.app.version >= (4, 1):
                mesh.normals_split_custom_set_from_vertices(normals)
            else:
                mi.import_normals_step2(mesh)
        elif hasattr(mesh, "calc_normals"):
            mesh.calc_normals()

        context.scene.collection.objects.link(obj)
        obj.select_set(True)
        context.view_layer.objects.active = obj

        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.select_all(action="SELECT")
        if merge_verts:
            bpy.ops.mesh.remove_doubles(use_sharp_edge_from_normals=True)
        if tris_to_quads:
            bpy.ops.mesh.tris_convert_to_quads(
                uvs=True, vcols=True, seam=True, sharp=True, materials=True
            )
        if clean_loose:
            bpy.ops.mesh.delete_loose()
        bpy.ops.object.mode_set(mode="OBJECT")
        if pose_path is not None:
            mi.import_pose(
                operator,
                context,
                pose_path,
                limit_bones_to_vertex_groups=True,
                axis_forward=axis_forward,
                axis_up=axis_up,
                pose_cb_off=pose_cb_off,
                pose_cb_step=pose_cb_step,
            )
            context.view_layer.objects.active = obj

        return obj

    mi.import_3dmigoto_vb_ib = _xxmi_import_3dmigoto_vb_ib


def _remove_xxmi_adapter():
    try:
        mi = importlib.import_module("XXMITools.migoto.import_ops")
    except Exception:
        return
    if hasattr(mi, "_xxmi_orig_import_3dmigoto_vb_ib"):
        mi.import_3dmigoto_vb_ib = mi._xxmi_orig_import_3dmigoto_vb_ib
        delattr(mi, "_xxmi_orig_import_3dmigoto_vb_ib")


def register():
    if not hasattr(bpy.types.WindowManager, "inips_addon_migoto"):
        bpy.types.WindowManager.inips_addon_migoto = BoolProperty(
            name="중복 페이스 유지",
            description="중복 페이스를 유지해 최대한 원본 모델을 임포트합니다",
            default=False,
        )
    for cls in classes:
        bpy.utils.register_class(cls)
    _apply_xxmi_adapter()


def unregister():
    _remove_xxmi_adapter()
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
    if hasattr(bpy.types.WindowManager, "inips_addon_migoto"):
        del bpy.types.WindowManager.inips_addon_migoto
