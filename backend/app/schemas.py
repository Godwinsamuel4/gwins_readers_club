from datetime import datetime, date
from typing import Optional, List
from pydantic import BaseModel, EmailStr, Field, computed_field


# ---------- Auth / Users ----------

class UserRegister(BaseModel):
    full_name: str
    email: EmailStr
    password: str = Field(min_length=6)
    phone_number: Optional[str] = None
    school: Optional[str] = None
    department: Optional[str] = None
    state: Optional[str] = None
    country: Optional[str] = "Nigeria"
    reading_interests: Optional[str] = None
    # --- Child-safety fields ---
    age_bracket: str  # "Under 13", "13-15", "16-17", "18+"
    guardian_name: Optional[str] = None
    guardian_email: Optional[EmailStr] = None
    guardian_consent: bool = False
    accepted_terms: bool = False


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class UserOut(BaseModel):
    id: int
    full_name: str
    email: str
    phone_number: Optional[str] = None
    school: Optional[str] = None
    department: Optional[str] = None
    state: Optional[str] = None
    country: Optional[str] = None
    profile_picture: Optional[str] = None
    biography: Optional[str] = None
    reading_interests: Optional[str] = None
    role: str
    is_active: bool = True
    age_bracket: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


class UserAdminOut(UserOut):
    """Extended user view for admin/moderator staff only — includes
    safeguarding fields that shouldn't be visible in ordinary public profiles."""
    guardian_name: Optional[str] = None
    guardian_email: Optional[str] = None
    guardian_consent: bool = False


class UserUpdate(BaseModel):
    full_name: Optional[str] = None
    phone_number: Optional[str] = None
    school: Optional[str] = None
    department: Optional[str] = None
    state: Optional[str] = None
    country: Optional[str] = None
    biography: Optional[str] = None
    reading_interests: Optional[str] = None


class AvatarPresetChoice(BaseModel):
    preset: str  # e.g. "avatar_male_1", "avatar_female_3"


class PasswordChange(BaseModel):
    current_password: str
    new_password: str = Field(min_length=6)


class DeactivateAccountRequest(BaseModel):
    password: str


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


# ---------- Books ----------

class BookCreate(BaseModel):
    title: str
    author: str
    publisher: Optional[str] = None
    description: Optional[str] = None
    category: str
    language: Optional[str] = "English"
    number_of_pages: Optional[int] = 0
    reading_time_minutes: Optional[int] = 0
    publication_year: Optional[int] = None
    cover_color: Optional[str] = "#4b2e83"
    content: Optional[str] = ""
    is_featured: Optional[bool] = False


class BookUpdate(BaseModel):
    title: Optional[str] = None
    author: Optional[str] = None
    publisher: Optional[str] = None
    description: Optional[str] = None
    category: Optional[str] = None
    language: Optional[str] = None
    number_of_pages: Optional[int] = None
    reading_time_minutes: Optional[int] = None
    publication_year: Optional[int] = None
    cover_color: Optional[str] = None
    content: Optional[str] = None
    is_featured: Optional[bool] = None
    status: Optional[str] = None
    rejection_reason: Optional[str] = None


class BookOut(BaseModel):
    id: int
    title: str
    author: str
    publisher: Optional[str] = None
    description: Optional[str] = None
    category: str
    language: str
    number_of_pages: int
    reading_time_minutes: int
    publication_year: Optional[int] = None
    cover_color: str
    cover_image: Optional[str] = Field(default=None, exclude=True)  # raw server path — never serialized
    file_format: Optional[str] = None
    file_original_name: Optional[str] = None
    is_featured: bool
    status: str = "approved"
    rejection_reason: Optional[str] = None
    created_at: datetime
    view_count: int
    average_rating: Optional[float] = None
    review_count: Optional[int] = 0

    @computed_field
    @property
    def cover_url(self) -> Optional[str]:
        return f"/api/admin/books/{self.id}/cover" if self.cover_image else None

    class Config:
        from_attributes = True


class BookRejectRequest(BaseModel):
    reason: str


class BookDetailOut(BookOut):
    content: Optional[str] = None


class BulkDeleteRequest(BaseModel):
    ids: List[int]


# ---------- Book Reactions ----------

