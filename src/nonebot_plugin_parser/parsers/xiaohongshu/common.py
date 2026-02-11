from typing import Any

from msgspec import Struct


class Stream(Struct):
    h264: list[dict[str, Any]] | None = None
    h265: list[dict[str, Any]] | None = None
    av1: list[dict[str, Any]] | None = None
    h266: list[dict[str, Any]] | None = None


class Media(Struct):
    stream: Stream


class Video(Struct):
    media: Media

    @property
    def video_url(self) -> str | None:
        stream = self.media.stream

        # h264 有水印，h265 无水印
        if stream.h265:
            return stream.h265[0]["masterUrl"]
        elif stream.h264:
            return stream.h264[0]["masterUrl"]
        elif stream.av1:
            return stream.av1[0]["masterUrl"]
        elif stream.h266:
            return stream.h266[0]["masterUrl"]
        return None


def get_note_no_water_img(img_url):
    """
    获取笔记无水印图片
    :param img_url: 你想要获取的图片的url
    返回笔记无水印图片
    """
    # https://sns-webpic-qc.xhscdn.com/202403211626/c4fcecea4bd012a1fe8d2f1968d6aa91/110/0/01e50c1c135e8c010010000000018ab74db332_0.jpg!nd_dft_wlteh_webp_3
    if ".jpg" in img_url:
        img_id = "/".join(list(img_url.split("/")[-3:])).split("!")[0]
        # return f"http://ci.xiaohongshu.com/{img_id}?imageview2/2/w/1920/format/png"
        # return f"http://ci.xiaohongshu.com/{img_id}?imageview2/2/w/format/png"
        # return f'https://sns-img-hw.xhscdn.com/{img_id}'
        return f"https://sns-img-qc.xhscdn.com/{img_id}"
    else:
        img_id = "/".join(img_url.split("/")[-2:]).split("!")[0]
        # return f'http://sns-webpic.xhscdn.com/{img_id}?imageView2/2/w/1920/format/jpg'
        return f"http://sns-webpic.xhscdn.com/{img_id}?imageView2/2/w/format/jpg"
