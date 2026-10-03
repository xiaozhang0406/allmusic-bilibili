#!/usr/bin/env python3
"""Serve completed MP3 cache files behind a reverse proxy, including byte ranges."""
import argparse
from functools import partial
import http.server
import os
from pathlib import Path
import re
from urllib.parse import unquote, urlsplit


def parse_range(value, size):
    """Return inclusive bounds, or None for an unsupported range unit/multipart."""
    if not value or not value.startswith('bytes=') or ',' in value:
        return None
    match = re.fullmatch(r'bytes=(\d*)-(\d*)', value.strip())
    if not match or not any(match.groups()) or size == 0:
        raise ValueError('Unsatisfiable byte range')
    first, last = match.groups()
    if not first:
        suffix = int(last)
        if suffix <= 0:
            raise ValueError('Unsatisfiable byte range')
        return max(0, size - suffix), size - 1
    start = int(first)
    end = min(int(last), size - 1) if last else size - 1
    if start >= size or start > end:
        raise ValueError('Unsatisfiable byte range')
    return start, end


class MusicHandler(http.server.BaseHTTPRequestHandler):
    server_version = 'AllMusicHTTP/1.0'

    def __init__(self, *args, directory, **kwargs):
        self.directory = Path(directory).resolve()
        super().__init__(*args, **kwargs)

    def do_GET(self):
        self._serve(head_only=False)

    def do_HEAD(self):
        self._serve(head_only=True)

    def _serve(self, head_only):
        request_path = unquote(urlsplit(self.path).path)
        if request_path == '/healthz':
            body = b'{"status":"ok"}\n'
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            if not head_only:
                self.wfile.write(body)
            return

        # A flat allowlist keeps temporary transcodes and directory listings private.
        if not re.fullmatch(r'/[A-Za-z0-9_-]+\.mp3', request_path):
            self.send_error(404, 'MP3 file not found')
            return
        path = self.directory / request_path[1:]
        if path.is_symlink() or not path.resolve().is_relative_to(self.directory):
            self.send_error(404, 'MP3 file not found')
            return
        try:
            stream = path.open('rb')
        except OSError:
            self.send_error(404, 'MP3 file not found')
            return
        with stream:
            stat = os.fstat(stream.fileno())
            if not stat.st_size:
                self.send_error(404, 'MP3 file not ready')
                return
            modified = self.date_time_string(stat.st_mtime)
            etag = f'"{stat.st_size:x}-{stat.st_mtime_ns:x}"'
            if self.headers.get('If-None-Match') in (etag, '*'):
                self.send_response(304)
                self.send_header('ETag', etag)
                self.end_headers()
                return
            range_header = None if head_only else self.headers.get('Range')
            if self.headers.get('If-Range') not in (None, etag, modified):
                range_header = None
            try:
                bounds = parse_range(range_header, stat.st_size)
            except ValueError:
                self.send_response(416)
                self.send_header('Content-Range', f'bytes */{stat.st_size}')
                self.send_header('Content-Length', '0')
                self.end_headers()
                return
            start, end = bounds if bounds is not None else (0, stat.st_size - 1)
            self.send_response(206 if bounds is not None else 200)
            self.send_header('Content-Type', 'audio/mpeg')
            self.send_header('Accept-Ranges', 'bytes')
            self.send_header('Content-Length', str(end - start + 1))
            self.send_header('Last-Modified', modified)
            self.send_header('ETag', etag)
            self.send_header('X-Content-Type-Options', 'nosniff')
            if bounds is not None:
                self.send_header('Content-Range', f'bytes {start}-{end}/{stat.st_size}')
            self.end_headers()
            if head_only:
                return
            stream.seek(start)
            remaining = end - start + 1
            try:
                while remaining:
                    chunk = stream.read(min(64 * 1024, remaining))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    remaining -= len(chunk)
            except (BrokenPipeError, ConnectionResetError):
                pass  # Clients can disconnect when seeking or switching songs.


class MusicServer(http.server.ThreadingHTTPServer):
    daemon_threads = True

    def get_request(self):
        sock, address = super().get_request()
        sock.settimeout(30)
        return sock, address


def create_server(directory, host='127.0.0.1', port=8090):
    cache = Path(directory).expanduser().resolve()
    if not cache.is_dir():
        raise ValueError(f'Cache directory does not exist: {cache}')
    return MusicServer((host, port), partial(MusicHandler, directory=cache))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', default=os.environ.get('ALLMUSIC_BILI_CACHE_DIR', '/home/minecraft/music_cache'))
    parser.add_argument('--host', default=os.environ.get('ALLMUSIC_BILI_HTTP_HOST', '127.0.0.1'))
    parser.add_argument('--port', type=int, default=os.environ.get('ALLMUSIC_BILI_HTTP_PORT', '8090'))
    args = parser.parse_args(argv)
    if not 1 <= args.port <= 65535:
        parser.error('port must be between 1 and 65535')
    try:
        server = create_server(args.directory, args.host, args.port)
    except (ValueError, OSError) as error:
        parser.error(str(error))
    with server:
        print(f'Music HTTP server on {args.host}:{server.server_port}, serving {Path(args.directory).resolve()}', flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == '__main__':
    main()
