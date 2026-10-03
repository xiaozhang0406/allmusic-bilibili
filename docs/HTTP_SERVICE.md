# 音乐缓存 HTTP 服务

`server/scripts/music_server.py` 使用 Python 3.10+ 标准库，无额外依赖。默认监听 `127.0.0.1:8090`，由 Caddy 提供对外 HTTPS。

Java 音乐源和 HTTP 服务必须使用同一个 `ALLMUSIC_BILI_CACHE_DIR`。缓存目录要提前创建，并确保运行用户能读取文件。服务不会修改进程的工作目录。

```bash
python3 server/scripts/music_server.py --directory /home/minecraft/music_cache
```

支持的配置：

| 参数 | 环境变量 | 默认值 |
| --- | --- | --- |
| `--directory` | `ALLMUSIC_BILI_CACHE_DIR` | `/home/minecraft/music_cache` |
| `--host` | `ALLMUSIC_BILI_HTTP_HOST` | `127.0.0.1` |
| `--port` | `ALLMUSIC_BILI_HTTP_PORT` | `8090` |

命令行参数优先。只有反向代理和服务运行在不同主机时才需要调整监听地址，并配合主机防火墙限制访问。

## 播放与健康检查

完整文件请求返回 `200`，单段字节范围请求返回 `206` 并包含 `Content-Range`。支持 `bytes=起点-终点`、`bytes=起点-` 和 `bytes=-末尾长度`，以便播放器拖动、断点续传。不可满足的范围返回 `416`；暂不支持的多段范围或单位按普通完整文件处理。`HEAD` 返回完整文件的头信息。

缓存文件仅允许根目录下名称为字母、数字、下划线或短横线的 `.mp3` 文件。不提供目录列表、子目录、符号链接、空文件或 `*.out.mp3` 转码中间文件。

```bash
curl -I http://127.0.0.1:8090/BVxxxxxxxxxx.mp3
curl -H 'Range: bytes=0-99' http://127.0.0.1:8090/BVxxxxxxxxxx.mp3
curl http://127.0.0.1:8090/healthz
```

以上 BV 文件名是占位符，应换成已转码的真实文件。`/healthz` 只证明 HTTP 服务响应，无法证明 ffmpeg、B 站接口或 Minecraft 客户端播放正常。

## systemd

参考 [allmusic-http.service](../server/scripts/allmusic-http.service)。把脚本复制到 `/home/minecraft/music_server.py`，按实际部署调整服务内的用户、脚本路径和缓存目录后安装服务。Java 转码进程需要缓存写权限，HTTP 服务只需读权限。

本仓库的修改不会自动部署到生产服务器；部署后需要分别验证本机 HTTP、Caddy HTTPS 和客户端拖动播放。

## 本地验证

```bash
python -m unittest discover -s tests -v
```

测试会启动临时的本机 HTTP 服务并发出真实请求，验证完整响应、Range/HEAD/ETag、健康检查及目录访问限制。无需外网、音乐 API、Java 插件或 ffmpeg，不覆盖真实 B 站取流和客户端播放。

协议参考：[HTTP Range](https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Headers/Range)、[Python http.server](https://docs.python.org/3/library/http.server.html)。
