const user = getUser();

function initAdminDashboard() {
  loadStats();
  loadUsers();
  loadCategoriesForForms();
  loadCategoriesTab();
  loadBooks();
  loadBookOptions();
  loadBotmHistory();
  loadChallenges();
  loadClubs();
  loadMentors();
  loadMentorshipPairings("pending");
  loadLiveSessions();
  loadResources();
  loadResourceBookOptions();
  loadOpportunities();
  loadReviews();
  loadDiscussions();
  loadCertificates();
  loadReports("pending");
  loadDonations();
  loadAuditLog();
}

function statCard(label, value) {
  return `<div class="col-6 col-md-2"><div class="card card-rc p-3 text-center"><h4>${value}</h4><small class="text-muted">${label}</small></div></div>`;
}

async function loadStats() {
  const s = await api("/admin/stats");
  document.getElementById("stats-row").innerHTML = `
    ${statCard("Total Members", s.total_members)}
    ${statCard("Active Readers (30d)", s.active_readers)}
    ${statCard("Books in Library", s.books_uploaded)}
    ${statCard("Books Completed", s.books_completed_total)}
    ${statCard("Reviews Submitted", s.reviews_total)}
    ${statCard("Discussion Posts", s.discussion_posts_total)}
    ${statCard("Pending Reports", s.pending_reports)}
    ${statCard("Pending Book Submissions", s.pending_book_submissions)}
    ${statCard("Active Clubs", s.active_clubs)}
    ${statCard("Upcoming Live Sessions", s.upcoming_live_sessions)}
    ${statCard("Active Mentors", s.active_mentors)}
    ${statCard("Open Challenges", s.open_challenges)}
    ${statCard("Certificates Issued", s.certificates_issued)}
  `;
}

// ===================== MEMBERS =====================

async function loadUsers() {
  const search = document.getElementById("user-search").value;
  const role = document.getElementById("role-filter").value;
  const params = new URLSearchParams();
  if (search) params.append("search", search);
  if (role) params.append("role", role);
  const users = await api(`/admin/users?${params.toString()}`);
  document.getElementById("users-table").innerHTML = users.map(u => `
    <tr>
      <td>${escapeHtml(u.full_name)} <span class="text-muted small">#${u.id}</span></td>
      <td>${escapeHtml(u.email)}</td>
      <td>${escapeHtml(u.school || "—")}</td>
      <td>
        ${user.role === "admin" ? `
        <select class="form-select form-select-sm" onchange="changeRole(${u.id}, this.value)">
          ${["member","mentor","moderator","admin"].map(r => `<option value="${r}" ${r === u.role ? "selected" : ""}>${r}</option>`).join("")}
        </select>` : u.role}
      </td>
      <td>${new Date(u.created_at).toLocaleDateString()}</td>
      <td>
        ${user.role === "admin" && u.id !== user.id ? `<button class="btn btn-sm btn-outline-danger" onclick="removeUser(${u.id})">Remove</button>` : ""}
      </td>
    </tr>
  `).join("");
}

async function changeRole(userId, role) {
  await api(`/admin/users/${userId}/role?role=${role}`, { method: "PUT" });
  loadUsers();
  loadStats();
}

async function removeUser(userId) {
  if (!confirm("Remove this user's account? This cannot be undone.")) return;
  await api(`/admin/users/${userId}`, { method: "DELETE" });
  loadUsers();
  loadStats();
}

