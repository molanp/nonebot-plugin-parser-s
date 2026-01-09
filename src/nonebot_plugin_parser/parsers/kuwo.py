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


class KuWoParser(BaseParser):
    # 平台信息
    platform: ClassVar[Platform] = Platform(name=PlatformEnum.KUWO, display_name="酷我音乐")
    
    @handle("kuwo.cn", r"https?://[^\s]*?kuwo\.cn/play_detail/\d+")
    async def _parse_kuwo_share(self, searched: Match[str]):
        """解析酷我音乐分享链接"""
        share_url = searched.group(0)
        logger.debug(f"触发酷我音乐解析: {share_url}")
        
        from httpx import AsyncClient
        
        # 使用API解析
        try:
            headers = COMMON_HEADER.copy()
            headers.update({
                "Content-Type": "application/json",
                "User-Agent": "API-Client/1.0"
            })
            
            async with AsyncClient(headers=headers, verify=False, timeout=self.timeout) as client:
                api_url = "https://api.bugpk.com/api/kuwo"
                params = {
                    "url": share_url
                }
                resp = await client.get(api_url, params=params)
                resp.raise_for_status()
                data = resp.json()
                
                # 检查接口返回状态
                if data.get("code") != 200:
                    raise ParseException(f"酷我音乐接口返回错误: {data.get('msg')}")
                    
                music_data = data["data"]
                logger.info(f"酷我音乐解析成功: {music_data['title']} - {music_data['artist']}")
                
                # 创建音频内容
                audio_url = music_data["music_url"]
                if not audio_url.startswith("http"):
                    raise ParseException("无效音乐URL")
                    
                # 解析时长
                duration = 0.0
                if music_data.get("songTimeMinutes"):
                    # 格式为 "mm:ss"
                    try:
                        minutes, seconds = map(int, music_data["songTimeMinutes"].split(":"))
                        duration = minutes * 60 + seconds
                    except ValueError:
                        pass
                
                # 创建音频内容
                audio_content = self.create_audio_content(
                    audio_url,
                    duration
                )
                
                # 创建封面图片内容
                contents: list[MediaContent] = []
                
                cover_url = music_data.get("pic")
                if cover_url:
                    from ..download import DOWNLOADER
                    cover_content = ImageContent(
                        DOWNLOADER.download_img(cover_url, ext_headers=self.headers)
                    )
                    contents.append(cover_content)
                
                # 添加音频内容到列表
                contents.append(audio_content)
                
                # 构建文本内容
                text = f"专辑: {music_data['album']}\n发行时间: {music_data['releaseDate']}\n时长: {music_data['songTimeMinutes']}"
                if "lyrics_url" in music_data and music_data["lyrics_url"]:
                    text += f"\n歌词:\n{music_data['lyrics_url']}"
                
                # 构建额外信息
                extra = {
                    "info": f"时长: {music_data['songTimeMinutes']} | 专辑: {music_data['album']}",
                    "type": "audio",
                    "type_tag": "音乐",
                    "type_icon": "fa-music",
                }
                
                return self.result(
                    title=music_data["title"],
                    author=self.create_author(music_data["artist"]),
                    url=share_url,
                    text=text,
                    contents=contents,
                    extra=extra,
                )
        except Exception as e:
            raise ParseException(f"酷我音乐解析失败: {e}")