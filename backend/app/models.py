"""
Database models for Gwin's Readers Club.

Upgrade notes (v2 schema):
- Every ForeignKey now declares explicit ON DELETE behavior instead of
  relying on SQLAlchemy/SQLite defaults. "Owning" relationships (a user's
  own favorites, progress, club memberships, session RSVPs, etc.) cascade
  on delete so removing a parent row doesn't leave orphans. "Attribution"
  relationships (who added/hosted/reviewed something) use SET NULL so the
  underlying record survives even if that user is later removed.
  SQLite only enforces this when foreign_keys=ON, which database.py sets
  on every connection.
- Junction/vote/membership tables get a UniqueConstraint so the same
  user can't double-join a club, double-RSVP, double-vote in a poll, etc.
- Rating and percentage fields get a CheckConstraint at the DB level as a
  last line of defense, in addition to whatever the API layer validates.
- users.role and the two backend-driven status machines
  (content_reports.status, mentorship_requests.status) get a
  CheckConstraint too, since those values are fixed and controlled by
  this codebase. Free-form categorization fields (notif_type,
  resource_type, opportunity_type, entry_type, goal_type, session_type,
  certificate_type, discussion category) are deliberately left as plain
  strings — they're open-ended tags, not a closed state machine.
- Composite indexes were added for the query patterns the routers
  actually use (e.g. messages within a session ordered by time,
  notifications for a user filtered by read state).

Because these are structural changes (constraints, not just new
columns), an existing readers_club.db needs to be rebuilt against this
schema — see migrate_db.py.
"""

import uuid
from datetime import datetime, date
from sqlalchemy import (
    Column, Integer, String, Text, Boolean, DateTime, Date, Float,
    ForeignKey, CheckConstraint, UniqueConstraint, Index,
)
from sqlalchemy.orm import relationship
from .database import Base


def _verification_code() -> str:
    """Short, human-typeable code printed on certificates for public verification."""
    return uuid.uuid4().hex[:10].upper()


def _fk(table_col: str, ondelete: str) -> ForeignKey:
    """Shorthand for a ForeignKey with an explicit ON DELETE rule."""
    return ForeignKey(table_col, ondelete=ondelete)


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint(
            "role IN ('admin', 'moderator', 'mentor', 'member')",
            name="ck_users_role_valid",
        ),
        CheckConstraint(
            "age_bracket IS NULL OR age_bracket IN ('Under 13', '13-15', '16-17', '18+')",
            name="ck_users_age_bracket_valid",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    full_name = Column(String, nullable=False)
    email = Column(String, unique=True, index=True, nullable=False)
    password_hash = Column(String, nullable=False)
    phone_number = Column(String, nullable=True)
    school = Column(String, nullable=True)
    department = Column(String, nullable=True)
    state = Column(String, nullable=True)
    country = Column(String, nullable=True, default="Nigeria")
    profile_picture = Column(String, nullable=True)  # staff: uploaded filename under uploads/avatars; member: preset avatar key (e.g. "avatar_female_2")
    biography = Column(Text, nullable=True)
    reading_interests = Column(String, nullable=True)  # comma-separated
    role = Column(String, nullable=False, default="member", index=True)  # admin, moderator, mentor, member
    email_verified = Column(Boolean, default=True)  # default true so existing/demo accounts aren't blocked
    is_active = Column(Boolean, default=True, index=True)  # self-service deactivation (distinct from admin removal)

    # --- Child-safety / safeguarding fields ---
    # Self-declared age band collected at registration. Not a strict legal age
    # verification (this app has no ID-check capability), but it drives the
    # guardian-consent requirement below and lets moderators see who may be a
    # minor at a glance.
    age_bracket = Column(String, nullable=True)  # "Under 13", "13-15", "16-17", "18+"
    guardian_name = Column(String, nullable=True)
    guardian_email = Column(String, nullable=True)
    guardian_consent = Column(Boolean, default=False)
    guardian_consent_at = Column(DateTime, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=True, onupdate=datetime.utcnow)

    favorites = relationship("Favorite", back_populates="user", cascade="all, delete-orphan")
    progress_entries = relationship("ReadingProgress", back_populates="user", cascade="all, delete-orphan")
    reviews = relationship("Review", back_populates="user", cascade="all, delete-orphan")
    journal_entries = relationship("JournalEntry", back_populates="user", cascade="all, delete-orphan")
    streak = relationship("ReadingStreak", back_populates="user", uselist=False, cascade="all, delete-orphan")
    goals = relationship("ReadingGoal", back_populates="user", cascade="all, delete-orphan")
    certificates = relationship("Certificate", back_populates="user", cascade="all, delete-orphan")
    notifications = relationship("Notification", back_populates="user", cascade="all, delete-orphan")
    mentor_profile = relationship("MentorProfile", back_populates="user", uselist=False, cascade="all, delete-orphan")


class Book(Base):
    __tablename__ = "books"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'approved', 'rejected')",
            name="ck_books_status_valid",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, nullable=False, index=True)
    author = Column(String, nullable=False, index=True)
    publisher = Column(String, nullable=True)
    description = Column(Text, nullable=True)
    category = Column(String, nullable=False, index=True)
    language = Column(String, default="English")
    number_of_pages = Column(Integer, default=0)
    reading_time_minutes = Column(Integer, default=0)
    publication_year = Column(Integer, nullable=True)
    cover_color = Column(String, default="#4b2e83")  # placeholder cover styling
    cover_image = Column(String, nullable=True)  # path to an uploaded cover image, if any
    content = Column(Text, nullable=True)  # plain-text body for the online reader
    file_path = Column(String, nullable=True)  # path to the original uploaded book file
    file_format = Column(String, nullable=True)  # pdf, epub, docx, txt
    file_original_name = Column(String, nullable=True)
    is_featured = Column(Boolean, default=False, index=True)
    # Books added via the staff/admin CRUD default straight to "approved" (no
    # change in behavior there). Member self-uploads (library_router's
    # /books/submit) set this to "pending" instead, so the book stays out of
    # public browsing/search until a moderator approves it from the admin
    # queue. "rejected" keeps the record (with rejection_reason) so the
    # submitter can see why, rather than the book silently disappearing.
    status = Column(String, default="approved", index=True)  # pending, approved, rejected
    rejection_reason = Column(Text, nullable=True)
    added_by = Column(Integer, _fk("users.id", "SET NULL"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, nullable=True, onupdate=datetime.utcnow)
    view_count = Column(Integer, default=0, index=True)

    reviews = relationship("Review", back_populates="book", cascade="all, delete-orphan")


class Category(Base):
    __tablename__ = "categories"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False, unique=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class Favorite(Base):
    __tablename__ = "favorites"
    __table_args__ = (
        UniqueConstraint("user_id", "book_id", name="uq_favorites_user_book"),
    )

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, _fk("users.id", "CASCADE"), nullable=False, index=True)
    book_id = Column(Integer, _fk("books.id", "CASCADE"), nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="favorites")


