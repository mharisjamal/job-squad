// Wire types - mirror IMPLEMENTATION_PLAN.md section 6 exactly (snake_case).

export type ApplicationStatus =
  | "saved"
  | "applied"
  | "assessment"
  | "interview"
  | "offer"
  | "rejected"
  | "ghosted";

export type PortalMemberStatus = "none" | "signed_up" | "active" | "abandoned";

export type ActivityType =
  | "member_joined"
  | "member_removed"
  | "join_requested"
  | "company_added"
  | "portal_added"
  | "application_status_changed"
  | "application_removed"
  | "comment_added"
  | "portal_status_changed";

export interface User {
  id: number;
  /** Server-derived handle; never chosen by the user. Display fallback. */
  username: string;
  display_name: string;
  email?: string | null;
  avatar_url?: string | null;
}

export interface AuthResponse {
  token: string;
  user: User;
}

export type GroupVisibility = "private" | "public";

export interface Group {
  id: number;
  name: string;
  invite_code: string;
  owner_id: number;
  created_at: string;
  member_count: number;
  visibility: GroupVisibility;
  description: string | null;
  /** Owner-only; omitted or 0 for non-owners. Drives the Members nav badge. */
  pending_request_count?: number;
}

export interface GroupMember {
  user_id: number;
  username: string;
  display_name: string;
  role: "owner" | "member";
  joined_at: string;
}

export interface GroupDetail extends Group {
  members: GroupMember[];
}

/** A public group in the discover directory (GET /api/groups/discover). */
export interface DiscoverGroup {
  id: number;
  name: string;
  description: string | null;
  member_count: number;
  /** The caller's standing with this group: no request, or one pending. */
  request_status: "none" | "pending";
}

/** A pending join request for the owner's review (GET /api/groups/{gid}/requests). */
export interface JoinRequest {
  id: number;
  user_id: number;
  username: string;
  display_name: string;
  created_at: string;
}

/** The raw join-request row returned by POST /api/groups/{gid}/request. */
export interface JoinRequestRecord {
  id: number;
  group_id: number;
  user_id: number;
  status: "pending" | "approved" | "rejected";
  created_at: string;
}

export interface ApplicationBrief {
  user_id: number;
  username: string;
  display_name: string;
  status: ApplicationStatus;
  applied_at: string | null;
  updated_at: string;
  resume_id: number | null;
  resume_label: string | null;
}

export interface ApplicationFull {
  id: number;
  company_id: number;
  company_name: string;
  user_id: number;
  username: string;
  display_name: string;
  status: ApplicationStatus;
  applied_via_portal_id: number | null;
  applied_via_portal_name: string | null;
  applied_at: string | null;
  follow_up_at: string | null;
  url: string | null;
  notes: string | null;
  created_at: string;
  updated_at: string;
  resume_id: number | null;
  resume_label: string | null;
  /**
   * Captured job posting (plan 9b, R2). Optional so the type is safe while the
   * backend rolls the field into serialize_application_full; the editor and the
   * match panel read it to hydrate and to decide readiness.
   */
  jd_text?: string | null;
}

export interface Company {
  id: number;
  group_id: number;
  name: string;
  website: string | null;
  careers_url: string | null;
  location: string | null;
  tags: string[];
  notes: string | null;
  archived: boolean;
  created_by: number;
  created_by_username: string;
  created_at: string;
  updated_at: string;
  applications: ApplicationBrief[];
  comment_count: number;
}

export interface Comment {
  id: number;
  company_id: number;
  user_id: number;
  username: string;
  display_name: string;
  body: string;
  created_at: string;
}

export interface CompanyDetail extends Omit<Company, "applications"> {
  applications: ApplicationFull[];
  comments: Comment[];
}

export interface PortalStatusRow {
  user_id: number;
  username: string;
  display_name: string;
  status: PortalMemberStatus;
  rating: number | null;
  notes: string | null;
  // null on the response to a "none" upsert (row deleted).
  updated_at: string | null;
}

export interface PortalStats {
  applications_via: number;
  interviews_via: number;
  offers_via: number;
}

export interface Portal {
  id: number;
  group_id: number;
  name: string;
  url: string | null;
  notes: string | null;
  /** Market this portal serves, e.g. "Middle East", "USA", "Global". */
  region: string | null;
  created_by: number;
  created_by_username: string;
  created_at: string;
  updated_at: string;
  statuses: PortalStatusRow[];
  stats: PortalStats;
}

export interface Activity {
  id: number;
  group_id: number;
  user_id: number;
  username: string;
  display_name: string;
  type: ActivityType;
  company_id: number | null;
  company_name: string | null;
  portal_id: number | null;
  portal_name: string | null;
  detail: Record<string, unknown>;
  created_at: string;
}

export interface StatusCounts {
  saved: number;
  applied: number;
  assessment: number;
  interview: number;
  offer: number;
  rejected: number;
  ghosted: number;
  total: number;
}

