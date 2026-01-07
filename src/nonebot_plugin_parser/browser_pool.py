import asyncio
import os
import re
from pathlib import Path
from typing import Optional, Dict, Any
from contextlib import asynccontextmanager
from playwright.async_api import async_playwright
from nonebot import logger

# 浏览器启动参数优化
BROWSER_ARGS = [
    "--disable-gpu",
    "--disable-dev-shm-usage",  # 限制共享内存使用
    "--no-sandbox",
    "--disable-setuid-sandbox",
    "--disable-features=AudioServiceOutOfProcess,TranslateUI",
    "--disable-accelerated-2d-canvas",
    "--disable-accelerated-video-decode",
    "--disable-breakpad",
    "--disable-component-extensions-with-background-pages",
    "--disable-component-update",
    "--disable-default-apps",
    "--disable-extensions",
    "--disable-background-networking",
    "--disable-background-timer-throttling",
    "--disable-backgrounding-occluded-windows",
    "--disable-client-side-phishing-detection",
    "--disable-hang-monitor",
    "--disable-ipc-flooding-protection",
    "--disable-notifications",
    "--disable-prompt-on-repost",
    "--disable-renderer-backgrounding",
    "--disable-sync",
    "--disable-translate",
    "--metrics-recording-only",
    "--no-default-browser-check",
    "--no-first-run",
    "--autoplay-policy=user-gesture-required",
    "--mute-audio",
    "--use-fake-device-for-media-stream",
    "--use-fake-ui-for-media-stream",
    "--disable-web-security",
    "--allow-running-insecure-content",
    "--ignore-certificate-errors",
    "--enable-unsafe-swiftshader",  # 解决WebGL错误
    "--memory-pressure-off"  # 禁用内存压力处理
]

# 浏览器池管理
class BrowserPool:
    _instance = None
    browsers = {}
    locks = {}
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    @asynccontextmanager
    async def get_browser(self, browser_type="chromium", headless=True, proxy: Optional[Dict[str, Any]] = None):
        key = f"{browser_type}-{headless}-{str(proxy)}"
        
        # 确保每个浏览器类型只有一个锁
        if key not in self.locks:
            self.locks[key] = asyncio.Lock()
        
        async with self.locks[key]:
            # 检查浏览器连接状态
            if key not in self.browsers or not await self.browsers[key].is_connected():
                # 如果已有实例但已断开，先移除
                if key in self.browsers:
                    try:
                        await self.browsers[key].close()
                    except Exception:
                        pass
                    del self.browsers[key]
                
                # 创建新的浏览器实例
                playwright = await async_playwright().start()
                
                # 配置启动选项
                launch_options = {
                    'headless': headless,
                    'args': BROWSER_ARGS,
                    'chromium_sandbox': False,
                    'handle_sigint': False,
                    'handle_sigterm': False,
                    'handle_sighup': False
                }
                
                # 添加代理配置
                if proxy:
                    launch_options['proxy'] = proxy
                    logger.info(f"使用代理: {proxy.get('server', '未知')}")
                
                self.browsers[key] = await playwright.chromium.launch(**launch_options)
                logger.info(f"创建了新的浏览器实例: {key}")
        
        try:
            yield self.browsers[key]
        except Exception as e:
            logger.error(f"浏览器操作出错: {e}")
            # 出错时关闭问题实例
            if key in self.browsers and await self.browsers[key].is_connected():
                try:
                    await self.browsers[key].close()
                except Exception:
                    pass
                del self.browsers[key]
            raise
    
    async def close_all(self):
        for key, browser in list(self.browsers.items()):
            if await browser.is_connected():
                try:
                    await browser.close()
                    logger.info(f"关闭浏览器实例: {key}")
                except Exception as e:
                    logger.error(f"关闭浏览器时出错: {e}")
        self.browsers = {}
        logger.info("所有浏览器实例已关闭")

# 安全创建上下文和页面的包装器
@asynccontextmanager
async def safe_browser_context(browser, max_retries=2):
    for attempt in range(max_retries):
        try:
            context = await browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                viewport={"width": 1280, "height": 720}
            )
            page = await context.new_page()
            
            # 设置超时时间
            page.set_default_timeout(120000)  # 120秒超时
            
            try:
                yield context, page
                return  # 成功则退出
            finally:
                # 确保上下文关闭
                await context.close()
        except Exception as e:
            if attempt < max_retries - 1 and "closed" in str(e).lower():
                logger.warning(f"浏览器上下文创建失败，重试 {attempt+1}/{max_retries}")
                await asyncio.sleep(1)  # 短暂延迟后重试
                continue
            else:
                logger.error(f"创建浏览器上下文失败: {e}")
                raise

# 初始化浏览器池
browser_pool = BrowserPool()

# 应用启动和关闭时的处理
from nonebot import get_driver

driver = get_driver()

@driver.on_startup
async def init_browser_pool():
    # 预热浏览器实例
    try:
        async with browser_pool.get_browser():
            logger.info("浏览器实例预热完成")
    except Exception as e:
        logger.error(f"浏览器预热失败: {e}")

@driver.on_shutdown
async def cleanup_browser_pool():
    await browser_pool.close_all()
    logger.info("浏览器池清理完成")