async function exportUsersCsv() {
  const token = getToken();
  const role = document.getElementById("role-filter").value;
  const params = new URLSearchParams();
  if (role) params.append("role", role);
  const res = await fetch(`/api/admin/users/export?${params.toString()}`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = "readers_club_members.csv";
  a.click();
  URL.revokeObjectURL(url);
}

// ===================== CATEGORIES (shared helper) =====================

let cachedCategories = [];

async function loadCategoriesForForms() {
  cachedCategories = await api("/library/categories").catch(() => []);
  const selects = [document.getElementById("bk_category"), document.getElementById("book-category-filter")];
  selects.forEach((sel, idx) => {
    if (!sel) return;
    const options = cachedCategories.map(c => `<option value="${c}">${c}</option>`).join("");
    if (idx === 1) {
      sel.innerHTML = `<option value="">All Categories</option>${options}`;
    } else {
      sel.innerHTML = options;
    }
  });
}

async function loadCategoriesTab() {
  const cats = await api("/admin/categories");
  const el = document.getElementById("categories-list");
  if (!cats.length) { el.innerHTML = `<p class="text-muted small mb-0">No categories yet.</p>`; return; }
  el.innerHTML = cats.map(c => `
    <div class="d-flex justify-content-between align-items-center border-bottom py-2">
      <span>${c.name}</span>
      <div>
        <button class="btn btn-sm btn-outline-secondary" onclick='renameCategory(${c.id}, "${c.name.replace(/"/g, "&quot;")}")'>Rename</button>
        <button class="btn btn-sm btn-outline-danger" onclick="deleteCategory(${c.id})">Delete</button>
      </div>
    </div>
  `).join("");
}

async function createCategory() {
  const name = document.getElementById("new-category-name").value.trim();
  if (!name) return;
  try {
    await api("/admin/categories", { method: "POST", body: JSON.stringify({ name }) });
    document.getElementById("new-category-name").value = "";
    showAlert("category-alert", "Category added.", "success");
    loadCategoriesTab();
    loadCategoriesForForms();
  } catch (err) {
    showAlert("category-alert", err.message);
  }
}

async function renameCategory(id, currentName) {
  const name = prompt("New category name:", currentName);
  if (!name || name === currentName) return;
  await api(`/admin/categories/${id}`, { method: "PUT", body: JSON.stringify({ name }) });
  loadCategoriesTab();
  loadCategoriesForForms();
}

async function deleteCategory(id) {
  if (!confirm("Delete this category?")) return;
  await api(`/admin/categories/${id}`, { method: "DELETE" });
  loadCategoriesTab();
  loadCategoriesForForms();
}

// ===================== BOOKS =====================

let editingBookId = null;

async function loadBooks() {
  const search = document.getElementById("book-search").value;
  const category = document.getElementById("book-category-filter").value;
  const status = document.getElementById("book-status-filter").value;
  const params = new URLSearchParams();
  if (search) params.append("search", search);
  if (category) params.append("category", category);
  if (status) params.append("status", status);
  const books = await api(`/admin/books?${params.toString()}`);
  const statusBadge = (s) => {
    const map = { pending: "warning", approved: "success", rejected: "danger" };
    return `<span class="badge bg-${map[s] || "secondary"}">${s}</span>`;
  };
  document.getElementById("books-table").innerHTML = books.map(b => `
    <tr>
      <td><input type="checkbox" class="book-checkbox" value="${b.id}"></td>
      <td>${b.cover_url ? `<img class="thumb-60" src="${b.cover_url}">` : `<div class="thumb-60" style="background:${b.cover_color}"></div>`}</td>
      <td>${b.title}</td>
      <td>${b.author}</td>
      <td>${b.category}</td>
      <td>${b.file_format ? `<span class="category-pill">${b.file_format.toUpperCase()}</span> <a href="#" onclick="downloadBookFile(${b.id}); return false;">⬇</a>` : `<span class="text-muted small">none</span>`}</td>
      <td>
        ${statusBadge(b.status)}
        ${b.status === "rejected" && b.rejection_reason ? `<div class="small text-muted" style="max-width:160px;">${b.rejection_reason}</div>` : ""}
      </td>
      <td>
        <div class="form-check form-switch">
          <input class="form-check-input" type="checkbox" ${b.is_featured ? "checked" : ""} onchange="toggleFeatured(${b.id}, this.checked)">
        </div>
      </td>
      <td>
        ${b.status === "pending" ? `
          <button class="btn btn-sm btn-success" onclick="approveBook(${b.id})">Approve</button>
          <button class="btn btn-sm btn-outline-danger" onclick="rejectBook(${b.id})">Reject</button>
        ` : ""}
        <button class="btn btn-sm btn-outline-secondary" onclick='startEditBook(${JSON.stringify(b).replace(/'/g, "&#39;")})'>Edit</button>
        <button class="btn btn-sm btn-outline-danger" onclick="deleteBook(${b.id})">Delete</button>
      </td>
    </tr>
  `).join("");
}

async function approveBook(id) {
  await api(`/admin/books/${id}/approve`, { method: "POST" });
  loadBooks();
  loadStats();
}

async function rejectBook(id) {
  const reason = prompt("Reason for rejecting this book (shown to the submitter):");
  if (!reason) return;
  await api(`/admin/books/${id}/reject`, { method: "POST", body: JSON.stringify({ reason }) });
  loadBooks();
  loadStats();
}

async function downloadBookFile(id) {
  const token = getToken();
  const res = await fetch(`/api/admin/books/${id}/file`, { headers: { Authorization: `Bearer ${token}` } });
  if (!res.ok) { alert("No file available for this book."); return; }
  const disposition = res.headers.get("Content-Disposition") || "";
  const match = disposition.match(/filename="?([^"]+)"?/);
  const filename = match ? match[1] : `book-${id}`;
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url; a.download = filename; a.click();
  URL.revokeObjectURL(url);
}

async function toggleFeatured(id, value) {
  await api(`/admin/books/${id}`, { method: "PUT", body: JSON.stringify({ is_featured: value }) });
}

function startEditBook(book) {
  editingBookId = book.id;
  document.getElementById("book-form-title").textContent = `Edit: ${book.title}`;
  document.getElementById("bk_title").value = book.title;
  document.getElementById("bk_author").value = book.author;
  document.getElementById("bk_category").value = book.category;
  document.getElementById("bk_publisher").value = book.publisher || "";
  document.getElementById("bk_language").value = book.language || "English";
  document.getElementById("bk_pages").value = book.number_of_pages || 0;
  document.getElementById("bk_reading_time").value = book.reading_time_minutes || 0;
  document.getElementById("bk_year").value = book.publication_year || "";
  document.getElementById("bk_description").value = book.description || "";
  document.getElementById("bk_cover_color").value = book.cover_color || "#35538F";
  document.getElementById("bk_featured").checked = !!book.is_featured;
  document.getElementById("bk_content").value = "";
  document.getElementById("bk_file").value = "";
  document.getElementById("bk_cover").value = "";
  document.getElementById("book-submit-btn").textContent = "Save Changes";
  document.getElementById("book-cancel-btn").classList.remove("d-none");
  document.getElementById("tab-books").scrollIntoView({ behavior: "smooth" });
}

function cancelBookEdit() {
  editingBookId = null;
  document.getElementById("book-form").reset();
  document.getElementById("book-form-title").textContent = "Add a Book";
  document.getElementById("book-submit-btn").textContent = "Add Book";
  document.getElementById("book-cancel-btn").classList.add("d-none");
}

