from .base import Renderer

RENDERER = Renderer()


def get_renderer(platform: str) -> Renderer:
    """根据平台名称获取对应的 Renderer 类"""
    return RENDERER

