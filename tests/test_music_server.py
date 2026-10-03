import http.client
import importlib.util
from pathlib import Path
import tempfile
import threading
import unittest

SOURCE = Path(__file__).resolve().parents[1] / 'server/scripts/music_server.py'
spec = importlib.util.spec_from_file_location('music_server', SOURCE)
music = importlib.util.module_from_spec(spec)
spec.loader.exec_module(music)


class MusicHTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        cls.audio = bytes(range(256)) * 8
        (cls.root / 'sample.mp3').write_bytes(cls.audio)
        (cls.root / 'empty.mp3').write_bytes(b'')
        (cls.root / 'partial.out.mp3').write_bytes(b'unfinished')
        (cls.root / 'secret.txt').write_text('not public')
        cls.server = music.create_server(cls.root, port=0)
        cls.server.RequestHandlerClass.func.log_message = lambda *args: None
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=5)
        cls.temp.cleanup()

    def request(self, path='/sample.mp3', headers=None, method='GET'):
        connection = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=5)
        try:
            connection.request(method, path, headers=headers or {})
            response = connection.getresponse()
            return response.status, dict(response.getheaders()), response.read()
        finally:
            connection.close()

    def test_full_file(self):
        status, headers, body = self.request()
        self.assertEqual(status, 200)
        self.assertEqual(body, self.audio)
        self.assertEqual(headers['Accept-Ranges'], 'bytes')
        self.assertEqual(headers['Content-Type'], 'audio/mpeg')

    def test_seek_range(self):
        status, headers, body = self.request(headers={'Range': 'bytes=10-19'})
        self.assertEqual(status, 206)
        self.assertEqual(headers['Content-Range'], 'bytes 10-19/2048')
        self.assertEqual(body, self.audio[10:20])

    def test_open_ended_and_suffix_ranges(self):
        for header, expected in [('bytes=2000-', self.audio[2000:]), ('bytes=-10', self.audio[-10:]), ('bytes=-9999', self.audio)]:
            with self.subTest(header=header):
                self.assertEqual(self.request(headers={'Range': header})[2], expected)

    def test_range_end_is_clamped(self):
        status, headers, body = self.request(headers={'Range': 'bytes=2040-9999'})
        self.assertEqual(status, 206)
        self.assertEqual(body, self.audio[2040:])

    def test_invalid_ranges(self):
        for value in ['bytes=9999-', 'bytes=20-10', 'bytes=-0', 'bytes=-', 'bytes=a-b']:
            with self.subTest(value=value):
                status, headers, body = self.request(headers={'Range': value})
                self.assertEqual(status, 416)
                self.assertEqual(headers['Content-Range'], 'bytes */2048')
                self.assertEqual(body, b'')

    def test_unsupported_units_and_multipart_use_full_response(self):
        for value in ['items=1-2', 'bytes=0-1,10-11']:
            self.assertEqual(self.request(headers={'Range': value})[0], 200)

    def test_head_ignores_range_and_sends_no_body(self):
        status, headers, body = self.request(method='HEAD', headers={'Range': 'bytes=10-19'})
        self.assertEqual(status, 200)
        self.assertEqual(headers['Content-Length'], str(len(self.audio)))
        self.assertEqual(body, b'')

    def test_if_range_with_stale_validator_uses_full_file(self):
        self.assertEqual(self.request(headers={'Range': 'bytes=10-19', 'If-Range': '"old"'})[0], 200)
        etag = self.request(method='HEAD')[1]['ETag']
        self.assertEqual(self.request(headers={'Range': 'bytes=10-19', 'If-Range': etag})[0], 206)

    def test_etag_revalidation(self):
        etag = self.request(method='HEAD')[1]['ETag']
        self.assertEqual(self.request(headers={'If-None-Match': etag})[0], 304)

    def test_private_and_unready_paths_are_not_served(self):
        for path in ['/', '/secret.txt', '/missing.mp3', '/empty.mp3', '/partial.out.mp3', '/../sample.mp3', '/%2e%2e/sample.mp3', '/folder/sample.mp3']:
            with self.subTest(path=path):
                self.assertEqual(self.request(path)[0], 404)

    def test_symlink_is_not_served(self):
        link = self.root / 'linked.mp3'
        try:
            link.symlink_to(self.root / 'sample.mp3')
        except OSError:
            self.skipTest('Symlinks require platform permission')
        self.assertEqual(self.request('/linked.mp3')[0], 404)

    def test_health_endpoint(self):
        status, headers, body = self.request('/healthz')
        self.assertEqual(status, 200)
        self.assertEqual(body, b'{"status":"ok"}\n')
        self.assertEqual(headers['Cache-Control'], 'no-store')

    def test_cache_path_is_validated_without_changing_cwd(self):
        import os
        previous = os.getcwd()
        with self.assertRaises(ValueError):
            music.create_server(self.root / 'missing', port=0)
        self.assertEqual(os.getcwd(), previous)


if __name__ == '__main__':
    unittest.main()
