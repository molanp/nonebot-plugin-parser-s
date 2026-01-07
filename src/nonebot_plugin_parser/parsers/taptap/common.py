import json
import re
from datetime import datetime
from typing import Optional, Dict, Any, List

from nonebot import logger
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
                # 导航到 URL，增加等待时间确保页面完全加载
                await page.goto(url, wait_until="networkidle")  # 等待网络空闲，确保资源加载完成
                await page.wait_for_timeout(5000)  # 增加等待时间到5秒，确保页面完全渲染
                
                # 获取页面内容
                response_text = await page.content()
                
                # 调试：记录页面基本信息
                logger.debug(f"页面 URL: {url}")
                logger.debug(f"页面大小: {len(response_text)} 字节")
                logger.debug(f"页面包含 __NUXT_DATA__: {'__NUXT_DATA__' in response_text}")
                
                # 尝试多种方式提取 Nuxt 数据
                nuxt_data = None
                
                # 方式1: 尝试原始的 __NUXT_DATA__ 提取
                if "__NUXT_DATA__" in response_text:
                    # 尝试多种正则表达式匹配
                    patterns = [
                        r'<script id="__NUXT_DATA__"[^>]*>(.*?)</script>',
                        r'<script[^>]*id=["\']__NUXT_DATA__["\'][^>]*>(.*?)</script>',
                        r'<script[^>]*>(.*?__NUXT_DATA__.*?)</script>',
                    ]
                    
                    for pattern in patterns:
                        match = re.search(pattern, response_text, re.DOTALL)
                        if match:
                            logger.debug(f"使用正则表达式匹配成功: {pattern[:50]}...")
                            try:
                                # 提取json数据部分
                                json_match = re.search(r'__NUXT_DATA__\s*=\s*(\[.*?\])', match.group(1), re.DOTALL)
                                if json_match:
                                    nuxt_data = json.loads(json_match.group(1))
                                    break
                                # 尝试直接解析整个匹配内容
                                nuxt_data = json.loads(match.group(1))
                                break
                            except json.JSONDecodeError as e:
                                logger.debug(f"解析 Nuxt 数据失败，尝试下一个正则表达式: {e}")
                                continue
                
                # 方式2: 如果找不到 __NUXT_DATA__，尝试从 window.__NUXT__ 中提取
                if not nuxt_data and "window.__NUXT__" in response_text:
                    logger.debug("尝试从 window.__NUXT__ 中提取数据")
                    match = re.search(r'window\.__NUXT__\s*=\s*(\[.*?\])', response_text, re.DOTALL)
                    if match:
                        try:
                            nuxt_data = json.loads(match.group(1))
                        except json.JSONDecodeError as e:
                            logger.debug(f"解析 window.__NUXT__ 失败: {e}")
                
                # 方式3: 尝试从 window.__NUXT_DATA__ 中提取
                if not nuxt_data and "window.__NUXT_DATA__" in response_text:
                    logger.debug("尝试从 window.__NUXT_DATA__ 中提取数据")
                    match = re.search(r'window\.__NUXT_DATA__\s*=\s*(\[.*?\])', response_text, re.DOTALL)
                    if match:
                        try:
                            nuxt_data = json.loads(match.group(1))
                        except json.JSONDecodeError as e:
                            logger.debug(f"解析 window.__NUXT_DATA__ 失败: {e}")
                
                # 如果仍然没有找到数据，抛出异常并记录更多调试信息
                if not nuxt_data:
                    # 保存页面内容到临时文件，便于调试
                    temp_file = f"taptap_debug_{datetime.now().strftime('%Y%m%d_%H%M%S')}.html"
                    with open(temp_file, "w", encoding="utf-8") as f:
                        f.write(response_text)
                    logger.debug(f"页面内容已保存到临时文件: {temp_file}")
                    raise ParseException(f"无法找到 Nuxt 数据: {url}")
                
                # 确保返回的是列表
                return nuxt_data if isinstance(nuxt_data, list) else []
    
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
            "videos": [],
            "author": {
                "name": "",
                "avatar": ""
            },
            "publish_time": "",
            "stats": {
                "likes": 0,
                "comments": 0,
                "shares": 0
            }
        }
        
        # 补全标题、文本内容、作者信息和发布时间
        for item in data:
            if not isinstance(item, dict):
                continue
                
            # 提取标题和摘要（文本内容）
            if 'title' in item and 'summary' in item:
                title = self._resolve_nuxt_value(data, item['title'])
                summary = self._resolve_nuxt_value(data, item['summary'])
                if title and isinstance(title, str):
                    result['title'] = title
                if summary and isinstance(summary, str):
                    result['summary'] = summary
            
            # 尝试提取完整的文本内容
            if 'content' in item:
                content = self._resolve_nuxt_value(data, item['content'])
                if content and isinstance(content, str):
                    result['summary'] = content
            
            # 尝试从其他可能的字段提取文本
            if 'text' in item:
                text = self._resolve_nuxt_value(data, item['text'])
                if text and isinstance(text, str):
                    result['summary'] = text
            
            # 提取作者信息
            if 'author' in item:
                author = self._resolve_nuxt_value(data, item['author'])
                if isinstance(author, dict):
                    result['author']['name'] = self._resolve_nuxt_value(data, author.get('name', '')) or ''
                    # 尝试提取作者头像
                    if 'avatar' in author:
                        avatar = self._resolve_nuxt_value(data, author['avatar'])
                        if isinstance(avatar, dict) and 'original_url' in avatar:
                            result['author']['avatar'] = self._resolve_nuxt_value(data, avatar['original_url']) or ''
            
            # 提取发布时间
            if 'created_at' in item or 'publish_time' in item:
                publish_time = self._resolve_nuxt_value(data, item.get('created_at') or item.get('publish_time'))
                if publish_time:
                    result['publish_time'] = publish_time
            
            # 提取统计信息
            if 'stats' in item:
                stats = self._resolve_nuxt_value(data, item['stats'])
                if isinstance(stats, dict):
                    result['stats']['likes'] = stats.get('likes', 0)
                    result['stats']['comments'] = stats.get('comments', 0)
                    result['stats']['shares'] = stats.get('shares', 0)
        
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
        media_contents = []
        
        # 添加图片
        for img_url in detail['images']:
            contents.append(self.create_image_contents([img_url])[0])
        
        # 添加视频
        for video_url in detail['videos']:
            # 简单处理，不获取封面和时长
            video_content = self.create_video_content(video_url)
            contents.append(video_content)
            # 将视频添加到media_contents中，用于延迟发送
            media_contents.append((VideoContent, video_content))
        
        # 构建作者对象
        author = None
        if detail['author']['name']:
            author = self.create_author(
                name=detail['author']['name'],
                avatar_url=detail['author']['avatar']
            )
        
        # 处理发布时间，转换为时间戳
        timestamp = None
        publish_time = detail['publish_time']
        if publish_time:
            # 如果已经是整数，直接使用
            if isinstance(publish_time, int):
                timestamp = publish_time
            else:
                # 尝试解析不同格式的时间字符串
                try:
                    # 示例：2023-12-25T14:30:00+08:00
                    dt = datetime.fromisoformat(str(publish_time).replace('Z', '+00:00'))
                    timestamp = int(dt.timestamp())
                except (ValueError, TypeError):
                    # 如果解析失败，使用None
                    pass
        
        # 构建解析结果
        result = self.result(
            title=detail['title'],
            text=detail['summary'],
            url=detail['url'],
            author=author,
            timestamp=timestamp,
            contents=contents,
            extra={
                'stats': detail['stats'],
                'images': detail['images']  # 将图片列表放入extra，用于模板渲染
            }
        )
        
        # 设置media_contents，用于延迟发送
        result.media_contents = media_contents
        logger.debug(f"构建解析结果完成: title={detail['title']}, images={len(detail['images'])}, videos={len(detail['videos'])}, media_contents={len(media_contents)}")
        
        return result
