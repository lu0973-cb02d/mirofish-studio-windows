import test from 'node:test'
import assert from 'node:assert/strict'
import { renderReportMarkdown } from '../src/utils/reportMarkdown.js'

// Every literal HTML tag must be one of the renderer's own static tags.
// Model content may contain dangerous words as text, never as HTML attributes.
const assertControlledTags = (html) => {
  const allowed = /^<\/?(?:p|h[2-6]|blockquote|ul|ol|li|pre|code|strong|em|br|hr)(?: class="(?:md-(?:p|h[2-6]|quote|ul|ol|li|oli|hr)|code-block|inline-code)"| data-level="\d+"| start="\d+")*>$/
  for (const tag of html.match(/<[^>]*>/g) || []) assert.match(tag, allowed)
}

test('raw executable HTML is escaped in text, headings, quotes and lists', () => {
  const attacks = [
    '<script>alert(1)</script>',
    '<img src=x onerror="alert(1)">',
    '<svg/onload=alert(1)>',
    '<math><mtext><img src=x onerror=alert(1)></mtext></math>',
    '</p><iframe srcdoc="<script>alert(1)</script>"></iframe>',
    '<style>body{display:none}</style><input autofocus onfocus=alert(1)>',
    '" onmouseover="alert(1)" data-x="'
  ]
  for (const attack of attacks) {
    for (const source of [attack, `# ${attack}`, `> ${attack}`, `- ${attack}`, `**${attack}**`]) {
      const html = renderReportMarkdown(source)
      assertControlledTags(html)
      assert.doesNotMatch(html, /<(?:script|img|svg|math|iframe|style|input)\b/i)
    }
  }
  assert.match(renderReportMarkdown(attacks[1]), /&lt;img src=x onerror=&quot;alert\(1\)&quot;&gt;/)
})

test('encoded entities are escaped once, never decoded into active markup', () => {
  const source = '&lt;script&gt;alert(1)&lt;/script&gt; &#x3c;img src=x onerror=alert(1)&#x3e; &amp;lt;svg/onload=alert(1)&amp;gt;'
  const html = renderReportMarkdown(source)
  assertControlledTags(html)
  assert.match(html, /&amp;lt;script&amp;gt;/)
  assert.match(html, /&amp;#x3c;img/)
  assert.match(html, /&amp;amp;lt;svg/)
  assert.doesNotMatch(html, /<(?:script|img|svg)/i)
})

test('fenced code stays literal and fence metadata cannot inject attributes', () => {
  const html = renderReportMarkdown('```html" onmouseover="alert(1)\n<img src=x onerror=alert(1)>\n**not bold**\n> not a quote\n# not a heading\n```')
  assert.equal(html, '<pre class="code-block"><code>&lt;img src=x onerror=alert(1)&gt;\n**not bold**\n&gt; not a quote\n# not a heading</code></pre>')
  assertControlledTags(html)
  assert.doesNotMatch(html, /<strong>|<blockquote|<h[2-6]/)
  assert.doesNotMatch(html, /<pre[^>]*onmouseover/)
})

test('inline code and an unclosed code fence cannot break out of code tags', () => {
  const inline = renderReportMarkdown('`</code><img src=x onerror=alert(1)> **literal**`')
  assert.equal(inline, '<p class="md-p"><code class="inline-code">&lt;/code&gt;&lt;img src=x onerror=alert(1)&gt; **literal**</code></p>')
  const unclosed = renderReportMarkdown('~~~\n</code></pre><svg/onload=alert(1)>')
  assert.match(unclosed, /&lt;\/code&gt;&lt;\/pre&gt;&lt;svg\/onload=alert\(1\)&gt;/)
  assertControlledTags(inline)
  assertControlledTags(unclosed)
})

test('normal headings, quotes, lists, bold and emphasis still render', () => {
  const html = renderReportMarkdown('# 总览\n\n## 发现\n\n> **采访证据**\n> 第二行\n\n- 第一项\n- *第二项*\n\n3. 第三项\n4. 第四项\n\n---')
  assert.match(html, /<h2 class="md-h2">总览<\/h2>/)
  assert.match(html, /<h3 class="md-h3">发现<\/h3>/)
  assert.match(html, /<blockquote class="md-quote"><p class="md-p"><strong>采访证据<\/strong><br>第二行<\/p><\/blockquote>/)
  assert.match(html, /<ul class="md-ul"><li class="md-li" data-level="0">第一项<\/li><li class="md-li" data-level="0"><em>第二项<\/em><\/li><\/ul>/)
  assert.match(html, /<ol class="md-ol" start="3">/)
  assert.match(html, /<hr class="md-hr">/)
  assertControlledTags(html)
})

test('raw quote markers retain Markdown meaning while written entities remain text', () => {
  const quote = renderReportMarkdown('> <script>alert(1)</script>')
  assert.match(quote, /^<blockquote class="md-quote">/)
  assert.match(quote, /&lt;script&gt;alert\(1\)&lt;\/script&gt;/)
  const writtenEntity = renderReportMarkdown('&gt; literal quote marker')
  assert.equal(writtenEntity, '<p class="md-p">&amp;gt; literal quote marker</p>')
})

test('Markdown URLs and images do not create executable elements', () => {
  const html = renderReportMarkdown('[click](javascript:alert(1)) ![image](data:image/svg+xml,<svg onload=alert(1)>)')
  assertControlledTags(html)
  assert.doesNotMatch(html, /<(?:a|img|svg)\b/i)
  assert.match(html, /javascript:alert\(1\)/)
})

test('legacy section-title suppression is optional and input is not mutated', () => {
  const source = '## 已在外层展示的标题\n\n**正文**'
  assert.match(renderReportMarkdown(source), /<h3 class="md-h3">/)
  assert.equal(renderReportMarkdown(source, { stripLeadingSectionHeading: true }), '<p class="md-p"><strong>正文</strong></p>')
  assert.equal(source, '## 已在外层展示的标题\n\n**正文**')
  assert.equal(renderReportMarkdown(null), '')
  assert.equal(renderReportMarkdown(undefined), '')
})

test('deeply nested quotes stay bounded and cannot enable raw HTML', () => {
  const html = renderReportMarkdown(`${'> '.repeat(100)}<img src=x onerror=alert(1)>`)
  assertControlledTags(html)
  assert.equal((html.match(/<blockquote /g) || []).length, 32)
  assert.match(html, /&lt;img src=x onerror=alert\(1\)&gt;/)
})
