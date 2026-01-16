import asyncio
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
        max_retries = 3
        retry_count = 0
        
        while retry_count <= max_retries:
            try:
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
                        nuxt_data: list = []  # 明确类型标注为列表
                        
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
                                            parsed_data = json.loads(json_match.group(1))
                                            if isinstance(parsed_data, list):
                                                nuxt_data = parsed_data
                                                break
                                        # 尝试直接解析整个匹配内容
                                        parsed_data = json.loads(match.group(1))
                                        if isinstance(parsed_data, list):
                                            nuxt_data = parsed_data
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
                                    parsed_data = json.loads(match.group(1))
                                    if isinstance(parsed_data, list):
                                        nuxt_data = parsed_data
                                except json.JSONDecodeError as e:
                                    logger.debug(f"解析 window.__NUXT__ 失败: {e}")
                        
                        # 方式3: 尝试从 window.__NUXT_DATA__ 中提取
                        if not nuxt_data and "window.__NUXT_DATA__" in response_text:
                            logger.debug("尝试从 window.__NUXT_DATA__ 中提取数据")
                            match = re.search(r'window\.__NUXT_DATA__\s*=\s*(\[.*?\])', response_text, re.DOTALL)
                            if match:
                                try:
                                    parsed_data = json.loads(match.group(1))
                                    if isinstance(parsed_data, list):
                                        nuxt_data = parsed_data
                                except json.JSONDecodeError as e:
                                    logger.debug(f"解析 window.__NUXT_DATA__ 失败: {e}")
                        
                        # 如果仍然没有找到数据，抛出异常
                        if not nuxt_data:
                            # 保存页面内容到临时文件，便于调试
                            temp_file = f"taptap_debug_{datetime.now().strftime('%Y%m%d_%H%M%S')}.html"
                            with open(temp_file, "w", encoding="utf-8") as f:
                                f.write(response_text)
                            logger.debug(f"页面内容已保存到临时文件: {temp_file}")
                            raise ParseException(f"无法找到 Nuxt 数据: {url}")
                        
                        # 确保返回的是列表
                        return nuxt_data
            
            except Exception as e:
                retry_count += 1
                if retry_count > max_retries:
                    logger.error(f"获取 Nuxt 数据失败，已重试 {max_retries} 次 | url: {url}, error: {e}")
                    raise ParseException(f"获取 Nuxt 数据失败: {url}, error: {e}")
                
                logger.warning(f"获取 Nuxt 数据失败，正在重试 ({retry_count}/{max_retries}) | url: {url}, error: {e}")
                await asyncio.sleep(1 * retry_count)  # 指数退避
        
        # 这个代码路径理论上不会执行，因为循环中要么返回要么抛出异常
        # 但为了类型检查通过，我们添加一个兜底返回
        return []
    
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
            
            # 尝试从 contents 字段提取嵌套的文本内容
            if 'contents' in item:
                contents = self._resolve_nuxt_value(data, item['contents'])
                if isinstance(contents, list):
                    text_parts = []
                    for content_item in contents:
                        if not isinstance(content_item, dict):
                            continue
                        children = content_item.get('children')
                        if isinstance(children, list):
                            for child in children:
                                if isinstance(child, dict) and 'text' in child:
                                    child_text = self._resolve_nuxt_value(data, child['text'])
                                    if child_text and isinstance(child_text, str):
                                        text_parts.append(child_text)
                    if text_parts:
                        result['summary'] = '\n'.join(text_parts)
            
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
        
        # 尝试提取视频 ID
        video_id = None
        
        # 首先，查找所有包含视频封面的对象（这是最可靠的视频标识）
        video_cover_items = []
        for i, item in enumerate(data):
            if isinstance(item, dict) and 'original_url' in item:
                img_url = self._resolve_nuxt_value(data, item['original_url'])
                if isinstance(img_url, str) and 'video-picture' in img_url:
                    video_cover_items.append((i, item))
        
        # 提取图片
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
        
        # 处理视频封面相关的视频 ID
        for idx, video_cover_item in video_cover_items:
            logger.debug(f"找到视频封面 item: {idx}, {video_cover_item.keys()}")
            
            # 情况1: 当前 item 包含 video 字段，指向视频对象
            if 'video' in video_cover_item:
                video_ref = video_cover_item['video']
                video_obj = self._resolve_nuxt_value(data, video_ref)
                logger.debug(f"解析到视频对象: {video_obj}")
                
                if isinstance(video_obj, dict):
                    # 视频对象中直接包含 video_id
                    if 'video_id' in video_obj:
                        video_id = str(video_obj['video_id'])
                        break
                    # 视频对象中包含 id
                    elif 'id' in video_obj:
                        video_id = str(video_obj['id'])
                        break
                elif isinstance(video_obj, (str, int)):
                    # 直接是视频 ID
                    video_id = str(video_obj)
                    break
            
            # 情况2: 查找当前 item 的父对象
            # 遍历所有可能的父对象，查找包含当前视频封面的视频对象
            for i, item in enumerate(data):
                if isinstance(item, dict):
                    # 递归检查对象中是否包含当前视频封面的引用
                    def check_contains_cover(obj, cover_idx=idx):
                        if isinstance(obj, dict):
                            for k, v in obj.items():
                                if v == cover_idx:
                                    return True
                                if check_contains_cover(v, cover_idx):
                                    return True
                        elif isinstance(obj, list):
                            for v in obj:
                                if v == cover_idx:
                                    return True
                                if check_contains_cover(v, cover_idx):
                                    return True
                        return False
                    
                    # 检查当前 item 是否包含视频封面的引用
                    if check_contains_cover(item):
                        logger.debug(f"找到包含视频封面引用的父对象: {i}, {item.keys()}")
                        # 从父对象中提取视频 ID
                        if 'video_id' in item:
                            video_id = str(item['video_id'])
                            break
                        elif 'id' in item:
                            video_id = str(item['id'])
                            break
            
            # 如果已经找到视频 ID，退出循环
            if video_id:
                break
        
        # 如果还没找到视频 ID，尝试深度搜索
        if not video_id:
            logger.debug("深度搜索视频 ID...")
            
            def deep_search_video_id(obj):
                """深度搜索视频 ID"""
                nonlocal video_id
                if video_id:
                    return
                
                if isinstance(obj, dict):
                    # 查找 video_id 字段
                    if 'video_id' in obj:
                        val = obj['video_id']
                        if isinstance(val, (str, int)):
                            # 过滤掉小数字 ID
                            try:
                                if int(val) > 10000:
                                    video_id = str(val)
                                    return
                            except ValueError:
                                pass
                    # 查找包含视频信息的对象
                    elif any(k in obj for k in ['play_url', 'video_info', 'video_detail']) and 'id' in obj:
                        val = obj['id']
                        if isinstance(val, (str, int)):
                            try:
                                if int(val) > 10000:
                                    video_id = str(val)
                                    return
                            except ValueError:
                                pass
                    # 递归搜索
                    for k, v in obj.items():
                        deep_search_video_id(v)
                elif isinstance(obj, list):
                    for v in obj:
                        deep_search_video_id(v)
            
            # 对整个数据进行深度搜索
            deep_search_video_id(data)
        
        # 如果找到了视频 ID，尝试通过 API 获取视频信息
        if video_id:
            # 过滤掉明显无效的视频 ID
            try:
                video_id_int = int(video_id)
                # 视频 ID 应该是较大的数字，过滤掉太小的 ID
                if video_id_int < 10000:
                    logger.warning(f"视频 ID {video_id} 看起来无效，跳过 API 调用")
                    video_id = None
            except ValueError:
                logger.warning(f"视频 ID {video_id} 不是有效数字，跳过 API 调用")
                video_id = None
        
        if video_id:
            logger.info(f"找到视频 ID: {video_id}, 尝试通过 API 获取视频信息")
            try:
                # 使用正确的 API 端点获取视频信息
                api_url = f"https://www.taptap.cn/webapiv2/video-resource/v1/multi-get?video_ids={video_id}&X-UA=V%3D1%26PN%3DWebApp%26LANG%3Dzh_CN%26VN_CODE%3D102%26LOC%3DCN%26PLT%3DPC%26DS%3DAndroid%26UID%3D6a5a7508-f0cc-48aa-818a-2a836028fc51%26OS%3DWindows%26OSV%3D10%26DT%3DPC"
                
                # 创建 httpx 客户端
                import httpx
                async with httpx.AsyncClient() as client:
                    response = await client.get(api_url, headers=self.headers, timeout=10)
                    response.raise_for_status()
                    
                    # 解析 API 响应
                    api_response = response.json()
                    logger.debug(f"API 返回: {api_response}")
                    
                    # 检查响应是否成功
                    if api_response.get('success'):
                        data = api_response.get('data', {})
                        video_list = data.get('list', [])
                        
                        # 遍历视频列表
                        for video_item in video_list:
                            if isinstance(video_item, dict):
                                # 检查 best_format_name（为空则忽略）
                                best_format_name = video_item.get('info', {}).get('best_format_name', '')
                                if best_format_name:
                                    logger.info(f"视频最佳格式: {best_format_name}")
                                
                                # 提取视频链接
                                play_url = video_item.get('play_url', {})
                                if isinstance(play_url, dict):
                                    # 获取不同格式的视频链接
                                    for url_key in ['url', 'url_h265']:
                                        if url_key in play_url:
                                            video_url = play_url[url_key]
                                            if isinstance(video_url, str) and video_url.startswith('http'):
                                                if video_url not in result['videos']:
                                                    result['videos'].append(video_url)
                                                    logger.info(f"成功获取视频链接: {video_url}")
            except Exception as e:
                logger.error(f"通过 API 获取视频信息失败: {e}")
        
        # 如果仍然没有找到视频链接，尝试从页面中提取替代的m3u8链接
        if not result['videos']:
            logger.info("尝试从页面中提取替代的m3u8链接")
            
            # 清晰度优先级：2208 1080P > 2206 720P > 2204 540P > 2202 360P
            quality_priority = ['2208', '2206', '2204', '2202']
            
            # 首先提取基础的hls路径
            base_hls_url = None
            
            def find_base_hls_url(obj):
                """查找基础的hls路径"""
                nonlocal base_hls_url
                if base_hls_url:
                    return
                
                if isinstance(obj, dict):
                    for k, v in obj.items():
                        if isinstance(v, str) and '.m3u8' in v and 'pl.taptap.cn/hls/' in v:
                            # 提取基础路径，例如从 https://pl.taptap.cn/hls/xxx.m3u8?xxx 提取 https://pl.taptap.cn/hls/xxx/
                            hls_base = v.split('.m3u8')[0]
                            if '/hls/' in hls_base:
                                # 提取最后一个斜杠前的部分
                                hls_path = hls_base.rsplit('/', 1)[0] + '/'
                                base_hls_url = hls_path
                                logger.info(f"找到基础hls路径: {base_hls_url}")
                                return
                        else:
                            find_base_hls_url(v)
                elif isinstance(obj, list):
                    for item in obj:
                        find_base_hls_url(item)
            
            # 查找基础hls路径
            find_base_hls_url(data)
            
            # 如果找到基础hls路径，构建不同清晰度的链接
            if base_hls_url:
                for quality in quality_priority:
                    # 构建不同清晰度的m3u8链接
                    m3u8_url = f"{base_hls_url}{quality}.m3u8"
                    result['videos'].append(m3u8_url)
                    logger.info(f"添加清晰度 {quality} 的视频链接: {m3u8_url}")
            else:
                # 直接搜索所有m3u8链接
                def deep_search_all_m3u8(obj):
                    """深度搜索所有m3u8链接"""
                    if isinstance(obj, dict):
                        for k, v in obj.items():
                            if isinstance(v, str) and '.m3u8' in v and v.startswith('http'):
                                if v not in result['videos']:
                                    result['videos'].append(v)
                                    logger.info(f"直接从页面提取到m3u8链接: {v}")
                            else:
                                deep_search_all_m3u8(v)
                    elif isinstance(obj, list):
                        for item in obj:
                            deep_search_all_m3u8(item)
                
                # 深度搜索所有数据中的m3u8链接
                deep_search_all_m3u8(data)
        
        result["images"] = images
        logger.debug(f"解析结果: videos={len(result['videos'])}, images={len(images)}")
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
