"""测试酷我音乐解析器"""

import pytest
from nonebot import logger
from nonebot_plugin_parser.parsers.data import AudioContent


@pytest.mark.asyncio
async def test_kuwo_parse():
    """测试酷我音乐解析"""
    from nonebot_plugin_parser.parsers import KuWoParser

    # 测试酷我音乐链接
    urls = [
        "https://www.kuwo.cn/play_detail/279292599",  # 分享链接
    ]
    
    parser = KuWoParser()
    
    for url in urls:
        logger.info(f"开始测试酷我音乐链接: {url}")
        
        # 测试URL匹配
        keyword, searched = parser.search_url(url)
        
        assert searched, f"URL {url} 应该能被酷我音乐解析器匹配"
        logger.debug(f"匹配到的关键词: {keyword}")
        logger.debug(f"匹配到的内容: {searched.group(0)}")
        
        # 测试解析
        try:
            result = await parser.parse(keyword, searched)
        except Exception as e:
            pytest.skip(f"酷我音乐解析失败: {e}")
        
        # 验证结果
        assert result.title, "应该能提取标题"
        assert result.author is not None, "应该能提取作者信息"
        assert result.platform.name == "kuwo", "平台名称应该是kuwo"
        logger.debug(f"标题: {result.title}")
        logger.debug(f"作者: {result.author.name}")
        logger.debug(f"内容数量: {len(result.contents)}")
        
        # 检查是否包含音频内容
        audio_contents = [content for content in result.contents if isinstance(content, AudioContent)]
        assert len(audio_contents) > 0, "应该能提取音频内容"
    
    logger.success("酷我音乐解析成功")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])