class ReadingProgress(Base):
    __tablename__ = "reading_progress"
    __table_args__ = (
        UniqueConstraint("user_id", "book_id", name="uq_progress_user_book"),
        CheckConstraint(
            "percent_complete >= 0 AND percent_complete <= 100",
            name="ck_progress_percent_range",
        ),
        Index("ix_progress_user_status", "user_id", "status"),
    )

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, _fk("users.id", "CASCADE"), nullable=False, index=True)
    book_id = Column(Integer, _fk("books.id", "CASCADE"), nullable=False, index=True)
    percent_complete = Column(Float, default=0.0)
    current_position = Column(Integer, default=0)  # character offset in content
    status = Column(String, default="reading")  # reading, completed
    started_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)
    last_read_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="progress_entries")
    book = relationship("Book")


class Bookmark(Base):
    __tablename__ = "bookmarks"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, _fk("users.id", "CASCADE"), nullable=False, index=True)
    book_id = Column(Integer, _fk("books.id", "CASCADE"), nullable=False, index=True)
    position = Column(Integer, default=0)
    label = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class Highlight(Base):
    __tablename__ = "highlights"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, _fk("users.id", "CASCADE"), nullable=False, index=True)
    book_id = Column(Integer, _fk("books.id", "CASCADE"), nullable=False, index=True)
    quoted_text = Column(Text, nullable=False)
    note = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class BookOfMonth(Base):
    __tablename__ = "book_of_month"
    __table_args__ = (
        UniqueConstraint("month", "year", name="uq_book_of_month_period"),
    )

    id = Column(Integer, primary_key=True, index=True)
    book_id = Column(Integer, _fk("books.id", "CASCADE"), nullable=False, index=True)
    month = Column(Integer, nullable=False)
    year = Column(Integer, nullable=False)
    reading_guide = Column(Text, nullable=True)
    discussion_questions = Column(Text, nullable=True)  # newline-separated
    start_date = Column(Date, default=date.today)
    is_active = Column(Boolean, default=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    book = relationship("Book")


class Review(Base):
    __tablename__ = "reviews"
    __table_args__ = (
        CheckConstraint("rating >= 1 AND rating <= 5", name="ck_reviews_rating_range"),
        Index("ix_reviews_book_approved", "book_id", "is_approved"),
    )

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, _fk("users.id", "CASCADE"), nullable=False, index=True)
    book_id = Column(Integer, _fk("books.id", "CASCADE"), nullable=False, index=True)
    rating = Column(Integer, nullable=False)  # 1-5
    lessons_learned = Column(Text, nullable=True)
    review_text = Column(Text, nullable=False)
    is_approved = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=True, onupdate=datetime.utcnow)

    user = relationship("User", back_populates="reviews")
    book = relationship("Book", back_populates="reviews")
    comments = relationship("ReviewComment", back_populates="review", cascade="all, delete-orphan")


