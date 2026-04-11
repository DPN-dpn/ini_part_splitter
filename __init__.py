# Blender 애드온 정보
bl_info = {
    "name": "INI 기반 파츠 분리",
    "author": "DPN",
    "version": (2, 0, 0),
    "blender": (3, 6, 23),
    "location": "3D 뷰 > 우측 UI 패널 > 파츠 분리",
    "description": "INI의 DrawIndexed 값을 기반으로 오브젝트에서 파츠를 분리합니다.",
    "category": "Object",
}

# 라이브러리 임포트
from .source import core, updator, parts_sperator, drawindexed, addon


# 애드온 등록 함수
def register():
    core.register()
    parts_sperator.register()
    drawindexed.register()
    addon.register()
    updator.register()


# 애드온 해제 함수
def unregister():
    updator.unregister()
    addon.unregister()
    drawindexed.unregister()
    parts_sperator.unregister()
    core.unregister()


# 스크립트 직접 실행 시 등록
if __name__ == "__main__":
    register()
