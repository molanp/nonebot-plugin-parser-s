import uuid
import datetime
from io import BytesIO
from typing import Any, ClassVar
from pathlib import Path
from itertools import chain
from collections.abc import AsyncGenerator

import qrcode  # pyright: ignore[reportMissingModuleSource]
from nonebot import logger, require

from .utils import build_content
from ..config import pconfig, _nickname
from ..helper import UniHelper, UniMessage, ForwardNodeInner
from ..exception import DownloadException, ZeroSizeException, DownloadLimitException
from ..parsers.data import (
    ParseResult,
    AudioContent,
    ImageContent,
    VideoContent,
    DynamicContent,
    GraphicsContent,
)

require("nonebot_plugin_htmlrender")
from nonebot_plugin_htmlrender import template_to_pic


class Renderer:
    """统一的渲染器，将解析结果转换为消息"""

    templates_dir: ClassVar[Path] = Path(__file__).parent / "templates"
    """模板目录"""

    async def render_messages(self, result: ParseResult) -> AsyncGenerator[UniMessage[Any], None]:
        """渲染消息

        Args:
            result (ParseResult): 解析结果
        """
        image_seg = await self.cache_or_render_image(result)

        msg = UniMessage(image_seg)
        if self.append_url:
            urls = (result.display_url, result.repost_display_url)
            msg += "\n".join(url for url in urls if url)
        yield msg

        # 媒体内容
        async for message in self.render_contents(result):
            yield message

    async def render_contents(self, result: ParseResult) -> AsyncGenerator[UniMessage[Any], None]:
        """渲染媒体内容消息

        Args:
            result (ParseResult): 解析结果

        Returns:
            AsyncGenerator[UniMessage[Any], None]: 消息生成器
        """
        failed_count = 0
        forwardable_segs: list[ForwardNodeInner] = []
        dynamic_segs: list[ForwardNodeInner] = []

        for cont in chain(result.contents, result.repost.contents if result.repost else ()):
            match cont:
                case VideoContent() | AudioContent():
                    # 立即发送模式
                    try:
                        path = await cont.get_path()
                        logger.debug(f"立即发送{type(cont).__name__}: {path}")

                        if isinstance(cont, VideoContent):
                            try:
                                # 尝试直接发送视频
                                yield UniMessage(UniHelper.video_seg(path))
                                # 如果需要上传视频文件，且没有因为大小问题发送失败
                                if pconfig.need_upload_video:
                                    await UniMessage(UniHelper.file_seg(path)).send()
                            except Exception as e:
                                # 直接发送失败，可能是因为文件太大，尝试使用群文件发送
                                logger.debug(f"直接发送视频失败，尝试使用群文件发送: {e}")
                                await UniMessage(UniHelper.file_seg(path)).send()
                        elif isinstance(cont, AudioContent):
                            try:
                                # 尝试直接发送音频
                                yield UniMessage(UniHelper.record_seg(path))
                                # 如果需要上传音频文件，且没有因为大小问题发送失败
                                if pconfig.need_upload_audio:
                                    await UniMessage(UniHelper.file_seg(path)).send()
                            except Exception as e:
                                # 直接发送失败，可能是因为文件太大，尝试使用群文件发送
                                logger.debug(f"直接发送音频失败，尝试使用群文件发送: {e}")
                                await UniMessage(UniHelper.file_seg(path)).send()
                    except (DownloadLimitException, ZeroSizeException):
                        continue
                    except DownloadException:
                        failed_count += 1
                        continue
                case ImageContent():
                    try:
                        path = await cont.get_path()
                        forwardable_segs.append(UniHelper.img_seg(path))
                    except (DownloadLimitException, ZeroSizeException):
                        continue
                    except DownloadException:
                        failed_count += 1
                        continue
                case DynamicContent():
                    try:
                        path = await cont.get_path()
                        dynamic_segs.append(UniHelper.video_seg(path))
                    except (DownloadLimitException, ZeroSizeException):
                        continue
                    except DownloadException:
                        failed_count += 1
                        continue
                case GraphicsContent() as graphics:
                    try:
                        path = await cont.get_path()
                        graphics_msg = UniHelper.img_seg(path)
                        if graphics.alt is not None:
                            graphics_msg = graphics_msg + graphics.alt
                        forwardable_segs.append(graphics_msg)
                    except (DownloadLimitException, ZeroSizeException):
                        continue
                    except DownloadException:
                        failed_count += 1
                        continue

        if forwardable_segs:
            # 添加原始动态的文本，包含作者信息
            # 对于转发动态，当前result是转发者的动态，result.repost是被转发者的内容
            author_name = result.author.name if result.author else "未知用户"

            # 添加转发内容的标题和文本，包含原作者信息
            if result.contents:
                if result.repost:
                    # result.repost是被转发者的内容，所以repost_author是被转发者
                    repost_author = result.repost.author.name if result.repost.author else "未知用户"
                    # 当前result是转发者的动态，所以作者是转发者
                    forwardable_segs.append(f"{author_name}[转发{repost_author}]：{result.text}")

                    repost_text = []
                    if result.repost.title:
                        repost_text.append(result.repost.title)
                    if result.repost.text:
                        repost_text.append(result.repost.text)

                    # 构造转发文本，格式为：XXXB[转发XXXA]：XXX内容 XXXA:XXX内容
                    # 其中XXXB是转发者，XXXA是被转发者
                    if repost_text:
                        repost_content = "\n".join(repost_text)
                        # 被转发者：被转发者的内容
                        forwardable_segs.append(f"{repost_author}[被转作者]：{repost_content}")
                else:
                    forwardable_segs.append(f"{author_name}：{result.text}")

            if pconfig.need_forward_contents or len(forwardable_segs) > 4:
                forward_msg = UniHelper.construct_forward_message(forwardable_segs + dynamic_segs)
                yield UniMessage(forward_msg)
            else:
                yield UniMessage(forwardable_segs)

                if dynamic_segs:
                    yield UniMessage(UniHelper.construct_forward_message(dynamic_segs))

        if failed_count > 0:
            message = f"{failed_count} 项媒体下载失败"
            yield UniMessage(message)
            raise DownloadException(message)

    @property
    def append_url(self) -> bool:
        return pconfig.append_url

    @property
    def append_qrcode(self) -> bool:
        return pconfig.append_qrcode

    async def render_image(self, result: ParseResult) -> bytes:
        """使用 HTML 绘制通用社交媒体帖子卡片"""
        # 准备模板数据
        template_data = await self._resolve_parse_result(result)

        # 处理模板针对
        template_name = "card.html.jinja"
        if result.platform:
            # 音乐平台使用音乐模板
            music_platforms = ["kugou", "netease", "kuwo", "qsmusic"]
            platform_name = result.platform.name.lower()

            if platform_name in music_platforms:
                template_name = "music.html.jinja"
            else:
                # 其他平台使用各自的模板
                file_name = f"{platform_name}.html.jinja"
                if (self.templates_dir / file_name).exists():
                    template_name = file_name

        # from jinja2 import FileSystemLoader, Environment

        # # 创建一个包加载器对象
        # env = Environment(loader=FileSystemLoader(self.templates_dir))
        # template = env.get_template(template_name)
        # # 渲染
        # with open(f"{self.templates_dir.parent.parent}/{datetime.datetime.now().strftime('%Y-%m-%d-%H%M%S')}.html", "w", encoding="utf8") as f:
        #     f.write(
        #         template.render(
        #             **{
        #                 "result": template_data,
        #                 "rendering_time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        #                 "bot_name": _nickname,
        #             }
        #         )
        #     )

        return await template_to_pic(
            template_path=str(self.templates_dir),
            template_name=template_name,
            screenshot_timeout=60000,
            templates={
                "result": template_data,
                "rendering_time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "bot_name": _nickname,
            },
            pages={
                "viewport": {"width": 800, "height": 100},
                "base_url": f"file://{self.templates_dir}",
            },
        )

    async def _resolve_parse_result(self, result: ParseResult) -> dict[str, Any]:
        """解析 ParseResult 为模板可用的字典数据"""

        logo_path = Path(__file__).parent / "resources" / f"{result.platform.name}.png"
        content, cover_path = await build_content(result)

        # if ori := result.extra.get("origin"):
        #     if oric := ori.get("contents"):
        #         ori["contents"], _ = await self._build_contents(oric)
        # 这些是一定会有的字段
        data: dict[str, Any] = {
            "title": result.title,
            "formatted_datetime": result.formatted_datetime,
            "extra_info": result.extra_info,
            "extra": result.extra,
            "platform": {
                "display_name": result.platform.display_name,
                "name": result.platform.name,
                "logo_path": (logo_path.as_uri() if logo_path.exists() else None),
            },
            "content": content,
            "cover_path": cover_path,
            "text": result.text,
        }

        if result.author:
            avatar_path = await result.author.get_avatar_path()
            author_id = getattr(result.author, "id", None)
            if not author_id and result.extra:
                author_id = result.extra.get("author_id")

            data["author"] = {
                "name": result.author.name,
                "id": author_id,  # 传递 UID
                "avatar_path": avatar_path.as_uri() if avatar_path else None,
            }

        if result.repost:
            data["repost"] = await self._resolve_parse_result(result.repost)

        # 添加二维码支持
        if pconfig.append_qrcode and result.url:
            # 生成二维码
            qr = qrcode.QRCode(
                version=1,
                error_correction=1,  # ERROR_CORRECT_L 的数值
                box_size=10,
                border=4,
            )
            qr.add_data(result.url)
            qr.make(fit=True)
            img = qr.make_image(fill_color="black", back_color="white")

            # 将二维码转换为 base64 编码
            buffer = BytesIO()
            img.save(buffer, format="PNG")  # type: ignore
            buffer.seek(0)
            import base64

            img_base64 = base64.b64encode(buffer.getvalue()).decode("utf-8")

            # 添加 base64 编码的图片数据到模板数据
            data["qr_code_path"] = f"data:image/png;base64,{img_base64}"

        return data

    async def cache_or_render_image(self, result: ParseResult):
        """获取缓存图片

        Args:
            result (ParseResult): 解析结果

        Returns:
            Image: 图片 Segment
        """
        if result.render_image is None:
            image_raw = await self.render_image(result)
            image_path = await self.save_img(image_raw)
            result.render_image = image_path
            if pconfig.use_base64:
                return UniHelper.img_seg(raw=image_raw)

        return UniHelper.img_seg(result.render_image)

    @classmethod
    async def save_img(cls, raw: bytes) -> Path:
        """保存图片

        Args:
            raw (bytes): 图片字节

        Returns:
            Path: 图片路径
        """
        import aiofiles

        file_name = f"{uuid.uuid4().hex}.png"
        image_path = pconfig.cache_dir / file_name
        async with aiofiles.open(image_path, "wb+") as f:
            await f.write(raw)
        return image_path
