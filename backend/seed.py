"""
Seed demo data for Gwin's Readers Club.
Run with: python seed.py  (from the backend/ directory, venv active)
"""
import sys
import os
from datetime import date, datetime, timedelta

sys.path.insert(0, os.path.dirname(__file__))

from app.database import SessionLocal, engine, Base
from app import models
from app.auth import hash_password

Base.metadata.create_all(bind=engine)
db = SessionLocal()

print("Seeding Gwin's Readers Club demo data...")

if db.query(models.User).filter(models.User.email == "admin@readersclub.ng").first():
    print("Demo data already present. Skipping.")
    db.close()
    sys.exit(0)

# ---------- Users ----------
admin = models.User(
    full_name="Amaka Okafor", email="admin@readersclub.ng",
    password_hash=hash_password("admin123"), role="admin",
    school="Readers Club HQ", state="Lagos", country="Nigeria",
    biography="Platform administrator for Gwin's Readers Club.",
)
moderator = models.User(
    full_name="Tunde Bakare", email="mod@readersclub.ng",
    password_hash=hash_password("mod12345"), role="moderator",
    state="Oyo", country="Nigeria",
)
mentor = models.User(
    full_name="Dr. Ifeoma Nwosu", email="mentor@readersclub.ng",
    password_hash=hash_password("mentor123"), role="mentor",
    biography="Literature lecturer and reading mentor.", state="Enugu",
)
member1 = models.User(
    full_name="Chidinma Eze", email="chidinma@example.com",
    password_hash=hash_password("member123"), role="member",
    school="University of Lagos", department="Mass Communication",
    state="Lagos", reading_interests="African Literature,Personal Development,Fiction",
)
member2 = models.User(
    full_name="Samuel Adeyemi", email="samuel@example.com",
    password_hash=hash_password("member123"), role="member",
    school="Covenant University", department="Computer Science",
    state="Ogun", reading_interests="Technology,Entrepreneurship,Business",
)

# Simple, clearly-labeled test accounts (one per role) — easiest set to use
# when just testing role-based privileges rather than exploring seeded content.
test_admin = models.User(
    full_name="Test Admin", email="testadmin@readersclub.ng",
    password_hash=hash_password("Test1234"), role="admin",
)
test_moderator = models.User(
    full_name="Test Moderator", email="testmoderator@readersclub.ng",
    password_hash=hash_password("Test1234"), role="moderator",
)
test_mentor = models.User(
    full_name="Test Mentor", email="testmentor@readersclub.ng",
    password_hash=hash_password("Test1234"), role="mentor",
)
test_user = models.User(
    full_name="Test User", email="testuser@readersclub.ng",
    password_hash=hash_password("Test1234"), role="member",
)

all_seed_users = (admin, moderator, mentor, member1, member2, test_admin, test_moderator, test_mentor, test_user)

for u in all_seed_users:
    db.add(u)
db.commit()
for u in all_seed_users:
    db.refresh(u)
    db.add(models.ReadingStreak(user_id=u.id, current_streak=0, longest_streak=0))
db.commit()

