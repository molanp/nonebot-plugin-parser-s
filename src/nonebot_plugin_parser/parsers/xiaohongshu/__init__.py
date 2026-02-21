import re
from typing import ClassVar
from urllib.parse import parse_qsl

from curl_cffi import AsyncSession

from ..base import Platform, BaseParser, PlatformEnum, ParseException, handle, pconfig
from ..data import MediaContent
from .explore import InitialState as exploreInitialState
from .explore import decoder as exploreDecoder


class XiaoHongShuParser(BaseParser):
    # 平台信息
    platform: ClassVar[Platform] = Platform(name=PlatformEnum.XIAOHONGSHU, display_name="小红书")
    session: AsyncSession
    # 小红书笔记详情页对真实浏览器仍有速率限制，达到限制后需要时间恢复
    # 暂时不知ck能否缓解此问题

    def __init__(self):
        super().__init__()
        explore_headers = {
            "accept": (
                "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,"
                "image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7"
            )
        }
        self.headers.update(explore_headers)

        discovery_headers = {
            "origin": "https://www.xiaohongshu.com",
            "x-requested-with": "XMLHttpRequest",
            "sec-fetch-site": "same-origin",
            "sec-fetch-mode": "cors",
            "sec-fetch-dest": "empty",
        }
        self.ios_headers.update(discovery_headers)

        if pconfig.xhs_ck:
            self.headers["cookie"] = pconfig.xhs_ck
            self.ios_headers["cookie"] = pconfig.xhs_ck
        self.session = AsyncSession(headers=self.headers, timeout=15, impersonate="chrome131")

    @handle("xhslink.com", r"xhslink\.com/[A-Za-z0-9._?%&+=/#@-]+")
    async def _parse_short_link(self, searched: re.Match[str]):
        url = f"https://{searched[0]}"
        return await self.parse_with_redirect(url, self.ios_headers)

    # discovery 链接需要在控制台使用手机模式打开，不然会跳转 explore
    # https://www.xiaohongshu.com/discovery/item/691e68a8000000001e02bcda?xsec_token=CBunzr4Cq8N7jbcXqpWDxGn11k7XwVIJ59KOvkRS_Qabw=
    # https://www.xiaohongshu.com/explore/691e68a8000000001e02bcda?xsec_token=CBunzr4Cq8N7jbcXqpWDxGn11k7XwVIJ59KOvkRS_Qabw=
    @handle(
        "xiaohongshu.com",
        r"(?P<type>explore|search_result|discovery/item)/(?P<note_id>[0-9a-zA-Z]+)\?(?P<qs>[A-Za-z0-9._%&+=/#@-]+)",
    )
    async def _parse_common(self, searched: re.Match[str]):
        xhs_domain = "https://www.xiaohongshu.com"
        # parse_type = searched["type"]
        note_id = searched["note_id"]
        qs = searched["qs"]

        # 原始 URL（保留所有 query 参数）
        full_url = f"{xhs_domain}/explore/{note_id}"

        # 解析 query string，检查 xsec_token
        params_dict = dict(parse_qsl(qs, keep_blank_values=True))
        xsec_token = params_dict.get("xsec_token")
        if not xsec_token:
            # TODO: 无需 xsec_token 解析, 即自动搜索获取 xsec_token
            # 参考 https://github.com/Cloxl/xhshow
            # 使用搜索 API 进行获取, 但极易死号
            raise ParseException("缺少 xsec_token, 无法解析小红书链接")

        full_url += f"?xsec_token={xsec_token}&xsec_source=pc_share"

        return await self.parse_explore(full_url, note_id)

    async def _fetch_initial_state(self, url: str) -> exploreInitialState:
        """
        mode: "explore" | "discovery"
        """
        response = await self.session.get(url)
        # may be 302
        if response.status_code > 400:
            response.raise_for_status()
        html = response.text
        pattern = r"window\.__INITIAL_STATE__=(.*?)</script>"
        if matched := re.search(pattern, html):
            raw = matched[1].replace("undefined", "null")
        else:
            raise ParseException("小红书分享链接失效或内容已删除")
        return exploreDecoder.decode(raw)

    def _build_result_from_note(
        self,
        *,
        title: str,
        text: str,
        author_name: str,
        author_avatar: str,
        video_url: str | None,
        live_urls: list[tuple[str, str]],
        image_urls: list[str],
        timestamp: int,
        cover_from_images: bool = True,
    ):
        contents: list[MediaContent | str] = [text]

        if video_url:
            cover_url = image_urls[0] if cover_from_images and image_urls else None
            contents.append(self.create_video(video_url, cover_url))
        elif image_urls:
            contents.extend(self.create_images(image_urls))

        contents.extend(self.create_video(live_url, live_cover_url) for live_url, live_cover_url in live_urls)
        author = self.create_author(author_name, author_avatar)

        return self.result(title=title, author=author, content=contents, timestamp=timestamp)

    async def parse_explore(self, url: str, note_id: str):
        init_state = await self._fetch_initial_state(url)
        note_detail = init_state.note.noteDetailMap[note_id].note

        return self._build_result_from_note(
            title=note_detail.title,
            text=note_detail.desc,
            author_name=note_detail.nickname,
            author_avatar=note_detail.avatar_url,
            video_url=note_detail.video_url,
            live_urls=note_detail.live_urls,
            image_urls=note_detail.image_urls,
            timestamp=note_detail.lastUpdateTime // 1000,
        )