async function saveBook() {
  const bookFile = document.getElementById("bk_file").files[0];
  const coverFile = document.getElementById("bk_cover").files[0];

  try {
    if (editingBookId) {
      const payload = {
        title: document.getElementById("bk_title").value,
        author: document.getElementById("bk_author").value,
        category: document.getElementById("bk_category").value,
        publisher: document.getElementById("bk_publisher").value || null,
        language: document.getElementById("bk_language").value || "English",
        number_of_pages: parseInt(document.getElementById("bk_pages").value) || 0,
        reading_time_minutes: parseInt(document.getElementById("bk_reading_time").value) || 0,
        publication_year: document.getElementById("bk_year").value ? parseInt(document.getElementById("bk_year").value) : null,
        description: document.getElementById("bk_description").value || null,
        cover_color: document.getElementById("bk_cover_color").value,
        is_featured: document.getElementById("bk_featured").checked,
      };
      const contentVal = document.getElementById("bk_content").value;
      if (contentVal) payload.content = contentVal;
      await api(`/admin/books/${editingBookId}`, { method: "PUT", body: JSON.stringify(payload) });
      if (bookFile) {
        const fd = new FormData(); fd.append("book_file", bookFile);
        await apiUpload(`/admin/books/${editingBookId}/file`, fd);
      }
      if (coverFile) {
        const fd = new FormData(); fd.append("cover_image", coverFile);
        await apiUpload(`/admin/books/${editingBookId}/cover`, fd);
      }
      showAlert("book-form-alert", "Book updated.", "success");
      cancelBookEdit();
    } else {
      const fd = new FormData();
      fd.append("title", document.getElementById("bk_title").value);
      fd.append("author", document.getElementById("bk_author").value);
      fd.append("category", document.getElementById("bk_category").value);
      fd.append("publisher", document.getElementById("bk_publisher").value || "");
      fd.append("language", document.getElementById("bk_language").value || "English");
      fd.append("number_of_pages", document.getElementById("bk_pages").value || "0");
      fd.append("reading_time_minutes", document.getElementById("bk_reading_time").value || "0");
      if (document.getElementById("bk_year").value) fd.append("publication_year", document.getElementById("bk_year").value);
      fd.append("description", document.getElementById("bk_description").value || "");
      fd.append("cover_color", document.getElementById("bk_cover_color").value);
      fd.append("content", document.getElementById("bk_content").value || "");
      fd.append("is_featured", document.getElementById("bk_featured").checked);
      if (bookFile) fd.append("book_file", bookFile);
      if (coverFile) fd.append("cover_image", coverFile);
      await apiUpload("/admin/books", fd);
      showAlert("book-form-alert", "Book added.", "success");
      document.getElementById("book-form").reset();
    }
    loadBooks();
    loadBookOptions();
    loadStats();
  } catch (err) {
    showAlert("book-form-alert", err.message);
  }
}

async function deleteBook(id) {
  if (!confirm("Delete this book permanently?")) return;
  await api(`/admin/books/${id}`, { method: "DELETE" });
  loadBooks();
  loadBookOptions();
  loadStats();
}

async function bulkDeleteBooks() {
  const ids = Array.from(document.querySelectorAll(".book-checkbox:checked")).map(el => parseInt(el.value));
  if (!ids.length) { alert("Select at least one book first."); return; }
  if (!confirm(`Delete ${ids.length} selected book(s)?`)) return;
  await api("/admin/books/bulk-delete", { method: "POST", body: JSON.stringify({ ids }) });
  loadBooks();
  loadStats();
}

// ===================== BOOK OF THE MONTH =====================

async function loadBookOptions() {
  const books = await api("/library/books?sort=title");
  const sel = document.getElementById("botm_book_id");
  sel.innerHTML = books.map(b => `<option value="${b.id}">${b.title} — ${b.author}</option>`).join("");
  const now = new Date();
  document.getElementById("botm_month").value = now.getMonth() + 1;
  document.getElementById("botm_year").value = now.getFullYear();
}

let editingBotmId = null;

async function setBotm() {
  const payload = {
    book_id: parseInt(document.getElementById("botm_book_id").value),
    month: parseInt(document.getElementById("botm_month").value),
    year: parseInt(document.getElementById("botm_year").value),
    reading_guide: document.getElementById("botm_guide").value,
    discussion_questions: document.getElementById("botm_questions").value,
  };
  try {
    if (editingBotmId) {
      await api(`/library/book-of-month/${editingBotmId}`, { method: "PUT", body: JSON.stringify(payload) });
      showAlert("botm-alert", "Book of the Month entry updated!", "success");
      cancelBotmEdit();
    } else {
      await api("/library/book-of-month", { method: "POST", body: JSON.stringify(payload) });
      showAlert("botm-alert", "Book of the Month published!", "success");
    }
    loadBotmHistory();
  } catch (err) {
    showAlert("botm-alert", err.message);
  }
}

let botmHistoryCache = [];

async function loadBotmHistory() {
  const history = await api("/library/book-of-month/history");
  botmHistoryCache = history;
  const el = document.getElementById("botm-history");
  if (!history.length) { el.innerHTML = `<p class="text-muted small mb-0">No entries yet.</p>`; return; }
  el.innerHTML = history.map(h => `
    <div class="d-flex justify-content-between align-items-center border-bottom py-2">
      <div>
        <strong class="small">${escapeHtml(h.book ? h.book.title : "Book #" + h.book_id)}</strong>
        <span class="text-muted small ms-1">${h.month}/${h.year}${h.is_active ? " (current)" : ""}</span>
      </div>
      <button class="btn btn-sm btn-outline-secondary" onclick="startEditBotm(${h.id})">Edit</button>
    </div>
  `).join("");
}

// Looks the entry up from the last-loaded history rather than passing the
// whole object through an inline onclick attribute — book titles containing
// an apostrophe (e.g. "Charlotte's Web") broke the previous JSON.stringify()
// approach and made Edit silently do nothing.
function startEditBotm(id) {
  const entry = botmHistoryCache.find(h => h.id === id);
  if (!entry) return;
  editingBotmId = entry.id;
  document.getElementById("botm_book_id").value = entry.book_id;
  document.getElementById("botm_month").value = entry.month;
  document.getElementById("botm_year").value = entry.year;
  document.getElementById("botm_guide").value = entry.reading_guide || "";
  document.getElementById("botm_questions").value = entry.discussion_questions || "";
  document.getElementById("botm-submit-btn").textContent = "Save Changes";
  document.getElementById("botm-cancel-edit-btn").classList.remove("d-none");
}

function cancelBotmEdit() {
  editingBotmId = null;
  document.getElementById("botm-submit-btn").textContent = "Publish";
  document.getElementById("botm-cancel-edit-btn").classList.add("d-none");
}

// ===================== CHALLENGES =====================

let editingChallengeId = null;

async function loadChallenges() {
  const challenges = await api("/admin/challenges");
  document.getElementById("challenges-table").innerHTML = challenges.map(c => `
    <tr>
      <td>${c.name}</td>
      <td>${c.start_date} → ${c.end_date}</td>
      <td>${c.target_books}</td>
      <td>${c.participant_count}</td>
      <td>
        <button class="btn btn-sm btn-outline-secondary" onclick='startEditChallenge(${JSON.stringify(c)})'>Edit</button>
        <button class="btn btn-sm btn-outline-danger" onclick="deleteChallenge(${c.id})">Delete</button>
      </td>
    </tr>
  `).join("") || `<tr><td colspan="5" class="text-muted">No challenges yet.</td></tr>`;
}

