from pathlib import Path

from nonebot import require, get_driver, get_plugin_config
from apilmoji import ELK_SH_CDN, EmojiStyle
from pydantic import BaseModel
from bilibili_api.video import VideoCodecs, VideoQuality

from .constants import RenderType, PlatformEnum

require("nonebot_plugin_localstore")
import nonebot_plugin_localstore as _store

from nonebot.plugin import PluginMetadata


# 默认配置
ELK_SH_CDN = "https://emojicdn.elk.sh"
MQRIO_DEV_CDN = "https://emoji-cdn.mqrio.dev"

_driver = get_driver()
_nickname = next(iter(_driver.config.nickname), "nonebot-plugin-parser")
_cache_dir: Path = _store.get_plugin_cache_dir()
_config_dir: Path = _store.get_plugin_config_dir()
_data_dir: Path = _store.get_plugin_data_dir()


# 定义Config类
class Config(BaseModel):
    parser_bili_ck: str | None = None
    """bilibili cookies"""
    parser_ytb_ck: str | None = None
    """youtube cookies"""
    parser_xhs_ck: str | None = None
    """小红书 cookies"""
    parser_proxy: str | None = None
    """代理"""
    parser_need_upload: bool = False
    """是否需要上传音视频文件"""
    parser_use_base64: bool = False
    """是否使用 base64 编码发送图片，音频，视频"""
    parser_max_size: int = 90
    """资源最大大小，默认 100 单位 MB"""
    parser_duration_maximum: int = 480
    """视频/音频最大时长"""
    parser_append_url: bool = False
    """是否在解析结果中添加原始URL"""
    parser_append_qrcode: bool = False
    """是否在解析结果中添加原始URL二维码"""
    parser_disabled_platforms: list[PlatformEnum] = []
    """禁用的解析器"""
    parser_blacklist_users: list[str] = []
    """黑名单用户列表，这些用户触发的解析将被忽略"""
    parser_bili_video_codes: list[VideoCodecs] = [
        VideoCodecs.AVC,
        VideoCodecs.AV1,
        VideoCodecs.HEV,
    ]
    """B站视频编码"""
    parser_bili_video_quality: VideoQuality = VideoQuality._1080P
    """B站视频清晰度"""
    parser_render_type: RenderType = RenderType.common
    """Renderer 类型"""
    parser_custom_font: str | None = None
    """自定义字体"""
    parser_need_forward_contents: bool = True
    """是否需要转发原文内容"""
    parser_emoji_cdn: str = ELK_SH_CDN
    """Pilmoji 表情 CDN"""
    parser_emoji_style: str = "facebook"
    """Pilmoji 表情风格"""
    parser_delay_send_media: bool = False
    """是否延迟发送视频/音频，需要用户发送特定表情或点赞特定表情后才发送"""
    parser_delay_send_emoji: str = "👍"
    """触发延迟发送视频的表情"""
    parser_delay_send_emoji_ids: list[int] = []
    """触发延迟发送视频的表情ID列表，用于监听group_msg_emoji_like事件"""
    parser_delay_send_lazy_download: bool = False
    """是否开启懒下载模式，仅在用户请求时才下载视频"""

    @property
    def nickname(self) -> str:
        """机器人昵称"""
        return _nickname

    @property
    def cache_dir(self) -> Path:
        """插件缓存目录"""
        return _cache_dir

    @property
    def config_dir(self) -> Path:
        """插件配置目录"""
        return _config_dir

    @property
    def data_dir(self) -> Path:
        """插件数据目录"""
        return _data_dir

    @property
    def max_size(self) -> int:
        """资源最大大小"""
        return self.parser_max_size

    @property
    def duration_maximum(self) -> int:
        """视频/音频最大时长"""
        return self.parser_duration_maximum

    @property
    def disabled_platforms(self) -> list[PlatformEnum]:
        """禁用的解析器"""
        return self.parser_disabled_platforms

    @property
    def bili_video_codes(self) -> list[VideoCodecs]:
        """B站视频编码"""
        return self.parser_bili_video_codes

    @property
    def bili_video_quality(self) -> VideoQuality:
        """B站视频清晰度"""
        return self.parser_bili_video_quality

    @property
    def render_type(self) -> RenderType:
        """Renderer 类型"""
        return self.parser_render_type

    @property
    def bili_ck(self) -> str | None:
        """bilibili cookies"""
        return self.parser_bili_ck

    @property
    def ytb_ck(self) -> str | None:
        """youtube cookies"""
        return self.parser_ytb_ck

    @property
    def xhs_ck(self) -> str | None:
        """小红书 cookies"""
        return self.parser_xhs_ck

    @property
    def proxy(self) -> str | None:
        """代理"""
        return self.parser_proxy

    @property
    def need_upload(self) -> bool:
        """是否需要上传音视频文件"""
        return self.parser_need_upload

    @property
    def use_base64(self) -> bool:
        """是否使用 base64 编码发送图片，音频，视频"""
        return self.parser_use_base64

    @property
    def append_url(self) -> bool:
        """是否在解析结果中添加原始URL"""
        return self.parser_append_url

    @property
    def append_qrcode(self) -> bool:
        """是否在解析结果中添加原始URL二维码"""
        return self.parser_append_qrcode

    @property
    def custom_font(self) -> Path | None:
        """自定义字体"""
        return (self.data_dir / self.parser_custom_font) if self.parser_custom_font else None

    @property
    def need_forward_contents(self) -> bool:
        """是否需要转发原文内容"""
        return self.parser_need_forward_contents

    @property
    def emoji_cdn(self) -> str:
        """Pilmoji 表情 CDN"""
        return self.parser_emoji_cdn

    @property
    def emoji_style(self) -> EmojiStyle:
        """Pilmoji 表情风格"""
        from apilmoji import EmojiStyle as ApilmojiEmojiStyle
        return ApilmojiEmojiStyle(self.parser_emoji_style)

    @property
    def delay_send_media(self) -> bool:
        """是否延迟发送视频/音频"""
        return self.parser_delay_send_media

    @property
    def delay_send_emoji(self) -> str:
        """触发延迟发送视频的表情"""
        return self.parser_delay_send_emoji

    @property
    def delay_send_emoji_ids(self) -> list[int]:
        """触发延迟发送视频的表情ID列表"""
        return self.parser_delay_send_emoji_ids

    @property
    def delay_send_lazy_download(self) -> bool:
        """是否开启懒下载模式"""
        return self.parser_delay_send_lazy_download

    @property
    def blacklist_users(self) -> list[str]:
        """黑名单用户列表"""
        return self.parser_blacklist_users


# 定义插件元数据
__plugin_meta__ = PluginMetadata(
    name="nonebot-plugin-parser",
    description="Nonebot2 链接分享自动解析插件",
    usage="无需任何命令，直接发送链接即可",
    homepage="https://github.com/fllesser/nonebot-plugin-parser",
    type="application",
    config=Config,
    supported_adapters={"~onebot.v11", "~onebot.v12"},
)


# 初始化配置实例
_driver = get_driver()
pconfig: Config = get_plugin_config(Config)
"""插件配置"""
gconfig = _driver.config
"""全局配置"""
_nickname: str = next(iter(gconfig.nickname), "nonebot-plugin-parser")
"""机器人昵称"""