class ReviewHelpfulVote(Base):
    __tablename__ = "review_helpful_votes"
    __table_args__ = (
        UniqueConstraint("review_id", "user_id", name="uq_review_helpful_vote"),
    )

    id = Column(Integer, primary_key=True, index=True)
    review_id = Column(Integer, _fk("reviews.id", "CASCADE"), nullable=False, index=True)
    user_id = Column(Integer, _fk("users.id", "CASCADE"), nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class ReviewComment(Base):
    __tablename__ = "review_comments"

    id = Column(Integer, primary_key=True, index=True)
    review_id = Column(Integer, _fk("reviews.id", "CASCADE"), nullable=False, index=True)
    user_id = Column(Integer, _fk("users.id", "CASCADE"), nullable=False, index=True)
    content = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    review = relationship("Review", back_populates="comments")


class DiscussionPost(Base):
    __tablename__ = "discussion_posts"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, _fk("users.id", "CASCADE"), nullable=False, index=True)
    category = Column(String, default="general", index=True)  # general, book, topic, qna, announcement
    book_id = Column(Integer, _fk("books.id", "SET NULL"), nullable=True)
    title = Column(String, nullable=False)
    content = Column(Text, nullable=False)
    is_pinned = Column(Boolean, default=False)
    is_removed = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, nullable=True, onupdate=datetime.utcnow)

    replies = relationship("DiscussionReply", back_populates="post", cascade="all, delete-orphan")


class DiscussionReply(Base):
    __tablename__ = "discussion_replies"
    __table_args__ = (
        Index("ix_discussion_replies_post_created", "post_id", "created_at"),
    )

    id = Column(Integer, primary_key=True, index=True)
    post_id = Column(Integer, _fk("discussion_posts.id", "CASCADE"), nullable=False, index=True)
    user_id = Column(Integer, _fk("users.id", "CASCADE"), nullable=False, index=True)
    parent_reply_id = Column(Integer, _fk("discussion_replies.id", "CASCADE"), nullable=True)  # nested threading
    content = Column(Text, nullable=False)
    is_removed = Column(Boolean, default=False)
    is_edited = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=True, onupdate=datetime.utcnow)

    post = relationship("DiscussionPost", back_populates="replies")


class JournalEntry(Base):
    __tablename__ = "journal_entries"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, _fk("users.id", "CASCADE"), nullable=False, index=True)
    book_id = Column(Integer, _fk("books.id", "SET NULL"), nullable=True)
    entry_type = Column(String, default="reflection", index=True)
    # reflection, note, quote, prayer, action_plan, weekly_reflection
    content = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=True, onupdate=datetime.utcnow)

    user = relationship("User", back_populates="journal_entries")


class ReadingStreak(Base):
    __tablename__ = "reading_streaks"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, _fk("users.id", "CASCADE"), unique=True, nullable=False, index=True)
    current_streak = Column(Integer, default=0)
    longest_streak = Column(Integer, default=0)
    last_read_date = Column(Date, nullable=True)

    user = relationship("User", back_populates="streak")


class ReadingGoal(Base):
    __tablename__ = "reading_goals"
    __table_args__ = (
        Index("ix_reading_goals_user_period", "user_id", "year", "month"),
    )

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, _fk("users.id", "CASCADE"), nullable=False, index=True)
    goal_type = Column(String, default="monthly")  # monthly, annual
    target_books = Column(Integer, nullable=False)
    year = Column(Integer, nullable=False)
    month = Column(Integer, nullable=True)
    books_completed = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="goals")


class Challenge(Base):
    __tablename__ = "challenges"
    __table_args__ = (
        Index("ix_challenges_dates", "start_date", "end_date"),
    )

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    start_date = Column(Date, nullable=False)
    end_date = Column(Date, nullable=False)
    target_books = Column(Integer, default=1)
    created_at = Column(DateTime, default=datetime.utcnow)


class ChallengeParticipant(Base):
    __tablename__ = "challenge_participants"
    __table_args__ = (
        UniqueConstraint("challenge_id", "user_id", name="uq_challenge_participant"),
    )

    id = Column(Integer, primary_key=True, index=True)
    challenge_id = Column(Integer, _fk("challenges.id", "CASCADE"), nullable=False, index=True)
    user_id = Column(Integer, _fk("users.id", "CASCADE"), nullable=False, index=True)
    books_completed = Column(Integer, default=0)
    is_completed = Column(Boolean, default=False)
    joined_at = Column(DateTime, default=datetime.utcnow)


class Certificate(Base):
    __tablename__ = "certificates"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, _fk("users.id", "CASCADE"), nullable=False, index=True)
    certificate_type = Column(String, nullable=False, index=True)
    # book_of_month, challenge, discussion, annual_goal
    title = Column(String, nullable=False)
    related_id = Column(Integer, nullable=True)
    issued_at = Column(DateTime, default=datetime.utcnow)
    revoked = Column(Boolean, default=False)
    revoked_reason = Column(String, nullable=True)
    # Printed on the certificate (as text + QR code) so anyone can confirm on
    # the public /verify.html page that a certificate is genuine and current.
    verification_code = Column(String, unique=True, index=True, default=_verification_code)

    user = relationship("User", back_populates="certificates")


