import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from html_markdown import ArticleTextParser


def extract(html):
    parser = ArticleTextParser("https://example.com/docs/article")
    parser.feed(html)
    parser.close()
    return parser.text()


class HTMLMarkdownTests(unittest.TestCase):
    def test_code_preserves_indentation_blank_lines_and_backtick_fences(self):
        code = 'if ready:\n    launch()\n\n\nfinish("```")\n'
        result = extract('<h2>运行</h2><pre><code class="language-python">' + code + '</code></pre><p>完成</p>')
        self.assertIn('## 运行', result)
        self.assertIn('````python\n' + code + '````', result)
        self.assertIn('完成', result)

    def test_table_retains_headers_cells_and_right_aligned_numbers(self):
        result = extract('<table><tr><th>操作</th><th>延迟</th></tr><tr><td>read</td><td>10</td></tr><tr><td>write</td><td>20</td></tr></table>')
        self.assertIn('| 操作 | 延迟 |', result)
        self.assertIn('| --- | ---: |', result)
        self.assertIn('| read | 10 |', result)
        self.assertIn('| write | 20 |', result)

    def test_table_without_header_does_not_promote_data_to_a_heading(self):
        result = extract('<table><tr><td>A</td><td>1</td></tr><tr><td>B</td><td>2</td></tr></table>')
        self.assertIn('|  |  |', result)
        self.assertIn('| A | 1 |', result)
        self.assertIn('| B | 2 |', result)

    def test_complex_table_preserves_spans_and_nested_markup(self):
        result = extract('<table><tr><th colspan="2">结果</th></tr><tr><td rowspan="2">A</td><td><pre>x\n\n\n  y</pre></td></tr></table>')
        self.assertIn('colspan="2"', result)
        self.assertIn('rowspan="2"', result)
        self.assertIn('<pre>x\n\n\n  y</pre>', result)

    def test_literal_html_and_markdown_characters_remain_visible(self):
        result = extract('<p>Use &lt;T&gt;, snake_case and *literal*.</p>')
        self.assertIn('&lt;T&gt;', result)
        self.assertIn('snake\\_case', result)
        self.assertIn('\\*literal\\*', result)
        self.assertEqual(extract('<p>&amp;copy; &amp; literal</p>'), '&amp;copy; & literal')

    def test_links_images_ordered_lists_and_footers_survive(self):
        result = extract('<p>见 <a href="../guide">文档</a> 与 <img src="/image.png" alt="结构图"></p><ol start="3"><li>读取</li><li>验证</li></ol><footer>来源说明</footer>')
        self.assertIn('[文档](<https://example.com/guide>)', result)
        self.assertIn('![结构图](<https://example.com/image.png>)', result)
        self.assertIn('3. 读取\n4. 验证', result)
        self.assertIn('来源说明', result)
