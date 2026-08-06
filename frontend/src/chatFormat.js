// Parses the coach agent's reply text into renderable blocks. Deliberately
// tolerant: SYSTEM_PROMPT (teachable_moment_chat/app/agent.py) asks the model
// for a "⚠️ Simulated message (not real):" prefix and lettered A/B/C options,
// but never guarantees exact formatting. Anything the regexes don't recognise
// falls through to a plain paragraph — never worse than unformatted text.

const SIM_PREFIX_RE = /^\s*(?:⚠️\s*)?\*{0,2}\s*simulated message[^:]*:\s*\*{0,2}\s*/i
const OPTION_LINE_RE = /^\s*([A-Za-z])[.)]\s+(.+)$/
const BOLD_RE = /\*\*(.+?)\*\*/g

function parseInlineBold(str) {
  const segments = []
  let lastIndex = 0
  let match
  BOLD_RE.lastIndex = 0
  while ((match = BOLD_RE.exec(str)) !== null) {
    if (match.index > lastIndex) {
      segments.push({ text: str.slice(lastIndex, match.index), bold: false })
    }
    segments.push({ text: match[1], bold: true })
    lastIndex = BOLD_RE.lastIndex
  }
  if (lastIndex < str.length) {
    segments.push({ text: str.slice(lastIndex), bold: false })
  }
  if (segments.length === 0) {
    segments.push({ text: str, bold: false })
  }
  return segments
}

function parseOptionParagraph(paragraph) {
  const blocks = []
  let buffer = []
  const flush = () => {
    if (buffer.length) {
      blocks.push({ type: 'para', segments: parseInlineBold(buffer.join('\n')) })
      buffer = []
    }
  }
  for (const rawLine of paragraph.split('\n')) {
    const line = rawLine.trim()
    const optionMatch = line.match(OPTION_LINE_RE)
    if (optionMatch) {
      flush()
      blocks.push({
        type: 'option',
        letter: optionMatch[1].toUpperCase(),
        segments: parseInlineBold(optionMatch[2]),
      })
    } else if (line) {
      buffer.push(line)
    }
  }
  flush()
  return blocks
}

export function parseCoachMessage(text) {
  if (!text) return []
  const paragraphs = String(text)
    .split(/\n\s*\n/)
    .map((p) => p.trim())
    .filter(Boolean)

  const blocks = []
  let i = 0
  while (i < paragraphs.length) {
    const paragraph = paragraphs[i]
    const simMatch = paragraph.match(SIM_PREFIX_RE)
    if (simMatch) {
      const stripped = paragraph.slice(simMatch[0].length).trim()
      if (stripped) {
        blocks.push({ type: 'sim', paragraphs: [parseInlineBold(stripped)] })
        i += 1
      } else if (i + 1 < paragraphs.length) {
        blocks.push({ type: 'sim', paragraphs: [parseInlineBold(paragraphs[i + 1])] })
        i += 2
      } else {
        i += 1
      }
      continue
    }

    if (paragraph.split('\n').some((l) => OPTION_LINE_RE.test(l.trim()))) {
      blocks.push(...parseOptionParagraph(paragraph))
      i += 1
      continue
    }

    blocks.push({ type: 'para', segments: parseInlineBold(paragraph) })
    i += 1
  }
  return blocks
}
