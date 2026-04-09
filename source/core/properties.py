import bpy
from bpy.types import PropertyGroup
from bpy.props import StringProperty, EnumProperty, IntProperty, CollectionProperty


class INPS_INISection(PropertyGroup):
    section_name: StringProperty(name="Section")
    lines: StringProperty(name="Lines", description="Section lines (newline-separated)")


def _inips_resource_items(scene, context):
    return INIPS_Resources._resource_items


class INIPS_Resources(PropertyGroup):
    _resource_items = [
        ("NONE", "None", "선택 없음"),
    ]


def register():
    bpy.utils.register_class(INPS_INISection)
    bpy.types.Scene.inips_ini_sections = CollectionProperty(type=INPS_INISection)

    # 파츠 분리
    bpy.types.Scene.inips_ini_path = StringProperty(
        name="INI 파일 경로",
        description="선택된 INI 파일의 경로입니다",
        default="",
        subtype="FILE_PATH",
    )
    bpy.types.Scene.inips_resource = bpy.props.EnumProperty(
        name="IB",
        description="파츠를 분리할 IB의 리소스 이름입니다",
        items=_inips_resource_items,
        default=0,
    )

    # drawindexed
    bpy.types.Scene.inips_drawindexed_start = IntProperty(
        name="DrawIndexed Start",
        description="drawindexed = ???, ???, 0 형식에서 두 번째 값",
        default=0,
        min=0,
        max=1000000000,
        step=1,
    )
    bpy.types.Scene.inips_drawindexed_count = IntProperty(
        name="DrawIndexed Count",
        description="drawindexed = ???, ???, 0 형식에서 첫 번째 값",
        default=0,
        min=0,
        max=1000000000,
        step=1,
    )


def unregister():
    del bpy.types.Scene.inips_drawindexed_count
    del bpy.types.Scene.inips_drawindexed_start

    del bpy.types.Scene.inips_resource
    del bpy.types.Scene.inips_ini_path

    del bpy.types.Scene.inips_ini_sections
    bpy.utils.unregister_class(INPS_INISection)
