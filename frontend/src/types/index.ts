export type Severity = 'critical' | 'warning' | 'nit';

export interface ReviewComment {
  file: string;
  line: number;
  severity: Severity;
  category: string;
  comment: string;
  confidence: number;
  suggested_fix?: string | null;
}

export interface Classification {
  change_type: string;
  risk_level: 'low' | 'medium' | 'high';
  summary: string;
  focus_areas: string[];
  reasoning: string;
}

export interface PRDetail {
  repo: string;
  pr_number: number;
  run_id: string;
  status: string;
  classification: Classification;
  comments: ReviewComment[];
  recommendation: string;
  low_confidence_count: number;
}

export interface PRListItem {
  repo: string;
  pr_number: number;
  run_id: string;
  status: string;
  title: string;
  risk_level: string | null;
  comment_count: number;
  recommendation: string | null;
}

export interface DiffFile {
  filename: string;
  status: string;
  additions: number;
  deletions: number;
  patch: string;
}

export const CONFIDENCE_THRESHOLD = 0.6;
export const isLowConfidence = (c: ReviewComment) => c.confidence < CONFIDENCE_THRESHOLD;