async function saveChallenge() {
  const payload = {
    name: document.getElementById("ch_name").value,
    description: document.getElementById("ch_description").value,
    start_date: document.getElementById("ch_start").value,
    end_date: document.getElementById("ch_end").value,
    target_books: parseInt(document.getElementById("ch_target").value) || 1,
  };
  try {
    if (editingChallengeId) {
      await api(`/admin/challenges/${editingChallengeId}`, { method: "PUT", body: JSON.stringify(payload) });
      showAlert("challenge-alert", "Challenge updated.", "success");
      cancelChallengeEdit();
    } else {
      await api("/progress/challenges", { method: "POST", body: JSON.stringify(payload) });
      showAlert("challenge-alert", "Challenge created!", "success");
      document.getElementById("ch_name").value = "";
      document.getElementById("ch_description").value = "";
    }
    loadChallenges();
    loadStats();
  } catch (err) {
    showAlert("challenge-alert", err.message);
  }
}

function startEditChallenge(c) {
  editingChallengeId = c.id;
  document.getElementById("challenge-form-title").textContent = `Edit: ${c.name}`;
  document.getElementById("ch_name").value = c.name;
  document.getElementById("ch_description").value = c.description || "";
  document.getElementById("ch_start").value = c.start_date;
  document.getElementById("ch_end").value = c.end_date;
  document.getElementById("ch_target").value = c.target_books;
  document.getElementById("challenge-submit-btn").textContent = "Save Changes";
  document.getElementById("challenge-cancel-btn").classList.remove("d-none");
}

function cancelChallengeEdit() {
  editingChallengeId = null;
  document.getElementById("challenge-form-title").textContent = "Create a Reading Challenge";
  document.getElementById("challenge-submit-btn").textContent = "Create Challenge";
  document.getElementById("challenge-cancel-btn").classList.add("d-none");
}

async function deleteChallenge(id) {
  if (!confirm("Delete this challenge?")) return;
  await api(`/admin/challenges/${id}`, { method: "DELETE" });
  loadChallenges();
  loadStats();
}

// ===================== CLUBS & EVENTS =====================

let editingClubId = null;

async function loadClubs() {
  const clubs = await api("/clubs");
  document.getElementById("clubs-table").innerHTML = clubs.map(c => `
    <tr>
      <td>${c.name}</td>
      <td>${c.school_or_org || "—"}</td>
      <td>${c.member_count}</td>
      <td>
        <button class="btn btn-sm btn-outline-secondary" onclick='startEditClub(${JSON.stringify(c)})'>Edit</button>
        <button class="btn btn-sm btn-outline-danger" onclick="deleteClub(${c.id})">Delete</button>
      </td>
    </tr>
  `).join("") || `<tr><td colspan="4" class="text-muted">No clubs yet.</td></tr>`;

  const sel = document.getElementById("event_club_id");
  sel.innerHTML = clubs.map(c => `<option value="${c.id}">${c.name}</option>`).join("");
}

async function saveClub() {
  const payload = {
    name: document.getElementById("club_name").value,
    school_or_org: document.getElementById("club_school").value || null,
    description: document.getElementById("club_description").value || null,
  };
  try {
    if (editingClubId) {
      await api(`/clubs/${editingClubId}`, { method: "PUT", body: JSON.stringify(payload) });
      showAlert("club-alert", "Club updated.", "success");
      cancelClubEdit();
    } else {
      await api("/clubs", { method: "POST", body: JSON.stringify(payload) });
      showAlert("club-alert", "Club created!", "success");
      document.getElementById("club_name").value = "";
      document.getElementById("club_school").value = "";
      document.getElementById("club_description").value = "";
    }
    loadClubs();
    loadStats();
  } catch (err) {
    showAlert("club-alert", err.message);
  }
}

function startEditClub(c) {
  editingClubId = c.id;
  document.getElementById("club-form-title").textContent = `Edit: ${c.name}`;
  document.getElementById("club_name").value = c.name;
  document.getElementById("club_school").value = c.school_or_org || "";
  document.getElementById("club_description").value = c.description || "";
  document.getElementById("club-submit-btn").textContent = "Save Changes";
  document.getElementById("club-cancel-btn").classList.remove("d-none");
}

function cancelClubEdit() {
  editingClubId = null;
  document.getElementById("club-form-title").textContent = "Create a Reading Club";
  document.getElementById("club-submit-btn").textContent = "Create Club";
  document.getElementById("club-cancel-btn").classList.add("d-none");
}

async function deleteClub(id) {
  if (!confirm("Delete this club? This removes its memberships and events too.")) return;
  await api(`/clubs/${id}`, { method: "DELETE" });
  loadClubs();
  loadStats();
}

async function createEvent() {
  const clubId = document.getElementById("event_club_id").value;
  if (!clubId) { showAlert("event-alert", "Create a club first."); return; }
  const payload = {
    title: document.getElementById("event_title").value,
    description: document.getElementById("event_description").value || null,
    event_date: document.getElementById("event_date").value,
  };
  try {
    await api(`/clubs/${clubId}/events`, { method: "POST", body: JSON.stringify(payload) });
    showAlert("event-alert", "Event added.", "success");
    document.getElementById("event_title").value = "";
    document.getElementById("event_description").value = "";
  } catch (err) {
    showAlert("event-alert", err.message);
  }
}

// ===================== MENTORS =====================

