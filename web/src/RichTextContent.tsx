import {useMemo} from 'react';
import Markdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import remarkMath from 'remark-math';
import remarkParse from 'remark-parse';
import rehypeKatex from 'rehype-katex';
import {unified} from 'unified';
import 'katex/dist/katex.min.css';

const parser = unified().use(remarkParse);

function mathDelimiters(text: string) {
  // Normalize common model-produced TeX delimiters only outside code. Parse
  // code ranges rather than guessing fences with a string replacement regex.
  const ranges: [number, number][] = [];
  type Node = {type: string; position?: {start: {offset?: number}; end: {offset?: number}}; children?: Node[]};
  function visit(node: Node) {
    if ((node.type === 'code' || node.type === 'inlineCode') && node.position) {
      ranges.push([node.position.start.offset!, node.position.end.offset!]);
    } else node.children?.forEach(visit);
  }
  visit(parser.parse(text));
  const normalize = (part: string) => part.replace(/(?<!\\)\\\[([\s\S]*?)\\\]/g, (_, formula: string) => '\n$$\n' + formula + '\n$$\n')
    .replace(/(?<!\\)\\\(([\s\S]*?)\\\)/g, (_, formula: string) => `$${formula}$`);
  let start = 0;
  const parts: string[] = [];
  for (const [left, right] of ranges) {
    parts.push(normalize(text.slice(start, left)), text.slice(left, right)); start = right;
  }
  parts.push(normalize(text.slice(start)));
  return parts.join('');
}

export default function RichTextContent({text}: {text: string}) {
  const source = useMemo(() => mathDelimiters(text), [text]);
  return <Markdown skipHtml remarkPlugins={[remarkGfm, remarkMath]}
    rehypePlugins={[[rehypeKatex, {trust: false, strict: 'error', maxExpand: 1000, maxSize: 20}]]}
    components={{
      // Model text cannot navigate users or request remote tracking media.
      a: ({children}) => <span>{children}</span>,
      img: ({alt}) => <span className="quiet-note">[图片说明：{alt || '未提供说明'}；请从课程资料入口查看原图]</span>,
      h1: ({children}) => <h3>{children}</h3>,
      h2: ({children}) => <h3>{children}</h3>,
      h3: ({children}) => <h4>{children}</h4>,
      table: ({children}) => <div className="material-table"><small className="quiet-note">窄屏下可左右滑动表格</small><div className="table-scroll" role="region" aria-label="学习材料表格" tabIndex={0}><table>{children}</table></div></div>,
      ul: ({children}) => <ol>{children}</ol>,
    }}>{source}</Markdown>;
}
