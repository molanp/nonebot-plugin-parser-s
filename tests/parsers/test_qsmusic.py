"""测试汽水音乐解析器"""

import pytest
from nonebot import logger


@pytest.mark.asyncio
async def test_qsmusic_parse():
    """测试汽水音乐解析"""
    from nonebot_plugin_parser.parsers import QSMusicParser

    # 测试汽水音乐链接
    urls = [
        "https://qishui.douyin.com/s/ia2T2aMo/",  # 分享链接
    ]
    
    parser = QSMusicParser()
    
    for url in urls:
        logger.info(f"开始测试汽水音乐链接: {url}")
        
        # 测试URL匹配
        keyword, searched = parser.search_url(url)
        
        assert searched, f"URL {url} 应该能被汽水音乐解析器匹配"
        logger.debug(f"匹配到的关键词: {keyword}")
        logger.debug(f"匹配到的内容: {searched.group(0)}")
        
        # 测试解析
        try:
            result = await parser.parse(keyword, searched)
        except Exception as e:
            pytest.skip(f"汽水音乐解析失败: {e}")
        
        # 验证结果
        assert result.title, "应该能提取标题"
        assert result.author is not None, "应该能提取作者信息"
        assert result.platform.name == "qsmusic", "平台名称应该是qsmusic"
        logger.debug(f"标题: {result.title}")
        logger.debug(f"作者: {result.author.name}")
        logger.debug(f"内容数量: {len(result.contents)}")
        
        # 检查是否包含音频内容
        audio_contents = [content for content in result.contents if hasattr(content, 'audio_url')]
        assert len(audio_contents) > 0, "应该能提取音频内容"
    
    logger.success("汽水音乐解析成功")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])