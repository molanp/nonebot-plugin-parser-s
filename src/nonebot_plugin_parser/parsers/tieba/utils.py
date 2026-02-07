# pyright: reportAttributeAccessIssue=false

from pathlib import Path

from httpx import AsyncClient, NetworkError
from google.protobuf import descriptor_pb2, descriptor_pool
from google.protobuf.message_factory import GetMessageClass

from .models import Posts


def get_message(name: str):
    fds = descriptor_pb2.FileDescriptorSet()
    fds.ParseFromString((Path(__file__).parent / f"{name}.desc").read_bytes())
    pool = descriptor_pool.DescriptorPool()
    for fd in fds.file:
        pool.Add(fd)

    msg_descriptor = pool.FindMessageTypeByName(name)
    return GetMessageClass(msg_descriptor)


def make_req(tid: int) -> bytes:
    req_proto = get_message("PbPageReqIdl")()
    req_proto.data.common._client_type = 2
    req_proto.data.common._client_version = "12.64.1.1"
    req_proto.data.kz = tid
    req_proto.data.pn = 1
    req_proto.data.rn = 30
    req_proto.data.r = 2
    req_proto.data.lz = 0
    req_proto.data.with_floor = True
    req_proto.data.floor_sort_type = True
    req_proto.data.floor_rn = 4
    return req_proto.SerializeToString()


async def pack_req(data: bytes) -> bytes:
    """
    打包移动端protobuf请求

    :param data: protobuf序列化后的二进制数据
    :return: bytes
    """
    boundary = "-*_r1999"

    body = (
        (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="data"; filename="file"\r\n'
            f"\r\n"
        ).encode()
        + data
        + f"\r\n--{boundary}--\r\n".encode()
    )

    # 设置 Content-Type，带上固定 boundary
    async with AsyncClient(verify=False) as client:
        response = await client.post(
            "http://tiebac.baidu.com/c/f/pb/page",
            headers={
                "x_bd_data_type": "protobuf",
                "Connection": "keep-alive",
                "Accept-Encoding": "gzip",
                "User-Agent": "miku/39",
                "Host": "tiebac.baidu.com",
                "Content-Type": f"multipart/form-data; boundary={boundary}",
            },
            params={"cmd": 302001},
            content=body,
        )
        return response.content


def parse_res(data: bytes) -> Posts:
    res = get_message("PbPageResIdl")()
    res.ParseFromString(data)
    if res.error.errorno:
        raise NetworkError(res.error.errmsg)

    data_proto = res.data
    return Posts.from_tbdata(data_proto)


async def get_post(tid: int) -> Posts:
    req = make_req(tid)
    data = await pack_req(req)
    return parse_res(data)
