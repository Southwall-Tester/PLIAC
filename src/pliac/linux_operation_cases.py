"""Observed command failure episodes, including correction before lab check.

Operand roles are coarse categories, not exact paths. A later successful command
and artifact check establish chronology, never a confirmed mental cause.
"""


def cases(report, nodes, existing):
    from .linux_mastery import COMMANDS, reference_nodes

    ops = sorted(report.get('operations', []), key=lambda o: o['sequence'])
    events = report['events']
    result, consumed = [], set()
    for first in ops:
        seq, phase, command = first['sequence'], first['phase'], first['command']
        ids = sorted(reference_nodes(command) & set(nodes))
        if (seq in consumed or first['exit_code'] == 0 or not ids
                or command not in {c for commands in COMMANDS.values() for c in commands}
                or first.get('command_kind') not in ('file', 'builtin', 'missing')):
            continue
        boundary = next((e for e in events if e['phase'] == phase
                         and e['operation_cursor'] >= seq and e['kind'] in ('repair', 'passed')), None)
        limit = boundary['operation_cursor'] if boundary else report['operation_total']
        related = [o for o in ops if o['phase'] == phase and seq <= o['sequence'] <= limit
                   and o['command'] == command and o.get('command_kind') in ('file', 'builtin', 'missing')
                   and o.get('operand_roles') == first.get('operand_roles')]
        # Help/version/listing success cannot stand in for task execution.
        def task_success(o):
            flags = o.get('flags', [])
            if (o['exit_code'] != 0 or o.get('known_options') is not True
                    or not o.get('operand_roles') or 'other' in o['operand_roles']
                    or any(f in ('--help', '--version', '-h') for f in flags)):
                return False
            if command == 'tar':
                return any(f in ('--extract', '--get', '--create', '--append', '--update')
                           or (f.startswith('-') and not f.startswith('--') and any(c in f[1:] for c in 'xcru'))
                           for f in flags)
            return True
        success = next((o for o in related if o['sequence'] > seq and task_success(o)), None)
        end = success['sequence'] if success else limit
        failures = [o for o in related if o['sequence'] <= end and o['exit_code'] != 0]
        consumed.update(o['sequence'] for o in failures)
        refs = ['operation:' + str(o['sequence']) for o in failures]
        observations = [f"{command} 命令出现非零退出码（首条为 {first['exit_code']}）；记录到 {len(failures)} 次失败执行。"]
        observations.append('退出码只表明命令未正常完成；未采集原生错误输出，不能直接确定失败原因。')
        references = [r for r in report.get('reference_lookups', []) if r['phase'] == phase
                      and not r['after_completion'] and seq <= r['operation_cursor'] <= end
                      and (not success or r['operation_cursor'] < end)
                      and (not boundary or r['at'] <= boundary['at'])
                      and set(ids) & reference_nodes(r['topic'])]
        help_events = [e for e in events if e['phase'] == phase and e['kind'] in ('hint', 'tutor')
                       and seq <= e['operation_cursor'] <= end
                       and (not success or e['operation_cursor'] < end)
                       and (not boundary or e['id'] < boundary['id'])]
        refs += ['reference:' + str(r['sequence']) for r in references]
        refs += ['check:' + str(e['id']) for e in help_events]
        if references:
            observations.append('失败后查阅了相关资料：' + '、'.join(dict.fromkeys(r['topic'] for r in references)) + '。')
        if help_events:
            observations.append('此过程还记录到提示或助教帮助，后续表现不能认定为无辅助完成。')
        passed = boundary if boundary and boundary['kind'] == 'passed' else None
        if success:
            refs.append('operation:' + str(success['sequence']))
            observations.append('随后同关、同命令、同操作数角色的执行退出码为 0；角色记录不含精确路径，不能证明是完全相同目标。')
            outcome = 'command_succeeded'
        else:
            outcome = 'awaiting_verification'
        if passed:
            refs.append('check:' + str(passed['id']))
            observations.append('随后本关检查通过，任务结果满足检查项；不据此确认早先失败原因或概念掌握。')
            outcome = 'operation_corrected' if success else 'later_check_passed'
        elif boundary:
            refs.append('check:' + str(boundary['id']))
            observations.append('后续发生现场恢复，恢复之后的成功不能作为本次自行纠错的依据。')
            outcome = 'repair_boundary'
        if references or help_events:
            observations.append('帮助与操作的先后关系可追溯，但不能据此证明帮助造成了纠正。')
        if report.get('operation_total', 0) > len(ops) or not report.get('tracking_enabled'):
            observations.append('过程记录不完整，只能描述保留的观察，不能补推缺失操作。')
        # Link overlapping check/input cases rather than treating them as
        # independent conceptual errors. Each episode keeps its first-op ID.
        linked = []
        for case in existing:
            if case['phase'] != phase or not set(ids) & set(case['node_ids']):
                continue
            check_ids = {int(r.split(':')[1]) for r in case['evidence_refs'] if r.startswith('check:')}
            matching_check = any(e['id'] in check_ids and e['kind'] == 'retry'
                                 and seq <= e['operation_cursor'] <= end for e in events)
            matching_input = any('input:' + p['id'] in case['evidence_refs'] and p['command'] == command
                                 and seq <= p['operation_cursor'] <= end for p in report.get('input_patterns', []))
            if matching_check or matching_input:
                linked.append(case['id'])
        if linked:
            observations.append('本过程与其他检查或输入案例有关联，不应将关联记录累计为独立知识错误。')
        prior_help = max((e['prompt_level'] for e in events if e['phase'] == phase
                          and e['operation_cursor'] <= end
                          and (not boundary or e['id'] <= boundary['id'])), default=0)
        result.append(dict(id='operation-' + str(seq), kind='operation', phase=phase, phases=[phase],
                           node_ids=ids, observations=observations, evidence_refs=list(dict.fromkeys(refs)),
                           hypotheses=['可能涉及命令选项、操作数或路径设置，也可能是权限、文件状态或其他环境条件；需结合实际错误信息和学习者解释核验。'],
                           outcome=outcome, check_attempts=0, command_attempts=len(failures) + bool(success),
                           failed_operations=len(failures), episodes=1, prompt_level=prior_help,
                           linked_case_ids=linked))
    return result