export interface MemberStats {
  user_id: number;
  username: string;
  display_name: string;
  counts: StatusCounts;
  response_rate: number | null;
}

export interface PortalEffectiveness {
  portal_id: number;
  name: string;
  applications_via: number;
  interviews_via: number;
  offers_via: number;
}

export interface GroupStats {
  group: {
    companies: number;
    portals: number;
    applications: number;
    members: number;
  };
  per_member: MemberStats[];
  per_portal: PortalEffectiveness[];
}

// Request payloads

export interface RegisterPayload {
  display_name: string;
  email: string;
  password: string;
}

export interface LoginPayload {
  /** Email or (legacy) username. */
  identifier: string;
  password: string;
}

export type OAuthProvider = "google" | "github" | "linkedin";

/** Public server capability probe: decides which signup flow the UI shows. */
export interface AuthConfig {
  otp_required: boolean;
  providers: OAuthProvider[];
}

export interface RegisterStartRequest {
  display_name: string;
  email: string;
  password: string;
}

export interface RegisterStartResponse {
  ok: boolean;
  resend_after_seconds: number;
}

export interface RegisterVerifyRequest {
  email: string;
  code: string;
}

export interface GroupCreatePayload {
  name: string;
  visibility?: GroupVisibility;
  description?: string | null;
}

export interface GroupPatch {
  name?: string;
  visibility?: GroupVisibility;
  description?: string | null;
}

export interface CompanyPayload {
  name: string;
  website?: string | null;
  careers_url?: string | null;
  location?: string | null;
  tags?: string[];
  notes?: string | null;
}

export interface CompanyPatch extends Partial<CompanyPayload> {
  archived?: boolean;
}

export interface ApplicationUpsert {
  status: ApplicationStatus;
  applied_via_portal_id?: number | null;
  applied_at?: string | null;
  follow_up_at?: string | null;
  url?: string | null;
  notes?: string | null;
  resume_id?: number | null;
  /** Pasted job posting (<=50,000 chars); merge semantics, null clears. */
  jd_text?: string | null;
}

export interface PortalPayload {
  name: string;
  url?: string | null;
  notes?: string | null;
  region?: string | null;
}

export interface PortalStatusUpsert {
  status: PortalMemberStatus;
  rating?: number | null;
  notes?: string | null;
}

// Resumes (plan section 9b, Phase R1)

export type ResumeKind = "pdf" | "tex" | "docx";

export interface Resume {
  id: number;
  label: string;
  filename: string | null;
  kind: ResumeKind;
  size_bytes: number;
  created_at: string;
  attached_count: number;
}

export interface ResumeStatsRow {
  resume_id: number;
  label: string;
  applications: number;
  interviews: number;
  offers: number;
  rejected: number;
  ghosted: number;
}

// Deterministic JD <-> resume match report (plan section 9b, Phase R2)

export interface MatchSkill {
  skill: string;
  present: boolean;
}

export interface MatchReport {
  jd_skills: MatchSkill[];
  /** Percentage 0-100 (present / total). Guidance, not a target to max out. */
  coverage: number;
  missing: string[];
  resume_id: number | null;
  resume_label: string | null;
  /**
   * False when the attached resume is image-only/scanned, so no text could be
   * extracted to compare. Optional so the type is safe before/after the backend
   * field lands; treated as true when absent.
   */
  resume_text_available?: boolean;
}

// BYOK AI settings, tailoring, and share links (plan section 9b, Phase R3)

export type AiProvider = "gemini" | "groq" | "custom";

/**
 * GET /api/settings/ai. The key is never returned; key_set says one is stored.
 * On a fresh account nothing is configured yet, so provider/base_url/model come
 * back null; the settings panel coalesces those to the recommended defaults.
 */
export interface AiSettings {
  provider: AiProvider | null;
  base_url: string | null;
  model: string | null;
  key_set: boolean;
}

/** PUT /api/settings/ai. A blank or omitted key keeps the stored one. */
export interface AiSettingsPut {
  provider: AiProvider;
  base_url?: string;
  model?: string;
  key?: string;
}

/** POST /api/settings/ai/test. error carries the provider text when ok is false. */
export interface AiTestResult {
  ok: boolean;
  error?: string | null;
}

export interface TailorSuggestion {
  section: string;
  original: string;
  suggested: string;
  reason: string;
}

/** Tailoring a .tex resume returns an editable source plus a change summary. */
export interface TailorTexResult {
  kind: "tex";
  tailored_tex: string;
  changes: string[];
}

/** Tailoring a pdf/docx resume returns non-destructive suggestions only. */
export interface TailorAdviceResult {
  kind: "advice";
  suggestions: TailorSuggestion[];
  keywords_to_add: string[];
}

export type TailorResult = TailorTexResult | TailorAdviceResult;

export interface ShareLink {
  url: string;
}