class Notification(Base):
    __tablename__ = "notifications"
    __table_args__ = (
        Index("ix_notifications_user_read", "user_id", "is_read"),
    )

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, _fk("users.id", "CASCADE"), nullable=False, index=True)
    notif_type = Column(String, default="general")
    message = Column(String, nullable=False)
    is_read = Column(Boolean, default=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="notifications")


# ---------- Campus Reading Clubs ----------

class ReadingClub(Base):
    __tablename__ = "reading_clubs"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    school_or_org = Column(String, nullable=True)
    description = Column(Text, nullable=True)
    created_by = Column(Integer, _fk("users.id", "SET NULL"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class ClubMembership(Base):
    __tablename__ = "club_memberships"
    __table_args__ = (
        UniqueConstraint("club_id", "user_id", name="uq_club_membership"),
    )

    id = Column(Integer, primary_key=True, index=True)
    club_id = Column(Integer, _fk("reading_clubs.id", "CASCADE"), nullable=False, index=True)
    user_id = Column(Integer, _fk("users.id", "CASCADE"), nullable=False, index=True)
    is_leader = Column(Boolean, default=False)
    joined_at = Column(DateTime, default=datetime.utcnow)


class ClubEvent(Base):
    __tablename__ = "club_events"

    id = Column(Integer, primary_key=True, index=True)
    club_id = Column(Integer, _fk("reading_clubs.id", "CASCADE"), nullable=False, index=True)
    title = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    event_date = Column(DateTime, nullable=False, index=True)
    is_cancelled = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class ClubEventRSVP(Base):
    __tablename__ = "club_event_rsvps"
    __table_args__ = (
        UniqueConstraint("event_id", "user_id", name="uq_club_event_rsvp"),
    )

    id = Column(Integer, primary_key=True, index=True)
    event_id = Column(Integer, _fk("club_events.id", "CASCADE"), nullable=False, index=True)
    user_id = Column(Integer, _fk("users.id", "CASCADE"), nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)


# ---------- Mentorship ----------

class MentorProfile(Base):
    __tablename__ = "mentor_profiles"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, _fk("users.id", "CASCADE"), unique=True, nullable=False, index=True)
    specialties = Column(String, nullable=True)  # comma-separated
    bio = Column(Text, nullable=True)
    is_accepting_mentees = Column(Boolean, default=True, index=True)

    user = relationship("User", back_populates="mentor_profile")


class MentorshipRequest(Base):
    __tablename__ = "mentorship_requests"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'accepted', 'declined', 'ended')",
            name="ck_mentorship_status_valid",
        ),
        Index("ix_mentorship_mentor_status", "mentor_id", "status"),
        Index("ix_mentorship_mentee_status", "mentee_id", "status"),
    )

    id = Column(Integer, primary_key=True, index=True)
    mentor_id = Column(Integer, _fk("users.id", "CASCADE"), nullable=False, index=True)
    mentee_id = Column(Integer, _fk("users.id", "CASCADE"), nullable=False, index=True)
    status = Column(String, default="pending")  # pending, accepted, declined, ended
    requested_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=True, onupdate=datetime.utcnow)


class MentorRating(Base):
    __tablename__ = "mentor_ratings"
    __table_args__ = (
        CheckConstraint("rating >= 1 AND rating <= 5", name="ck_mentor_rating_range"),
    )

    id = Column(Integer, primary_key=True, index=True)
    mentorship_id = Column(Integer, _fk("mentorship_requests.id", "CASCADE"), unique=True, nullable=False, index=True)
    mentor_id = Column(Integer, _fk("users.id", "CASCADE"), nullable=False, index=True)
    mentee_id = Column(Integer, _fk("users.id", "CASCADE"), nullable=False, index=True)
    rating = Column(Integer, nullable=False)  # 1-5
    review_text = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class MentorQuestion(Base):
    __tablename__ = "mentor_questions"

    id = Column(Integer, primary_key=True, index=True)
    mentorship_id = Column(Integer, _fk("mentorship_requests.id", "CASCADE"), nullable=False, index=True)
    asked_by = Column(Integer, _fk("users.id", "CASCADE"), nullable=False, index=True)
    question = Column(Text, nullable=False)
    answer = Column(Text, nullable=True)
    answered_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


# ---------- Live Discussions (polling-based, no websockets) ----------

