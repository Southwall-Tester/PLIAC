"""Validate explicit chat evidence and relate it to observed Lab outcomes."""
import re
import unicodedata

from learning_agent.course_graph import CourseGraphError

POLICY = 'linuxlab-dialogue-v1'
KINDS = {'question', 'explanation', 'reported_error', 'uncertainty'}
RAW_KEYS = {'id', 'sequence', 'phase', 'at', 'answered_at', 'event_cursor', 'response_event_id',
            'operation_cursor', 'response_operation_cursor', 'prior_help_level', 'learner', 'assistant'}


def text(value, limit):
    return (isinstance(value, str) and 0 < len(value) <= limit
            and not any(unicodedata.category(c).startswith('C') and c not in '\n\t' for c in value))


def validate(report, activity):
    from .linux_mastery import REFERENCE_TOPICS
    rows, analyses, total = (report.get('dialogue_evidence', []), report.get('dialogue_analysis', []),
                              report.get('dialogue_total', 0))
    if (not isinstance(rows, list) or not isinstance(analyses, list) or type(total) is not int or total < 0
            or len(rows) != min(total, 100) or len(analyses) != len(rows)):
        raise CourseGraphError('对话记录容量或计数无效。')
    events = {e['id']: e for e in report['events']}
    ids = set()
    previous_event = -1
    for seq, row in enumerate(rows, total - len(rows) + 1):
        if (not isinstance(row, dict) or set(row) != RAW_KEYS
                or not isinstance(row['id'], str) or not re.fullmatch('[0-9a-f]{32}', row['id']) or row['id'] in ids
                or type(row['sequence']) is not int or row['sequence'] != seq
                or type(row['phase']) is not int or row['phase'] not in range(1, 10)
                or not text(row['at'], 80) or not text(row['answered_at'], 80)
                or any(type(row[k]) is not int for k in ('event_cursor', 'response_event_id', 'operation_cursor', 'response_operation_cursor', 'prior_help_level'))
                or not 0 <= row['operation_cursor'] <= row['response_operation_cursor'] <= report['operation_total']
                or not 0 <= row['event_cursor'] < row['response_event_id'] or row['response_event_id'] <= previous_event
                or row['prior_help_level'] not in range(4)):
            raise CourseGraphError('对话记录标识或时间顺序无效。')
        help_event = events.get(row['response_event_id'], {})
        if (help_event.get('kind') != 'tutor' or help_event.get('phase') != row['phase'] or help_event.get('prompt_level') != 3
                or help_event.get('operation_cursor') != row['response_operation_cursor']
                or sum(e['kind'] == 'passed' for e in report['events'] if e['id'] <= row['event_cursor']) != row['phase'] - 1):
            raise CourseGraphError('对话缺少对应的实际求助事件。')
        earlier_help = max((e['prompt_level'] for e in report['events']
                            if e['id'] <= row['event_cursor'] and e['phase'] == row['phase']), default=0)
        if row['prior_help_level'] < earlier_help:
            raise CourseGraphError('对话低报了已有帮助程度。')
        for role, origins in (('learner', {'learner_expression'}), ('assistant', {'model_inference', 'local_material'})):
            speech = row[role]
            if (not isinstance(speech, dict) or set(speech) != {'text', 'origin'}
                    or not isinstance(speech['origin'], str) or speech['origin'] not in origins or not text(speech['text'], 1200)):
                raise CourseGraphError('对话发言来源或文字无效。')
        ids.add(row['id'])
        previous_event = row['response_event_id']
    topics = {'concept:' + k for k in activity['concept_map']} | {'command:' + k for k in REFERENCE_TOPICS if k}
    for row, analysis in zip(rows, analyses):
        if (not isinstance(analysis, dict) or set(analysis) != {'turn_id', 'policy_version', 'origin', 'status', 'signals'}
                or analysis['turn_id'] != row['id'] or analysis['policy_version'] != POLICY
                or analysis['origin'] not in ('model_inference', 'local_rule') or analysis['status'] != 'unverified'
                or not isinstance(analysis['signals'], list) or len(analysis['signals']) > 3):
            raise CourseGraphError('对话候选分析来源或格式无效。')
        for signal in analysis['signals']:
            if (not isinstance(signal, dict) or set(signal) != {'topic', 'kind', 'quote', 'hypothesis'}
                    or not all(isinstance(v, str) for v in signal.values()) or signal['topic'] not in topics
                    or signal['kind'] not in KINDS or not text(signal['quote'], 320)
                    or signal['quote'] not in row['learner']['text'] or not text(signal['hypothesis'], 240)):
                raise CourseGraphError('对话候选必须引用学习者原话及已有知识标识。')


