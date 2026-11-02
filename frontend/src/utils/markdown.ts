import DOMPurify from 'dompurify'
import hljs from 'highlight.js/lib/core'
import bash from 'highlight.js/lib/languages/bash'
import css from 'highlight.js/lib/languages/css'
import go from 'highlight.js/lib/languages/go'
import java from 'highlight.js/lib/languages/java'
import javascript from 'highlight.js/lib/languages/javascript'
import json from 'highlight.js/lib/languages/json'
import python from 'highlight.js/lib/languages/python'
import sql from 'highlight.js/lib/languages/sql'
import typescript from 'highlight.js/lib/languages/typescript'
import xml from 'highlight.js/lib/languages/xml'
import yaml from 'highlight.js/lib/languages/yaml'
import { marked } from 'marked'

import 'highlight.js/styles/github.css'

// 只注册常用语言，避免全量引入把包体积顶上去
const LANGS: Record<string, unknown> = {
  bash,
  css,
  go,
  java,
  javascript,
  json,
  python,
  sql,
  typescript,
  xml,
  yaml,
}
for (const [name, lang] of Object.entries(LANGS)) {
  hljs.registerLanguage(name, lang as never)
}
hljs.registerAliases(['js', 'jsx'], { languageName: 'javascript' })
hljs.registerAliases(['ts', 'tsx'], { languageName: 'typescript' })
hljs.registerAliases(['sh', 'shell'], { languageName: 'bash' })
hljs.registerAliases(['html'], { languageName: 'xml' })
hljs.registerAliases(['yml'], { languageName: 'yaml' })

marked.setOptions({ gfm: true, breaks: true })

const CITE_PATTERN = /\[(\d{1,2})\]/g
const SKIP_TAGS = new Set(['CODE', 'PRE', 'SCRIPT', 'STYLE', 'A'])

function highlightCode(root: HTMLElement): void {
  root.querySelectorAll('pre code').forEach((el) => {
    const codeEl = el as HTMLElement
    const langClass = Array.from(codeEl.classList).find((c) => c.startsWith('language-'))
    const lang = langClass?.replace('language-', '')
    try {
      if (lang && hljs.getLanguage(lang)) {
        codeEl.innerHTML = hljs.highlight(codeEl.textContent || '', { language: lang }).value
      } else {
        codeEl.innerHTML = hljs.highlightAuto(codeEl.textContent || '').value
      }
      codeEl.classList.add('hljs')
    } catch {
      // 高亮失败不影响展示，保留纯文本
    }
  })
}

/** 只在文本节点里替换 [n]，跳过代码块与链接，避免把代码里的数组下标也变成角标 */
function replaceCitations(root: HTMLElement, citeIndexes: Set<number>): void {
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
    acceptNode(node) {
      const parent = node.parentElement
      if (parent && SKIP_TAGS.has(parent.tagName)) return NodeFilter.FILTER_REJECT
      return CITE_PATTERN.test(node.textContent || '')
        ? NodeFilter.FILTER_ACCEPT
        : NodeFilter.FILTER_REJECT
    },
  })

  const targets: Text[] = []
  while (walker.nextNode()) targets.push(walker.currentNode as Text)
  CITE_PATTERN.lastIndex = 0

  for (const node of targets) {
    const text = node.textContent || ''
    const frag = document.createDocumentFragment()
    let cursor = 0
    let matched = false

    text.replace(CITE_PATTERN, (raw, n, offset: number) => {
      const idx = Number(n)
      if (!citeIndexes.has(idx)) return raw
      matched = true
      frag.appendChild(document.createTextNode(text.slice(cursor, offset)))
      const span = document.createElement('span')
      span.className = 'cite'
      span.dataset.idx = String(idx)
      span.textContent = n
      frag.appendChild(span)
      cursor = offset + raw.length
      return raw
    })

    if (!matched) continue
    frag.appendChild(document.createTextNode(text.slice(cursor)))
    node.parentNode?.replaceChild(frag, node)
  }
}

/**
 * Markdown 渲染 + 引用角标 + 代码高亮。
 *
 * 安全顺序很重要：先 sanitize，再插入我们自己生成的 cite span。
 * 如果先插 span 再 sanitize，span 里的 data-idx 可能被清洗掉；
 * 而如果把未经消毒的 HTML 直接 v-html，模型输出就成了 XSS 入口。
 */
export function renderMarkdown(text: string, citeIndexes: number[] = []): string {
  if (!text) return ''

  let html: string
  try {
    html = marked.parse(text, { async: false }) as string
  } catch {
    // 流式过程中 markdown 可能不完整（如 ``` 未闭合），降级为纯文本
    html = text.replace(/[&<>]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' })[c] as string)
  }

  const clean = DOMPurify.sanitize(html, {
    ADD_TAGS: ['span'],
    ADD_ATTR: ['data-idx', 'target', 'rel'],
  })

  const doc = new DOMParser().parseFromString(clean, 'text/html')
  highlightCode(doc.body as HTMLElement)
  if (citeIndexes.length) {
    replaceCitations(doc.body as HTMLElement, new Set(citeIndexes))
  }
  return doc.body.innerHTML
}

/** 流式输出时用于节流：内容变化不一定每个 token 都重排 DOM */
export function createRenderScheduler(intervalMs = 60) {
  let timer: number | null = null
  return function schedule(fn: () => void) {
    if (timer !== null) return
    timer = window.setTimeout(() => {
      timer = null
      fn()
    }, intervalMs)
  }
}
