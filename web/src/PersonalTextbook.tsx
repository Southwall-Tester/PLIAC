import {useEffect, useState} from 'react';
import {useParams} from 'react-router-dom';
import {api, localLearner, type TutorTurn} from './api';
import {ExportPDF} from './ExportPDF';
import {RichText} from './RichText';

type SavedMaterial = Pick<TutorTurn, 'request_id' | 'created_at' | 'proposal' | 'source_catalog' | 'resource_catalog'> & {course_version: number};

export function PersonalTextbook({reportId}: {reportId: string}) {
  const {courseId = ''} = useParams();
  const [materials, setMaterials] = useState<SavedMaterial[]>();
  const [error, setError] = useState('');
  const [retry, setRetry] = useState(0);
  useEffect(() => {
    const controller = new AbortController(); setMaterials(undefined); setError('');
    const query = new URLSearchParams({course_id: courseId, student_id: localLearner(), report_id: reportId});
    api<{materials: SavedMaterial[]}>(`/api/tutor/textbook?${query}`, controller.signal)
      .then(result => {if (!controller.signal.aborted) setMaterials(result.materials);})
      .catch(failure => {if (!controller.signal.aborted) setError(failure.message);});
    return () => controller.abort();
  }, [courseId, reportId, retry]);
  return <section className="personal-textbook"><h2>本阶段个人教材汇编</h2>
    <p>按保存顺序汇集本报告引用的讲解，笔记与学习记录保留在下方报告中。不会加入之后生成的内容，也不将阅读等同于掌握。</p>
    {error ? <p role="alert">{error}<button onClick={() => setRetry(value => value + 1)}>重试读取教材</button></p>
      : !materials ? <p role="status">正在读取教材汇编…</p> : <>
        <ExportPDF kind="textbook" id={reportId}/>
        {!materials.length && <p>本阶段尚无已保存讲解，汇编仍保留报告中的笔记与学习记录。</p>}
        <ol>{materials.map((turn, index) => <li key={turn.request_id}><a href={`#textbook-${index}`}>{turn.proposal.blocks[0]?.heading || '教学安排'}</a></li>)}</ol>
        {materials.map((turn, index) => <section id={`textbook-${index}`} key={turn.request_id}>
          <h3>{index + 1}. {turn.proposal.blocks[0]?.heading || '教学安排'}</h3>
          <p>课程 v{turn.course_version} · {new Date(turn.created_at).toLocaleString('zh-CN')}</p>
          <RichText text={turn.proposal.response}/>
          {!!turn.proposal.recommended_resources?.length && <details><summary>当时推荐的学习材料</summary><ol>{turn.proposal.recommended_resources.map(item => {
            const resource = turn.resource_catalog?.find(value => value.id === item.resource_id);
            return <li key={item.resource_id}>{resource?.title || '历史推荐材料'}<p>{item.reason}</p>{resource?.video_segment && <p>当时推荐片段：{resource.video_segment.start_seconds}—{resource.video_segment.end_seconds} 秒。</p>}</li>;
          })}</ol><p>这是当时的推荐说明。</p></details>}
          {turn.proposal.blocks.map((block, i) => <section key={i}><h4>{block.heading}</h4><RichText text={block.text}/>
            <details><summary>当时保存的来源与依据</summary><ol>{block.citations.map((citation, j) => {
              const source = turn.source_catalog?.find(item => item.id === citation.source_id);
              return <li key={j}>{source?.title || citation.source_id}{source?.page ? ` · 第 ${source.page} 页` : ''}<blockquote>{citation.quote}</blockquote></li>;
            })}</ol></details>
          </section>)}
          {turn.proposal.question && <><h4>继续思考</h4><RichText text={turn.proposal.question}/></>}
          <details><summary>当时的教学安排</summary><p>{turn.proposal.rationale}</p></details>
          <p>{turn.proposal.uncertainty}</p>
        </section>)}
      </>}
  </section>;
}
