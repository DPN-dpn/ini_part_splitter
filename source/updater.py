# 라이브러리 임포트
import bpy
from bpy.types import Operator, Panel

# 업데이터 패널 UI
class PT_UpdaterPanel(Panel):
	bl_label = "업데이트"
	bl_idname = "VIEW3D_PT_updater_panel"
	bl_space_type = 'VIEW_3D'
	bl_region_type = 'UI'
	bl_category = '파츠 분리'
	bl_options = {'DEFAULT_CLOSED'}

	def draw(self, context):
		layout = self.layout
		layout.operator("updater.check_update", text="업데이트 체크", icon='FILE_REFRESH')
		layout.operator("updater.do_update", text="업데이트", icon='IMPORT')
		layout.operator("updater.open_github", text="GitHub", icon='URL')

# 업데이트 체크
class OT_CheckUpdate(Operator):
	bl_idname = "updater.check_update"
	bl_label = "업데이트 체크"
	bl_description = "최신 버전이 있는지 확인합니다."

	def execute(self, context):
		self.report({'INFO'}, "업데이트 체크 기능은 아직 구현되지 않았습니다.")
		return {'FINISHED'}

# 업데이트 실행
class OT_DoUpdate(Operator):
	bl_idname = "updater.do_update"
	bl_label = "업데이트"
	bl_description = "애드온을 최신 버전으로 업데이트합니다."

	def execute(self, context):
		self.report({'INFO'}, "업데이트 기능은 아직 구현되지 않았습니다.")
		return {'FINISHED'}

# GitHub 이동
class OT_OpenGithub(Operator):
	bl_idname = "updater.open_github"
	bl_label = "GitHub"
	bl_description = "애드온의 GitHub 페이지를 엽니다."

	def execute(self, context):
		import webbrowser
		webbrowser.open('https://github.com/DPN-dpn/ini_part_splitter')
		self.report({'INFO'}, "ini_part_splitter GitHub 페이지를 엽니다.")
		return {'FINISHED'}
