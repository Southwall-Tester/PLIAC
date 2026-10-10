import {type TutorTurn} from './api';
import {useState} from 'react';
import {SourcePreview} from './SourcePreview';

export function SourceCitation({turn, citation}: {turn: TutorTurn; citation: {source_id: string; quote: string}}) {
  const [preview, setPreview] = useState(false);
  const source = turn.source_catalog?.find(item => item.id === citation.source_id);
  // Source links are produced by the server, but only the expected local route
  // is rendered as a link; imported historical records are not trusted HTML.
  const url = source?.url && /^\/api\/documents\/[A-Za-z0-9_-]+\/source(?:#page=\d+)?$/.test(source.url) ? source.url : undefined;
  const origin = source?.origin === 'uploaded_document' ? '原始资料' : source?.origin === 'course_source' ? '课程来源正文' : '课程编写内容';
  return <blockquote><small>{source ? `${origin} · ${source.title}${source.page ? ` · 第 ${source.page} 页／单元` : ''}` : citation.source_id}</small>
    <p>{citation.quote}</p>{url && <a className="material-link" href={url} target="_blank" rel="noreferrer">查看原始资料</a>}
    {url && source?.origin === 'uploaded_document' && <button onClick={() => setPreview(true)}>在工作台预览原文</button>}
    {preview && <SourcePreview turn={turn} initial={citation.source_id} close={() => setPreview(false)}/>}
    {source && <small>引用片段已随讲解保存；原资料若修订，历史引文仍保留。</small>}
  </blockquote>;
}
