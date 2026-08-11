import bpy
from bpy.props import BoolProperty
import importlib
import collections


class INIPS_PT_Addon_XXMI(bpy.types.Panel):
    bl_label = "INI 파츠 분리 옵션"
    bl_space_type = "FILE_BROWSER"
    bl_region_type = "TOOL_PROPS"
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
        layout.prop(wm, "inips_addon_xxmi")


classes = (INIPS_PT_Addon_XXMI,)


def _apply_xxmi_adapter():
    try:
        mi = importlib.import_module("XXMITools.migoto.import_ops")
    except Exception:
        return
    if hasattr(mi, "_xxmi_orig_import_3dmigoto_vb_ib"):
        return

    import inspect
    import re
    import textwrap

    mi._xxmi_orig_import_3dmigoto_vb_ib = mi.import_3dmigoto_vb_ib

    try:
        source = inspect.getsource(mi.import_3dmigoto_vb_ib)
    except Exception as e:
        print(f"INIPS Adapter Error: 원본 함수 소스를 가져올 수 없습니다. {e}")
        return

    pattern = re.compile(r'^([ \t]+)mesh\.validate\(\s*verbose=False,\s*clean_customdata=False\s*\)', re.MULTILINE)

    def replacer(match):
        indent = match.group(1)
        block = """# --- INIPS ADAPTER INJECTED CODE ---
skip_validate = False
try:
    wm = bpy.context.window_manager
    if getattr(wm, "inips_addon_xxmi", False):
        if getattr(operator, "bl_idname", "") == "import_mesh.migoto_raw_buffers":
            skip_validate = True
        elif ib is not None:
            seen = set()
            for face in ib.faces:
                key = frozenset(face)
                if key in seen:
                    skip_validate = True
                    break
                seen.add(key)
except Exception as e:
    print(f"INIPS Adapter Error: {e}")

if not skip_validate:
    mesh.validate(
        verbose=False, clean_customdata=False
    )
else:
    mesh.update(calc_edges=True)
# -----------------------------------"""
        return "\n".join(indent + line for line in block.split("\n"))

    new_source, count = pattern.subn(replacer, source)

    if count == 0:
        print("INIPS Adapter Error: mesh.validate 호출을 찾지 못했습니다. 원본 함수를 유지합니다.")
        return

    new_source = textwrap.dedent(new_source)

    exec_globals = mi.import_3dmigoto_vb_ib.__globals__
    exec_locals = {}
    try:
        exec(new_source, exec_globals, exec_locals)
        mi.import_3dmigoto_vb_ib = exec_locals['import_3dmigoto_vb_ib']
    except Exception as e:
        print(f"INIPS Adapter Error: 주입된 코드 컴파일 실패. 원본 함수를 유지합니다. {e}")


def _remove_xxmi_adapter():
    try:
        mi = importlib.import_module("XXMITools.migoto.import_ops")
    except Exception:
        return
    if hasattr(mi, "_xxmi_orig_import_3dmigoto_vb_ib"):
        mi.import_3dmigoto_vb_ib = mi._xxmi_orig_import_3dmigoto_vb_ib
        delattr(mi, "_xxmi_orig_import_3dmigoto_vb_ib")


def register():
    if not hasattr(bpy.types.WindowManager, "inips_addon_xxmi"):
        bpy.types.WindowManager.inips_addon_xxmi = BoolProperty(
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
    if hasattr(bpy.types.WindowManager, "inips_addon_xxmi"):
        del bpy.types.WindowManager.inips_addon_xxmi
