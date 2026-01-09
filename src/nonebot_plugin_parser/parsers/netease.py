import re
import asyncio
from typing import ClassVar
from re import Match

from nonebot import logger

from .base import (
    BaseParser,
    PlatformEnum,
    ParseException,
    handle,
)
from .data import Platform, AudioContent, ImageContent
from ..constants import COMMON_HEADER


class NCMParser(BaseParser):
    # 平台信息
    platform: ClassVar[Platform] = Platform(name=PlatformEnum.NETEASE, display_name="网易云音乐")
    
    def __init__(self):
        self.short_url_pattern = re.compile(r"(http:|https:)//163cn\.tv/([a-zA-Z0-9]+)")
        # 音质优先级列表
        self.audio_qualities = [
            "jymaster",  # 超清母带
            "sky",       # 沉浸环绕声
            "jyeffect",  # 高清环绕声
            "hires",     # Hi-Res音质
            "lossless",  # 无损音质
            "exhigh",    # 极高音质
            "standard"   # 标准音质
        ]
    
    async def _get_redirect_url(self, url: str) -> str:
        """获取重定向后的URL"""
        from httpx import AsyncClient
        
        headers = COMMON_HEADER.copy()
        async with AsyncClient(headers=headers, verify=False, follow_redirects=True, timeout=self.timeout) as client:
            response = await client.get(url)
            response.raise_for_status()
            return str(response.url)
    
    async def parse_ncm(self, ncm_url: str) -> dict:
        """解析网易云音乐链接"""
        # 处理短链接
        if matched := self.short_url_pattern.search(ncm_url):
            ncm_url = matched.group(0)
            ncm_url = await self._get_redirect_url(ncm_url)
        
        # 获取网易云歌曲id
        matched = re.search(r"(?:\?|&)id=(\d+)", ncm_url)
        if not matched:
            raise ParseException(f"无效网易云链接: {ncm_url}")
        
        ncm_id = matched.group(1)
        logger.info(f"成功提取ID: {ncm_id} 来自 {ncm_url}")
        
        # 使用API解析
        try:
            # 尝试多种音质直到成功
            for quality in self.audio_qualities:
                try:
                    from httpx import AsyncClient
                    
                    headers = COMMON_HEADER.copy()
                    async with AsyncClient(headers=headers, verify=False, timeout=self.timeout) as client:
                        api_url = f"https://api.cenguigui.cn/api/netease/music_v1.php?id={ncm_id}&type=json&level={quality}"
                        resp = await client.get(api_url)
                        resp.raise_for_status()
                        data = resp.json()
                        
                        # 检查接口返回状态
                        if data.get("code") != 200:
                            logger.warning(f"网易云接口返回错误: {data.get('msg')}，尝试下一种音质")
                            continue
                            
                        music_data = data["data"]
                        ncm_title = music_data["name"]
                        ncm_singer = music_data["artist"]
                        ncm_cover = music_data["pic"]
                        ncm_music_url = music_data["url"]
                        
                        # 验证音乐URL有效性
                        if not ncm_music_url.startswith("http"):
                            logger.warning(f"无效音乐URL: {ncm_music_url}，尝试下一种音质")
                            continue
                            
                        logger.info(f"使用音质: {quality} 解析成功: {ncm_title} - {ncm_singer}")
                        audio_info = f"音质: {music_data['format']} | 大小: {music_data['size']} | 时长: {music_data['duration']}"
                        
                        # 提取MV信息（如果存在）
                        mv_info = {}
                        if "mv_info" in music_data and music_data["mv_info"].get("mv"):
                            mv_info = {
                                "url": music_data["mv_info"]["mv"],
                                "size": music_data["mv_info"].get("size", ""),
                                "quality": f"{music_data['mv_info'].get('br', '')}P",
                                "duration": music_data.get("duration", "")
                            }
                            # 验证MV有效性
                            if not mv_info["url"].startswith("http"):
                                logger.warning(f"无效MV URL: {mv_info['url']}，忽略")
                                mv_info = {}
                            else:
                                logger.info(f"找到MV: {mv_info['url']} ({mv_info['quality']})")
                        
                        # 提取歌词信息（如果存在）
                        lyric = ""
                        if "lyric" in music_data and music_data["lyric"]:
                            lyric = music_data["lyric"]
                            logger.info(f"找到歌词，长度: {len(lyric)}字符")
                        
                        # 成功获取，返回结果
                        return {
                            "title": ncm_title,
                            "author": ncm_singer,
                            "audio_info": audio_info,
                            "cover_url": ncm_cover,
                            "audio_url": ncm_music_url,
                            "mv_info": mv_info,
                            "lyric": lyric
                        }
                except Exception as e:
                    logger.warning(f"请求失败: {e}，尝试下一种音质")
                    # 延时
                    await asyncio.sleep(1)
            else:
                raise ParseException("所有音质解析均失败")
                
        except Exception as e:
            raise ParseException(f"网易云音乐解析失败: {e}")
    
    @handle("music.163.com", r"https?://[^]*?music\.163\.com.*?(?:id=\d+|song/\d+)")
    @handle("163cn.tv", r"https?://[^]*?163cn\.tv/[a-zA-Z0-9]+")
    async def _parse_netease(self, searched: Match[str]):
        """解析网易云音乐分享链接"""
        share_url = searched.group(0)
        logger.debug(f"触发网易云解析: {share_url}")
        
        # 解析网易云音乐
        result = await self.parse_ncm(share_url)
        
        # 创建音频内容
        audio_content = self.create_audio_content(
            result["audio_url"],
            0.0  # 暂时无法从API获取准确时长
        )
        
        # 创建封面图片内容
        from ..download import DOWNLOADER
        cover_content = ImageContent(
            DOWNLOADER.download_img(result["cover_url"], ext_headers=self.headers)
        )
        
        # 构建内容列表
        contents = [cover_content, audio_content]
        
        # 构建文本内容
        text = f"{result['audio_info']}"
        if result["lyric"]:
            text += f"\n歌词:\n{result['lyric']}"
        
        # 构建额外信息
        extra = {
            "info": result["audio_info"],
            "type": "audio",
            "type_tag": "音乐",
            "type_icon": "fa-music",
        }
        
        return self.result(
            title=result["title"],
            author=self.create_author(result["author"]),
            url=share_url,
            text=text,
            contents=contents,
            extra=extra,
        )