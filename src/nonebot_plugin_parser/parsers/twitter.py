import re
from typing import ClassVar

from httpx import AsyncClient
from msgspec import Struct, field
from msgspec.json import Decoder

from .base import BaseParser, PlatformEnum, handle
from .data import Platform, ParseResult, MediaContent


class MediaElement(Struct):
    type: str
    """媒体类型 video/image/gif"""
    url: str
    altText: str | None = None
    thumbnail_url: str | None = None
    duration_millis: int | None = None


class VxTwitterResponse(Struct):
    article: str | None
    date_epoch: int
    fetched_on: int
    likes: int
    text: str
    user_name: str
    user_screen_name: str
    user_profile_image_url: str
    qrt: "VxTwitterResponse | None" = None
    """引用推文"""
    media_extended: list[MediaElement] = field(default_factory=list)


decoder = Decoder(VxTwitterResponse)


class TwitterParser(BaseParser):
    platform: ClassVar[Platform] = Platform(name=PlatformEnum.X, display_name="X")

    @handle("x.com", r"x.com/[0-9-a-zA-Z_]{1,20}/status/([0-9]+)")
    async def _parse(self, searched: re.Match[str]) -> ParseResult:
        url = f"https://{searched.group(0)}"
        return await self.parse_by_vxapi(url)

    async def parse_by_vxapi(self, url: str):
        """使用 vxtwitter API 解析 Twitter 链接"""

        api_url = url.replace("x.com", "api.vxtwitter.com")
        async with AsyncClient(headers=self.headers, timeout=self.timeout) as client:
            response = await client.get(api_url)
            response.raise_for_status()

        data = decoder.decode(response.content)
        return self._collect_result(data)

    def _collect_result(self, data: VxTwitterResponse) -> ParseResult:
        author = self.create_author(data.user_screen_name, data.user_profile_image_url)

        contents: list[MediaContent | str] = [data.text]

        for media in data.media_extended:
            if media.type in ("video", "gif"):
                contents.append(self.create_video(media.url, media.thumbnail_url))
            elif media.type == "image":
                contents.append(self.create_image(media.url))

        repost = self._collect_result(data.qrt) if data.qrt else None

        return self.result(
            author=author,
            title=data.article,
            timestamp=data.date_epoch,
            content=contents,
            repost=repost,
        )
