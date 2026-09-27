// Render the report's Markdown subset without accepting HTML, links, images,
// or user-controlled attributes. Escape once, before parsing any Markdown;
// generated markup is never sent back through an unescape/replacement pass.
const escapeHtml = (text) => text.replace(/[&<>"']/g, (character) => ({
  '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
}[character]))

const MAX_DEPTH = 32

const renderInline = (text, depth = 0) => {
  if (depth >= MAX_DEPTH) return text
  let output = ''
  let index = 0
  while (index < text.length) {
    const character = text[index]
    if (character === '\\' && /[\\`*_\[\]{}()#+.!~-]/.test(text[index + 1] || '')) {
      output += text[index + 1]
      index += 2
      continue
    }
    if (character === '`') {
      let ticks = 1
      while (text[index + ticks] === '`') ticks += 1
      const marker = '`'.repeat(ticks)
      const end = text.indexOf(marker, index + ticks)
      if (end !== -1) {
        output += `<code class="inline-code">${text.slice(index + ticks, end)}</code>`
        index = end + ticks
        continue
      }
      output += marker
      index += ticks
      continue
    }
    if (character === '*' || character === '_') {
      const marker = text[index + 1] === character ? character.repeat(2) : character
      // An underscore inside a word is literal (for example, a saved ID).
      const insideWord = character === '_' && /[\p{L}\p{N}]/u.test(text[index - 1] || '')
      let end = insideWord ? -1 : text.indexOf(marker, index + marker.length)
      while (end !== -1 && text[end - 1] === '\\') end = text.indexOf(marker, end + marker.length)
      if (end > index + marker.length) {
        const tag = marker.length === 2 ? 'strong' : 'em'
        output += `<${tag}>${renderInline(text.slice(index + marker.length, end), depth + 1)}</${tag}>`
        index = end + marker.length
        continue
      }
    }
    output += character
    index += 1
  }
  return output
}

const fenceMatch = (line) => line.match(/^ {0,3}(`{3,}|~{3,})(.*)$/)
const headingMatch = (line) => line.match(/^ {0,3}(#{1,6})[ \t]+(.+)$/)
// Raw '>' was escaped before parsing. A user-written '&gt;' is now
// '&amp;gt;' and therefore cannot masquerade as a Markdown quote marker.
const quoteMatch = (line) => line.match(/^ {0,3}&gt;[ \t]?(.*)$/)
const listMatch = (line) => line.match(/^([ \t]*)([-+*]|\d{1,9}[.)])[ \t]+(.+)$/)
const isRule = (line) => /^ {0,3}(?:-{3,}|\*{3,}|_{3,})[ \t]*$/.test(line)
const isBlockStart = (line) => !line.trim() || fenceMatch(line) || headingMatch(line) || quoteMatch(line) || listMatch(line) || isRule(line)

const renderBlocks = (lines, depth = 0) => {
  if (depth >= MAX_DEPTH) return `<p class="md-p">${lines.map((line) => renderInline(line)).join('<br>')}</p>`
  const output = []
  let index = 0
  while (index < lines.length) {
    const line = lines[index]
    if (!line.trim()) {
      index += 1
      continue
    }
    const fence = fenceMatch(line)
    if (fence) {
      const marker = fence[1][0]
      const minimumLength = fence[1].length
      const code = []
      index += 1
      while (index < lines.length) {
        const closing = lines[index].trim()
        if (closing.length >= minimumLength && [...closing].every((character) => character === marker)) {
          index += 1
          break
        }
        code.push(lines[index])
        index += 1
      }
      // Fence language/info text is deliberately not used in an attribute.
      output.push(`<pre class="code-block"><code>${code.join('\n')}</code></pre>`)
      continue
    }
    const heading = headingMatch(line)
    if (heading) {
      const level = Math.min(6, heading[1].length + 1)
      output.push(`<h${level} class="md-h${level}">${renderInline(heading[2].replace(/[ \t]+#+[ \t]*$/, ''))}</h${level}>`)
      index += 1
      continue
    }
    if (isRule(line)) {
      output.push('<hr class="md-hr">')
      index += 1
      continue
    }
    if (quoteMatch(line)) {
      const quoted = []
      while (index < lines.length) {
        const quote = quoteMatch(lines[index])
        if (!quote) break
        quoted.push(quote[1])
        index += 1
      }
      output.push(`<blockquote class="md-quote">${renderBlocks(quoted, depth + 1)}</blockquote>`)
      continue
    }
    const firstItem = listMatch(line)
    if (firstItem) {
      const ordered = /^\d/.test(firstItem[2])
      const tag = ordered ? 'ol' : 'ul'
      const itemClass = ordered ? 'md-oli' : 'md-li'
      const start = ordered ? Number.parseInt(firstItem[2], 10) : 1
      const items = []
      while (index < lines.length) {
        const item = listMatch(lines[index])
        if (!item || /^\d/.test(item[2]) !== ordered) break
        const level = Math.min(MAX_DEPTH, Math.floor(item[1].replace(/\t/g, '  ').length / 2))
        items.push(`<li class="${itemClass}" data-level="${level}">${renderInline(item[3])}</li>`)
        index += 1
      }
      const startAttribute = ordered && start !== 1 ? ` start="${start}"` : ''
      output.push(`<${tag} class="md-${tag}"${startAttribute}>${items.join('')}</${tag}>`)
      continue
    }
    const paragraph = [line]
    index += 1
    while (index < lines.length && !isBlockStart(lines[index])) {
      paragraph.push(lines[index])
      index += 1
    }
    output.push(`<p class="md-p">${paragraph.map((text) => renderInline(text)).join('<br>')}</p>`)
  }
  return output.join('\n')
}

export const renderReportMarkdown = (content, { stripLeadingSectionHeading = false } = {}) => {
  if (content === null || content === undefined || content === '') return ''
  const escaped = escapeHtml(String(content).replace(/\r\n?/g, '\n').replace(/\0/g, '\uFFFD'))
  const lines = escaped.split('\n')
  // Report sections already display their title in the surrounding component.
  if (stripLeadingSectionHeading && lines.length > 1 && /^##[ \t]+/.test(lines[0])) lines.shift()
  return renderBlocks(lines)
}
