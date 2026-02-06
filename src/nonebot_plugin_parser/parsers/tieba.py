from re import Match
from typing import ClassVar

from httpx import AsyncClient

from .base import (
    BaseParser,
    handle,
)
from .data import Platform, MediaContent
from ..constants import PlatformEnum


class TiebaParser(BaseParser):
    platform: ClassVar[Platform] = Platform(
        name=PlatformEnum.TIEBA, display_name="百度贴吧"
    )

    @handle("tieba.baidu.com", r"tieba\.baidu\.com/p/(?P<post_id>\d+)")
    async def _parse(self, searched: Match[str]):
        # TODO: 显示吧头像
        post_id = searched.group("post_id")

        async with AsyncClient(
            headers=self.headers, timeout=self.timeout, verify=False
        ) as client:
            resp = await client.get(
                "https://tb.wang1m.tech/post/raw",
                params={"tid": post_id, "page": 1},
            )
            resp.raise_for_status()
            data = resp.json()

        thread = data["thread"]
        author_info = thread["author"]
        post = data["postList"][0]

        author = self.create_author(
            name=author_info.get("nameShow") or author_info.get("name"),
            avatar_url=f"http://tb.himg.baidu.com/sys/portraith/item/{author_info['portrait']}",
        )

        # 主楼正文内容（图文混排）
        contents: list[MediaContent] = []
        text_parts = []
        content_list = post["content"]
        for item in content_list:
            content_type = item["type"]

            if content_type in [0, 40]:
                text = item["text"]
                text_parts.append(text)
            elif content_type == 2:
                text_parts.append(f"[{item['c']}]")
            elif content_type == 3:
                contents.append(
                    self.create_graphics_content(image_url=item["originSrc"])
                )
        extra = {
            "forum": {
                "name": data["forum"]["name"],
            }
        }

        return self.result(
            title=thread["title"],
            text="".join(text_parts),
            author=author,
            contents=contents,
            timestamp=thread["createTime"],
            url=f"https://tieba.baidu.com/p/{post_id}",
            extra=extra,
        )
