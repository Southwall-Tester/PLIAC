export interface Course { id: string; title: string; node_count: number; chapter_count: number; status: string }
export interface KnowledgeNode { id: string; title: string; chapter_id: string; description: string; objectives: string[] }
export interface Lesson { id: string; node_id: string; title: string; paragraphs: {id: string; text: string; heading?: string}[]; question: string; status: string }
export interface TutorTurn {
  resource_catalog?: {id: string; title: string; format: string; url: string; applicable_segment: string; video_segment?: {start_seconds: number; end_seconds: number} | null | ''}[];
  source_catalog?: {id: string; title: string; origin: string; page?: number; url?: string; content_digest: string; char_start: number; char_end: number}[];
  intent?: 'reply' | 'advance';
  activity?: {type: string; id?: string; node_id: string; status?: string; notice?: string};
  request_id: string; node_id: string; message: string; created_at: string;
  proposal: {response: string; target_node_id: string; action: string; rationale: string; question: string; uncertainty: string;
    recommended_resources?: {resource_id: string; reason: string}[];
    blocks: {heading: string; text: string; citations: {source_id: string; quote: string}[]}[]};
}
export interface Workspace {
  course: {id: string; title: string; version: number; chapters: {id: string; title: string}[]; nodes: KnowledgeNode[];
    edges?: {id: string; source: string; target: string; type: 'prerequisite' | 'related' | 'confusable' | 'contains'; reason?: string; source_ids?: string[]}[];
    sources?: {id: string; title: string}[]} | null;
  learner: {version: number; profile: {goals: string; background: string; interests?: string[]; explanation_preferences?: string}; states: Record<string, {status: string; reason: string}>};
  workspace: {onboarded: boolean; lessons: Lesson[]; drafts: Record<string, {text: string}>; tutor_turns?: TutorTurn[]; assessments?: Assessment[]; notes?: Record<string, Note[]>; memory?: {nodes: Record<string, LearningMemory>}; stage_reports?: StageReport[];
    learning_plans?: LearningPlan[];
    ml_lab?: {active_id: string | null; sessions: {id: string; step: number}[]};
    teaching_flow?: {enabled: boolean; current_turn_id: string | null; active_plan_id?: string | null; pending_plan_id?: string | null;
      plan_request?: {id: string; mode: string; preferred_form: string; anchor_node_id: string; course_version: number} | null;
      pending: {id: string; node_id: string; reason: string; source_id: string; course_version: number} | null}};
  current_lesson: Lesson | null;
  publication: {notice?: string};
  concept_map?: ConceptMap | null;
}

export interface ConceptMap {
  groups: {id: string; title: string}[];
  entry_concepts?: Record<string, string>;
  nodes: {id: string; title: string; group_id: string; lesson_ids: string[]; description: string; source_ids: string[]}[];
  edges: {id: string; source: string; target: string; predicate: string; reason?: string; directed?: boolean; source_ids?: string[]}[];
  sources: {id: string; title: string; url?: string}[];
}

export interface LearningPlan {
  completion?: {report_id: string; created_at: string; course_version: number};
  id: string; goal: string; mode: string; preferred_form: string; course_version: number; created_at: string;
  prerequisite_node_ids: string[];
  proposal: {status: 'proposed' | 'clarify'; summary: string; target_node_ids: string[]; learning_order: string[];
    start_node_id: string; rationale: string; clarification: string};
}

export interface Note {id: string; revision: number; text: string; course_version: number; material_id?: string; created_at: string}
export interface StageReport {
  id: string; request_id: string; title: string; course_version: number; learner_version: number; created_at: string;
  goals: string; scope: string; limitations: string; nodes: Record<string, LearningMemory>;
  evidence: {id: string; node_id: string; text: string; prompt_level: number; origin: string; source_type: string}[];
  diagnoses: {id: string; node_id: string; basis: string; evidence_ids: string[]; resolves_diagnosis_ids?: string[]; applicable?: boolean}[];
  notes: (Note & {node_id: string})[]; material_ids: string[];
}
export interface LearningMemory {
  title: string; status: string; reason: string; due_at?: string; version_changed: boolean;
  evidence_count: number; diagnosis_count: number; assisted_evidence_count: number;
  recent_feedback: {diagnosis_id: string; course_version: number; text: string; resolved?: boolean; applicable?: boolean}[];
  material_ids: string[]; pending_assessments: {id: string; status: string; course_version: number}[];
}

export async function api<T>(path: string, signal?: AbortSignal): Promise<T> {
  const response = await fetch(path, {signal});
  const data = await response.json();
  if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : '加载未完成，请重试。');
  return data;
}

export interface Assessment {
  id: string; node_id: string; course_version: number; question: string; options: {id: string; text: string}[];
  status: 'open' | 'submitted' | 'assessed'; answer?: string;
  assistance_turn_ids?: string[]; assistance_policy?: string;
  assistance_lab_event_ids?: string[]; lab_assistance_policy?: string;
  result?: {status: string; feedback: string; follow_up_question: string;
    criteria: {criterion_id: string; quote: string; reason: string}[];
    resolution?: {policy: string; diagnosis_ids: string[]; reason: string}};
}

let activeLearner: string | undefined;

// Set only after the identity bootstrap; authorization always stays on the server.
export function adoptLearner(id: string) {
  activeLearner = id;
  localStorage.setItem('pliac.local-learner', id);
}

// Pin the tab's identity so a second tab cannot silently reattribute in-flight work.
export function localLearner() {
  if (activeLearner) return activeLearner;
  let id = localStorage.getItem('pliac.local-learner');
  if (!id) { id = `learner-${crypto.randomUUID()}`; localStorage.setItem('pliac.local-learner', id); }
  activeLearner = id;
  return id;
}

export function learnerKey(name: string) {return `pliac.learner.${localLearner()}.${name}`;}