class LiveSession(Base):
    __tablename__ = "live_sessions"
    __table_args__ = (
        Index("ix_live_sessions_scheduled_active", "scheduled_at", "is_active"),
    )

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, nullable=False)
    session_type = Column(String, default="live_chat")  # live_chat, audio, webinar, author_interview
    host_id = Column(Integer, _fk("users.id", "SET NULL"), nullable=True)
    description = Column(Text, nullable=True)
    scheduled_at = Column(DateTime, nullable=False, index=True)
    duration_minutes = Column(Integer, default=60)
    is_active = Column(Boolean, default=True, index=True)
    is_cancelled = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=True, onupdate=datetime.utcnow)

    # ---- broadcast/session enhancements ----
    category = Column(String, nullable=True)  # free-form topic tag, e.g. "African Literature"
    book_id = Column(Integer, _fk("books.id", "SET NULL"), nullable=True)  # tie a session to a specific book
    max_capacity = Column(Integer, nullable=True)  # None = unlimited
    recurrence = Column(String, nullable=True)  # none, weekly, biweekly, monthly
    slow_mode_seconds = Column(Integer, default=0)  # min seconds between a user's messages
    announcement_only = Column(Boolean, default=False)  # only host/co-hosts can post
    attendee_list_public = Column(Boolean, default=True)
    recording_notes = Column(Text, nullable=True)  # host's post-session summary
    is_featured = Column(Boolean, default=False)
    ended_at = Column(DateTime, nullable=True)  # set when host ends session early or it's swept as ended
    parent_session_id = Column(Integer, _fk("live_sessions.id", "SET NULL"), nullable=True)  # recurrence/duplicate lineage