def unchanged(prior, current):
    if current.get('dialogue_total', 0) < prior.get('dialogue_total', 0):
        return False
    for field, key in (('dialogue_evidence', 'sequence'), ('dialogue_analysis', 'turn_id')):
        old = {row[key]: row for row in prior.get(field, [])}
        if any(row[key] in old and row != old[row[key]] for row in current.get(field, [])):
            return False
    return True


def topic_nodes(topic, activity, nodes):
    from .linux_mastery import reference_nodes
    kind, value = topic.split(':', 1)
    choices = activity['concept_map'].get(value, []) if kind == 'concept' else reference_nodes(value)
    return sorted(n for n in choices if n in nodes)


def cases(report, activity, nodes, existing):
    from .linux_mastery import COMMANDS
    rows = report.get('dialogue_evidence', [])
    analyses = {r['turn_id']: r for r in report.get('dialogue_analysis', [])}
    result = []
    for row in rows:
        analysis = analyses[row['id']]
        node_ids = sorted({n for signal in analysis['signals'] for n in topic_nodes(signal['topic'], activity, nodes)})
        if not node_ids:
            continue
        phase = row['phase']
        events = [e for e in report['events'] if e['phase'] == phase]
        boundary = max((e['id'] for e in events if e['kind'] == 'repair' and e['id'] <= row['event_cursor']), default=0)
        boundary_cursor = next((e['operation_cursor'] for e in events if e['id'] == boundary), 0)
        linked = [c for c in existing if c['phase'] == phase and set(c['node_ids']) & set(node_ids)
                  and (any(ref.startswith('check:') and boundary < int(ref.split(':')[1]) <= row['event_cursor'] for ref in c['evidence_refs'])
                       or (c.get('kind') == 'operation' and boundary_cursor < int(c['id'].split('-')[1]) <= row['operation_cursor']))][-3:]
        after = [e for e in events if e['id'] > row['response_event_id']]
        repaired = next((e for e in after if e['kind'] == 'repair'), None)
        # Recovery is a new intervention, not evidence that the chat fixed work.
        after = [e for e in after if not repaired or e['id'] < repaired['id']]
        passed = next((e for e in after if e['kind'] == 'passed'), None)
        failures = [e for e in after if e['kind'] == 'retry' and not e.get('repeat_checks', 0)
                    and set(node_ids) & {n for c in e.get('concepts', []) for n in activity['concept_map'].get(c, [])}]
        commands = {c for n in node_ids for c in COMMANDS.get(n, set())}
        later_ops = [o for o in report['operations'] if o['phase'] == phase and o['sequence'] > row['response_operation_cursor']
                     and o['command'] in commands and o.get('command_kind') in (None, 'file', 'builtin', 'missing')
                     and (not repaired or o['sequence'] <= repaired['operation_cursor'])]
        failed_ops = [o for o in later_ops if o['exit_code'] != 0]
        correction_cursor = max([row['response_operation_cursor']] + [e['operation_cursor'] for e in failures]
                                + [o['sequence'] for o in failed_ops])
        corrected = [o for o in later_ops if o['exit_code'] == 0 and o['sequence'] > correction_cursor
                     and passed and o['sequence'] <= passed['operation_cursor']]
        observations = ['学习者在终端主动提问或解释；这不是一次操作错误或测验作答。']
        observations.append('已保留当时的 AI 讲解，用作帮助背景，内容正确性尚未复核。' if row['assistant']['origin'] == 'model_inference'
                            else '当时提供的是本地资料，已与学习者发言分开保存。')
        refs = ['dialogue:' + row['id'], 'dialogue_analysis:' + row['id'], 'check:' + str(row['response_event_id'])]
        for c in linked:
            refs += [r for r in c['evidence_refs'] if r.startswith('check:') and int(r.split(':')[1]) <= row['event_cursor']]
            refs += [r for r in c['evidence_refs'] if r.startswith('operation:') and boundary_cursor < int(r.split(':')[1]) <= row['operation_cursor']]
        refs += ['check:' + str(e['id']) for e in failures[-3:]]
        refs += ['operation:' + str(o['sequence']) for o in (failed_ops[-1:] + corrected[-1:])]
        if passed:
            refs.append('check:' + str(passed['id']))
        if corrected and report.get('tracking_enabled'):
            outcome = 'checked_after_help'
            observations.append('收到帮助后有相关成功操作，随后同关检查通过；仅为先后关系，不能证明帮助有效或独立掌握。')
        elif failures or failed_ops:
            outcome = 'difficulty_after_help'
            observations.append('收到帮助后仍有相关失败记录；需同时核对讲解是否准确、操作是否执行及任务现场。')
        elif passed:
            outcome = 'later_check_passed'
            observations.append('后续同关检查通过，但缺少相关操作证据，不能推断该知识已理解。')
        elif repaired:
            outcome = 'repair_boundary'
            refs.append('check:' + str(repaired['id']))
            observations.append('后续使用过现场恢复，恢复后的结果不能直接归因于这次答疑。')
        else:
            outcome = 'awaiting_followup'
            observations.append('尚无足够的后续相关操作与检查，等待核验。')
        if any(e['kind'] in ('hint', 'tutor') for e in after):
            observations.append('此后还收到过其他帮助，不能把后续表现单独归因于这一轮讲解。')
        # Literal reuse is observable; understanding or copying intent is not.
        normalized = re.sub(r'\s+', '', row['learner']['text'])
        echoes = [old['id'] for old in rows if old['sequence'] < row['sequence'] and old['phase'] == phase
                  and len(normalized) >= 12 and normalized in re.sub(r'\s+', '', old['assistant']['text'])]
        if echoes:
            observations.append('这段学习者文字与此前助教回复有逐字重合；需要换例解释，不能据此认定独立理解。')
            refs += ['dialogue:' + ident for ident in echoes]
        context = dict(turn_id=row['id'], learner_text=row['learner']['text'], assistant_text=row['assistant']['text'],
                       assistant_origin=row['assistant']['origin'], signals=analysis['signals'], analysis_origin=analysis['origin'],
                       prior_help_level=row['prior_help_level'], echoes_tutor=bool(echoes))
        hypotheses = list(dict.fromkeys(s['hypothesis'] for s in analysis['signals']))
        hypotheses.append('提问可能是正常求知、措辞确认或理解困难；AI 讲解也可能有误，须结合原话、实际操作与独立复测区分。')
        result.append(dict(id='dialogue-' + row['id'], kind='dialogue', phase=phase, phases=[phase], node_ids=node_ids,
                           observations=observations, hypotheses=hypotheses, evidence_refs=sorted(set(refs)),
                           outcome=outcome, check_attempts=0, episodes=0, dialogue_count=1, prompt_level=3,
                           dialogue_context=[context], linked_case_ids=[c['id'] for c in linked]))
        for c in linked:
            c.setdefault('dialogue_context', []).append(context)
            c['evidence_refs'] += ['dialogue:' + row['id'], 'dialogue_analysis:' + row['id']]
            c['hypotheses'] = list(dict.fromkeys(c['hypotheses'] + hypotheses))
    return result
