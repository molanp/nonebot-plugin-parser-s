import json
import re
from typing import Optional, Dict, Any, List

from ..base import BaseParser, handle
from ..data import Platform, Author, MediaContent, ImageContent, VideoContent
from ...exception import ParseException
from ...constants import PlatformEnum
from ...browser_pool import browser_pool, safe_browser_context


class TapTapParser(BaseParser):
    """TapTap 解析器"""
    
    platform = Platform(
        name=PlatformEnum.TAPTAP.value,
        display_name="TapTap"
    )
    
    def __init__(self):
        super().__init__()
        self.base_url = "https://www.taptap.cn"
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8"
        }
    
    def _resolve_nuxt_value(self, root_data: list, value: Any) -> Any:
        """Nuxt数据解压"""
        if isinstance(value, int):
            if 0 <= value < len(root_data):
                return root_data[value]
            return value
        return value
    
    async def _fetch_nuxt_data(self, url: str) -> list:
        """获取页面的 Nuxt 数据"""
        async with browser_pool.get_browser() as browser:
            async with safe_browser_context(browser) as (context, page):
                # 导航到 URL
                await page.goto(url, wait_until="domcontentloaded")
                await page.wait_for_timeout(2000)  # 等待 2 秒确保页面完全加载
                
                # 获取页面内容
                response_text = await page.content()
                
                # 提取 __NUXT_DATA__
                match = re.search(r'<script id="__NUXT_DATA__"[^>]*>(.*?)</script>', response_text, re.DOTALL)
                if not match:
                    raise ParseException(f"无法找到 Nuxt 数据: {url}")
                
                try:
                    result = json.loads(match.group(1))
                    return result if isinstance(result, list) else []
                except json.JSONDecodeError as e:
                    raise ParseException(f"解析 Nuxt 数据失败: {e}")
    
    async def _parse_post_detail(self, post_id: str) -> Dict[str, Any]:
        """解析动态详情"""
        url = f"{self.base_url}/moment/{post_id}"
        data = await self._fetch_nuxt_data(url)
        
        result = {
            "id": post_id,
            "url": url,
            "title": "",
            "summary": "",
            "images": [],
            "videos": []
        }
        
        # 补全标题和摘要
        for item in data:
            if isinstance(item, dict) and 'title' in item and 'summary' in item:
                title = self._resolve_nuxt_value(data, item['title'])
                summary = self._resolve_nuxt_value(data, item['summary'])
                if title and isinstance(title, str):
                    result['title'] = title
                if summary and isinstance(summary, str):
                    result['summary'] = summary
        
        if not result['title']:
            result['title'] = "TapTap 动态分享"
        
        # 图片处理
        images = []
        img_blacklist = ['appicon', 'avatars', 'logo', 'badge', 'emojis', 'market']
        for item in data:
            if not isinstance(item, dict):
                continue
            if 'original_url' in item:
                img_url = self._resolve_nuxt_value(data, item['original_url'])
                if img_url and isinstance(img_url, str) and img_url.startswith('http'):
                    lower_url = img_url.lower()
                    if not any(k in lower_url for k in img_blacklist):
                        if img_url not in images:
                            images.append(img_url)
            
            # 尝试从 Nuxt 数据中找视频链接
            if 'video_url' in item or 'url' in item:
                video_url = self._resolve_nuxt_value(data, item.get('video_url') or item.get('url'))
                if isinstance(video_url, str) and ('.mp4' in video_url or '.m3u8' in video_url) and video_url.startswith('http'):
                    if video_url not in result['videos']:
                        result['videos'].append(video_url)
        
        result["images"] = images
        return result
    
    async def _parse_user_latest_post(self, user_id: str) -> Optional[Dict[str, Any]]:
        """获取用户最新动态"""
        url = f"{self.base_url}/user/{user_id}"
        data = await self._fetch_nuxt_data(url)
        
        candidates = []
        moment_signature = ['id_str', 'author', 'topic', 'created_time']
        
        for item in data:
            if isinstance(item, dict) and all(key in item for key in moment_signature):
                moment_id = self._resolve_nuxt_value(data, item.get('id_str'))
                if not (moment_id and isinstance(moment_id, str) and moment_id.isdigit() and len(moment_id) > 10):
                    continue
                
                topic_index = item.get('topic')
                if not isinstance(topic_index, int) or topic_index >= len(data):
                    continue
                topic_obj = data[topic_index]
                if not isinstance(topic_obj, dict):
                    continue
                
                candidates.append({
                    'id': moment_id,
                    'title': self._resolve_nuxt_value(data, topic_obj.get('title')),
                    'summary': self._resolve_nuxt_value(data, topic_obj.get('summary'))
                })
        
        if not candidates:
            return None
        return max(candidates, key=lambda x: int(x['id']))
    
    @handle(keyword="taptap.cn/user", pattern=r"taptap\.cn/user/(\d+)")
    async def handle_user(self, matched):
        """处理用户链接，返回最新动态"""
        user_id = matched.group(1)
        latest_post = await self._parse_user_latest_post(user_id)
        
        if not latest_post:
            raise ParseException(f"用户 {user_id} 暂无动态")
        
        detail = await self._parse_post_detail(latest_post['id'])
        return self._build_result(detail)
    
    @handle(keyword="taptap.cn/moment", pattern=r"taptap\.cn/moment/(\d+)")
    async def handle_moment(self, matched):
        """处理动态链接"""
        post_id = matched.group(1)
        detail = await self._parse_post_detail(post_id)
        return self._build_result(detail)
    
    @handle(keyword="taptap.cn/topic", pattern=r"taptap\.cn/topic/(\d+)")
    async def handle_topic(self, matched):
        """处理话题链接"""
        topic_id = matched.group(1)
        # 话题链接暂时返回动态列表，这里简化处理
        url = f"{self.base_url}/topic/{topic_id}"
        data = await self._fetch_nuxt_data(url)
        
        # 简单提取话题名称
        topic_name = "TapTap 话题"
        for item in data:
            if isinstance(item, dict) and 'title' in item:
                title = self._resolve_nuxt_value(data, item['title'])
                if title and isinstance(title, str):
                    topic_name = title
                    break
        
        return self.result(
            title=topic_name,
            text=f"查看话题详情: {url}",
            url=url
        )
    
    def _build_result(self, detail: Dict[str, Any]):
        """构建解析结果"""
        contents = []
        
        # 添加图片
        for img_url in detail['images']:
            contents.append(self.create_image_contents([img_url])[0])
        
        # 添加视频
        for video_url in detail['videos']:
            # 简单处理，不获取封面和时长
            contents.append(self.create_video_content(video_url))
        
        return self.result(
            title=detail['title'],
            text=detail['summary'],
            url=detail['url'],
            contents=contents
        )
