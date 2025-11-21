# Blender 애드온 정보
bl_info = {
    "name": "INI 기반 파츠 분리",
    "author": "DPN",
    "version": (1, 7, 1),
    "blender": (2, 93, 0),
    "location": "3D 뷰 > 우측 UI 패널 > 파츠 분리",
    "description": "INI의 DrawIndexed 값을 기반으로 오브젝트에서 파츠를 분리합니다.",
    "category": "Object",
}

# 라이브러리 임포트
from .source.parts_seperator import register_parts_seperator, unregister_parts_seperator
from .source.drawindexed import register_drawindexed, unregister_drawindexed
from .source.updater import register_updater, unregister_updater


# 애드온 등록 함수
def register():
    register_parts_seperator()
    register_drawindexed()
    register_updater()


# 애드온 해제 함수
def unregister():
    unregister_updater()
    unregister_drawindexed()
    unregister_parts_seperator()


# 스크립트 직접 실행 시 등록
if __name__ == "__main__":
    register()
