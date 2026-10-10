import {TutorTurn} from './api';
import {Link} from 'react-router-dom';
import {SourceCitation} from './SourceCitation';
import {ExportPDF} from './ExportPDF';
import {RichText} from './RichText';
import {ReadingPosition} from './ReadingPosition';
import {ResourceRecommendations} from './ResourceRecommendations';

export function TeachingMaterial({turn}: {turn: TutorTurn}) {
  const labURL = `?${new URLSearchParams({material: turn.request_id, lab: '1'})}`;
  return <article className="lesson teaching-material"><div className="eyebrow">个人学习材料 · 已保存</div><h1>{turn.proposal.blocks[0]?.heading || '教学说明'}</h1>
    <ExportPDF key={turn.request_id} kind="material" id={turn.request_id}/>
    <ReadingPosition key={'reading:' + turn.request_id} materialId={turn.request_id}/>
    <p className="material-meta">{turn.intent === 'advance' ? '根据学习目标与证据安排' : '根据你的问题生成'} · {new Date(turn.created_at).toLocaleString('zh-CN')}</p>
    <RichText text={turn.proposal.response}/>
    <ResourceRecommendations turn={turn}/>
    {turn.activity?.type === 'lab' && <section><p>{turn.activity.notice}</p><Link className="material-link" to={labURL}>进入或继续 ML Lab</Link></section>}
    {turn.proposal.blocks.map((block, index) => <section id={`paragraph-${index}`} key={index}>{index > 0 && <h2>{block.heading}</h2>}<RichText text={block.text}/><details><summary>来源与依据</summary>{block.citations.map((citation, j) => <SourceCitation key={j} turn={turn} citation={citation}/>)}</details></section>)}
    {turn.activity?.type === 'assessment' ? <p className="quiet-note">已衔接下方课程核验任务；请完成作答，再依据结果继续学习。</p> : turn.proposal.question && <section><h2>继续思考</h2><RichText text={turn.proposal.question}/><small>{turn.activity?.notice || '这是后续问题，尚未产生掌握结论。'}</small></section>}
    <details><summary>为什么这样安排</summary><p>{turn.proposal.rationale}</p></details>
    {turn.proposal.uncertainty && <p className="quiet-note">{turn.proposal.uncertainty}</p>}
  </article>;
}
