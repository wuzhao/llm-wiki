import copy
import io
import subprocess
import sys
import tempfile
import threading
import unittest
from email.message import Message
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

from kb_fixture import ROOT, initialize_kb, snapshot
from ingest_raw import fetch_url_content
from wiki_config import load_schema


class URLIngestTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path == "/missing":
                    self.send_error(404)
                    return
                if self.path == "/html":
                    data = '<html><head><title>标题</title></head><body><p>第一段 &amp; 内容</p><p>第二段</p><ul><li>条目一</li><li>条目二</li></ul><script>ignored</script></body></html>'.encode("gb18030")
                    content_type = "text/html; charset=gb18030"
                elif self.path == "/plain":
                    data = b"a < b\n\nnext paragraph\n"
                    content_type = "text/plain; charset=utf-8"
                else:
                    data = b"%PDF binary"
                    content_type = "application/pdf"
                self.send_response(200)
                self.send_header("Content-Type", content_type)
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *args):
                pass
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def test_html_charset_paragraphs_lists_and_entities(self):
        text, title = fetch_url_content(self.base + "/html", load_schema()["limits"])
        self.assertEqual(title, "标题")
        self.assertIn("第一段 & 内容\n\n第二段", text)
        self.assertIn("- 条目一\n- 条目二", text)
        self.assertNotIn("ignored", text)

    def test_plain_text_is_not_html_stripped(self):
        text, _ = fetch_url_content(self.base + "/plain", load_schema()["limits"])
        self.assertEqual(text, "a < b\n\nnext paragraph\n")

    def test_bad_responses_leave_no_files(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            kb = initialize_kb(temp_dir)
            before = snapshot(kb)
            for endpoint in ("/missing", "/binary"):
                result = subprocess.run([sys.executable, str(ROOT / "scripts/ingest_raw.py"), str(kb),
                                         "--url", self.base + endpoint], capture_output=True, text=True)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("请粘贴正文", result.stderr)
                self.assertEqual(snapshot(kb), before)

    def test_size_and_timeout_come_from_schema(self):
        limits = copy.deepcopy(load_schema()["limits"])
        limits["max_source_bytes"] = 4
        limits["url_timeout_seconds"] = 2
        response = io.BytesIO(b"12345678")
        response.headers = Message()
        response.headers["Content-Type"] = "text/plain"
        with patch("ingest_raw.urllib.request.urlopen", return_value=response) as opener:
            with self.assertRaisesRegex(ValueError, "max_source_bytes"):
                fetch_url_content("https://example.com", limits)
            self.assertEqual(opener.call_args.kwargs["timeout"], 2)

    def test_decode_errors_are_not_silently_ignored(self):
        response = io.BytesIO(b"\xff\xfeinvalid")
        response.headers = Message()
        response.headers["Content-Type"] = "text/plain; charset=utf-8"
        with patch("ingest_raw.urllib.request.urlopen", return_value=response):
            with self.assertRaises(UnicodeError):
                fetch_url_content("https://example.com", load_schema()["limits"])
