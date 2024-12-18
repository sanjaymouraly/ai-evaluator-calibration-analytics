// Shared API types mirroring the backend Pydantic schemas.

export type Role = 'admin' | 'adjudicator' | 'senior_reviewer' | 'reviewer'
export type ProjectStatus = 'draft' | 'active' | 'completed' | 'archived'
export type ScaleType = 'categorical' | 'ordinal' | 'numerical'
export type SeverityClass = 'minor' | 'major' | 'critical'

export interface User {
  id: string
  email: string
  full_name: string
  role: Role
  is_active: boolean
  created_at: string
}

export interface Project {
  id: string
  name: string
  description: string | null
  owner_id: string
  status: ProjectStatus
  mode: 'single' | 'pairwise'
  min_ratings_per_item: number
  disagreement_minor_fraction: number
  disagreement_major_fraction: number
  consensus_strategy: 'majority' | 'median' | 'expert'
  created_at: string
  updated_at: string
}

export interface ProjectProgress {
  total_tasks: number
  completed_tasks: number
  completion_pct: number
  submitted_ratings: number
  reviewers: number
}

export interface RubricAnchor {
  value: number | string
  label: string
  description?: string | null
  example?: string | null
}

export interface RubricCategory {
  id: string
  rubric_id?: string
  key: string
  name: string
  definition: string | null
  guidance: string | null
  weight: number
  scale_type: ScaleType
  min_value: number | null
  max_value: number | null
  options: RubricAnchor[] | null
  anchors: RubricAnchor[] | null
  examples: Array<Record<string, unknown>> | null
  item_order: number
}

export interface Rubric {
  id: string
  project_id: string
  name: string
  description: string | null
  version: number
  status: 'draft' | 'active' | 'superseded' | 'archived'
  change_note: string | null
  approved_by: string | null
  approved_at: string | null
  created_at: string
  categories: RubricCategory[]
}

export interface ProjectMember {
  id: string
  project_id: string
  user_id: string
  role_on_project: 'lead' | 'reviewer' | 'adjudicator'
  user?: User
}

export interface Task {
  id: string
  project_id: string
  dataset_id: string | null
  external_id: string | null
  mode: 'single' | 'pairwise'
  prompt: string
  response_a: string
  response_b: string | null
  reference_answer: string | null
  model_name: string | null
  model_version: string | null
  language: string | null
  task_type: string | null
  metadata: Record<string, unknown> | null
  status: string
  gold_label: { scores: Record<string, unknown>; rationale?: string | null } | null
  created_at: string
}

export interface Rating {
  id: string
  task_id: string
  reviewer_id: string
  reviewer_name?: string | null
  rubric_version_id: string | null
  version: number
  is_current?: boolean
  status: 'draft' | 'submitted'
  scores: Record<string, number | string> | null
  rationale: string | null
  evidence?: string | null
  confidence: number | null
  abstained: boolean
  submitted_at: string | null
  created_at?: string
}

export interface Workspace {
  task: Task
  rubric: Rubric
  my_rating: Rating | null
  my_draft: Rating | null
  submitted: boolean
  peer_ratings: Rating[]
  blinded: boolean
  assignment_status: string | null
}

export interface Assignment {
  id: string
  task_id: string
  reviewer_id: string
  status: string
  blinded: boolean
  assigned_at: string
  completed_at: string | null
}

export interface Disagreement {
  id: string
  project_id: string
  task_id: string
  category_key: string | null
  kind: string
  severity_score: number
  severity_class: SeverityClass
  details: Record<string, unknown> | null
  priority_score: number
  status: 'open' | 'in_review' | 'resolved' | 'dismissed'
  detected_at: string
}

export interface DisagreementDetail {
  disagreement: Disagreement
  task: Task
  ratings: Rating[]
  severity_formula: string
}

export interface Adjudication {
  id: string
  disagreement_id: string | null
  task_id: string
  adjudicator_id: string
  strategy: string
  decision: Record<string, unknown> | null
  rationale: string | null
  escalated: boolean
  status: 'proposed' | 'final' | 'reopened'
  created_at: string
}

export interface Consensus {
  strategy: string
  scores: Record<string, number | string>
  limitations: string[]
}

