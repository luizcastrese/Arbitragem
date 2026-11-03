import { Fragment } from 'react'

// Renderizador de markdown mínimo e seguro (sem dangerouslySetInnerHTML): títulos,
// parágrafos, listas, tabelas, citações, régua, negrito, itálico, código e links.
// Cobre o que os termos e a política de privacidade usam.

const INLINE = /(\*\*[^*]+\*\*|\*[^*\s][^*]*\*|_[^_\s][^_]*_|`[^`]+`|\[[^\]]+\]\([^)\s]+\))/g
const SAFE_HREF = /^(https?:\/\/|mailto:|\/)/i

function renderInline(text, keyBase) {
  return text.split(INLINE).filter((part) => part !== '').map((part, index) => {
    const key = `${keyBase}-${index}`
    if (/^\*\*[^*]+\*\*$/.test(part)) return <strong key={key}>{part.slice(2, -2)}</strong>
    if (/^\*[^*\s][^*]*\*$/.test(part) || /^_[^_\s][^_]*_$/.test(part)) return <em key={key}>{part.slice(1, -1)}</em>
    if (/^`[^`]+`$/.test(part)) return <code key={key}>{part.slice(1, -1)}</code>
    const link = part.match(/^\[([^\]]+)\]\(([^)\s]+)\)$/)
    if (link) {
      return SAFE_HREF.test(link[2])
        ? <a key={key} href={link[2]} target="_blank" rel="noopener noreferrer">{link[1]}</a>
        : <Fragment key={key}>{link[1]}</Fragment>
    }
    return <Fragment key={key}>{part}</Fragment>
  })
}

const LIST_ITEM = /^\s*([-*]|\d+\.)\s+(.*)$/
const TABLE_SEPARATOR = /^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$/

function cells(line) {
  return line.trim().replace(/^\|/, '').replace(/\|$/, '').split('|').map((cell) => cell.trim())
}

export function parseMarkdown(source) {
  const lines = String(source || '').replace(/\r\n?/g, '\n').split('\n')
  const blocks = []
  let index = 0
  while (index < lines.length) {
    const line = lines[index]
    if (!line.trim()) { index += 1; continue }

    const heading = line.match(/^(#{1,4})\s+(.*)$/)
    if (heading) {
      blocks.push({ type: 'heading', level: heading[1].length, text: heading[2].trim() })
      index += 1
      continue
    }
    if (/^\s*(-{3,}|\*{3,}|_{3,})\s*$/.test(line)) {
      blocks.push({ type: 'rule' })
      index += 1
      continue
    }
    if (line.trim().startsWith('|') && TABLE_SEPARATOR.test(lines[index + 1] || '')) {
      const header = cells(line)
      const rows = []
      index += 2
      while (index < lines.length && lines[index].trim().startsWith('|')) {
        rows.push(cells(lines[index]))
        index += 1
      }
      blocks.push({ type: 'table', header, rows })
      continue
    }
    if (line.trim().startsWith('>')) {
      const quote = []
      while (index < lines.length && lines[index].trim().startsWith('>')) {
        quote.push(lines[index].replace(/^\s*>\s?/, ''))
        index += 1
      }
      blocks.push({ type: 'quote', blocks: parseMarkdown(quote.join('\n')) })
      continue
    }
    const item = line.match(LIST_ITEM)
    if (item) {
      const ordered = /\d+\./.test(item[1])
      const items = []
      while (index < lines.length) {
        const current = lines[index]
        const match = current.match(LIST_ITEM)
        if (match && /\d+\./.test(match[1]) === ordered) {
          items.push(match[2].trim())
        } else if (current.trim() && items.length && !/^#{1,4}\s/.test(current) && !match) {
          items[items.length - 1] += ` ${current.trim()}`
        } else {
          break
        }
        index += 1
      }
      blocks.push({ type: ordered ? 'ol' : 'ul', items })
      continue
    }
    const paragraph = []
    while (
      index < lines.length
      && lines[index].trim()
      && !/^#{1,4}\s/.test(lines[index])
      && !LIST_ITEM.test(lines[index])
      && !lines[index].trim().startsWith('>')
      && !lines[index].trim().startsWith('|')
    ) {
      paragraph.push(lines[index].trim())
      index += 1
    }
    if (paragraph.length) blocks.push({ type: 'p', text: paragraph.join(' ') })
    else index += 1
  }
  return blocks
}

function renderBlocks(blocks, keyBase = 'b') {
  return blocks.map((block, index) => {
    const key = `${keyBase}-${index}`
    switch (block.type) {
      case 'heading': {
        const Tag = `h${Math.min(block.level + 1, 5)}`
        return <Tag key={key}>{renderInline(block.text, key)}</Tag>
      }
      case 'rule': return <hr key={key} />
      case 'ul':
      case 'ol': {
        const Tag = block.type
        return <Tag key={key}>{block.items.map((text, itemIndex) => <li key={itemIndex}>{renderInline(text, `${key}-${itemIndex}`)}</li>)}</Tag>
      }
      case 'quote': return <blockquote key={key}>{renderBlocks(block.blocks, key)}</blockquote>
      case 'table':
        return (
          <div className="md-table" key={key} role="region" tabIndex={0} aria-label="Tabela">
            <table>
              <thead><tr>{block.header.map((cell, cellIndex) => <th scope="col" key={cellIndex}>{renderInline(cell, `${key}-h${cellIndex}`)}</th>)}</tr></thead>
              <tbody>
                {block.rows.map((row, rowIndex) => (
                  <tr key={rowIndex}>{row.map((cell, cellIndex) => <td key={cellIndex}>{renderInline(cell, `${key}-${rowIndex}-${cellIndex}`)}</td>)}</tr>
                ))}
              </tbody>
            </table>
          </div>
        )
      default: return <p key={key}>{renderInline(block.text, key)}</p>
    }
  })
}

export default function Markdown({ source }) {
  return <div className="markdown">{renderBlocks(parseMarkdown(source))}</div>
}
