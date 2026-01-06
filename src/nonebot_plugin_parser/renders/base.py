import uuid
from abc import ABC, abstractmethod
from typing import Any, ClassVar
from pathlib import Path
from itertools import chain
from collections.abc import AsyncGenerator
from typing_extensions import override

from nonebot import logger

from ..config import pconfig
from ..helper import UniHelper, UniMessage, ForwardNodeInner
from ..parsers.data import (
    ParseResult,
    AudioContent,
    ImageContent,
    VideoContent,
    DynamicContent,
    GraphicsContent,
    MediaContent,
)
from ..exception import DownloadException, ZeroSizeException, DownloadLimitException


class BaseRenderer(ABC):
    """统一的渲染器，将解析结果转换为消息"""

    templates_dir: ClassVar[Path] = Path(__file__).parent / "templates"
    """模板目录"""

    @abstractmethod
    async def render_messages(self, result: ParseResult) -> AsyncGenerator[UniMessage[Any], None]:
        """消息生成器

        Args:
            result (ParseResult): 解析结果

        Returns:
            AsyncGenerator[UniMessage[Any], None]: 消息生成器
        """
        if False:
            yield
        raise NotImplementedError

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
        
        # 用于存储延迟发送的媒体内容
        media_contents: list[tuple[type, MediaContent | Path]] = []

        for cont in chain(result.contents, result.repost.contents if result.repost else ()):
            match cont:
                case VideoContent() | AudioContent():
                    # 检查是否需要延迟发送或懒下载
                    need_delay = pconfig.delay_send_media or pconfig.delay_send_lazy_download
                    logger.debug(f"处理{type(cont).__name__}，need_delay={need_delay}, lazy_download={pconfig.delay_send_lazy_download}")
                    if need_delay:
                        # 延迟发送模式：缓存MediaContent对象或路径
                        if pconfig.delay_send_lazy_download:
                            # 真正的延迟下载，缓存MediaContent对象，不立即下载
                            logger.debug(f"延迟发送{type(cont).__name__}，缓存MediaContent对象，不立即下载")
                            media_contents.append((type(cont), cont))
                        else:
                            # 解析时自动下载，但延迟发送
                            try:
                                path = await cont.get_path()
                                logger.debug(f"延迟发送{type(cont).__name__}，已下载，缓存路径: {path}")
                                media_contents.append((type(cont), path))
                            except (DownloadLimitException, ZeroSizeException):
                                continue
                            except DownloadException:
                                failed_count += 1
                                continue
                    else:
                        # 立即发送模式
                        try:
                            path = await cont.get_path()
                            logger.debug(f"立即发送{type(cont).__name__}: {path}")
                            if isinstance(cont, VideoContent):
                                yield UniMessage(UniHelper.video_seg(path))
                            elif isinstance(cont, AudioContent):
                                yield UniMessage(UniHelper.record_seg(path))
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
                        if graphics.text is not None:
                            graphics_msg = graphics.text + graphics_msg
                        if graphics.alt is not None:
                            graphics_msg = graphics_msg + graphics.alt
                        forwardable_segs.append(graphics_msg)
                    except (DownloadLimitException, ZeroSizeException):
                        continue
                    except DownloadException:
                        failed_count += 1
                        continue

        # 如果有延迟发送的媒体，存储到解析结果中
        if media_contents:
            result.media_contents = media_contents

        if forwardable_segs:
            if result.text:
                forwardable_segs.append(result.text)

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


class ImageRenderer(BaseRenderer):
    """图片渲染器"""

    @abstractmethod
    async def render_image(self, result: ParseResult) -> bytes:
        """渲染图片

        Args:
            result (ParseResult): 解析结果

        Returns:
            bytes: 图片字节 png 格式
        """
        raise NotImplementedError

    @override
    async def render_messages(self, result: ParseResult):
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