class BookReactionIn(BaseModel):
    emoji: str


class BookReactionsOut(BaseModel):
    counts: dict
    my_reaction: Optional[str] = None


# ---------- Categories ----------

class CategoryCreate(BaseModel):
    name: str


class CategoryOut(BaseModel):
    id: int
    name: str

    class Config:
        from_attributes = True


# ---------- Reading progress / bookmarks / highlights ----------

class ProgressUpdate(BaseModel):
    book_id: int
    percent_complete: float
    current_position: int


class ProgressOut(BaseModel):
    id: int
    book_id: int
    percent_complete: float
    current_position: int
    status: str
    started_at: datetime
    completed_at: Optional[datetime] = None
    last_read_at: datetime

    class Config:
        from_attributes = True


class BookmarkCreate(BaseModel):
    book_id: int
    position: int
    label: Optional[str] = None


class BookmarkOut(BaseModel):
    id: int
    book_id: int
    position: int
    label: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


class HighlightCreate(BaseModel):
    book_id: int
    quoted_text: str
    note: Optional[str] = None


class HighlightUpdate(BaseModel):
    note: Optional[str] = None


class HighlightOut(BaseModel):
    id: int
    book_id: int
    quoted_text: str
    note: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


# ---------- Book of the Month ----------

class BookOfMonthCreate(BaseModel):
    book_id: int
    month: int
    year: int
    reading_guide: Optional[str] = None
    discussion_questions: Optional[str] = None


class BookOfMonthUpdate(BaseModel):
    book_id: Optional[int] = None
    month: Optional[int] = None
    year: Optional[int] = None
    reading_guide: Optional[str] = None
    discussion_questions: Optional[str] = None


class BookOfMonthOut(BaseModel):
    id: int
    book: BookOut
    month: int
    year: int
    reading_guide: Optional[str] = None
    discussion_questions: Optional[str] = None
    start_date: date
    is_active: bool

    class Config:
        from_attributes = True


# ---------- Reviews ----------

class ReviewCreate(BaseModel):
    book_id: int
    rating: int = Field(ge=1, le=5)
    lessons_learned: Optional[str] = None
    review_text: str


class ReviewOut(BaseModel):
    id: int
    book_id: int
    book_title: Optional[str] = None
    user_id: int
    reviewer_name: str
    rating: int
    lessons_learned: Optional[str] = None
    review_text: str
    created_at: datetime
    comment_count: int = 0
    helpful_count: int = 0
    marked_helpful_by_me: bool = False

    class Config:
        from_attributes = True


class ReviewCommentCreate(BaseModel):
    content: str


class ReviewCommentOut(BaseModel):
    id: int
    user_id: int
    commenter_name: str
    content: str
    created_at: datetime

    class Config:
        from_attributes = True


# ---------- Discussions ----------

class DiscussionPostCreate(BaseModel):
    category: str = "general"
    book_id: Optional[int] = None
    title: str
    content: str


class DiscussionPostOut(BaseModel):
    id: int
    user_id: int
    author_name: str
    category: str
    book_id: Optional[int] = None
    title: str
    content: str
    is_pinned: bool
    is_removed: bool = False
    created_at: datetime
    reply_count: int = 0

    class Config:
        from_attributes = True


class DiscussionReplyCreate(BaseModel):
    content: str
    parent_reply_id: Optional[int] = None


class DiscussionReplyUpdate(BaseModel):
    content: str


class DiscussionReplyOut(BaseModel):
    id: int
    user_id: int
    author_name: str
    parent_reply_id: Optional[int] = None
    content: str
    is_edited: bool = False
    created_at: datetime

    class Config:
        from_attributes = True


# ---------- Journal ----------

class JournalEntryCreate(BaseModel):
    book_id: Optional[int] = None
    entry_type: str = "reflection"
    content: str


class JournalEntryUpdate(BaseModel):
    content: str


class JournalEntryOut(BaseModel):
    id: int
    book_id: Optional[int] = None
    entry_type: str
    content: str
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


# ---------- Goals / Streak ----------

class GoalCreate(BaseModel):
    goal_type: str = "monthly"
    target_books: int
    year: int
    month: Optional[int] = None


class GoalUpdate(BaseModel):
    target_books: int