export interface AdjudicationDetail {
  adjudication: Adjudication
  task: Task
  ratings: Rating[]
  consensus: Consensus
  votes: Array<{ user_id: string; decision: Record<string, unknown>; rationale: string | null }>
}

export interface CalibrationSession {
  id: string
  project_id: string
  name: string
  description: string | null
  pass_threshold_kappa: number
  pass_threshold_accuracy: number
  status: string
  created_at: string
}

export interface CalibrationAttempt {
  id: string
  session_id: string
  reviewer_id: string
  phase: 'pre' | 'post'
  kappa: number | null
  accuracy: number | null
  mae: number | null
  passed: boolean | null
  feedback: { items?: Array<Record<string, unknown>> } | null
  completed_at: string
}

export interface CategoryMetric {
  n_items: number
  n_ratings?: number
  scale_type?: ScaleType
  metric?: string
  fleiss_kappa?: number | null
  krippendorff_alpha?: number | null
  icc_2_1?: number | null
  raw_agreement?: number | null
  mad?: number | null
  warnings?: string[]
}

export interface Dashboard {
  progress: ProjectProgress
  metrics: { n_ratings: number; n_rated_items: number; categories: Record<string, CategoryMetric> }
  disagreements: {
    total: number
    by_class: Record<string, number>
    by_kind: Record<string, number>
    by_category: Record<string, number>
    by_status: Record<string, number>
  }
  adjudication: { total: number; final: number; pending: number; escalated: number }
  reviewer_bias: Array<{
    reviewer_id: string
    mean_deviation: number
    std_deviation: number
    n_scores: number
    tendency: 'severe' | 'lenient' | 'neutral'
    by_category: Record<string, number>
  }>
  accuracy_vs_gold: {
    n_gold_tasks: number
    overall_accuracy: number | null
    by_reviewer: Record<string, { accuracy: number | null; mae_vs_gold: number | null; n_scores: number }>
  }
}

export interface RubricInsight {
  id: string
  project_id: string
  rubric_category_id: string | null
  issue_type: string
  severity: 'low' | 'medium' | 'high' | 'critical'
  evidence: Record<string, unknown> | null
  affected_task_ids: string[] | null
  sample_size: number
  stat_value: number | null
  suggestion: {
    recommendation?: string
    proposed_improvements?: string[]
    requires_human_approval?: boolean
  } | null
  source: string
  status: string
  created_at: string
}

export interface ChangeRequest {
  id: string
  rubric_id: string
  rubric_category_id: string | null
  proposed_changes: Record<string, unknown> | null
  evidence: Record<string, unknown> | null
  rationale: string
  requested_by: string
  source: string
  is_ai_generated: boolean
  status: 'pending' | 'approved' | 'rejected'
  review_note: string | null
  created_at: string
  reviewed_at: string | null
}

export interface Report {
  id: string
  project_id: string
  title: string
  report_format: 'csv' | 'json' | 'pdf'
  filters: Record<string, unknown> | null
  metric_definitions: Record<string, string> | null
  file_path: string | null
  generated_by: string
  created_at: string
}

export interface Job {
  id: string
  job_type: string
  status: 'queued' | 'running' | 'succeeded' | 'failed'
  result: Record<string, unknown> | null
  error_message: string | null
  created_at: string
}

export interface ImportResult {
  session_id: string
  dataset_id: string | null
  total_rows: number
  valid_rows: number
  error_rows: number
  duplicates_skipped: number
  preview: Array<{ row_number: number; valid: boolean; errors: string[]; data: Record<string, unknown> }>
  errors: Array<{ row: number; error: string }>
  dry_run: boolean
}

export interface PairwiseAgreement {
  reviewer_a: string
  reviewer_b: string
  shared_items: number
  exact_agreement: number | null
  mean_abs_diff: number
}

export interface ActivityPoint {
  date: string
  ratings: number
}

export interface ScoreDistribution {
  scale_type?: ScaleType
  n: number
  mean?: number | null
  median?: number | null
  std?: number | null
  min?: number | null
  max?: number | null
  histogram?: Record<string, number>
  counts?: Record<string, number>
}

export interface AuditEntry {
  id: string
  user_id: string | null
  action: string
  entity_type: string | null
  entity_id: string | null
  details: Record<string, unknown> | null
  created_at: string
}