# ---------- Books ----------
books_data = [
    dict(
        title="Things Fall Apart", author="Chinua Achebe", publisher="Heinemann",
        category="African Literature", publication_year=1958, number_of_pages=209,
        reading_time_minutes=300, cover_color="#8c3b2e",
        description="A landmark novel following Okonkwo, a respected Igbo leader, as colonial forces reshape his world.",
        content=(
            "Okonkwo was well known throughout the nine villages and even beyond. His fame rested on solid "
            "personal achievements. As a young man of eighteen he had brought honour to his village by throwing "
            "Amalinze the Cat...\n\n"
            "Chapter Two\n\n"
            "As Okonkwo lay on his bamboo bed he thought about the ceremony of the ozo, and about how the world "
            "he knew was slowly changing around him..."
        ),
        is_featured=True,
    ),
    dict(
        title="The Lean Startup", author="Eric Ries", publisher="Crown Business",
        category="Entrepreneurship", publication_year=2011, number_of_pages=336,
        reading_time_minutes=420, cover_color="#2e6b4f",
        description="A methodology for developing businesses and products through validated learning and rapid iteration.",
        content=(
            "The Lean Startup method has been developed to help entrepreneurs increase their odds of building a "
            "successful venture. It is a principle that could be adopted by any entrepreneur, anywhere...\n\n"
            "Chapter One: Start\n\n"
            "Entrepreneurship is management. Startups need a specific kind of management tuned to the context of "
            "extreme uncertainty in which they operate."
        ),
    ),
    dict(
        title="Atomic Habits", author="James Clear", publisher="Penguin",
        category="Personal Development", publication_year=2018, number_of_pages=320,
        reading_time_minutes=390, cover_color="#c47f17",
        description="A practical guide to building good habits and breaking bad ones, one small change at a time.",
        content=(
            "Habits are the compound interest of self-improvement. The same way that money multiplies through "
            "compound interest, the effects of your habits multiply as you repeat them...\n\n"
            "Chapter 1: The Surprising Power of Atomic Habits\n\n"
            "It is so easy to overestimate the importance of one defining moment and underestimate the value of "
            "making small improvements on a daily basis."
        ),
        is_featured=True,
    ),
    dict(
        title="Half of a Yellow Sun", author="Chimamanda Ngozi Adichie", publisher="Farafina",
        category="African Literature", publication_year=2006, number_of_pages=433,
        reading_time_minutes=520, cover_color="#b8860b",
        description="A powerful story of five characters caught in the events of the Nigeria-Biafra war.",
        content=(
            "Master was a little crazy; he had spent too many years reading books overseas, talked to himself in "
            "his office, did not always return greetings, and had too much hair...\n\n"
            "Part One: The Early Sixties\n\n"
            "Ugwu did not know what to think of Master's rambling..."
        ),
    ),
    dict(
        title="Rich Dad Poor Dad", author="Robert Kiyosaki", publisher="Plata Publishing",
        category="Finance", publication_year=1997, number_of_pages=336,
        reading_time_minutes=400, cover_color="#1f6f6f",
        description="Contrasting lessons on money from two father figures, and why financial literacy matters more than income.",
        content=(
            "The poor and the middle class work for money. The rich have money work for them...\n\n"
            "Lesson One: The Rich Don't Work for Money\n\n"
            "My real dad, the one with the PhD, was highly educated. My other dad had never finished the eighth grade."
        ),
    ),
    dict(
        title="Purpose Driven Life", author="Rick Warren", publisher="Zondervan",
        category="Christian", publication_year=2002, number_of_pages=368,
        reading_time_minutes=440, cover_color="#5a3d99",
        description="A 40-day spiritual journey to discovering the answer to life's most important question: what on earth am I here for?",
        content=(
            "It's not about you. The purpose of your life is far greater than your own personal fulfillment, "
            "your peace of mind, or even your happiness...\n\n"
            "Day 1: It All Starts with God\n\nYou are not an accident."
        ),
    ),
    dict(
        title="Sapiens", author="Yuval Noah Harari", publisher="Harper",
        category="History", publication_year=2011, number_of_pages=443,
        reading_time_minutes=500, cover_color="#333333",
        description="A sweeping narrative of how Homo sapiens came to dominate the planet.",
        content=(
            "About 13.5 billion years ago, matter, energy, time and space came into being in what is known as the "
            "Big Bang...\n\n"
            "Chapter 1: An Animal of No Significance\n\nOur planet took shape about 4.5 billion years ago."
        ),
    ),
    dict(
        title="Clean Code", author="Robert C. Martin", publisher="Prentice Hall",
        category="Technology", publication_year=2008, number_of_pages=464,
        reading_time_minutes=480, cover_color="#0b5b6b",
        description="A handbook of agile software craftsmanship, teaching principles and practices for writing clean code.",
        content=(
            "Even bad code can function. But if code isn't clean, it can bring a development organization to its "
            "knees...\n\n"
            "Chapter 1: Clean Code\n\nYou are reading this book for two reasons."
        ),
    ),
]

book_objs = []
for bd in books_data:
    b = models.Book(**bd, added_by=admin.id)
    db.add(b)
    book_objs.append(b)
db.commit()
for b in book_objs:
    db.refresh(b)

# ---------- Book of the Month ----------
today = date.today()
botm = models.BookOfMonth(
    book_id=book_objs[2].id,  # Atomic Habits
    month=today.month, year=today.year,
    reading_guide="Read one chapter every 2-3 days. Focus on identifying one habit you want to build or break.",
    discussion_questions=(
        "What is one 'atomic habit' you want to start this month?\n"
        "How does your identity shape your habits, according to the author?\n"
        "Share one system (not goal) you've set up to support a habit."
    ),
    is_active=True,
)
db.add(botm)

# ---------- Challenge ----------
challenge = models.Challenge(
    name="7-Day Reading Challenge",
    description="Read for at least 20 minutes every day for 7 consecutive days.",
    start_date=today, end_date=today + timedelta(days=7), target_books=1,
)
db.add(challenge)

# ---------- Sample reviews & discussion ----------
db.commit()
review = models.Review(
    user_id=member1.id, book_id=book_objs[0].id, rating=5,
    lessons_learned="Tradition and change always collide — resilience matters more than resistance.",
    review_text="A masterpiece. Achebe's portrayal of Igbo society before and during colonisation is unforgettable.",
)
db.add(review)

post = models.DiscussionPost(
    user_id=member2.id, category="general",
    title="Welcome to Gwin's Readers Club!",
    content="Excited to be part of this community. What's everyone currently reading?",
    is_pinned=True,
)
db.add(post)
db.commit()

reply = models.DiscussionReply(
    post_id=post.id, user_id=member1.id,
    content="Welcome! I'm currently on Things Fall Apart for the first time. Loving it so far.",
)
db.add(reply)
db.commit()

