import asyncio
import json
import re
import httpx
from datetime import datetime
from typing import Optional, Dict, Any, List, Set

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
    
    async def _fetch_api_data(self, post_id: str) -> Optional[Dict[str, Any]]:
        """从TapTap API获取动态详情"""
        api_url = f"https://www.taptap.cn/webapiv2/moment/v3/detail"
        params = {
            "id": post_id,
            "X-UA": "V=1&PN=WebApp&LANG=zh_CN&VN_CODE=102&LOC=CN&PLT=PC&DS=Android&UID=f69478c8-27a3-4581-877b-45ade0e61b0b&OS=Windows&OSV=10&DT=PC"
        }
        
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(api_url, params=params, headers=self.headers)
                response.raise_for_status()
                return response.json()
        except Exception as e:
            logger.error(f"[TapTap] API请求失败: {e}")
            return None
    
    async def _parse_post_detail(self, post_id: str) -> Dict[str, Any]:
        """解析动态详情"""
        url = f"{self.base_url}/moment/{post_id}"
        
        result = {
            "id": post_id,
            "url": url,
            "title": "",
            "summary": "",
            "content_items": [],
            "images": [],
            "videos": [],
            "author": {
                "name": "",
                "avatar": "",
                "app_title": "",
                "app_icon": ""
            },
            "created_time": "",
            "publish_time": "",
            "stats": {
                "likes": 0,
                "comments": 0,
                "shares": 0,
                "views": 0,
                "plays": 0
            },
            "video_cover": ""
        }
        
        # 首先尝试使用API获取数据
        api_data = await self._fetch_api_data(post_id)
        if api_data and api_data.get("success"):
            logger.info(f"[TapTap] 使用API获取数据成功")
            data = api_data.get("data", {})
            moment_data = data.get("moment", {})
            
            # 提取标题
            topic = moment_data.get("topic", {})
            result["title"] = topic.get("title", "TapTap 动态分享")
            
            # 提取创建时间和发布时间
            result["created_time"] = moment_data.get("created_time", "")
            result["publish_time"] = moment_data.get("publish_time", "")
            
            # 提取作者信息
            author_data = moment_data.get("author", {})
            user_data = author_data.get("user", {})
            result["author"]["name"] = user_data.get("name", "")
            result["author"]["avatar"] = user_data.get("avatar", "")
            
            # 提取作者游戏信息
            app_data = author_data.get("app", {})
            result["author"]["app_title"] = app_data.get("title", "")
            app_icon = app_data.get("icon", {})
            result["author"]["app_icon"] = app_icon.get("original_url", "")
            
            # 提取帖子游戏信息
            moment_app = moment_data.get("app", {})
            if moment_app:
                result["app"] = {
                    "title": moment_app.get("title", ""),
                    "icon": moment_app.get("icon", {}).get("original_url", ""),
                    "rating": moment_app.get("stat", {}).get("rating", {}).get("score", ""),
                    "latest_score": moment_app.get("stat", {}).get("rating", {}).get("latest_score", ""),
                    "tags": moment_app.get("tags", [])
                }
            
            # 提取统计信息
            stats_data = moment_data.get("stat", {})
            result["stats"]["likes"] = stats_data.get("ups", 0)  # 使用ups作为点赞数据
            result["stats"]["comments"] = stats_data.get("comments", 0)
            result["stats"]["shares"] = stats_data.get("shares", 0) or 0
            result["stats"]["views"] = stats_data.get("pv_total", 0)
            result["stats"]["plays"] = stats_data.get("play_total", 0)
            
            # 提取视频信息
            pin_video = topic.get("pin_video", {})
            video_id = pin_video.get("video_id")
            if video_id:
                logger.debug(f"[TapTap] 从API获取到视频ID: {video_id}")
                result["video_id"] = video_id
                
                # 提取视频封面
                thumbnail = pin_video.get("thumbnail", {})
                if thumbnail:
                    video_cover = thumbnail.get("original_url")
                    if video_cover:
                        result["video_cover"] = video_cover
                        # 不再将视频封面添加到图片列表中，避免重复显示
                        # result["images"].append(video_cover)
                
                # 使用video_id获取视频链接
                play_info_url = f"https://www.taptap.cn/video/v1/play-info"
                play_info_params = {
                    "video_id": video_id
                }
                
                try:
                    async with httpx.AsyncClient(timeout=10.0) as client:
                        play_response = await client.get(play_info_url, params=play_info_params, headers=self.headers)
                        play_response.raise_for_status()
                        play_data = play_response.json()
                        
                        if play_data.get("data") and play_data["data"].get("url"):
                            real_url = play_data["data"]["url"]
                            result["videos"].append(real_url)
                            logger.success(f"[TapTap] 从play-info接口获取到视频链接: {real_url[:50]}...")
                except Exception as e:
                    logger.error(f"[TapTap] 获取视频play-info失败: {e}")
                    # 如果play-info接口失败，继续使用浏览器解析兜底
                    pass
            
            # 提取文本和图片内容
            first_post = data.get("first_post", {})
            contents = first_post.get("contents", {})
            json_contents = contents.get("json", [])
            
            text_parts = []
            
            for content_item in json_contents:
                item_type = content_item.get("type")
                result["content_items"].append({
                    "type": item_type,
                    "data": content_item
                })
                
                # 处理文本内容
                if item_type == "paragraph":
                    children = content_item.get("children", [])
                    for child in children:
                        if isinstance(child, dict) and "text" in child:
                            text_parts.append(child["text"])
                
                # 处理图片内容
                elif item_type == "image":
                    image_info = content_item.get("info", {}).get("image", {})
                    original_url = image_info.get("original_url")
                    if original_url:
                        result["images"].append(original_url)
            
            if text_parts:
                result["summary"] = "\n".join(text_parts)
            
            logger.debug(f"API解析结果: videos={len(result['videos'])}, images={len(result['images'])}, content_items={len(result['content_items'])}")
            
            # 如果API获取成功但视频获取失败，尝试使用浏览器解析获取视频
            if result.get("video_id") and not result.get("videos"):
                logger.info(f"[TapTap] API视频play-info获取失败，尝试浏览器解析获取视频")
            else:
                return result
        
        # 使用 set 自动去重完全相同的 URL
        captured_videos: Set[str] = set()
        
        async with browser_pool.get_browser() as browser:
            context = None
            try:
                # 创建隐身页面
                context = await browser.new_context(
                    user_agent=self.headers["User-Agent"],
                    viewport={"width": 1920, "height": 1080},
                    device_scale_factor=1,
                    is_mobile=False,
                    has_touch=False,
                    locale="zh-CN",
                    timezone_id="Asia/Shanghai"
                )
                
                # 注入防检测脚本
                await context.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined});")
                await context.add_init_script("Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});")
                
                page = await context.new_page()
                page.set_default_timeout(40000)
                
                # --- 定义监听器 ---
                async def handle_response(response):
                    try:
                        resp_url = response.url
                        
                        # 1. 捕获 .m3u8 (含签名)
                        if '.m3u8' in resp_url and 'sign=' in resp_url:
                            # 简单的过滤：排除掉非 TapTap 域名的（比如广告）
                            if 'taptap.cn' in resp_url:
                                logger.debug(f"[TapTap] 嗅探到 M3U8: {resp_url[:50]}...")
                                captured_videos.add(resp_url)
                        
                        # 2. 捕获 play-info 接口
                        if 'video/v1/play-info' in resp_url and response.status == 200:
                            try:
                                json_data = await response.json()
                                if json_data.get('data') and json_data['data'].get('url'):
                                    real_url = json_data['data']['url']
                                    captured_videos.add(real_url)
                            except:
                                pass
                    except Exception:
                        pass
                
                page.on("response", handle_response)
                
                # --- 访问页面 ---
                logger.info(f"[TapTap] 正在访问详情页(开启嗅探): {url}")
                await page.goto(url, wait_until="domcontentloaded")
                
                # --- 获取 Nuxt 数据 --- 
                data = []
                try:
                    await page.wait_for_selector('#__NUXT_DATA__', timeout=25000, state='attached')
                    json_str = await page.evaluate('document.getElementById("__NUXT_DATA__").textContent')
                    if json_str:
                        data = json.loads(json_str)
                except Exception as e:
                    logger.error(f"[TapTap] 提取 Nuxt 数据异常: {e}")
                
                # 额外等待，确保视频请求发出
                try:
                    await page.evaluate("window.scrollTo(0, 200)")
                    await asyncio.sleep(3)
                except:
                    pass
                
                # 补全标题、文本内容、作者信息和发布时间
                if data:
                    # 提取所有可能的文本内容
                    all_text_parts = []
                    
                    for item in data:
                        if not isinstance(item, dict):
                            continue
                            
                        # 处理包含 user 字段的对象，提取作者信息
                        if 'user' in item:
                            user_ref = item['user']
                            user_obj = self._resolve_nuxt_value(data, user_ref)
                            if isinstance(user_obj, dict):
                                # 提取作者名称
                                result['author']['name'] = self._resolve_nuxt_value(data, user_obj.get('name', '')) or ''
                                # 提取作者头像
                                if 'avatar' in user_obj:
                                    avatar = self._resolve_nuxt_value(data, user_obj['avatar'])
                                    if isinstance(avatar, str) and avatar.startswith('http'):
                                        result['author']['avatar'] = avatar
                                    elif isinstance(avatar, dict) and 'original_url' in avatar:
                                        result['author']['avatar'] = self._resolve_nuxt_value(data, avatar['original_url']) or ''
                        
                        # 处理包含 title 和 summary 字段的对象，提取标题和完整摘要
                        if 'title' in item and 'summary' in item:
                            title = self._resolve_nuxt_value(data, item['title'])
                            summary = self._resolve_nuxt_value(data, item['summary'])
                            if title and isinstance(title, str):
                                result['title'] = title
                            if summary and isinstance(summary, str):
                                # 将摘要添加到所有文本部分
                                all_text_parts.append(summary)
                        
                        # 处理包含 stat 字段的对象，提取统计信息
                        if 'stat' in item:
                            stat_ref = item['stat']
                            stat_obj = self._resolve_nuxt_value(data, stat_ref)
                            if isinstance(stat_obj, dict):
                                # 提取点赞数
                                result['stats']['likes'] = stat_obj.get('supports', 0) or stat_obj.get('likes', 0)
                                # 提取评论数
                                result['stats']['comments'] = stat_obj.get('comments', 0)
                                # 提取分享数
                                result['stats']['shares'] = stat_obj.get('shares', 0)
                                # 提取浏览数
                                result['stats']['views'] = stat_obj.get('pv_total', 0)
                                # 提取播放数
                                result['stats']['plays'] = stat_obj.get('play_total', 0)
                        
                        # 直接处理包含统计数据的对象
                        if 'supports' in item or 'likes' in item:
                            # 提取点赞数
                            result['stats']['likes'] = item.get('supports', 0) or item.get('likes', 0)
                            # 提取评论数
                            result['stats']['comments'] = item.get('comments', 0)
                            # 提取分享数
                            result['stats']['shares'] = item.get('shares', 0)
                            # 提取浏览数
                            result['stats']['views'] = item.get('pv_total', 0)
                            # 提取播放数
                            result['stats']['plays'] = item.get('play_total', 0)
                        
                        # 处理包含 contents 字段的对象，提取额外文本内容
                        if 'contents' in item:
                            contents = self._resolve_nuxt_value(data, item['contents'])
                            if isinstance(contents, list):
                                for content_item in contents:
                                    if isinstance(content_item, dict):
                                        # 处理文本内容
                                        if 'text' in content_item:
                                            text = self._resolve_nuxt_value(data, content_item['text'])
                                            if text and isinstance(text, str):
                                                all_text_parts.append(text)
                                        # 处理段落内容
                                        elif content_item.get('type') == 'paragraph':
                                            children = content_item.get('children')
                                            if isinstance(children, list):
                                                for child in children:
                                                    if isinstance(child, dict) and 'text' in child:
                                                        child_text = self._resolve_nuxt_value(data, child['text'])
                                                        if child_text and isinstance(child_text, str):
                                                            all_text_parts.append(child_text)
                                        # 处理带有text引用的内容项
                                        elif 'text' in self._resolve_nuxt_value(data, content_item):
                                            text = self._resolve_nuxt_value(data, content_item['text'])
                                            if text and isinstance(text, str):
                                                all_text_parts.append(text)
                        
                        # 处理包含 description 字段的对象，可能包含文本内容
                        if 'description' in item:
                            description = self._resolve_nuxt_value(data, item['description'])
                            if description and isinstance(description, str):
                                all_text_parts.append(description)
                        
                        # 处理包含 content 字段的对象，可能包含文本内容
                        if 'content' in item:
                            content = self._resolve_nuxt_value(data, item['content'])
                            if content and isinstance(content, str):
                                all_text_parts.append(content)
                        
                        # 处理包含 body 字段的对象，可能包含文本内容
                        if 'body' in item:
                            body = self._resolve_nuxt_value(data, item['body'])
                            if body and isinstance(body, str):
                                all_text_parts.append(body)
                        
                        # 提取发布时间
                        if 'created_at' in item or 'publish_time' in item:
                            publish_time = self._resolve_nuxt_value(data, item.get('created_at') or item.get('publish_time'))
                            if publish_time:
                                result['publish_time'] = publish_time
                        
                        # 提取视频信息
                        if 'pin_video' in item:
                            video_info = self._resolve_nuxt_value(data, item['pin_video'])
                            if isinstance(video_info, dict):
                                # 提取视频时长
                                if 'duration' in video_info:
                                    result['video_duration'] = self._resolve_nuxt_value(data, video_info['duration'])
                                # 提取视频ID
                                if 'video_id' in video_info:
                                    result['video_id'] = self._resolve_nuxt_value(data, video_info['video_id'])
                        
                        # 提取作者等级和标签
                        if 'honor_title' in item:
                            result['author']['honor_title'] = self._resolve_nuxt_value(data, item['honor_title']) or ''
                        if 'honor_obj_id' in item:
                            result['author']['honor_obj_id'] = self._resolve_nuxt_value(data, item['honor_obj_id']) or ''
                        if 'honor_obj_type' in item:
                            result['author']['honor_obj_type'] = self._resolve_nuxt_value(data, item['honor_obj_type']) or ''
                    
                    # 合并所有文本部分，去重并保留顺序
                    seen_text = set()
                    unique_text_parts = []
                    for text in all_text_parts:
                        if text not in seen_text:
                            seen_text.add(text)
                            unique_text_parts.append(text)
                    
                    # 构建完整的摘要
                    if unique_text_parts:
                        result['summary'] = '\n'.join(unique_text_parts)
                    
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
                        
                        # 尝试从 Nuxt 数据中找 MP4 直链
                        if 'video_url' in item or 'url' in item:
                            u = self._resolve_nuxt_value(data, item.get('video_url') or item.get('url'))
                            if isinstance(u, str) and ('.mp4' in u) and u.startswith('http'):
                                captured_videos.add(u)
                    
                    result["images"] = images
                
                # === [关键修改] 视频去重和智能选择逻辑 ===
                unique_videos = []
                
                # 将捕获的视频链接转换为列表，并优先处理主M3U8
                video_list = list(captured_videos)
                
                # 首先，提取所有视频ID并分类
                video_dict = {}  # video_id -> [urls]
                for v_url in video_list:
                    # 尝试提取 TapTap 视频 ID
                    match = re.search(r'/hls/([a-zA-Z0-9\-_]+)', v_url)
                    
                    if match:
                        vid_id = match.group(1)
                        if vid_id not in video_dict:
                            video_dict[vid_id] = []
                        video_dict[vid_id].append(v_url)
                    else:
                        # 如果没有匹配到ID (可能是 MP4 直链或其他 CDN 格式)，则单独处理
                        if v_url not in unique_videos:
                            unique_videos.append(v_url)
                
                # 对于每个视频ID，优先选择最高分辨率的M3U8
                for vid_id, urls in video_dict.items():
                    if len(urls) == 1:
                        # 只有一个URL，直接使用
                        unique_videos.append(urls[0])
                    else:
                        # 多个URL，优先选择最高分辨率
                        # 清晰度优先级：2208 1080P > 2206 720P > 2204 540P > 2202 360P
                        quality_priority = ['2208', '2206', '2204', '2202']
                        
                        # 按清晰度优先级排序
                        def get_quality_priority(url):
                            for i, quality in enumerate(quality_priority):
                                if f'/{quality}.m3u8' in url:
                                    return i
                            return len(quality_priority)  # 默认优先级最低
                        
                        urls.sort(key=get_quality_priority)
                        # 选择优先级最高的URL
                        highest_priority_url = urls[0]
                        unique_videos.append(highest_priority_url)
                        logger.debug(f"[TapTap] 视频 {vid_id} 选择最高分辨率: {highest_priority_url}")
                
                if unique_videos:
                    logger.success(f"[TapTap] 捕获并去重后得到 {len(unique_videos)} 个视频")
                    result["videos"] = unique_videos
                else:
                    logger.warning("[TapTap] 未检测到视频链接")
                
            except Exception as e:
                logger.error(f"[TapTap] 详情页抓取流程失败: {e}")
            finally:
                if context:
                    await context.close()
        
        logger.debug(f"解析结果: videos={len(result['videos'])}, images={len(result['images'])}")
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
                'images': detail['images'],  # 将图片列表放入extra，用于模板渲染
                'content_items': detail.get('content_items', []),
                'author': detail.get('author', {}),
                'created_time': detail.get('created_time', ''),
                'publish_time': detail.get('publish_time', ''),
                'video_cover': detail.get('video_cover', ''),
                'app': detail.get('app', {})  # 添加游戏信息
            }
        )
        
        # 设置media_contents，用于延迟发送
        result.media_contents = media_contents
        logger.debug(f"构建解析结果完成: title={detail['title']}, images={len(detail['images'])}, videos={len(detail['videos'])}, media_contents={len(media_contents)}")
        
        return result