class GoalOut(BaseModel):
    id: int
    goal_type: str
    target_books: int
    year: int
    month: Optional[int] = None
    books_completed: int
    created_at: datetime

    class Config:
        from_attributes = True


class StreakOut(BaseModel):
    current_streak: int
    longest_streak: int
    last_read_date: Optional[date] = None

    class Config:
        from_attributes = True


# ---------- Challenges ----------

class ChallengeCreate(BaseModel):
    name: str
    description: Optional[str] = None
    start_date: date
    end_date: date
    target_books: int = 1


class ChallengeUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    target_books: Optional[int] = None


class ChallengeOut(BaseModel):
    id: int
    name: str
    description: Optional[str] = None
    start_date: date
    end_date: date
    target_books: int
    participant_count: int = 0

    class Config:
        from_attributes = True


# ---------- Certificates ----------

class CertificateOut(BaseModel):
    id: int
    user_id: Optional[int] = None
    user_name: Optional[str] = None
    certificate_type: str
    title: str
    issued_at: datetime
    revoked: bool = False
    revoked_reason: Optional[str] = None
    verification_code: Optional[str] = None

    class Config:
        from_attributes = True


class CertificateVerifyOut(BaseModel):
    """Public, minimal payload shown on the verify.html page — no email/ID exposure."""
    valid: bool
    recipient_name: Optional[str] = None
    title: Optional[str] = None
    certificate_type: Optional[str] = None
    issued_at: Optional[datetime] = None
    revoked: bool = False
    message: Optional[str] = None


# ---------- Notifications ----------

class NotificationOut(BaseModel):
    id: int
    notif_type: str
    message: str
    is_read: bool
    created_at: datetime

    class Config:
        from_attributes = True


class NotificationCreate(BaseModel):
    user_ids: Optional[List[int]] = None  # None = broadcast to all
    notif_type: str = "announcement"
    message: str


class NotificationPreferenceOut(BaseModel):
    category: str
    muted: bool


class NotificationPreferenceUpdate(BaseModel):
    category: str
    muted: bool


# ---------- Admin dashboard ----------

class AdminStats(BaseModel):
    total_members: int
    active_readers: int
    books_uploaded: int
    books_completed_total: int
    reviews_total: int
    discussion_posts_total: int
    clubs_placeholder: int = 0
    pending_reports: int = 0
    pending_book_submissions: int = 0
    active_clubs: int = 0
    upcoming_live_sessions: int = 0
    active_mentors: int = 0
    open_challenges: int = 0
    certificates_issued: int = 0


# ---------- Reading Clubs ----------

class ClubCreate(BaseModel):
    name: str
    school_or_org: Optional[str] = None
    description: Optional[str] = None


class ClubUpdate(BaseModel):
    name: Optional[str] = None
    school_or_org: Optional[str] = None
    description: Optional[str] = None


class ClubOut(BaseModel):
    id: int
    name: str
    school_or_org: Optional[str] = None
    description: Optional[str] = None
    member_count: int = 0
    is_member: bool = False
    is_leader: bool = False

    class Config:
        from_attributes = True


class ClubEventCreate(BaseModel):
    title: str
    description: Optional[str] = None
    event_date: datetime


class ClubEventUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    event_date: Optional[datetime] = None


class ClubEventOut(BaseModel):
    id: int
    title: str
    description: Optional[str] = None
    event_date: datetime
    is_cancelled: bool = False
    rsvp_count: int = 0
    is_attending: bool = False
    created_at: datetime

    class Config:
        from_attributes = True


# ---------- Mentorship ----------

class MentorProfileOut(BaseModel):
    user_id: int
    mentor_name: str
    specialties: Optional[str] = None
    bio: Optional[str] = None
    is_accepting_mentees: bool
    average_rating: Optional[float] = None
    rating_count: int = 0

    class Config:
        from_attributes = True


class MentorRatingCreate(BaseModel):
    rating: int = Field(ge=1, le=5)
    review_text: Optional[str] = None


class MentorRatingOut(BaseModel):
    id: int
    mentorship_id: int
    mentor_id: int
    mentee_id: int
    mentee_name: str
    rating: int
    review_text: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


class BecomeMentorPayload(BaseModel):
    specialties: Optional[str] = None
    bio: Optional[str] = None