# ---------- Reading Club ----------
club = models.ReadingClub(
    name="UNILAG Book Lovers", school_or_org="University of Lagos",
    description="A campus reading circle for students who want to read beyond the syllabus.",
    created_by=member1.id,
)
db.add(club)
db.commit()
db.refresh(club)
db.add(models.ClubMembership(club_id=club.id, user_id=member1.id, is_leader=True))
db.add(models.ClubMembership(club_id=club.id, user_id=member2.id))
db.commit()
db.add(models.ClubEvent(
    club_id=club.id, title="Monthly Book Discussion: Atomic Habits",
    description="In-person meetup to discuss this month's book club pick.",
    event_date=datetime.utcnow() + timedelta(days=10),
))
db.commit()

# ---------- Mentor profile & request ----------
mentor_profile = models.MentorProfile(
    user_id=mentor.id,
    specialties="African Literature,Personal Development,Career guidance",
    bio="20+ years teaching literature; happy to help you build a reading habit that sticks.",
    is_accepting_mentees=True,
)
db.add(mentor_profile)
db.commit()

mentorship = models.MentorshipRequest(mentor_id=mentor.id, mentee_id=member2.id, status="accepted")
db.add(mentorship)
db.commit()
db.refresh(mentorship)
db.add(models.MentorQuestion(
    mentorship_id=mentorship.id, asked_by=member2.id,
    question="What's a good next book after The Lean Startup for someone exploring entrepreneurship?",
    answer="Try 'Zero to One' by Peter Thiel next — it pairs well and offers a different lens.",
    answered_at=datetime.utcnow(),
))
db.commit()

# ---------- Live session ----------
live_session = models.LiveSession(
    title="Author Q&A: Writing African Literature Today",
    session_type="author_interview", host_id=mentor.id,
    description="A live chat session discussing themes in contemporary African literature.",
    scheduled_at=datetime.utcnow() + timedelta(days=3),
    duration_minutes=45,
)
db.add(live_session)
db.commit()
db.refresh(live_session)
db.add(models.LiveMessage(session_id=live_session.id, user_id=mentor.id, content="Looking forward to this discussion — see everyone soon!"))
db.commit()

# ---------- Reading Resources ----------
db.add(models.ReadingResource(
    book_id=book_objs[2].id,  # Atomic Habits
    resource_type="study_guide",
    title="Atomic Habits — Study Guide",
    content="Focus on the Four Laws of Behavior Change as you read: make it obvious, make it attractive, "
            "make it easy, make it satisfying. Keep a habit tracker alongside your reading journal.",
    added_by=mentor.id,
))
db.add(models.ReadingResource(
    book_id=book_objs[0].id,  # Things Fall Apart
    resource_type="author_bio",
    title="About Chinua Achebe",
    content="Chinua Achebe (1930-2013) was a Nigerian novelist, poet, and critic, widely regarded as a "
            "central figure of modern African literature. Things Fall Apart (1958) is his best-known work.",
    added_by=mentor.id,
))
db.add(models.ReadingResource(
    book_id=None,
    resource_type="vocabulary_list",
    title="General Literary Terms Glossary",
    content="Protagonist, antagonist, motif, allegory, foreshadowing, narrative arc, unreliable narrator.",
    added_by=admin.id,
))
db.commit()

# ---------- Opportunities Hub ----------
db.add(models.Opportunity(
    opportunity_type="scholarship",
    title="MTN Foundation Scholarship 2026",
    description="Undergraduate scholarship for Nigerian students in any discipline, based on academic merit and financial need.",
    application_url="https://example.org/mtn-scholarship",
    deadline=today + timedelta(days=45),
    posted_by=admin.id,
))
db.add(models.Opportunity(
    opportunity_type="essay_contest",
    title="Young African Writers Essay Prize",
    description="Submit a 2000-word essay on African literature and identity. Top 3 entries published in an anthology.",
    application_url="https://example.org/essay-prize",
    deadline=today + timedelta(days=20),
    posted_by=admin.id,
))
db.add(models.Opportunity(
    opportunity_type="internship",
    title="Publishing Internship — Farafina Books",
    description="3-month internship in editorial and publishing operations for undergraduates and recent graduates.",
    deadline=today + timedelta(days=10),
    posted_by=admin.id,
))
db.commit()

print("Seed complete.")
print("Login as: admin@readersclub.ng / admin123 (Administrator — with demo content)")
print("          mod@readersclub.ng / mod12345 (Moderator — with demo content)")
print("          mentor@readersclub.ng / mentor123 (Mentor — with demo content)")
print("          chidinma@example.com / member123 (Member — with demo content)")
print("          samuel@example.com / member123 (Member — with demo content)")
print("")
print("Simple test accounts (no extra demo content attached):")
print("          testadmin@readersclub.ng / Test1234 (Administrator)")
print("          testmoderator@readersclub.ng / Test1234 (Moderator)")
print("          testmentor@readersclub.ng / Test1234 (Mentor)")
print("          testuser@readersclub.ng / Test1234 (Member)")
db.close()
