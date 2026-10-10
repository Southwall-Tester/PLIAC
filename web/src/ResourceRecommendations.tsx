import {useParams} from 'react-router-dom';
import {TutorTurn} from './api';
import {ResourceChoices} from './ResourceChoices';

export function ResourceRecommendations({turn}: {turn: TutorTurn}) {
  const {courseId = ''} = useParams();
  if (!turn.proposal.recommended_resources?.length) return null;
  return <details className="resource-recommendations"><summary>本次建议的学习材料</summary><ol>
    {turn.proposal.recommended_resources.map(item => {
      const resource = turn.resource_catalog?.find(entry => entry.id === item.resource_id);
      return <li key={item.resource_id}><p>{resource?.title || '历史推荐材料'}{resource?.applicable_segment ? ` · ${resource.applicable_segment}` : ''}</p>
        {resource?.video_segment && <p>当时推荐片段：{resource.video_segment.start_seconds}—{resource.video_segment.end_seconds} 秒。打开材料时将核对当前版本。</p>}
        <p>{item.reason}</p>{resource ? <ResourceChoices course={courseId} node={turn.proposal.target_node_id} resourceId={item.resource_id} label={`查看推荐材料：${resource.title}`}/> : <p>此记录没有保存资源映射，请从课程材料中重新选择。</p>}
      </li>;
    })}
  </ol><p className="quiet-note">也可以换一种形式来学。</p></details>;
}
