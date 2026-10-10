import {BookOpen, ClipboardCheck, FileText, FlaskConical, PlayCircle, type LucideIcon} from 'lucide-react';

// 学习活动注册表：工作台中栏一次呈现一种活动。新增一种学习形式（例如交互模拟、情境任务、复习卡）
// 只需在这里登记，并在 WorkspacePage 的 renderers 中提供渲染；活动标签、路径条与 URL 都从这里读取。
export type ActivityKey = 'learn' | 'handout' | 'materials' | 'check' | 'lab';

export type ActivityContext = {hasLab: boolean};

export type Activity = {
  key: ActivityKey;
  label: string;
  icon: LucideIcon;
  /** 在路径条中视为本节的一个步骤（材料与讲义是可选的学习形式，不算步骤）。 */
  step?: boolean;
  available: (context: ActivityContext) => boolean;
};

export const ACTIVITIES: Activity[] = [
  {key: 'learn', label: '讲解', icon: BookOpen, step: true, available: () => true},
  {key: 'handout', label: '讲义', icon: FileText, available: () => true},
  {key: 'materials', label: '视频与资料', icon: PlayCircle, available: () => true},
  {key: 'check', label: '检验', icon: ClipboardCheck, step: true, available: () => true},
  {key: 'lab', label: '实验', icon: FlaskConical, step: true, available: context => context.hasLab},
];

/** URL 是活动的唯一来源：?view=handout|materials|check，实验沿用 ?lab=1。 */
export function activityFromSearch(search: URLSearchParams, assessmentMaterial: boolean): ActivityKey {
  if (search.get('lab') === '1') return 'lab';
  const view = search.get('view');
  if (view === 'handout' || view === 'materials' || view === 'check') return view;
  if (assessmentMaterial && view !== 'learn') return 'check';
  return 'learn';
}

export function searchForActivity(search: URLSearchParams, next: ActivityKey, assessmentMaterial: boolean) {
  const params = new URLSearchParams(search);
  params.delete('lab'); params.delete('view'); params.delete('report');
  if (next === 'lab') params.set('lab', '1');
  else if (next !== 'learn') params.set('view', next);
  else if (assessmentMaterial) params.set('view', 'learn');
  return params;
}
