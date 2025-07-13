bl_info = {
    "name": "INI 기반 파츠 분리",
    "author": "OpenAI + DPN",
    "version": (1, 2),
    "blender": (2, 93, 0),
    "location": "3D 뷰 > 우측 UI 패널 > 파츠 분리",
    "description": "INI 파일을 기반으로 DrawIndexed 파츠를 오브젝트에서 분리합니다.",
    "category": "Object"
}

import bpy
import bmesh
import re
from bpy_extras.io_utils import ImportHelper
from bpy.types import Operator, Panel
from bpy.props import StringProperty, EnumProperty, PointerProperty


class INISectionProperties(bpy.types.PropertyGroup):
    ini_path: StringProperty(name="INI 파일 경로", default="")
    _section_items = []

    def section_items(self, context):
        return self._section_items

    section: EnumProperty(
        name="IB 섹션",
        items=lambda self, context: self.section_items(context)
    )


class OT_SelectIniFile(Operator, ImportHelper):
    bl_idname = "wm.select_ini_file_panel"
    bl_label = "INI 파일 선택"
    filter_glob: StringProperty(default="*.ini", options={'HIDDEN'})

    def execute(self, context):
        props = context.scene.ini_section_props
        props.ini_path = self.filepath

        ib_sections = []
        current_section = None
        found_sections = set()
        with open(self.filepath, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line.startswith('[') and line.endswith(']'):
                    current_section = line[1:-1]
                elif current_section and current_section.startswith("TextureOverride"):
                    if line.lower().startswith("ib"):
                        if current_section not in found_sections:
                            ib_sections.append((current_section, current_section, ""))
                            found_sections.add(current_section)

        if not ib_sections:
            self.report({'ERROR'}, "IB 섹션이 없습니다.")
            return {'CANCELLED'}

        INISectionProperties._section_items = ib_sections
        props.section = ib_sections[0][0]

        return {'FINISHED'}


class OT_SeparatePartsFromIni(Operator):
    bl_idname = "object.separate_parts_from_ini"
    bl_label = "INI로 파츠 분리"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        props = context.scene.ini_section_props
        ini_path = props.ini_path
        section = props.section

        if not ini_path or not section:
            self.report({'ERROR'}, "INI 파일과 섹션을 선택해야 합니다.")
            return {'CANCELLED'}

        # 🔄 섹션별 라인 저장
        section_map = {}
        with open(ini_path, encoding='utf-8') as f:
            current_section = None
            for line in f:
                line = line.strip()
                if line.startswith('[') and line.endswith(']'):
                    current_section = line[1:-1]
                    section_map[current_section] = []
                elif current_section:
                    section_map[current_section].append(line)

        drawindexed_map = []
        seen = set()
        last_comment = None

        def extract_drawindexed(lines):
            nonlocal seen, last_comment
            results = []
            for line in lines:
                if line.startswith(';'):
                    comment_match = re.match(r";\s*([^\(]+)", line)
                    if comment_match:
                        last_comment = comment_match.group(1).strip()
                elif line.lower().startswith("drawindexed"):
                    parts = line.split('=', 1)
                    if len(parts) == 2:
                        value = parts[1].strip()
                        if re.match(r"^\d+,\s*\d+,\s*0$", value) and value not in seen:
                            seen.add(value)
                            results.append((value, last_comment or f"draw_{len(seen)}"))
                    last_comment = None
            return results

        # 1. 직접적인 drawindexed
        drawindexed_map.extend(extract_drawindexed(section_map.get(section, [])))

        # 2. run=CommandListXXX 추적
        for line in section_map.get(section, []):
            if line.lower().startswith("run"):
                parts = line.split('=', 1)
                if len(parts) == 2:
                    target = parts[1].strip()
                    if target in section_map:
                        drawindexed_map.extend(extract_drawindexed(section_map[target]))

        if not drawindexed_map:
            self.report({'ERROR'}, "drawindexed 항목이 없습니다.")
            return {'CANCELLED'}

        original_obj = bpy.context.active_object
        if not original_obj or original_obj.type != 'MESH':
            self.report({'ERROR'}, "메시 오브젝트를 선택하세요.")
            return {'CANCELLED'}

        original_obj_name = original_obj.name
        new_collection = bpy.data.collections.new(original_obj_name)
        context.scene.collection.children.link(new_collection)

        bpy.ops.object.select_all(action='DESELECT')

        for i, (entry, name) in enumerate(drawindexed_map):
            numbers = list(map(int, re.findall(r'\d+', entry)))
            if len(numbers) < 2:
                continue
            index_count, start_index = numbers[:2]

            original_obj.select_set(True)
            context.view_layer.objects.active = original_obj
            bpy.ops.object.duplicate()
            dup_obj = context.active_object
            mesh = dup_obj.data

            bpy.ops.object.mode_set(mode='OBJECT')
            index_buffer = []
            for poly in mesh.polygons:
                if len(poly.vertices) == 3:
                    index_buffer.extend(poly.vertices)

            selected_indices = set(index_buffer[start_index:start_index + index_count])

            bpy.ops.object.mode_set(mode='EDIT')
            bm = bmesh.from_edit_mesh(mesh)
            bm.faces.ensure_lookup_table()
            bm.verts.ensure_lookup_table()

            for f in bm.faces:
                f.select = False

            for f in bm.faces:
                if any(v.index in selected_indices for v in f.verts):
                    f.select = True

            bmesh.update_edit_mesh(mesh)
            selected_face_count = sum(1 for f in bm.faces if f.select)

            if selected_face_count == 0:
                bpy.ops.object.mode_set(mode='OBJECT')
                bpy.data.objects.remove(dup_obj)
                continue

            bpy.ops.mesh.separate(type='SELECTED')
            bpy.ops.object.mode_set(mode='OBJECT')

            for obj in context.selected_objects:
                if obj != dup_obj:
                    new_collection.objects.link(obj)
                    context.scene.collection.objects.unlink(obj)
                    obj.name = name

            bpy.ops.object.select_all(action='DESELECT')
            dup_obj.select_set(True)
            bpy.ops.object.delete()

        bpy.ops.object.select_all(action='DESELECT')
        original_obj.select_set(True)
        bpy.ops.object.delete()

        self.report({'INFO'}, f"{len(drawindexed_map)}개의 drawindexed로 분리 완료")
        return {'FINISHED'}


class PT_IBSectionSelector(Panel):
    bl_label = "INI 파츠 분리"
    bl_idname = "VIEW3D_PT_ib_section_selector"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = '파츠 분리'

    def draw(self, context):
        layout = self.layout
        props = context.scene.ini_section_props

        layout.operator("wm.select_ini_file_panel", text="INI 파일 열기")

        if props.ini_path:
            layout.label(text=f"INI: {props.ini_path.split('/')[-1]}")
            layout.prop(props, "section")

        obj = context.active_object
        enable_button = (
            obj is not None and obj.type == 'MESH'
            and bool(props.ini_path.strip())
            and bool(props.section.strip())
        )

        row = layout.row()
        row.enabled = enable_button
        row.operator("object.separate_parts_from_ini", text="파츠 분리")


classes = (
    INISectionProperties,
    OT_SelectIniFile,
    OT_SeparatePartsFromIni,
    PT_IBSectionSelector,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.ini_section_props = PointerProperty(type=INISectionProperties)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
    del bpy.types.Scene.ini_section_props


if __name__ == "__main__":
    register()