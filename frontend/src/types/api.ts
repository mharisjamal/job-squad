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

export interface Group {
  id: number;
  name: string;
  invite_code: string;
  owner_id: number;
  created_at: string;
  member_count: number;
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

export interface ApplicationBrief {
  user_id: number;
  username: string;
  display_name: string;
  status: ApplicationStatus;
  applied_at: string | null;
  updated_at: string;
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
}

export interface PortalPayload {
  name: string;
  url?: string | null;
  notes?: string | null;
}

export interface PortalStatusUpsert {
  status: PortalMemberStatus;
  rating?: number | null;
  notes?: string | null;
}
