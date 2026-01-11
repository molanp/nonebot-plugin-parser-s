import re
import json
from typing import ClassVar
from re import Match

from nonebot import logger

from .base import (
    BaseParser,
    PlatformEnum,
    ParseException,
    handle,
)
from .data import Platform, MediaContent, VideoContent, ImageContent
from ..constants import COMMON_HEADER


class ToutiaoParser(BaseParser):
    # 平台信息
    platform: ClassVar[Platform] = Platform(name=PlatformEnum.TOUTIAO, display_name="今日头条")
    
    @handle("ixigua.com", r"https?://[^\s]*?(?:toutiao\.com|ixigua\.com)/(?:is|video)/[^\s/]+/?")
    @handle("toutiao.com", r"https?://[^\s]*?(?:toutiao\.com|ixigua\.com)/(?:is|video)/[^\s/]+/?")
    async def _parse_toutiao_share(self, searched: Match[str]):
        """解析今日头条分享链接"""
        share_url = searched.group(0)
        logger.debug(f"触发今日头条解析: {share_url}")
        
        from httpx import AsyncClient
        
        # 使用API解析
        try:
            headers = COMMON_HEADER.copy()
            headers.update({
                "Content-Type": "application/json",
                "User-Agent": "API-Client/1.0"
            })
            
            async with AsyncClient(headers=headers, verify=False, timeout=self.timeout) as client:
                api_url = "https://api.bugpk.com/api/toutiao"
                params = {
                    "url": share_url
                }
                resp = await client.get(api_url, params=params)
                resp.raise_for_status()
                
                # 检查响应内容
                if not resp.content:
                    raise ParseException("今日头条接口返回空内容")
                    
                try:
                    data = resp.json()
                except json.JSONDecodeError as e:
                    # 记录响应内容以便调试
                    logger.error(f"今日头条接口返回无效JSON: {resp.text[:100]}...")
                    raise ParseException(f"今日头条接口返回无效JSON: {e}")
                
                # 检查接口返回状态
                if data.get("code") != 200:
                    raise ParseException(f"今日头条接口返回错误: {data.get('msg', '未知错误')}")
                    
                video_data = data.get("data")
                if not video_data:
                    raise ParseException("今日头条接口返回空数据")
                    
                logger.info(f"今日头条解析成功: {video_data.get('title', '未知标题')} - {video_data.get('author', '未知作者')}")
                
                # 创建视频内容 - 使用get方法安全访问
                video_url = video_data.get("url")
                if not video_url or not video_url.startswith("http"):
                    raise ParseException("无效视频URL")
                    
                # 解析封面 - 使用get方法安全访问
                cover_url = video_data.get("cover")
                
                # 创建视频内容
                video_content = self.create_video_content(
                    video_url,
                    cover_url,
                    0.0  # API没有返回时长
                )
                
                # 构建内容列表
                contents: list[MediaContent] = [video_content]
                
                # 构建额外信息
                extra = {
                    "info": f"作者: {video_data.get('author', '未知作者')}",
                    "type": "video",
                    "type_tag": "短视频",
                    "type_icon": "fa-video",
                }
                
                # 构建作者信息 - 安全访问字段
                author_name = video_data.get("author", "未知作者")
                author_avatar = video_data.get("avatar")
                
                return self.result(
                    title=video_data.get("title", "无标题"),
                    author=self.create_author(author_name, author_avatar),
                    url=share_url,
                    text=video_data.get("description", ""),
                    contents=contents,
                    extra=extra,
                )
        except Exception as e:
            raise ParseException(f"今日头条解析失败: {e}")