class MentorshipRequestOut(BaseModel):
    id: int
    mentor_id: int
    mentor_name: str
    mentee_id: int
    mentee_name: str
    status: str
    requested_at: datetime

    class Config:
        from_attributes = True


class MentorQuestionCreate(BaseModel):
    question: str


class MentorQuestionOut(BaseModel):
    id: int
    mentorship_id: int
    asked_by: int
    question: str
    answer: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


class AnswerPayload(BaseModel):
    answer: str


# ---------- Live Discussions ----------

class LiveSessionCreate(BaseModel):
    title: str
    session_type: str = "live_chat"
    description: Optional[str] = None
    scheduled_at: datetime
    duration_minutes: int = 60
    category: Optional[str] = None
    book_id: Optional[int] = None
    max_capacity: Optional[int] = None
    recurrence: Optional[str] = None  # none, weekly, biweekly, monthly
    slow_mode_seconds: int = 0
    announcement_only: bool = False
    attendee_list_public: bool = True


class LiveSessionUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    scheduled_at: Optional[datetime] = None
    duration_minutes: Optional[int] = None
    category: Optional[str] = None
    max_capacity: Optional[int] = None
    slow_mode_seconds: Optional[int] = None
    announcement_only: Optional[bool] = None
    attendee_list_public: Optional[bool] = None
    recording_notes: Optional[str] = None


class LiveSessionOut(BaseModel):
    id: int
    title: str
    session_type: str
    host_id: Optional[int] = None
    host_name: Optional[str] = None
    co_host_names: List[str] = []
    description: Optional[str] = None
    scheduled_at: datetime
    duration_minutes: int
    is_active: bool
    is_cancelled: bool = False
    rsvp_count: int = 0
    is_attending: bool = False
    category: Optional[str] = None
    book_id: Optional[int] = None
    book_title: Optional[str] = None
    max_capacity: Optional[int] = None
    waitlist_count: int = 0
    is_waitlisted: bool = False
    recurrence: Optional[str] = None
    slow_mode_seconds: int = 0
    announcement_only: bool = False
    attendee_list_public: bool = True
    recording_notes: Optional[str] = None
    is_featured: bool = False
    status: str = "upcoming"  # upcoming, live, ended
    viewer_count: int = 0
    average_rating: Optional[float] = None
    rating_count: int = 0

    class Config:
        from_attributes = True


class LiveMessageCreate(BaseModel):
    content: str
    reply_to_id: Optional[int] = None


class LiveMessageReactionOut(BaseModel):
    emoji: str
    count: int
    reacted_by_me: bool = False


class LiveMessageOut(BaseModel):
    id: int
    user_id: int
    author_name: str
    content: str
    created_at: datetime
    reply_to_id: Optional[int] = None
    reply_to_author: Optional[str] = None
    reply_to_snippet: Optional[str] = None
    is_pinned: bool = False
    is_deleted: bool = False
    is_system: bool = False
    edited_at: Optional[datetime] = None
    reactions: List[LiveMessageReactionOut] = []

    class Config:
        from_attributes = True


class LiveMessageEdit(BaseModel):
    content: str


class LiveMessageReactionToggle(BaseModel):
    emoji: str


class LiveSessionResourceCreate(BaseModel):
    title: str
    url: str


class LiveSessionResourceOut(BaseModel):
    id: int
    title: str
    url: str
    added_by: Optional[int] = None

    class Config:
        from_attributes = True


class LiveSessionRatingCreate(BaseModel):
    rating: int
    comment: Optional[str] = None


class LiveSessionRatingOut(BaseModel):
    id: int
    user_id: int
    author_name: str
    rating: int
    comment: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


class LiveSessionPollOptionCreate(BaseModel):
    text: str


class LiveSessionPollCreate(BaseModel):
    question: str
    options: List[str]


class LiveSessionPollOptionOut(BaseModel):
    id: int
    text: str
    vote_count: int = 0


class LiveSessionPollOut(BaseModel):
    id: int
    question: str
    is_closed: bool
    options: List[LiveSessionPollOptionOut] = []
    total_votes: int = 0
    my_vote_option_id: Optional[int] = None

    class Config:
        from_attributes = True