async function loadMentors() {
  const mentors = await api("/admin/mentors");
  document.getElementById("mentors-table").innerHTML = mentors.map(m => `
    <tr>
      <td>${m.mentor_name} <span class="text-muted small">#${m.user_id}</span></td>
      <td>${m.specialties || "—"}</td>
      <td class="small">${(m.bio || "").slice(0, 80)}${(m.bio || "").length > 80 ? "…" : ""}</td>
      <td>
        <div class="form-check form-switch">
          <input class="form-check-input" type="checkbox" ${m.is_accepting_mentees ? "checked" : ""} onchange="toggleMentorAccepting(${m.user_id}, this.checked)">
        </div>
      </td>
      <td>${m.average_rating ? `${m.average_rating} ★ (${m.rating_count})` : "—"}</td>
      <td>
        <button class="btn btn-sm btn-outline-secondary" onclick="editMentorProfile(${m.user_id}, ${JSON.stringify(m.specialties || "")}, ${JSON.stringify(m.bio || "")}, ${m.is_accepting_mentees})">Edit</button>
        <button class="btn btn-sm btn-outline-danger" onclick="removeMentorProfile(${m.user_id})">Remove</button>
      </td>
    </tr>
  `).join("") || `<tr><td colspan="6" class="text-muted">No mentor profiles yet. Use the form above to create one for any user whose role is "mentor".</td></tr>`;
}

function editMentorProfile(userId, specialties, bio, accepting) {
  document.getElementById("mentor-form-title").textContent = `Editing Mentor Profile #${userId}`;
  document.getElementById("mp_user_id").value = userId;
  document.getElementById("mp_specialties").value = specialties;
  document.getElementById("mp_bio").value = bio;
  document.getElementById("mp_accepting").checked = accepting;
  document.getElementById("mp_user_id").scrollIntoView({ behavior: "smooth", block: "center" });
}

async function saveMentorProfile() {
  const userId = document.getElementById("mp_user_id").value;
  if (!userId) { showAlert("mentor-form-alert", "Enter the mentor's user ID."); return; }
  const specialties = document.getElementById("mp_specialties").value;
  const bio = document.getElementById("mp_bio").value;
  const accepting = document.getElementById("mp_accepting").checked;
  try {
    const params = new URLSearchParams({
      specialties, bio, is_accepting_mentees: accepting,
    });
    await api(`/admin/mentors/${userId}?${params.toString()}`, { method: "PUT" });
    showAlert("mentor-form-alert", "Mentor profile saved.", "success");
    document.getElementById("mentor-form-title").textContent = "Create / Edit Mentor Profile";
    document.getElementById("mp_user_id").value = "";
    document.getElementById("mp_specialties").value = "";
    document.getElementById("mp_bio").value = "";
    document.getElementById("mp_accepting").checked = true;
    loadMentors();
    loadStats();
  } catch (err) {
    showAlert("mentor-form-alert", err.message);
  }
}

async function toggleMentorAccepting(userId, value) {
  await api(`/admin/mentors/${userId}?is_accepting_mentees=${value}`, { method: "PUT" });
}

async function removeMentorProfile(userId) {
  if (!confirm("Remove this mentor's profile listing? Their account role is unaffected.")) return;
  await api(`/admin/mentors/${userId}`, { method: "DELETE" });
  loadMentors();
  loadStats();
}

async function loadMentorshipPairings(status = "") {
  const params = status ? `?status=${status}` : "";
  const pairings = await api(`/admin/mentorship-requests${params}`);
  const statusBadge = { pending: "warning", accepted: "success", declined: "secondary", ended: "secondary" };
  document.getElementById("mentorship-pairings-table").innerHTML = pairings.map(p => `
    <tr>
      <td>${p.mentor_name} <span class="text-muted small">#${p.mentor_id}</span></td>
      <td>${p.mentee_name} <span class="text-muted small">#${p.mentee_id}</span></td>
      <td><span class="badge bg-${statusBadge[p.status] || "secondary"}">${p.status}</span></td>
      <td>${new Date(p.requested_at).toLocaleDateString()}</td>
      <td>${p.status === "accepted" ? `<button class="btn btn-sm btn-outline-danger" onclick="endMentorshipPairing(${p.id})">End</button>` : ""}</td>
    </tr>
  `).join("") || `<tr><td colspan="5" class="text-muted">No pairings found.</td></tr>`;
}

async function endMentorshipPairing(requestId) {
  if (!confirm("End this mentorship pairing? Both mentor and mentee will see it as ended.")) return;
  await api(`/admin/mentorship-requests/${requestId}/end`, { method: "PUT" });
  loadMentorshipPairings("accepted");
}

// ===================== LIVE SESSIONS =====================

let editingLiveId = null;

async function loadLiveSessions() {
  const sessions = await api("/live/sessions");
  document.getElementById("live-table").innerHTML = sessions.map(s => `
    <tr>
      <td>${s.title}${s.is_cancelled ? ' <span class="text-danger small">(cancelled)</span>' : ""}</td>
      <td>${s.session_type}</td>
      <td>${new Date(s.scheduled_at).toLocaleString()}</td>
      <td>${s.rsvp_count}</td>
      <td>
        <button class="btn btn-sm btn-outline-secondary" onclick='startEditLive(${JSON.stringify(s)})'>Edit</button>
        <button class="btn btn-sm btn-outline-danger" onclick="deleteLiveSession(${s.id})">Delete</button>
      </td>
    </tr>
  `).join("") || `<tr><td colspan="5" class="text-muted">No sessions yet.</td></tr>`;
}

async function saveLiveSession() {
  const payload = {
    title: document.getElementById("live_title").value,
    session_type: document.getElementById("live_type").value,
    description: document.getElementById("live_description").value || null,
    scheduled_at: document.getElementById("live_scheduled_at").value,
    duration_minutes: parseInt(document.getElementById("live_duration").value) || 60,
  };
  try {
    if (editingLiveId) {
      await api(`/live/sessions/${editingLiveId}`, { method: "PUT", body: JSON.stringify(payload) });
      showAlert("live-alert", "Session updated.", "success");
      cancelLiveEdit();
    } else {
      await api("/live/sessions", { method: "POST", body: JSON.stringify(payload) });
      showAlert("live-alert", "Session scheduled!", "success");
      document.getElementById("live_title").value = "";
      document.getElementById("live_description").value = "";
    }
    loadLiveSessions();
    loadStats();
  } catch (err) {
    showAlert("live-alert", err.message);
  }
}

