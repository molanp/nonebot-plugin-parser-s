import json
import asyncio
from re import Match
from typing import ClassVar, List, Dict, Any, Optional
from collections.abc import AsyncGenerator

from msgspec import convert
from nonebot import logger
import httpx
from bilibili_api import HEADERS, Credential, select_client, request_settings
from bilibili_api.opus import Opus
from bilibili_api.video import Video
from bilibili_api.login_v2 import QrCodeLogin, QrCodeLoginEvents

from ..base import (
    DOWNLOADER,
    BaseParser,
    PlatformEnum,
    ParseException,
    DownloadException,
    DurationLimitException,
    handle,
    pconfig,
)
from ..data import Platform, ImageContent, MediaContent
from ..cookie import ck2dict

# 选择客户端
select_client("curl_cffi")
# 模拟浏览器，第二参数数值参考 curl_cffi 文档
# https://curl-cffi.readthedocs.io/en/latest/impersonate.html
request_settings.set("impersonate", "chrome131")


class BilibiliParser(BaseParser):
    # 平台信息
    platform: ClassVar[Platform] = Platform(name=PlatformEnum.BILIBILI, display_name="哔哩哔哩")

    def __init__(self):
        self.headers = HEADERS.copy()
        self._credential: Credential | None = None
        self._cookies_file = pconfig.config_dir / "bilibili_cookies.json"

    def _format_stat(self, num: int | None) -> str:
        """将数字格式化为 1.2万 的形式"""
        if num is None:
            return "0"
        format_num = str(num) if num < 10000 else f"{num / 10000:.1f}万"
        return format_num

    @handle("b23.tv", r"b23\.tv/[A-Za-z\d\._?%&+\-=/#]+")
    @handle("bili2233", r"bili2233\.cn/[A-Za-z\d\._?%&+\-=/#]+")
    async def _parse_short_link(self, searched: Match[str]):
        """解析短链"""
        url = f"https://{searched.group(0)}"
        return await self.parse_with_redirect(url)

    @handle("BV", r"^(?P<bvid>BV[0-9a-zA-Z]{10})(?:\s)?(?P<page_num>\d{1,3})?$")
    @handle("/BV", r"bilibili\.com(?:/video)?/(?P<bvid>BV[0-9a-zA-Z]{10})(?:\?p=(?P<page_num>\d{1,3}))?")
    async def _parse_bv(self, searched: Match[str]):
        """解析视频信息"""
        bvid = str(searched.group("bvid"))
        page_num = int(searched.group("page_num") or 1)

        return await self.parse_video(bvid=bvid, page_num=page_num)

    @handle("av", r"^av(?P<avid>\d{6,})(?:\s)?(?P<page_num>\d{1,3})?$")
    @handle("/av", r"bilibili\.com(?:/video)?/av(?P<avid>\d{6,})(?:\?p=(?P<page_num>\d{1,3}))?")
    async def _parse_av(self, searched: Match[str]):
        """解析视频信息"""
        avid = int(searched.group("avid"))
        page_num = int(searched.group("page_num") or 1)

        return await self.parse_video(avid=avid, page_num=page_num)

    @handle("/dynamic/", r"bilibili\.com/dynamic/(?P<dynamic_id>\d+)")
    @handle("t.bili", r"t\.bilibili\.com/(?P<dynamic_id>\d+)")
    @handle("/opus/", r"bilibili\.com/opus/(?P<dynamic_id>\d+)")
    async def _parse_dynamic(self, searched: Match[str]):
        """解析动态信息"""
        dynamic_id = int(searched.group("dynamic_id"))
        return await self.parse_dynamic_or_opus(dynamic_id)

    @handle("live.bili", r"live\.bilibili\.com/(?P<room_id>\d+)")
    async def _parse_live(self, searched: Match[str]):
        """解析直播信息"""
        room_id = int(searched.group("room_id"))
        return await self.parse_live(room_id)

    @handle("/favlist", r"favlist\?fid=(?P<fav_id>\d+)")
    async def _parse_favlist(self, searched: Match[str]):
        """解析收藏夹信息"""
        fav_id = int(searched.group("fav_id"))
        return await self.parse_favlist(fav_id)

    @handle("/read/", r"bilibili\.com/read/cv(?P<read_id>\d+)")
    async def _parse_read(self, searched: Match[str]):
        """解析专栏信息"""
        read_id = int(searched.group("read_id"))
        return await self.parse_read(read_id)
    
    XOR_CODE = 23442827791579
    MASK_CODE = 2251799813685247
    MAX_AID = 1 << 51
    ALPHABET = "FcwAPNKTMug3GV5Lj7EJnHpWsx4tb8haYeviqBz6rkCy12mUSDQX9RdoZf"
    ENCODE_MAP = (8, 7, 0, 5, 1, 3, 2, 4, 6)
    DECODE_MAP = tuple(reversed(ENCODE_MAP))
    
    BASE = len(ALPHABET)
    PREFIX = "BV1"
    PREFIX_LEN = len(PREFIX)
    CODE_LEN = len(ENCODE_MAP)
    
    @classmethod
    def av2bv(cls, aid: int) -> str:
        """将AV号转换为BV号"""
        bvid = [""] * 9
        tmp = (cls.MAX_AID | aid) ^ cls.XOR_CODE
        for i in range(cls.CODE_LEN):
            bvid[cls.ENCODE_MAP[i]] = cls.ALPHABET[tmp % cls.BASE]
            tmp //= cls.BASE
        return cls.PREFIX + "".join(bvid)
    
    @classmethod
    def bv2av(cls, bvid: str) -> int:
        """将BV号转换为AV号"""
        assert bvid[:cls.PREFIX_LEN] == cls.PREFIX
        
        bvid = bvid[cls.PREFIX_LEN:]
        tmp = 0
        for i in range(cls.CODE_LEN):
            idx = cls.ALPHABET.index(bvid[cls.DECODE_MAP[i]])
            tmp = tmp * cls.BASE + idx
        return (tmp & cls.MASK_CODE) ^ cls.XOR_CODE
    
    async def parse_video(
        self,
        *,
        bvid: str | None = None,
        avid: int | None = None,
        page_num: int = 1,
    ):
        """解析视频信息

        Args:
            bvid (str | None): bvid
            avid (int | None): avid
            page_num (int): 页码
        """

        from .video import VideoInfo, AIConclusion

        video = await self._get_video(bvid=bvid, avid=avid)
        # 转换为 msgspec struct
        video_info = convert(await video.get_info(), VideoInfo)
        # 获取简介
        text = f"简介: {video_info.desc}" if video_info.desc else None
        # up
        author = self.create_author(video_info.owner.name, video_info.owner.face)
        # 处理分 p
        page_info = video_info.extract_info_with_page(page_num)

        # 获取 AI 总结
        if self._credential:
            cid = await video.get_cid(page_info.index)
            ai_conclusion = await video.get_ai_conclusion(cid)
            ai_conclusion = convert(ai_conclusion, AIConclusion)
            ai_summary = ai_conclusion.summary
        else:
            ai_summary: str = "哔哩哔哩 cookie 未配置或失效, 无法使用 AI 总结"

        url = f"https://bilibili.com/{video_info.bvid}"
        url += f"?p={page_info.index + 1}" if page_info.index > 0 else ""

        # 视频下载任务
        async def download_video():
            output_path = pconfig.cache_dir / f"{video_info.bvid}-{page_num}.mp4"
            if output_path.exists():
                return output_path
            v_url, a_url = await self.extract_download_urls(video=video, page_index=page_info.index)
            if page_info.duration > pconfig.duration_maximum:
                raise DurationLimitException
            if a_url is not None:
                return await DOWNLOADER.download_av_and_merge(
                    v_url, a_url, output_path=output_path, ext_headers=self.headers
                )
            else:
                return await DOWNLOADER.streamd(v_url, file_name=output_path.name, ext_headers=self.headers)

        # 创建视频下载内容（传递下载函数而非立即执行）
        video_content = self.create_video_content(
            download_video,
            page_info.cover,
            page_info.duration,
        )

        # 提取统计数据
        stats = {}
        try:
            if video_info.stat:
                stats = {
                    "play": self._format_stat(video_info.stat.view),
                    "danmaku": self._format_stat(video_info.stat.danmaku),
                    "like": self._format_stat(video_info.stat.like),
                    "coin": self._format_stat(video_info.stat.coin),
                    "favorite": self._format_stat(video_info.stat.favorite),
                    "share": self._format_stat(video_info.stat.share),
                    "reply": self._format_stat(video_info.stat.reply),
                }
                logger.debug(f"[BiliParser] 视频统计数据: {stats}")
        except Exception as e:
            logger.warning(f"[BiliParser] 统计数据提取异常: {e}")

        # 使用BV-AV转换算法将BV号转换为AV号
        bvid = video_info.bvid
        try:
            if bvid.startswith('BV'):
                # 使用类中已封装的bv2av方法进行转换
                video_oid = self.bv2av(bvid)
                logger.debug(f"[BiliParser] BV号 {bvid} 转换为AV号 {video_oid}")
            else:
                # 如果不是BV号，直接使用
                video_oid = int(bvid)
        except Exception as e:
            logger.error(f"[BiliParser] BV-AV转换失败: {e}")
            # 转换失败时使用BV号的数值形式作为oid
            video_oid = int(bvid.replace('BV', ''), 36)
            logger.debug(f"[BiliParser] 使用备用方法获取oid: {video_oid}")
        
        # 获取评论数据 - _fetch_comments方法已经处理好所有数据
        comments = await self._fetch_comments(video_oid, 1)  # type=1 表示视频
        processed_comments = comments if comments else []

        # 构造 extra_data
        extra_data = {
            "info": ai_summary,
            "stats": stats,
            "type": "video",
            "type_tag": "视频",
            "type_icon": "fa-circle-play",
            "author_id": str(video_info.owner.mid),
            "content_id": video_info.bvid,
            "comments": processed_comments
        }
        logger.debug(f"Video extra data: {extra_data}")

        return self.result(
            url=url,
            title=page_info.title,
            timestamp=page_info.timestamp,
            text=text,
            author=author,
            contents=[video_content],
            extra=extra_data,
        )

    async def parse_dynamic_or_opus(self, dynamic_id: int):
        """解析动态和图文信息

        Args:
            url (str): 动态链接
        """
        from bilibili_api.dynamic import Dynamic

        from .dynamic import DynamicData

        dynamic = Dynamic(dynamic_id, await self.credential)
        logger.debug(f"B站解析 动态链接 原始：{dynamic}")
        if await dynamic.is_article():
            return await self._parse_opus_obj(dynamic.turn_to_opus())

        dynamic_info_data = await dynamic.get_info()
        logger.debug(f"B站动态链接 dynamic_info_data 原始：{dynamic_info_data}")
        dynamic_info = convert(dynamic_info_data, DynamicData).item

        author = self.create_author(dynamic_info.name, dynamic_info.avatar)

        # 下载图片
        contents: list[MediaContent] = []
        image_urls = dynamic_info.image_urls

        # 只下载主体图片，不添加默认图片到contents
        for image_url in image_urls:
            img_task = DOWNLOADER.download_img(image_url, ext_headers=self.headers)
            contents.append(ImageContent(img_task))

        # 提取当前动态的统计数据
        stats = {}
        try:
            if dynamic_info.modules.module_stat:
                m_stat = dynamic_info.modules.module_stat
                stats = {
                    "like": self._format_stat(m_stat.get("like", {}).get("count", 0)),
                    "reply": self._format_stat(m_stat.get("comment", {}).get("count", 0)),
                    "share": self._format_stat(m_stat.get("forward", {}).get("count", 0)),
                    "favorite": self._format_stat(m_stat.get("favorite", {}).get("count", 0)),
                }
            # 检查是否有浏览量字段
            modules = dynamic_info.modules
            if (hasattr(modules, "module_author") and
                hasattr(modules.module_author, "views_text")):
                views_value = modules.module_author.views_text
                if views_value is not None:
                    stats["play"] = views_value
        except Exception:
            pass

        # --- 基础 extra 数据 ---
        extra_data = {
            "stats": stats,
            "type": "dynamic",
            "type_tag": "动态",
            "type_icon": "fa-quote-left",
            "author_id": str(dynamic_info.modules.module_author.mid),
            "content_id": str(dynamic_id),
        }

        # --- 新增：处理转发内容 (叠加到 extra) ---
        repost_result = None
        if dynamic_info.type == "DYNAMIC_TYPE_FORWARD" and dynamic_info.orig:
            orig_item = dynamic_info.orig

            if orig_item.visible:
                orig_type_tag = "动态"
                major_info = orig_item.modules.major_info

                # 尝试判断源动态类型
                is_article = False
                orig_title = orig_item.title
                orig_text = orig_item.text
                orig_author = orig_item.name
                major_type = None

                if major_info:
                    major_type = major_info.get("type")
                    if major_type == "MAJOR_TYPE_ARCHIVE":
                        orig_type_tag = "视频"
                    elif major_type == "MAJOR_TYPE_OPUS":
                        orig_type_tag = "图文"
                        # 【新增】检查是否是专栏文章
                        opus_data = major_info.get("opus", {})
                        if opus_data and opus_data.get("jump_url"):
                            import re
                            match = re.search(r"/opus/(\d+)", opus_data["jump_url"])
                            if match:
                                is_article = True
                                orig_type_tag = "专栏"
                    elif major_type == "MAJOR_TYPE_DRAW":
                        orig_type_tag = "图文"

                # 获取源动态封面 (优先取视频封面，否则取第一张图)
                orig_cover = orig_item.cover_url
                if not orig_cover and orig_item.image_urls:
                    orig_cover = orig_item.image_urls[0]

                # 【新增】如果是专栏文章，使用 opus 解析获取完整内容
                if is_article and major_info:
                    opus_data = major_info.get("opus", {})
                    if opus_data and opus_data.get("jump_url"):
                        import re
                        match = re.search(r"/opus/(\d+)", opus_data["jump_url"])
                        if match:
                            opus_id = int(match.group(1))
                            try:
                                repost_result = await self.parse_opus(opus_id)
                                # 使用解析结果更新源动态信息
                                if repost_result.title:
                                    orig_title = repost_result.title
                                if repost_result.text:
                                    orig_text = repost_result.text
                                if repost_result.author:
                                    orig_author = repost_result.author.name
                            except Exception as e:
                                logger.warning(f"解析转发专栏失败: {e}")
                # 【新增】如果是视频，使用视频解析获取完整内容
                elif major_info and major_type == "MAJOR_TYPE_ARCHIVE" and major_info.get("archive"):
                    archive_data = major_info.get("archive", {})
                    bvid = archive_data.get("bvid")
                    if bvid:
                        try:
                            repost_result = await self.parse_video(bvid=bvid)
                            # 使用解析结果更新源动态信息
                            if repost_result.title:
                                orig_title = repost_result.title
                            if repost_result.text:
                                orig_text = repost_result.text
                            if repost_result.author:
                                orig_author = repost_result.author.name
                        except Exception as e:
                            logger.warning(f"解析转发视频失败: {e}")
                # 【新增】如果是动态，使用动态解析获取完整内容
                elif dynamic_info.orig:
                    try:
                        repost_result = await self.parse_dynamic_or_opus(int(orig_item.id_str))
                        # 使用解析结果更新源动态信息
                        if repost_result.title:
                            orig_title = repost_result.title
                        if repost_result.text:
                            orig_text = repost_result.text
                        if repost_result.author:
                            orig_author = repost_result.author.name
                    except Exception as e:
                        logger.warning(f"解析转发动态失败: {e}")

                # 构造 origin 字典（使用更新后的信息）
                extra_data["origin"] = {
                    "exists": True,
                    "author": orig_author,
                    "title": orig_title,
                    "text": orig_text,
                    "cover": orig_cover,
                    "type_tag": orig_type_tag,
                    "mid": str(orig_item.modules.module_author.mid),
                }
            else:
                # 源动态已失效
                extra_data["origin"] = {
                    "exists": False,
                    "text": "源动态已被删除或不可见",
                    "author": "未知",
                    "title": "资源失效",
                }

        # 获取标题和文本
        dynamic_title = dynamic_info.title or "B站动态"
        dynamic_text = dynamic_info.text

        # 如果标题和文本内容一致，则将文本置空，避免重复展示
        final_text = dynamic_text if dynamic_text and dynamic_text != dynamic_title else None

        # 构建动态URL，用于二维码生成（使用t.bilibili.com格式）
        dynamic_url = f"https://t.bilibili.com/{dynamic_id}"
        
        # 获取评论数据 - _fetch_comments方法已经处理好所有数据
        comments = None
        # 尝试从原始动态数据中获取评论参数
        basic_info = dynamic_info_data.get("item", {}).get("basic", {})
        comment_id_str = basic_info.get("comment_id_str")
        comment_type = basic_info.get("comment_type")
        
        # 检查major_info，判断动态类型
        major_info = dynamic_info.modules.major_info if hasattr(dynamic_info.modules, "major_info") else {}
        major_type = major_info.get("type") if isinstance(major_info, dict) else None
        
        # 根据动态类型选择正确的评论参数
        if comment_id_str and comment_type:
            # 使用动态数据中提供的comment_id_str和comment_type
            comments = await self._fetch_comments(int(comment_id_str), comment_type)
            logger.debug(f"[BiliParser] 使用动态数据中提供的评论参数: oid={comment_id_str}, type={comment_type}")
        elif major_type == "MAJOR_TYPE_ARCHIVE" and major_info:
            # 视频动态，使用视频的aid作为oid，type=1
            archive_data = major_info.get("archive", {})
            aid = archive_data.get("aid")
            if aid:
                comments = await self._fetch_comments(int(aid), 1)  # type=1 表示视频
                logger.debug(f"[BiliParser] 使用视频aid作为评论参数: oid={aid}, type=1")
        elif major_type == "MAJOR_TYPE_OPUS" and major_info:
            # 图文动态，使用opus_id作为oid，type=12
            opus_data = major_info.get("opus", {})
            opus_id = opus_data.get("id") or opus_data.get("opus_id")
            if opus_id:
                comments = await self._fetch_comments(int(opus_id), 12)  # type=12 表示专栏
                logger.debug(f"[BiliParser] 使用opus_id作为评论参数: oid={opus_id}, type=12")
        elif major_type == "MAJOR_TYPE_DRAW" and major_info:
            # 图片动态，使用动态id作为oid，type=11
            comments = await self._fetch_comments(dynamic_id, 11)  # type=11 表示相簿（图片动态）
            logger.debug(f"[BiliParser] 使用动态id作为图片动态评论参数: oid={dynamic_id}, type=11")
        else:
            # 默认情况，使用动态id作为oid，type=17
            comments = await self._fetch_comments(dynamic_id, 17)  # type=17 表示动态（纯文字动态&分享）
            logger.debug(f"[BiliParser] 使用默认评论参数: oid={dynamic_id}, type=17")
        
        if comments:
            extra_data["comments"] = comments
            logger.debug(f"[BiliParser] 成功获取 {len(comments)} 条动态评论")
        else:
            logger.debug(f"[BiliParser] 未获取到动态评论")
        
        return self.result(
            url=dynamic_url,
            title=dynamic_title,
            text=final_text,
            timestamp=dynamic_info.timestamp,
            author=author,
            contents=contents,
            extra=extra_data,
            repost=repost_result,
        )

    async def parse_opus(self, opus_id: int):
        """解析图文动态信息

        Args:
            opus_id (int): 图文动态 id
        """
        opus = Opus(opus_id, await self.credential)
        logger.debug(f"B站OPUS解析 图文动态 原始：{opus}")
        return await self._parse_opus_obj(opus)

    async def parse_read(self, read_id: int):
        """解析专栏信息, 使用 Opus 接口

        Args:
            read_id (int): 专栏 id
        """
        from bilibili_api.article import Article

        article = Article(read_id)
        bili_opus = await article.turn_to_opus()
        logger.debug(f"B站OPUS解析 专栏 原始：{bili_opus}")
        return await self._parse_opus_obj(bili_opus)

    async def _parse_opus_obj(self, bili_opus: Opus):
        """解析图文动态信息

        Args:
            opus_id (int): 图文动态 id

        Returns:
            ParseResult: 解析结果
        """

        from .opus import OpusItem, TextNode, ImageNode

        opus_info = await bili_opus.get_info()
        logger.debug(f"B站OPUS解析原始：{opus_info}")
        if not isinstance(opus_info, dict):
            raise ParseException("获取图文动态信息失败")
        # 转换为结构体
        opus_data = convert(opus_info, OpusItem)
        logger.debug(f"opus_data: {opus_data}")

        # 提取作者信息
        author_name = ""
        author_face = ""
        author_mid = ""

        if hasattr(opus_data.item, "modules"):
            for module in opus_data.item.modules:
                if module.module_type == "MODULE_TYPE_AUTHOR" and module.module_author:
                    author_name = module.module_author.name
                    author_face = module.module_author.face
                    author_mid = str(module.module_author.mid)
                    break

        if not author_name and hasattr(opus_data, "name_avatar"):
            author_name, author_face = opus_data.name_avatar

        author = self.create_author(author_name, author_face)

        # 按顺序处理图文内容（参考 parse_read 的逻辑）
        contents: list[MediaContent] = []
        full_text_list = []

        for node in opus_data.gen_text_img():
            if isinstance(node, ImageNode):
                # 使用 DOWNLOADER 下载并封装为 ImageContent
                img_task = DOWNLOADER.download_img(node.url, ext_headers=self.headers)
                contents.append(ImageContent(img_task))

            elif isinstance(node, TextNode):
                full_text_list.append(node.text)

        full_text = "\n".join(full_text_list).strip()

        # 如果没有提取到文本，尝试从原始结构体中直接获取
        if not full_text:
            # 遍历所有模块，寻找可能的文本内容
            if hasattr(opus_data.item, "modules"):
                for module in opus_data.item.modules:
                    # 检查内容模块是否有直接的文本
                    if module.module_type == "MODULE_TYPE_CONTENT" and module.module_content:
                        for paragraph in module.module_content.paragraphs:
                            # 直接检查段落是否有文本属性
                            if hasattr(paragraph, "text") and paragraph.text:
                                # 直接检查文本是否有内容
                                if hasattr(paragraph.text, "nodes") and paragraph.text.nodes:
                                    # 尝试直接提取文本内容
                                    for node in paragraph.text.nodes:
                                        if isinstance(node, dict):
                                            # 检查不同类型的文本节点
                                            if node.get("type") in ["TEXT_NODE_TYPE_WORD", "TEXT_NODE_TYPE_RICH"]:
                                                if isinstance(node.get("word"), dict):
                                                    full_text += node["word"].get("words", "")
                                            elif node.get("type") == "TEXT_NODE_TYPE_TEXT":
                                                full_text += node.get("text", "")
                                            elif node.get("type") == "TEXT_NODE_TYPE_PLAIN":
                                                full_text += node.get("content", "")
                                            # 其他可能的文本节点类型
                                            elif isinstance(node.get("word"), dict):
                                                full_text += node["word"].get("words", "")
                                            elif isinstance(node.get("text"), str):
                                                full_text += node["text"]

        # 提取统计数据
        stats = {}
        try:
            if hasattr(opus_data.item, "modules"):
                for module in opus_data.item.modules:
                    if module.module_type == "MODULE_TYPE_STAT" and module.module_stat:
                        st = module.module_stat
                        stats = {
                            "like": self._format_stat(st.get("like", {}).get("count", 0)),
                            "reply": self._format_stat(st.get("comment", {}).get("count", 0)),
                            "share": self._format_stat(st.get("forward", {}).get("count", 0)),
                            "favorite": self._format_stat(st.get("favorite", {}).get("count", 0)),
                        }
                    # 检查是否有浏览量字段
                    elif module.module_type == "MODULE_TYPE_AUTHOR" and module.module_author:
                        if hasattr(module.module_author, "views_text"):
                            views_value = module.module_author.views_text
                            if views_value is not None:
                                stats["play"] = views_value
        except Exception:
            pass

        # 构造 Extra 数据
        extra_data = {
            "stats": stats,
            "type": "opus",
            "type_tag": "图文",
            "type_icon": "fa-file-pen",
            "author_id": author_mid,
            "content_id": str(opus_data.item.id_str),
        }

        # 优先使用basic.title作为标题，如果没有则使用提取的文本或默认值
        # 如果标题和文本内容一致，则将文本置空，避免重复展示
        basic_title = opus_data.item.basic.title if opus_data.item.basic else None

        # 提取原始标题，移除默认的"xxx的动态-哔哩哔哩"格式
        original_title = basic_title
        if original_title and f"{author_name}的动态 - 哔哩哔哩" in original_title:
            original_title = None

        # 确定最终标题
        final_title = original_title or full_text or f"{author_name}的哔哩哔哩动态"

        # 如果标题和文本内容一致，则将文本置空
        final_text = full_text if full_text and full_text != final_title else None

        # 构建图文动态URL，用于二维码生成
        opus_id = getattr(bili_opus, "_opus_id", None) or getattr(bili_opus, "id", None)
        opus_url = f"https://www.bilibili.com/opus/{opus_id}" if opus_id else None
        
        # 获取评论数据 - _fetch_comments方法已经处理好所有数据
        comments = None
        # 获取opus原始数据，用于提取评论参数
        opus_info = await bili_opus.get_info() if hasattr(bili_opus, "get_info") else {}
        # 确保opus_info是字典类型
        opus_info = opus_info if isinstance(opus_info, dict) else {}
        # 尝试从原始opus数据中获取评论参数
        comment_id_str = None
        comment_type = None
        item_info = opus_info.get("item", {})
        # 确保item_info是字典类型
        item_info = item_info if isinstance(item_info, dict) else {}
        basic_info = item_info.get("basic", {})
        # 确保basic_info是字典类型
        basic_info = basic_info if isinstance(basic_info, dict) else {}
        comment_id_str = basic_info.get("comment_id_str")
        comment_type = basic_info.get("comment_type")
        
        content_id = str(opus_data.item.id_str)
        
        # 根据opus类型选择正确的评论参数
        if comment_id_str and comment_type:
            # 使用opus数据中提供的comment_id_str和comment_type
            comments = await self._fetch_comments(int(comment_id_str), comment_type)
            logger.debug(f"[BiliParser] 使用opus数据中提供的评论参数: oid={comment_id_str}, type={comment_type}")
        else:
            # 默认为图文动态，使用content_id作为oid，type=12
            comments = await self._fetch_comments(int(content_id), 12)  # type=12 表示专栏/图文
            logger.debug(f"[BiliParser] 使用content_id作为opus评论参数: oid={content_id}, type=12")
        
        if comments:
            extra_data["comments"] = comments
            logger.debug(f"[BiliParser] 成功获取 {len(comments)} 条专栏/图文评论")
        else:
            logger.debug(f"[BiliParser] 未获取到专栏/图文评论")
        
        return self.result(
            url=opus_url,
            title=final_title,
            author=author,
            timestamp=opus_data.timestamp,
            contents=contents,
            text=final_text,
            extra=extra_data,
        )

    async def parse_live(self, room_id: int):
        """解析直播信息

        Args:
            room_id (int): 直播 id

        Returns:
            ParseResult: 解析结果
        """
        from bilibili_api.live import LiveRoom

        from .live import RoomData

        room = LiveRoom(room_display_id=room_id, credential=await self.credential)
        logger.debug(f"B站直播解析原始：{room}")
        info_dict = await room.get_room_info()

        room_data = convert(info_dict, RoomData)
        contents: list[MediaContent] = []
        # 下载封面
        if cover := room_data.cover:
            cover_task = DOWNLOADER.download_img(cover, ext_headers=self.headers)
            contents.append(ImageContent(cover_task))

        # 下载关键帧
        if keyframe := room_data.keyframe:
            keyframe_task = DOWNLOADER.download_img(keyframe, ext_headers=self.headers)
            contents.append(ImageContent(keyframe_task))

        author = self.create_author(room_data.name, room_data.avatar)

        url = f"https://www.bilibili.com/blackboard/live/live-activity-player.html?enterTheRoom=0&cid={room_id}"

        extra_data = {
            "type": "live",
            "type_tag": f"直播·{room_data.room_info.parent_area_name}",
            "type_icon": "fa-tower-broadcast",
            "content_id": f"ROOM{room_id}",
            "tags": str(room_data.room_info.tags),
            "live_info": {
                "level": str(room_data.anchor_info.live_info.level),
                "level_color": str(room_data.anchor_info.live_info.level_color),
                "score": str(room_data.anchor_info.live_info.score),
            },
        }

        return self.result(
            url=url, title=room_data.title, text=room_data.detail, contents=contents, author=author, extra=extra_data
        )

    async def parse_favlist(self, fav_id: int):
        """解析收藏夹信息

        Args:
            fav_id (int): 收藏夹 id

        Returns:
            list[GraphicsContent]: 图文内容列表
        """
        from bilibili_api.favorite_list import get_video_favorite_list_content

        from .favlist import FavData

        # 只会取一页，20 个
        fav_dict = await get_video_favorite_list_content(fav_id)

        if fav_dict["medias"] is None:
            raise ParseException("收藏夹内容为空, 或被风控")

        favdata = convert(fav_dict, FavData)

        return self.result(
            title=favdata.title,
            timestamp=favdata.timestamp,
            author=self.create_author(favdata.info.upper.name, favdata.info.upper.face),
            contents=[self.create_graphics_content(fav.cover, fav.desc) for fav in favdata.medias],
        )

    async def _get_video(self, *, bvid: str | None = None, avid: int | None = None) -> Video:
        """解析视频信息

        Args:
            bvid (str | None): bvid
            avid (int | None): avid
        """
        if avid:
            return Video(aid=avid, credential=await self.credential)
        elif bvid:
            return Video(bvid=bvid, credential=await self.credential)
        else:
            raise ParseException("avid 和 bvid 至少指定一项")

    async def extract_download_urls(
        self,
        video: Video | None = None,
        *,
        bvid: str | None = None,
        avid: int | None = None,
        page_index: int = 0,
    ) -> tuple[str, str | None]:
        """解析视频下载链接

        Args:
            bvid (str | None): bvid
            avid (int | None): avid
            page_index (int): 页索引 = 页码 - 1
        """

        from bilibili_api.video import (
            AudioStreamDownloadURL,
            VideoStreamDownloadURL,
            VideoDownloadURLDataDetecter,
        )

        if video is None:
            video = await self._get_video(bvid=bvid, avid=avid)

        # 获取下载数据
        download_url_data = await video.get_download_url(page_index=page_index)
        detecter = VideoDownloadURLDataDetecter(download_url_data)
        streams = detecter.detect_best_streams(
            video_max_quality=pconfig.bili_video_quality,
            codecs=pconfig.bili_video_codes,
            no_dolby_video=True,
            no_hdr=True,
        )
        video_stream = streams[0]
        if not isinstance(video_stream, VideoStreamDownloadURL):
            raise DownloadException("未找到可下载的视频流")
        logger.debug(f"视频流质量: {video_stream.video_quality.name}, 编码: {video_stream.video_codecs}")

        audio_stream = streams[1]
        if not isinstance(audio_stream, AudioStreamDownloadURL):
            return video_stream.url, None
        logger.debug(f"音频流质量: {audio_stream.audio_quality.name}")
        return video_stream.url, audio_stream.url

    def _save_credential(self):
        """存储哔哩哔哩登录凭证"""
        if self._credential is None:
            return

        self._cookies_file.write_text(json.dumps(self._credential.get_cookies()))

    def _load_credential(self):
        """从文件加载哔哩哔哩登录凭证"""
        if not self._cookies_file.exists():
            return

        self._credential = Credential.from_cookies(json.loads(self._cookies_file.read_text()))

    async def login_with_qrcode(self) -> bytes:
        """通过二维码登录获取哔哩哔哩登录凭证"""
        self._qr_login = QrCodeLogin()
        await self._qr_login.generate_qrcode()

        qr_pic = self._qr_login.get_qrcode_picture()
        return qr_pic.content

    async def check_qr_state(self) -> AsyncGenerator[str]:
        """检查二维码登录状态"""
        scan_tip_pending = True

        for _ in range(30):
            state = await self._qr_login.check_state()
            match state:
                case QrCodeLoginEvents.DONE:
                    yield "登录成功"
                    self._credential = self._qr_login.get_credential()
                    self._save_credential()
                    break
                case QrCodeLoginEvents.CONF:
                    if scan_tip_pending:
                        yield "二维码已扫描, 请确认登录"
                        scan_tip_pending = False
                case QrCodeLoginEvents.TIMEOUT:
                    yield "二维码过期, 请重新生成"
                    break
            await asyncio.sleep(2)
        else:
            yield "二维码登录超时, 请重新生成"

    async def _init_credential(self):
        """初始化哔哩哔哩登录凭证"""
        if pconfig.bili_ck is None:
            self._load_credential()
            return

        credential = Credential.from_cookies(ck2dict(pconfig.bili_ck))
        if await credential.check_valid():
            logger.info(f"`parser_bili_ck` 有效, 保存到 {self._cookies_file}")
            self._credential = credential
            self._save_credential()
        else:
            logger.info(f"`parser_bili_ck` 已过期, 尝试从 {self._cookies_file} 加载")
            self._load_credential()

    async def _fetch_comments(self, oid: int, type: int) -> Optional[List[Dict[str, Any]]]:
        """从Bilibili API获取评论数据
        
        Args:
            oid: 目标评论区id
            type: 评论区类型代码
                1: 视频
                11: 动态
                17: 专栏
                12: 音频
                14: 相簿
        
        Returns:
            评论列表，按点赞数排序，最多10条
        """
        # 使用热评接口获取评论
        api_url = "https://api.bilibili.com/x/v2/reply/hot"
        params = {
            "oid": oid,
            "type": type,
            "root": 0,  # 根回复rpid，0表示获取所有热评
            "ps": 10,  # 每页10条热评
            "pn": 1,   # 第1页
        }
        
        try:
            # 创建包含基本headers的请求头
            request_headers = self.headers.copy()
            # 添加cookie信息到请求头
            if self._credential:
                cookies = self._credential.get_cookies()
                if cookies:
                    request_headers.update({
                        "Cookie": "; ".join([f"{k}={v}" for k, v in cookies.items()])
                    })
            
            async with httpx.AsyncClient(timeout=10.0) as client:
                logger.debug(f"[Bilibili] 调用热评API: {api_url}, 参数: {params}")
                response = await client.get(api_url, params=params, headers=request_headers)
                response.raise_for_status()
                data = response.json()
                
                logger.debug(f"[Bilibili] 热评API返回: {data}")
                
                if data.get("code") == 0 and data.get("data"):
                    replies = data["data"].get("replies", [])
                    logger.debug(f"[Bilibili] 获得热评: {len(replies)}条")
                    
                    # 处理评论数据，直接封装为前端可直接使用的格式
                    processed_comments = []
                    for comment in replies[:10]:
                        # 处理评论内容，包括图片
                        content = comment.get("content", {})
                        message = content.get("message", "")
                        
                        # 处理评论中的图片
                        processed_content = message
                        if content.get("pictures"):
                            for picture in content["pictures"]:
                                img_src = picture.get("img_src", "")
                                if img_src:
                                    processed_content += f'<img src="{img_src}" style="max-width: 100%; height: auto; border-radius: 8px; margin: 5px 0;">'  # 直接生成HTML
                        
                        # 格式化时间戳为可读时间
                        import datetime
                        created_time = comment.get("ctime", 0)
                        formatted_time = datetime.datetime.fromtimestamp(created_time).strftime("%Y-%m-%d %H:%M:%S")
                        
                        # 处理子回复
                        child_posts = []
                        if comment.get("replies"):
                            for reply in comment["replies"][:5]:  # 最多显示5条回复
                                reply_content = reply.get("content", {})
                                reply_message = reply_content.get("message", "")
                                
                                # 处理回复中的图片
                                processed_reply_content = reply_message
                                if reply_content.get("pictures"):
                                    for picture in reply_content["pictures"]:
                                        img_src = picture.get("img_src", "")
                                        if img_src:
                                            processed_reply_content += f'<img src="{img_src}" style="max-width: 100%; height: auto; border-radius: 6px; margin: 4px 0;">'  # 直接生成HTML
                                
                                # 格式化回复时间
                                reply_created_time = reply.get("ctime", 0)
                                reply_formatted_time = datetime.datetime.fromtimestamp(reply_created_time).strftime("%Y-%m-%d %H:%M:%S")
                                
                                child_posts.append({
                                    "id": reply.get("rpid_str", ""),
                                    "author": {
                                        "id": reply.get("mid", ""),
                                        "name": reply.get("member", {}).get("uname", ""),
                                        "avatar": reply.get("member", {}).get("avatar", "")
                                    },
                                    "content": processed_reply_content,
                                    "created_time": reply_formatted_time,
                                    "like": reply.get("like", 0)
                                })
                        
                        # 封装评论数据
                        processed_comments.append({
                            "id": comment.get("rpid_str", ""),
                            "author": {
                                "id": comment.get("mid", ""),
                                "name": comment.get("member", {}).get("uname", ""),
                                "avatar": comment.get("member", {}).get("avatar", "")
                            },
                            "content": processed_content,
                            "created_time": formatted_time,
                            "like": comment.get("like", 0),
                            "replies_count": comment.get("count", 0),
                            "child_posts": child_posts
                        })
                    
                    return processed_comments
                logger.debug(f"[Bilibili] 热评API返回数据为空或错误: code={data.get('code')}, message={data.get('message')}， `https://api.bilibili.com/x/v2/reply` 作为兜底，我们获取每页20项，查看第一页")
                # 使用普通评论API作为兜底，按点赞数排序，获取第一页20条
                fallback_api_url = "https://api.bilibili.com/x/v2/reply"
                fallback_params = {
                    "oid": oid,
                    "type": type,
                    "sort": 1,  # 按点赞数排序
                    "ps": 20,  # 每页20条，根据API文档，ps参数定义域是1-20
                    "pn": 1,   # 第1页
                }
                
                try:
                    response = await client.get(fallback_api_url, params=fallback_params, headers=request_headers)
                    response.raise_for_status()
                    fallback_data = response.json()
                    
                    logger.debug(f"[Bilibili] 兜底评论API返回: {fallback_data}")
                    
                    if fallback_data.get("code") == 0 and fallback_data.get("data"):
                        data = fallback_data["data"]
                        processed_comments = []
                        # 确保data是字典类型
                        if isinstance(data, dict):
                            fallback_replies = data.get("replies", [])
                            logger.debug(f"[Bilibili] 获得兜底评论: {len(fallback_replies)}条")
                            # 确保fallback_replies是列表类型
                            if isinstance(fallback_replies, list):
                                for comment in fallback_replies[:10]:
                                    # 处理评论内容，包括图片
                                    content = comment.get("content", {})
                                    message = content.get("message", "")
                                    
                                    # 处理评论中的图片
                                    processed_content = message
                                    if content.get("pictures"):
                                        for picture in content["pictures"]:
                                            img_src = picture.get("img_src", "")
                                            if img_src:
                                                processed_content += f'<img src="{img_src}" style="max-width: 100%; height: auto; border-radius: 8px; margin: 5px 0;">'
                                    
                                    # 格式化时间戳为可读时间
                                    import datetime
                                    created_time = comment.get("ctime", 0)
                                    formatted_time = datetime.datetime.fromtimestamp(created_time).strftime("%Y-%m-%d %H:%M:%S")
                                    
                                    # 处理子回复
                                    child_posts = []
                                    if comment.get("replies"):
                                        for reply in comment["replies"][:5]:  # 最多显示5条回复
                                            reply_content = reply.get("content", {})
                                            reply_message = reply_content.get("message", "")
                                            
                                            # 处理回复中的图片
                                            processed_reply_content = reply_message
                                            if reply_content.get("pictures"):
                                                for picture in reply_content["pictures"]:
                                                    img_src = picture.get("img_src", "")
                                                    if img_src:
                                                        processed_reply_content += f'<img src="{img_src}" style="max-width: 100%; height: auto; border-radius: 6px; margin: 4px 0;">'
                                            
                                            # 格式化回复时间
                                            reply_created_time = reply.get("ctime", 0)
                                            reply_formatted_time = datetime.datetime.fromtimestamp(reply_created_time).strftime("%Y-%m-%d %H:%M:%S")
                                            
                                            child_posts.append({
                                                "id": reply.get("rpid_str", ""),
                                                "author": {
                                                    "id": reply.get("mid", ""),
                                                    "name": reply.get("member", {}).get("uname", ""),
                                                    "avatar": reply.get("member", {}).get("avatar", "")
                                                },
                                                "content": processed_reply_content,
                                                "created_time": reply_formatted_time,
                                                "like": reply.get("like", 0)
                                            })
                                    
                                    # 封装评论数据
                                    processed_comments.append({
                                        "id": comment.get("rpid_str", ""),
                                        "author": {
                                            "id": comment.get("mid", ""),
                                            "name": comment.get("member", {}).get("uname", ""),
                                            "avatar": comment.get("member", {}).get("avatar", "")
                                        },
                                        "content": processed_content,
                                        "created_time": formatted_time,
                                        "like": comment.get("like", 0),
                                        "replies_count": comment.get("count", 0),
                                        "child_posts": child_posts
                                    })
                        
                        return processed_comments
                    logger.debug(f"[Bilibili] 兜底评论API返回数据为空或错误: code={fallback_data.get('code')}, message={fallback_data.get('message')}")
                    return []
                except Exception as e:
                    logger.error(f"[Bilibili] 获取兜底评论失败: {e}")
                    return None
        except Exception as e:
            logger.error(f"[Bilibili] 获取热评失败: {e}")
            return None
    
    @property
    async def credential(self) -> Credential | None:
        """哔哩哔哩登录凭证"""

        if self._credential is None:
            await self._init_credential()
            return self._credential

        if not await self._credential.check_valid():
            logger.warning("哔哩哔哩凭证已过期, 请重新配置")
            return None

        if await self._credential.check_refresh():
            logger.info("哔哩哔哩凭证需要刷新")
            if self._credential.has_ac_time_value() and self._credential.has_bili_jct():
                await self._credential.refresh()
                logger.info(f"哔哩哔哩凭证刷新成功, 保存到 {self._cookies_file}")
                self._save_credential()
            else:
                logger.warning("哔哩哔哩凭证刷新需要包含 `SESSDATA`, `ac_time_value` 项")

        return self._credential
