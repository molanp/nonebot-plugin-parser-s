import re
from typing import ClassVar
from re import Match

from nonebot import logger

from .base import (
    BaseParser,
    PlatformEnum,
    ParseException,
    handle,
)
from .data import Platform, MediaContent, AudioContent, ImageContent
from ..constants import COMMON_HEADER


class QSMusicParser(BaseParser):
    # 平台信息
    platform: ClassVar[Platform] = Platform(name=PlatformEnum.QSMUSIC, display_name="汽水音乐")
    
    @handle("qishui.douyin.com", r"https?://[^\s]*?qishui\.douyin\.com/s/[a-zA-Z0-9]+/")
    async def _parse_qsmusic_share(self, searched: Match[str]):
        """解析汽水音乐分享链接"""
        share_url = searched.group(0)
        logger.debug(f"触发汽水音乐解析: {share_url}")
        
        from httpx import AsyncClient
        
        # 使用API解析
        try:
            headers = COMMON_HEADER.copy()
            headers.update({
                "Content-Type": "application/json",
                "User-Agent": "API-Client/1.0"
            })
            
            async with AsyncClient(headers=headers, verify=False, timeout=self.timeout) as client:
                api_url = "https://api.bugpk.com/api/qsmusic"
                params = {
                    "url": share_url
                }
                resp = await client.get(api_url, params=params)
                resp.raise_for_status()
                data = resp.json()
                
                # 检查接口返回状态
                if data.get("code") != 200:
                    raise ParseException(f"汽水音乐接口返回错误: {data.get('msg')}")
                    
                music_data = data["data"]
                logger.info(f"汽水音乐解析成功: {music_data['albumname']} - {music_data['artistsname']}")
                
                # 创建音频内容
                audio_url = music_data["url"]
                if not audio_url.startswith("http"):
                    raise ParseException("无效音乐URL")
                    
                # 由于API没有返回音频时长，我们设置为0.0
                audio_content = self.create_audio_content(
                    audio_url,
                    0.0
                )
                
                # 创建封面图片内容（如果有）
                contents: list[MediaContent] = [audio_content]
                
                # 构建文本内容
                text = f"专辑: {music_data['albumname']}\n音质: {music_data['Format']} | 大小: {music_data['Size']}"
                if "lyric" in music_data and music_data["lyric"]:
                    text += f"\n歌词:\n{music_data['lyric']}"
                
                # 构建额外信息
                extra = {
                    "info": f"音质: {music_data['Format']} | 大小: {music_data['Size']}",
                    "type": "audio",
                    "type_tag": "音乐",
                    "type_icon": "fa-music",
                }
                
                return self.result(
                    title=music_data["albumname"],
                    author=self.create_author(music_data["artistsname"]),
                    url=share_url,
                    text=text,
                    contents=contents,
                    extra=extra,
                )
        except Exception as e:
            raise ParseException(f"汽水音乐解析失败: {e}")