function startEditLive(s) {
  editingLiveId = s.id;
  document.getElementById("live-form-title").textContent = `Edit: ${s.title}`;
  document.getElementById("live_title").value = s.title;
  document.getElementById("live_type").value = s.session_type;
  document.getElementById("live_description").value = s.description || "";
  document.getElementById("live_scheduled_at").value = s.scheduled_at.slice(0, 16);
  document.getElementById("live_duration").value = s.duration_minutes;
  document.getElementById("live-submit-btn").textContent = "Save Changes";
  document.getElementById("live-cancel-btn").classList.remove("d-none");
}

function cancelLiveEdit() {
  editingLiveId = null;
  document.getElementById("live-form-title").textContent = "Schedule a Live Session";
  document.getElementById("live-submit-btn").textContent = "Schedule Session";
  document.getElementById("live-cancel-btn").classList.add("d-none");
}

async function deleteLiveSession(id) {
  if (!confirm("Cancel/delete this live session?")) return;
  await api(`/live/sessions/${id}`, { method: "DELETE" });
  loadLiveSessions();
  loadStats();
}

// ===================== RESOURCES =====================

let editingResourceId = null;

async function loadResourceBookOptions() {
  const books = await api("/library/books?sort=title");
  const sel = document.getElementById("res_book_id");
  sel.innerHTML = `<option value="">— None —</option>` + books.map(b => `<option value="${b.id}">${b.title}</option>`).join("");
}

async function loadResources() {
  const resources = await api("/resources");
  document.getElementById("resources-table").innerHTML = resources.map(r => `
    <tr>
      <td>${r.title}</td>
      <td>${r.resource_type}</td>
      <td>${r.book_title || "—"}</td>
      <td>
        <button class="btn btn-sm btn-outline-secondary" onclick='startEditResource(${JSON.stringify(r).replace(/'/g, "&#39;")})'>Edit</button>
        <button class="btn btn-sm btn-outline-danger" onclick="deleteResource(${r.id})">Delete</button>
      </td>
    </tr>
  `).join("") || `<tr><td colspan="4" class="text-muted">No resources yet.</td></tr>`;
}

async function saveResource() {
  const payload = {
    resource_type: document.getElementById("res_type").value,
    title: document.getElementById("res_title").value,
    book_id: document.getElementById("res_book_id").value ? parseInt(document.getElementById("res_book_id").value) : null,
    content: document.getElementById("res_content").value,
  };
  try {
    if (editingResourceId) {
      await api(`/resources/${editingResourceId}`, { method: "PUT", body: JSON.stringify(payload) });
      showAlert("resource-alert", "Resource updated.", "success");
      cancelResourceEdit();
    } else {
      await api("/resources", { method: "POST", body: JSON.stringify(payload) });
      showAlert("resource-alert", "Resource added!", "success");
      document.getElementById("res_title").value = "";
      document.getElementById("res_content").value = "";
    }
    loadResources();
  } catch (err) {
    showAlert("resource-alert", err.message);
  }
}

function startEditResource(r) {
  editingResourceId = r.id;
  document.getElementById("resource-form-title").textContent = `Edit: ${r.title}`;
  document.getElementById("res_type").value = r.resource_type;
  document.getElementById("res_title").value = r.title;
  document.getElementById("res_book_id").value = r.book_id || "";
  document.getElementById("res_content").value = r.content;
  document.getElementById("resource-submit-btn").textContent = "Save Changes";
  document.getElementById("resource-cancel-btn").classList.remove("d-none");
}

function cancelResourceEdit() {
  editingResourceId = null;
  document.getElementById("resource-form-title").textContent = "Add a Reading Resource";
  document.getElementById("resource-submit-btn").textContent = "Add Resource";
  document.getElementById("resource-cancel-btn").classList.add("d-none");
}

async function deleteResource(id) {
  if (!confirm("Delete this resource?")) return;
  await api(`/resources/${id}`, { method: "DELETE" });
  loadResources();
}

// ===================== OPPORTUNITIES =====================

let editingOppId = null;

async function loadOpportunities() {
  const opps = await api("/opportunities");
  document.getElementById("opportunities-table").innerHTML = opps.map(o => `
    <tr>
      <td>${o.logo_url ? `<img src="${o.logo_url}" class="thumb-60" style="width:44px;height:44px;object-fit:cover;border-radius:6px;">` : `<div class="thumb-60" style="width:44px;height:44px;background:#eee;border-radius:6px;"></div>`}</td>
      <td>${o.title}${o.organization ? `<div class="text-muted small">${o.organization}</div>` : ""}</td>
      <td>${o.opportunity_type}</td>
      <td>${o.deadline || "—"}</td>
      <td>${o.application_url ? `<a href="${o.application_url}" target="_blank" rel="noopener">✅ Linked</a>` : `<span class="text-danger">⚠️ No link</span>`}</td>
      <td>
        <button class="btn btn-sm btn-outline-secondary" onclick='startEditOpp(${JSON.stringify(o).replace(/'/g, "&#39;")})'>Edit</button>
        <button class="btn btn-sm btn-outline-danger" onclick="deleteOpportunity(${o.id})">Delete</button>
      </td>
    </tr>
  `).join("") || `<tr><td colspan="6" class="text-muted">No opportunities yet.</td></tr>`;
}

async function saveOpportunity() {
  const payload = {
    opportunity_type: document.getElementById("opp_type").value,
    title: document.getElementById("opp_title").value,
    description: document.getElementById("opp_description").value,
    application_url: document.getElementById("opp_url").value || null,
    deadline: document.getElementById("opp_deadline").value || null,
    organization: document.getElementById("opp_organization").value || null,
  };
  const logoFile = document.getElementById("opp_logo").files[0];
  try {
    let oppId = editingOppId;
    if (editingOppId) {
      await api(`/opportunities/${editingOppId}`, { method: "PUT", body: JSON.stringify(payload) });
    } else {
      const created = await api("/opportunities", { method: "POST", body: JSON.stringify(payload) });
      oppId = created.id;
    }
    if (logoFile && oppId) {
      const fd = new FormData();
      fd.append("file", logoFile);
      await apiUpload(`/opportunities/${oppId}/logo`, fd);
    }
    showAlert("opp-alert", editingOppId ? "Opportunity updated." : "Opportunity posted!", "success");
    if (editingOppId) {
      cancelOppEdit();
    } else {
      document.getElementById("opp_title").value = "";
      document.getElementById("opp_description").value = "";
      document.getElementById("opp_url").value = "";
      document.getElementById("opp_organization").value = "";
      document.getElementById("opp_logo").value = "";
    }
    loadOpportunities();
  } catch (err) {
    showAlert("opp-alert", err.message);
  }
}

