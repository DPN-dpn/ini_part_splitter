from . import (xxmi_tools, migoto)


def register():
    xxmi_tools.register()
    migoto.register()

def unregister():
    migoto.unregister()
    xxmi_tools.unregister()