class LiveSessionPollVoteCreate(BaseModel):
    option_id: int


class LiveSessionQuestionCreate(BaseModel):
    question: str


class LiveSessionQuestionAnswer(BaseModel):
    answer: str


class LiveSessionQuestionOut(BaseModel):
    id: int
    user_id: int
    author_name: str
    question: str
    answer: Optional[str] = None
    is_answered: bool = False
    upvote_count: int = 0
    upvoted_by_me: bool = False
    created_at: datetime

    class Config:
        from_attributes = True


class LiveSessionDuplicateRequest(BaseModel):
    scheduled_at: datetime


class LiveSessionTypingPing(BaseModel):
    is_typing: bool = True


class LiveSessionPresenceOut(BaseModel):
    viewer_count: int
    typing_names: List[str] = []


class LiveSessionHostStats(BaseModel):
    id: int
    title: str
    scheduled_at: datetime
    status: str
    rsvp_count: int
    message_count: int
    average_rating: Optional[float] = None
    rating_count: int = 0


# ---------- Reading Resources ----------

class ResourceCreate(BaseModel):
    book_id: Optional[int] = None
    resource_type: str
    title: str
    content: str


class ResourceUpdate(BaseModel):
    book_id: Optional[int] = None
    resource_type: Optional[str] = None
    title: Optional[str] = None
    content: Optional[str] = None


class ResourceOut(BaseModel):
    id: int
    book_id: Optional[int] = None
    book_title: Optional[str] = None
    resource_type: str
    title: str
    content: str
    created_at: datetime

    class Config:
        from_attributes = True


# ---------- Opportunities Hub ----------

class OpportunityCreate(BaseModel):
    opportunity_type: str
    title: str
    description: str
    application_url: Optional[str] = None
    deadline: Optional[date] = None
    organization: Optional[str] = None


class OpportunityUpdate(BaseModel):
    opportunity_type: Optional[str] = None
    title: Optional[str] = None
    description: Optional[str] = None
    application_url: Optional[str] = None
    deadline: Optional[date] = None
    organization: Optional[str] = None


class OpportunityOut(BaseModel):
    id: int
    opportunity_type: str
    title: str
    description: str
    application_url: Optional[str] = None
    deadline: Optional[date] = None
    created_at: datetime
    is_saved: bool = False
    applied: bool = False
    organization: Optional[str] = None
    logo_url: Optional[str] = None  # derived — /api/opportunities/{id}/logo when a logo is uploaded

    class Config:
        from_attributes = True


# ---------- Reading Lists / Shelves ----------

class ReadingListCreate(BaseModel):
    name: str
    description: Optional[str] = None


class ReadingListUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None


class ShelfReorderRequest(BaseModel):
    book_ids_in_order: List[int]


class ReadingListOut(BaseModel):
    id: int
    name: str
    description: Optional[str] = None
    book_count: int = 0
    created_at: datetime

    class Config:
        from_attributes = True


# ---------- Content Reporting ----------

class ReportCreate(BaseModel):
    content_type: str  # review, discussion_post, discussion_reply, user, safety_concern
    content_id: Optional[int] = None  # not required for a general safety_concern report
    reason: str


class SafetyConcernCreate(BaseModel):
    """For unauthenticated visitors — no account needed to flag a safety concern."""
    reason: str
    reporter_email: Optional[EmailStr] = None


class ReportOut(BaseModel):
    id: int
    reporter_id: Optional[int] = None
    reporter_name: str
    content_type: str
    content_id: Optional[int] = None
    reason: str
    status: str
    created_at: datetime
    content_preview: Optional[str] = None  # short snippet of the reported content, if it still exists
    content_author: Optional[str] = None  # name of whoever wrote the reported content
    content_exists: bool = True  # false if the content was already removed/deleted by the time this is read


# ---------- Donations ----------

class DonationAcknowledgmentCreate(BaseModel):
    donor_name: Optional[str] = None
    donor_email: Optional[EmailStr] = None
    amount_naira: Optional[int] = None
    note: Optional[str] = None


class DonationAcknowledgmentOut(BaseModel):
    id: int
    donor_name: Optional[str] = None
    donor_email: Optional[str] = None
    amount_naira: Optional[int] = None
    note: Optional[str] = None
    reviewed: bool
    created_at: datetime

    class Config:
        from_attributes = True

    class Config:
        from_attributes = True