class LiveSessionRSVP(Base):
    __tablename__ = "live_session_rsvps"
    __table_args__ = (
        UniqueConstraint("session_id", "user_id", name="uq_live_session_rsvp"),
    )

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(Integer, _fk("live_sessions.id", "CASCADE"), nullable=False, index=True)
    user_id = Column(Integer, _fk("users.id", "CASCADE"), nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class LiveSessionWaitlist(Base):
    __tablename__ = "live_session_waitlist"
    __table_args__ = (
        UniqueConstraint("session_id", "user_id", name="uq_live_session_waitlist"),
    )

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(Integer, _fk("live_sessions.id", "CASCADE"), nullable=False, index=True)
    user_id = Column(Integer, _fk("users.id", "CASCADE"), nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class LiveSessionCoHost(Base):
    __tablename__ = "live_session_cohosts"
    __table_args__ = (
        UniqueConstraint("session_id", "user_id", name="uq_live_session_cohost"),
    )

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(Integer, _fk("live_sessions.id", "CASCADE"), nullable=False, index=True)
    user_id = Column(Integer, _fk("users.id", "CASCADE"), nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class LiveSessionMute(Base):
    __tablename__ = "live_session_mutes"
    __table_args__ = (
        UniqueConstraint("session_id", "user_id", name="uq_live_session_mute"),
    )

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(Integer, _fk("live_sessions.id", "CASCADE"), nullable=False, index=True)
    user_id = Column(Integer, _fk("users.id", "CASCADE"), nullable=False, index=True)
    muted_by = Column(Integer, _fk("users.id", "SET NULL"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class LiveSessionBan(Base):
    __tablename__ = "live_session_bans"
    __table_args__ = (
        UniqueConstraint("session_id", "user_id", name="uq_live_session_ban"),
    )

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(Integer, _fk("live_sessions.id", "CASCADE"), nullable=False, index=True)
    user_id = Column(Integer, _fk("users.id", "CASCADE"), nullable=False, index=True)
    banned_by = Column(Integer, _fk("users.id", "SET NULL"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class LiveSessionResource(Base):
    __tablename__ = "live_session_resources"

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(Integer, _fk("live_sessions.id", "CASCADE"), nullable=False, index=True)
    title = Column(String, nullable=False)
    url = Column(String, nullable=False)
    added_by = Column(Integer, _fk("users.id", "SET NULL"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class LiveSessionRating(Base):
    __tablename__ = "live_session_ratings"
    __table_args__ = (
        UniqueConstraint("session_id", "user_id", name="uq_live_session_rating"),
        CheckConstraint("rating >= 1 AND rating <= 5", name="ck_live_session_rating_range"),
    )

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(Integer, _fk("live_sessions.id", "CASCADE"), nullable=False, index=True)
    user_id = Column(Integer, _fk("users.id", "CASCADE"), nullable=False, index=True)
    rating = Column(Integer, nullable=False)  # 1-5
    comment = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class LiveSessionPresence(Base):
    """Lightweight heartbeat table used for live viewer counts and typing indicators."""
    __tablename__ = "live_session_presence"
    __table_args__ = (
        UniqueConstraint("session_id", "user_id", name="uq_live_session_presence"),
    )

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(Integer, _fk("live_sessions.id", "CASCADE"), nullable=False, index=True)
    user_id = Column(Integer, _fk("users.id", "CASCADE"), nullable=False, index=True)
    is_typing = Column(Boolean, default=False)
    last_seen = Column(DateTime, default=datetime.utcnow)


class LiveSessionPoll(Base):
    __tablename__ = "live_session_polls"

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(Integer, _fk("live_sessions.id", "CASCADE"), nullable=False, index=True)
    question = Column(String, nullable=False)
    created_by = Column(Integer, _fk("users.id", "SET NULL"), nullable=True)
    is_closed = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class LiveSessionPollOption(Base):
    __tablename__ = "live_session_poll_options"

    id = Column(Integer, primary_key=True, index=True)
    poll_id = Column(Integer, _fk("live_session_polls.id", "CASCADE"), nullable=False, index=True)
    text = Column(String, nullable=False)
    order = Column(Integer, default=0)


class LiveSessionPollVote(Base):
    __tablename__ = "live_session_poll_votes"
    __table_args__ = (
        UniqueConstraint("poll_id", "user_id", name="uq_live_session_poll_vote"),
    )

    id = Column(Integer, primary_key=True, index=True)
    poll_id = Column(Integer, _fk("live_session_polls.id", "CASCADE"), nullable=False, index=True)
    option_id = Column(Integer, _fk("live_session_poll_options.id", "CASCADE"), nullable=False, index=True)
    user_id = Column(Integer, _fk("users.id", "CASCADE"), nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class LiveSessionQuestion(Base):
    """Structured Q&A queue, separate from free-flowing chat."""
    __tablename__ = "live_session_questions"

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(Integer, _fk("live_sessions.id", "CASCADE"), nullable=False, index=True)
    user_id = Column(Integer, _fk("users.id", "CASCADE"), nullable=False, index=True)
    question = Column(Text, nullable=False)
    answer = Column(Text, nullable=True)
    is_answered = Column(Boolean, default=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class LiveSessionQuestionUpvote(Base):
    __tablename__ = "live_session_question_upvotes"
    __table_args__ = (
        UniqueConstraint("question_id", "user_id", name="uq_live_session_question_upvote"),
    )

    id = Column(Integer, primary_key=True, index=True)
    question_id = Column(Integer, _fk("live_session_questions.id", "CASCADE"), nullable=False, index=True)
    user_id = Column(Integer, _fk("users.id", "CASCADE"), nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class LiveMessage(Base):
    __tablename__ = "live_messages"
    __table_args__ = (
        Index("ix_live_messages_session_created", "session_id", "created_at"),
    )

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(Integer, _fk("live_sessions.id", "CASCADE"), nullable=False, index=True)
    user_id = Column(Integer, _fk("users.id", "SET NULL"), nullable=True)  # null = auto-generated system message
    content = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    # ---- chat enhancements ----
    reply_to_id = Column(Integer, _fk("live_messages.id", "SET NULL"), nullable=True)
    is_pinned = Column(Boolean, default=False)
    is_deleted = Column(Boolean, default=False)
    is_system = Column(Boolean, default=False)  # auto-generated join/leave/session-status messages
    edited_at = Column(DateTime, nullable=True)


class LiveMessageReaction(Base):
    __tablename__ = "live_message_reactions"
    __table_args__ = (
        UniqueConstraint("message_id", "user_id", "emoji", name="uq_live_message_reaction"),
    )

    id = Column(Integer, primary_key=True, index=True)
    message_id = Column(Integer, _fk("live_messages.id", "CASCADE"), nullable=False, index=True)
    user_id = Column(Integer, _fk("users.id", "CASCADE"), nullable=False, index=True)
    emoji = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


# ---------- Reading Resources ----------

class ReadingResource(Base):
    __tablename__ = "reading_resources"
    __table_args__ = (
        Index("ix_reading_resources_book_type", "book_id", "resource_type"),
    )

    id = Column(Integer, primary_key=True, index=True)
    book_id = Column(Integer, _fk("books.id", "SET NULL"), nullable=True)  # null = general resource
    resource_type = Column(String, nullable=False)
    # chapter_summary, study_guide, vocabulary_list, author_bio, reading_guide, discussion_guide
    title = Column(String, nullable=False)
    content = Column(Text, nullable=False)
    added_by = Column(Integer, _fk("users.id", "SET NULL"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


# ---------- Opportunities Hub ----------

class Opportunity(Base):
    __tablename__ = "opportunities"
    __table_args__ = (
        Index("ix_opportunities_type_deadline", "opportunity_type", "deadline"),
    )

    id = Column(Integer, primary_key=True, index=True)
    opportunity_type = Column(String, nullable=False, index=True)
    # scholarship, internship, competition, essay_contest, conference, leadership_program, volunteer
    title = Column(String, nullable=False)
    description = Column(Text, nullable=False)
    application_url = Column(String, nullable=True)
    deadline = Column(Date, nullable=True, index=True)
    posted_by = Column(Integer, _fk("users.id", "SET NULL"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    logo_image = Column(String, nullable=True)  # path to an uploaded logo/cover image, if any
    organization = Column(String, nullable=True)  # e.g. "MTN Foundation" — shown under the title


class SavedOpportunity(Base):
    __tablename__ = "saved_opportunities"
    __table_args__ = (
        UniqueConstraint("user_id", "opportunity_id", name="uq_saved_opportunity"),
    )

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, _fk("users.id", "CASCADE"), nullable=False, index=True)
    opportunity_id = Column(Integer, _fk("opportunities.id", "CASCADE"), nullable=False, index=True)
    applied = Column(Boolean, default=False)
    saved_at = Column(DateTime, default=datetime.utcnow)


# ---------- Custom Reading Lists / Shelves ----------

class ReadingList(Base):
    __tablename__ = "reading_lists"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, _fk("users.id", "CASCADE"), nullable=False, index=True)
    name = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class ReadingListItem(Base):
    __tablename__ = "reading_list_items"
    __table_args__ = (
        UniqueConstraint("list_id", "book_id", name="uq_reading_list_item"),
    )

    id = Column(Integer, primary_key=True, index=True)
    list_id = Column(Integer, _fk("reading_lists.id", "CASCADE"), nullable=False, index=True)
    book_id = Column(Integer, _fk("books.id", "CASCADE"), nullable=False, index=True)
    position = Column(Integer, default=0)
    added_at = Column(DateTime, default=datetime.utcnow)


# ---------- Content Reporting / Moderation Queue ----------

class ContentReport(Base):
    __tablename__ = "content_reports"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'reviewed', 'dismissed')",
            name="ck_content_report_status_valid",
        ),
        Index("ix_content_reports_type_target", "content_type", "content_id"),
    )

    id = Column(Integer, primary_key=True, index=True)
    # Nullable so an unauthenticated visitor can file a general safety_concern
    # report without an account — everything else (reviews, discussions, etc.)
    # still requires a logged-in reporter_id via the API layer.
    reporter_id = Column(Integer, _fk("users.id", "CASCADE"), nullable=True, index=True)
    reporter_email = Column(String, nullable=True)  # contact for anonymous safety_concern reports only
    content_type = Column(String, nullable=False)  # review, discussion_post, discussion_reply, user, safety_concern
    content_id = Column(Integer, nullable=True)
    reason = Column(Text, nullable=False)
    status = Column(String, default="pending", index=True)  # pending, reviewed, dismissed
    reviewed_by = Column(Integer, _fk("users.id", "SET NULL"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=True, onupdate=datetime.utcnow)


# ---------- Direct Messaging ----------

class DirectMessage(Base):
    __tablename__ = "direct_messages"
    __table_args__ = (
        Index("ix_direct_messages_recipient_read", "recipient_id", "is_read"),
        Index("ix_direct_messages_thread", "sender_id", "recipient_id", "created_at"),
    )

    id = Column(Integer, primary_key=True, index=True)
    sender_id = Column(Integer, _fk("users.id", "CASCADE"), nullable=False, index=True)
    recipient_id = Column(Integer, _fk("users.id", "CASCADE"), nullable=False, index=True)
    content = Column(Text, nullable=False)
    is_read = Column(Boolean, default=False)
    deleted_by_sender = Column(Boolean, default=False)
    deleted_by_recipient = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class NotificationPreference(Base):
    __tablename__ = "notification_preferences"
    __table_args__ = (
        UniqueConstraint("user_id", "category", name="uq_notification_preference"),
    )

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, _fk("users.id", "CASCADE"), nullable=False, index=True)
    category = Column(String, nullable=False)  # matches notif_type, e.g. announcement, mentorship, club
    muted = Column(Boolean, default=False)


# ---------- Admin Audit Log ----------

class AuditLog(Base):
    __tablename__ = "audit_logs"
    __table_args__ = (
        Index("ix_audit_logs_target", "target_type", "target_id"),
    )

    id = Column(Integer, primary_key=True, index=True)
    actor_id = Column(Integer, _fk("users.id", "SET NULL"), nullable=True)
    action = Column(String, nullable=False, index=True)  # e.g. user.role_change, discussion.remove
    target_type = Column(String, nullable=False)
    target_id = Column(Integer, nullable=True)
    details = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)


# ---------- Book Reactions (lightweight emoji reactions, visible to everyone) ----------

class BookReaction(Base):
    __tablename__ = "book_reactions"
    __table_args__ = (
        UniqueConstraint("book_id", "user_id", name="uq_book_reaction_user"),
    )

    id = Column(Integer, primary_key=True, index=True)
    book_id = Column(Integer, _fk("books.id", "CASCADE"), nullable=False, index=True)
    user_id = Column(Integer, _fk("users.id", "CASCADE"), nullable=False, index=True)
    emoji = Column(String, nullable=False)  # one of a fixed set, enforced in the router
    created_at = Column(DateTime, default=datetime.utcnow)


# ---------- Auth Tokens (password reset, email verification — dev mode) ----------

class AuthToken(Base):
    __tablename__ = "auth_tokens"
    __table_args__ = (
        Index("ix_auth_tokens_user_type", "user_id", "token_type"),
    )

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, _fk("users.id", "CASCADE"), nullable=False, index=True)
    token = Column(String, unique=True, index=True, nullable=False)
    token_type = Column(String, nullable=False)  # password_reset, email_verification
    expires_at = Column(DateTime, nullable=False)
    used = Column(Boolean, default=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class DonationAcknowledgment(Base):
    """A voluntary, self-reported record that someone (a parent/guardian or
    supporter — never solicited from a child) says they've sent a donation via
    the bank-transfer details shown on the Support page. The app never
    collects or processes card/payment data itself; this is just a courtesy
    note staff can use to say thank you and reconcile against the Opay
    account statement. Anonymous (no login required) so a supporter who
    isn't a member can still let the club know."""
    __tablename__ = "donation_acknowledgments"

    id = Column(Integer, primary_key=True, index=True)
    donor_name = Column(String, nullable=True)
    donor_email = Column(String, nullable=True)
    amount_naira = Column(Integer, nullable=True)  # optional, self-reported
    note = Column(Text, nullable=True)
    reviewed = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)


# ---------- Training Groups ----------
# Standalone groups for pulling specific students together for focused,
# structured training (e.g. a public-speaking cohort, a debate team, exam
# prep) — independent of Reading Club membership. A member can belong to
# any number of reading clubs *and* any number of training groups; the two
# systems don't overlap.

class TrainingGroup(Base):
    __tablename__ = "training_groups"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    focus_area = Column(String, nullable=True)  # e.g. "Public Speaking", "Exam Prep"
    description = Column(Text, nullable=True)
    created_by = Column(Integer, _fk("users.id", "SET NULL"), nullable=True)
    is_active = Column(Boolean, default=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class TrainingGroupMember(Base):
    __tablename__ = "training_group_members"
    __table_args__ = (
        UniqueConstraint("group_id", "user_id", name="uq_training_group_member"),
    )

    id = Column(Integer, primary_key=True, index=True)
    group_id = Column(Integer, _fk("training_groups.id", "CASCADE"), nullable=False, index=True)
    user_id = Column(Integer, _fk("users.id", "CASCADE"), nullable=False, index=True)
    is_trainer = Column(Boolean, default=False)  # trainer/coach vs. trainee
    added_at = Column(DateTime, default=datetime.utcnow)


class TrainingSession(Base):
    """A single scheduled meeting of a training group. A group can have any
    number of sessions (past and future) — this is the "add more sessions"
    building block."""
    __tablename__ = "training_sessions"

    id = Column(Integer, primary_key=True, index=True)
    group_id = Column(Integer, _fk("training_groups.id", "CASCADE"), nullable=False, index=True)
    title = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    session_date = Column(DateTime, nullable=False, index=True)
    duration_minutes = Column(Integer, default=60)
    location = Column(String, nullable=True)  # room name, or a video-call link
    is_cancelled = Column(Boolean, default=False)
    created_by = Column(Integer, _fk("users.id", "SET NULL"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class TrainingSessionAttendance(Base):
    __tablename__ = "training_session_attendance"
    __table_args__ = (
        UniqueConstraint("session_id", "user_id", name="uq_training_attendance"),
    )

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(Integer, _fk("training_sessions.id", "CASCADE"), nullable=False, index=True)
    user_id = Column(Integer, _fk("users.id", "CASCADE"), nullable=False, index=True)
    status = Column(String, default="present")  # present, absent, excused
    marked_by = Column(Integer, _fk("users.id", "SET NULL"), nullable=True)
    marked_at = Column(DateTime, default=datetime.utcnow)


class TrainingSessionResource(Base):
    """Materials attached to a session — either an uploaded file or a link."""
    __tablename__ = "training_session_resources"

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(Integer, _fk("training_sessions.id", "CASCADE"), nullable=False, index=True)
    title = Column(String, nullable=False)
    file_path = Column(String, nullable=True)
    file_original_name = Column(String, nullable=True)
    url = Column(String, nullable=True)  # external link, used when no file is uploaded
    added_by = Column(Integer, _fk("users.id", "SET NULL"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class TrainingBreakoutGroup(Base):
    """A smaller sub-group within one session, for split-group activities."""
    __tablename__ = "training_breakout_groups"

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(Integer, _fk("training_sessions.id", "CASCADE"), nullable=False, index=True)
    name = Column(String, nullable=False)
    notes = Column(Text, nullable=True)  # instructions/task for this breakout group
    created_at = Column(DateTime, default=datetime.utcnow)


class TrainingBreakoutMember(Base):
    __tablename__ = "training_breakout_members"
    __table_args__ = (
        UniqueConstraint("breakout_group_id", "user_id", name="uq_training_breakout_member"),
    )

    id = Column(Integer, primary_key=True, index=True)
    breakout_group_id = Column(Integer, _fk("training_breakout_groups.id", "CASCADE"), nullable=False, index=True)
    user_id = Column(Integer, _fk("users.id", "CASCADE"), nullable=False, index=True)