function startEditOpp(o) {
  editingOppId = o.id;
  document.getElementById("opp-form-title").textContent = `Edit: ${o.title}`;
  document.getElementById("opp_type").value = o.opportunity_type;
  document.getElementById("opp_title").value = o.title;
  document.getElementById("opp_description").value = o.description;
  document.getElementById("opp_url").value = o.application_url || "";
  document.getElementById("opp_deadline").value = o.deadline || "";
  document.getElementById("opp_organization").value = o.organization || "";
  document.getElementById("opp_logo").value = "";
  document.getElementById("opp-submit-btn").textContent = "Save Changes";
  document.getElementById("opp-cancel-btn").classList.remove("d-none");
}

function cancelOppEdit() {
  editingOppId = null;
  document.getElementById("opp-form-title").textContent = "Post an Opportunity";
  document.getElementById("opp-submit-btn").textContent = "Post Opportunity";
  document.getElementById("opp-cancel-btn").classList.add("d-none");
  document.getElementById("opp_organization").value = "";
  document.getElementById("opp_logo").value = "";
}

async function deleteOpportunity(id) {
  if (!confirm("Delete this opportunity?")) return;
  await api(`/opportunities/${id}`, { method: "DELETE" });
  loadOpportunities();
}

// ===================== REVIEWS =====================

async function loadReviews() {
  const reviews = await api("/admin/reviews");
  document.getElementById("reviews-table").innerHTML = reviews.map(r => `
    <tr>
      <td>${escapeHtml(r.book_title || "Book #" + r.book_id)}</td>
      <td>${escapeHtml(r.reviewer_name)}</td>
      <td>${r.rating} ★</td>
      <td class="small">${escapeHtml((r.review_text || "").slice(0, 100))}${(r.review_text || "").length > 100 ? "…" : ""}</td>
      <td><button class="btn btn-sm btn-outline-danger" onclick="deleteReview(${r.id})">Delete</button></td>
    </tr>
  `).join("") || `<tr><td colspan="5" class="text-muted">No reviews yet.</td></tr>`;
}

async function deleteReview(id) {
  if (!confirm("Delete this review?")) return;
  await api(`/community/reviews/${id}`, { method: "DELETE" });
  loadReviews();
  loadStats();
}

// ===================== DISCUSSIONS =====================

async function loadDiscussions() {
  const posts = await api("/admin/discussions");
  document.getElementById("discussions-table").innerHTML = posts.map(p => `
    <tr>
      <td>${escapeHtml(p.title)}${p.is_pinned ? " 📌" : ""}</td>
      <td>${escapeHtml(p.author_name)}</td>
      <td>${escapeHtml(p.category)}</td>
      <td>${p.reply_count}</td>
      <td>${p.is_removed ? '<span class="text-danger">Removed</span>' : "Active"}</td>
      <td>
        <button class="btn btn-sm btn-outline-secondary" onclick="pinDiscussion(${p.id})">${p.is_pinned ? "Unpin" : "Pin"}</button>
        <button class="btn btn-sm btn-outline-danger" onclick="removeDiscussion(${p.id})">Remove</button>
      </td>
    </tr>
  `).join("") || `<tr><td colspan="6" class="text-muted">No discussions yet.</td></tr>`;
}

async function pinDiscussion(id) {
  await api(`/community/discussions/${id}/pin`, { method: "PUT" });
  loadDiscussions();
}

async function removeDiscussion(id) {
  if (!confirm("Remove this discussion post?")) return;
  await api(`/community/discussions/${id}`, { method: "DELETE" });
  loadDiscussions();
  loadStats();
}

// ===================== CERTIFICATES =====================

async function loadCertificates() {
  const certs = await api("/admin/certificates");
  document.getElementById("certificates-table").innerHTML = certs.map(c => `
    <tr>
      <td>${c.id}</td>
      <td>${c.user_name || "#" + c.user_id}</td>
      <td>${c.certificate_type}</td>
      <td>${c.title}</td>
      <td>${new Date(c.issued_at).toLocaleDateString()}</td>
      <td>${c.revoked ? `<span class="text-danger">Revoked${c.revoked_reason ? ": " + c.revoked_reason : ""}</span>` : "Active"}</td>
    </tr>
  `).join("") || `<tr><td colspan="6" class="text-muted">No certificates issued yet.</td></tr>`;
}

async function issueCertificate() {
  const userId = document.getElementById("issue_user_id").value;
  const certType = document.getElementById("issue_cert_type").value;
  const title = document.getElementById("issue_cert_title").value;
  if (!userId || !certType || !title) { showAlert("issue-cert-alert", "All fields are required."); return; }
  try {
    const params = new URLSearchParams({ user_id: userId, certificate_type: certType, title });
    await api(`/certificates/issue?${params.toString()}`, { method: "POST" });
    showAlert("issue-cert-alert", "Certificate issued.", "success");
    document.getElementById("issue_user_id").value = "";
    document.getElementById("issue_cert_type").value = "";
    document.getElementById("issue_cert_title").value = "";
    loadCertificates();
    loadStats();
  } catch (err) {
    showAlert("issue-cert-alert", err.message);
  }
}

async function revokeCertificate() {
  const id = document.getElementById("cert-id-input").value;
  if (!id) return;
  const reason = prompt("Reason for revoking (optional):") || "";
  try {
    await api(`/certificates/${id}/revoke?reason=${encodeURIComponent(reason)}`, { method: "PUT" });
    showAlert("cert-action-alert", "Certificate revoked.", "success");
    loadCertificates();
  } catch (err) {
    showAlert("cert-action-alert", err.message);
  }
}