# ---------- Direct Messaging ----------

class ContactOut(BaseModel):
    """Minimal user info for the 'start a new conversation' picker — deliberately
    leaner than UserOut so fellow club members/mentors don't see each other's
    email or phone number just to start a conversation."""
    id: int
    full_name: str
    role: str
    profile_picture: Optional[str] = None

    class Config:
        from_attributes = True


class MessageCreate(BaseModel):
    recipient_id: int
    content: str = Field(..., max_length=4000)


class MessageOut(BaseModel):
    id: int
    sender_id: int
    sender_name: str
    recipient_id: int
    content: str
    is_read: bool
    created_at: datetime

    class Config:
        from_attributes = True


class ConversationOut(BaseModel):
    other_user_id: int
    other_user_name: str
    last_message: str
    last_message_at: datetime
    unread_count: int


# ---------- Audit Log ----------

class AuditLogOut(BaseModel):
    id: int
    actor_id: Optional[int] = None
    actor_name: Optional[str] = None
    action: str
    target_type: str
    target_id: Optional[int] = None
    details: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


# ---------- Password Reset / Email Verification ----------

class PasswordResetRequest(BaseModel):
    email: EmailStr


class PasswordResetConfirm(BaseModel):
    token: str
    new_password: str = Field(min_length=6)


class EmailVerificationConfirm(BaseModel):
    token: str


# ---------- Leaderboard ----------

class LeaderboardEntry(BaseModel):
    user_id: int
    full_name: str
    books_completed: int
    current_streak: int


# ---------- Search ----------

class SearchResults(BaseModel):
    books: List[BookOut]
    discussions: List[DiscussionPostOut]
    resources: List[ResourceOut]


# ---------- Bulk Import ----------

class BulkImportRequest(BaseModel):
    file_content: str


class BulkImportResult(BaseModel):
    created: int
    skipped: int
    errors: List[str]


# ---------- Training Groups ----------

class TrainingGroupCreate(BaseModel):
    name: str
    focus_area: Optional[str] = None
    description: Optional[str] = None


class TrainingGroupUpdate(BaseModel):
    name: Optional[str] = None
    focus_area: Optional[str] = None
    description: Optional[str] = None
    is_active: Optional[bool] = None


class TrainingGroupOut(BaseModel):
    id: int
    name: str
    focus_area: Optional[str] = None
    description: Optional[str] = None
    is_active: bool = True
    member_count: int = 0
    session_count: int = 0
    is_member: bool = False
    is_trainer: bool = False
    created_at: datetime

    class Config:
        from_attributes = True


class TrainingGroupMemberOut(BaseModel):
    user_id: int
    name: str
    is_trainer: bool = False


class TrainingSessionCreate(BaseModel):
    title: str
    description: Optional[str] = None
    session_date: datetime
    duration_minutes: int = 60
    location: Optional[str] = None


class TrainingSessionUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    session_date: Optional[datetime] = None
    duration_minutes: Optional[int] = None
    location: Optional[str] = None


class TrainingSessionOut(BaseModel):
    id: int
    group_id: int
    title: str
    description: Optional[str] = None
    session_date: datetime
    duration_minutes: int = 60
    location: Optional[str] = None
    is_cancelled: bool = False
    resource_count: int = 0
    breakout_count: int = 0
    present_count: int = 0
    my_attendance: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


class TrainingAttendanceMark(BaseModel):
    user_id: int
    status: str = "present"  # present, absent, excused


class TrainingSessionResourceOut(BaseModel):
    id: int
    session_id: int
    title: str
    file_url: Optional[str] = None
    file_original_name: Optional[str] = None
    url: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


class TrainingSessionResourceCreate(BaseModel):
    title: str
    url: Optional[str] = None


class TrainingBreakoutGroupCreate(BaseModel):
    name: str
    notes: Optional[str] = None
    member_ids: List[int] = []


class TrainingBreakoutGroupOut(BaseModel):
    id: int
    session_id: int
    name: str
    notes: Optional[str] = None
    members: List[TrainingGroupMemberOut] = []

    class Config:
        from_attributes = True
