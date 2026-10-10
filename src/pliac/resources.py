"""Read-only material choice; prerequisite guidance is not a browsing veto."""
from learning_agent.course_graph import safe_id
from learning_agent.recommendation import recommend_resources


def resource_choices(store, student, node_id):
    safe_id(student, '学习编号')
    graph = store._require_graph()
    store._node(graph, node_id)
    learner = store._derive(store._read_learner(student), graph)
    nodes = {node['id']: node for node in graph['nodes']}
    selection = recommend_resources(graph, learner['states'], node_id)
    recommended = {item['id']: item for item in selection['resources']}
    result = []
    for item in graph['resources']:
        if item.get('review_status') not in ('reviewed', 'auto_validated'):
            continue
        if node_id not in item.get('node_ids', []) and item['id'] not in recommended:
            continue
        missing = [ident for ident in item.get('prerequisite_ids', [])
                   if learner['states'].get(ident, {}).get('status') != 'mastered' or learner['states'].get(ident, {}).get('due')]
        result.append({key: item.get(key, '') for key in ('id', 'title', 'url', 'format', 'applicable_segment')} | {
            'for_current': node_id in item.get('node_ids', []),
            'video_segment': item.get('video_segment'),
            'reason': recommended.get(item['id'], {}).get('recommendation_reason', '关联当前知识点，可自主查看；阅读不作为掌握证据。'),
            'missing_prerequisites': [{'id': ident, 'title': nodes[ident]['title']} for ident in missing]})
    return {'course_version': graph['version'], 'resources': result,
            'notice': '材料来自当前可用课程；基础规则推荐不等同于智能体已作出完整教学判断。缺少所需形式时不会生成虚假入口。'}