async function reinstateCertificate() {
  const id = document.getElementById("cert-id-input").value;
  if (!id) return;
  try {
    await api(`/certificates/${id}/reinstate`, { method: "PUT" });
    showAlert("cert-action-alert", "Certificate reinstated.", "success");
    loadCertificates();
  } catch (err) {
    showAlert("cert-action-alert", err.message);
  }
}

// ===================== BROADCAST =====================

async function sendBroadcast() {
  const message = document.getElementById("broadcast-message").value.trim();
  if (!message) return;
  try {
    const r = await api("/notifications/broadcast", {
      method: "POST", body: JSON.stringify({ notif_type: "announcement", message }),
    });
    showAlert("broadcast-alert", r.message, "success");
    document.getElementById("broadcast-message").value = "";
  } catch (err) {
    showAlert("broadcast-alert", err.message);
  }
}

// ===================== REPORTS =====================

async function loadReports(status = "pending") {
  const reports = await api(`/reports?status=${status}`);
  const el = document.getElementById("reports-list");
  if (!reports.length) { el.innerHTML = `<p class="text-muted">No reports found.</p>`; return; }
  el.innerHTML = reports.map(r => `
    <div class="card card-rc p-3 mb-2">
      <div class="d-flex justify-content-between flex-wrap gap-2">
        <div>
          <span class="category-pill">${escapeHtml(r.content_type)}</span>
          <span class="text-muted small ms-2">reported by ${escapeHtml(r.reporter_name)} · ${new Date(r.created_at).toLocaleString()}</span>
          ${r.status !== "pending" ? `<span class="badge bg-secondary ms-2">${escapeHtml(r.status)}</span>` : ""}
          ${!r.content_exists ? `<span class="badge bg-secondary ms-2">content already removed</span>` : ""}
        </div>
        ${r.status === "pending" ? `
        <div>
          <button class="btn btn-sm btn-outline-secondary" onclick="resolveReport(${r.id}, 'dismissed')">Dismiss</button>
          <button class="btn btn-sm btn-outline-secondary" onclick="resolveReport(${r.id}, 'reviewed')">Mark Reviewed</button>
          ${r.content_exists ? `<button class="btn btn-sm btn-outline-danger" onclick="removeReportedContent(${r.id})">Remove Content</button>` : ""}
        </div>` : ""}
      </div>
      <p class="mb-1 mt-2 small"><strong>Reason:</strong> ${escapeHtml(r.reason)}${r.content_id ? ` (content id: ${r.content_id})` : ""}</p>
      ${r.content_preview ? `<p class="mb-0 small bg-light p-2 rounded"><strong>${escapeHtml(r.content_author || "Unknown")} wrote:</strong> "${escapeHtml(r.content_preview)}"</p>` : ""}
    </div>
  `).join("");
}

async function resolveReport(id, status) {
  await api(`/reports/${id}/resolve?status=${status}`, { method: "PUT" });
  loadReports("pending");
  loadStats();
}

async function removeReportedContent(id) {
  if (!confirm("Remove the reported content and mark this report reviewed? This cannot be undone.")) return;
  await api(`/reports/${id}/remove-content`, { method: "POST" });
  loadReports("pending");
  loadStats();
  loadDiscussions();
  loadReviews();
}

// ===================== DONATIONS =====================

async function loadDonations() {
  const acks = await api("/donations");
  const el = document.getElementById("donations-list");
  if (!acks.length) { el.innerHTML = `<p class="text-muted">No donation notes yet.</p>`; return; }
  el.innerHTML = acks.map(a => `
    <div class="card card-rc p-3 mb-2">
      <div class="d-flex justify-content-between flex-wrap gap-2">
        <div>
          <strong>${a.donor_name || "Anonymous"}</strong>
          ${a.donor_email ? `<span class="text-muted small ms-2">${a.donor_email}</span>` : ""}
          <span class="text-muted small ms-2">${new Date(a.created_at).toLocaleString()}</span>
          ${a.reviewed ? `<span class="badge bg-secondary ms-2">reviewed</span>` : ""}
        </div>
        ${!a.reviewed ? `<button class="btn btn-sm btn-outline-secondary" onclick="markDonationReviewed(${a.id})">Mark Reviewed</button>` : ""}
      </div>
      ${a.amount_naira ? `<p class="mb-1 mt-2 small">Approx. amount: ₦${a.amount_naira.toLocaleString()}</p>` : ""}
      ${a.note ? `<p class="mb-0 small bg-light p-2 rounded">${a.note}</p>` : ""}
    </div>
  `).join("");
}

async function markDonationReviewed(id) {
  await api(`/donations/${id}/reviewed`, { method: "PUT" });
  loadDonations();
}

// ===================== BULK IMPORT =====================

async function submitBulkImport() {
  const file_content = document.getElementById("import-csv").value;
  try {
    const r = await api("/library/books/bulk-import", { method: "POST", body: JSON.stringify({ file_content }) });
    showAlert("import-alert", `Imported ${r.created} books, skipped ${r.skipped}. ${r.errors.length ? "Errors: " + r.errors.join("; ") : ""}`, "success");
    loadBooks();
    loadStats();
  } catch (err) {
    showAlert("import-alert", err.message);
  }
}

// ===================== AUDIT LOG =====================

async function loadAuditLog() {
  const logs = await api("/admin/audit-logs").catch(() => []);
  const el = document.getElementById("audit-table");
  if (!logs.length) { el.innerHTML = `<tr><td colspan="5" class="text-muted">No audit entries yet (Admin only).</td></tr>`; return; }
  el.innerHTML = logs.map(l => `
    <tr>
      <td>${new Date(l.created_at).toLocaleString()}</td>
      <td>${l.actor_name || "System"}</td>
      <td>${l.action}</td>
      <td>${l.target_type}${l.target_id ? " #" + l.target_id : ""}</td>
      <td>${l.details || ""}</td>
    </tr>
  `).join("");
}
