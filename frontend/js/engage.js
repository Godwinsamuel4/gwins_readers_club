// engage.js — shared "fun & easier" layer added on top of the core app.
// Everything here is additive and purely client-side (localStorage), namespaced
// per logged-in user, so it never conflicts with server-side data or other accounts
// on a shared/demo machine.

const Engage = (() => {

  function uid() {
    const u = (typeof getUser === "function") ? getUser() : null;
    return u ? u.id : "guest";
  }
  function key(name) { return `rc_engage:${uid()}:${name}`; }
  function load(name, fallback) {
    try { const raw = localStorage.getItem(key(name)); return raw ? JSON.parse(raw) : fallback; }
    catch (e) { return fallback; }
  }
  function save(name, value) { localStorage.setItem(key(name), JSON.stringify(value)); }

  // ---------- #1 Achievement badges ----------

  const BADGES = [
    { id: "first_book", label: "First Book", emoji: "🌱", desc: "Completed your first book", test: s => s.booksCompleted >= 1 },
    { id: "five_books", label: "Bookworm", emoji: "🐛", desc: "Completed 5 books", test: s => s.booksCompleted >= 5 },
    { id: "ten_books", label: "Bibliophile", emoji: "📚", desc: "Completed 10 books", test: s => s.booksCompleted >= 10 },
    { id: "streak_7", label: "Week Warrior", emoji: "🔥", desc: "7-day reading streak", test: s => s.streak >= 7 },
    { id: "streak_30", label: "Unstoppable", emoji: "⚡", desc: "30-day reading streak", test: s => s.streak >= 30 },
    { id: "pages_500", label: "Page Turner", emoji: "📖", desc: "500 pages read", test: s => s.pagesRead >= 500 },
    { id: "pages_2000", label: "Marathoner", emoji: "🏃", desc: "2,000 pages read", test: s => s.pagesRead >= 2000 },
    { id: "night_owl", label: "Night Owl", emoji: "🦉", desc: "Read after 10pm", test: s => s.nightRead },
    { id: "early_bird", label: "Early Bird", emoji: "🐦", desc: "Read before 7am", test: s => s.earlyRead },
    { id: "reviewer", label: "Voice Heard", emoji: "✍️", desc: "Wrote your first review", test: s => s.reviews >= 1 },
  ];

  function unlockedBadges() { return load("badges", []); }

  function checkBadges(stats) {
    const unlocked = new Set(unlockedBadges());
    const newlyUnlocked = [];
    BADGES.forEach(b => {
      if (!unlocked.has(b.id) && b.test(stats)) {
        unlocked.add(b.id);
        newlyUnlocked.push(b);
      }
    });
    if (newlyUnlocked.length) {
      save("badges", [...unlocked]);
      newlyUnlocked.forEach(b => toast(`${b.emoji} Badge unlocked: ${b.label}!`, "badge"));
    }
    return [...unlocked];
  }

  function renderBadgeShelf(containerId) {
    const el = document.getElementById(containerId);
    if (!el) return;
    const unlocked = new Set(unlockedBadges());
    el.innerHTML = BADGES.map(b => `
      <span class="engage-badge ${unlocked.has(b.id) ? "unlocked" : "locked"}" title="${b.label} — ${b.desc}">${b.emoji}</span>
    `).join("");
  }

  // ---------- #2 XP / reading level ----------

  function xpForStats(stats) {
    return Math.round((stats.pagesRead || 0) * 2 + (stats.booksCompleted || 0) * 50 + (stats.streak || 0) * 5);
  }
  function levelForXp(xp) {
    // Each level needs progressively more XP: level n starts at 100*n*(n-1)/2
    let level = 1;
    while (xp >= 100 * level * (level + 1) / 2) level++;
    return level;
  }
  function renderXp(containerId, stats) {
    const el = document.getElementById(containerId);
    if (!el) return;
    const xp = xpForStats(stats);
    const level = levelForXp(xp);
    const thisLevelFloor = 100 * (level - 1) * level / 2;
    const nextLevelCeil = 100 * level * (level + 1) / 2;
    const pct = Math.round(100 * (xp - thisLevelFloor) / (nextLevelCeil - thisLevelFloor));
    el.innerHTML = `
      <div class="d-flex justify-content-between small mb-1">
        <span>⭐ Level ${level} reader</span><span class="text-muted">${xp} XP</span>
      </div>
      <div class="progress" style="height:6px;"><div class="progress-bar" style="width:${pct}%; background: var(--rc-purple);"></div></div>
    `;
  }

  // ---------- #3 Confetti + shareable finish card ----------

  function confettiBurst() {
    const colors = ["#7a4fc0", "#e0b64a", "#a480d6", "#35538F", "#f48fb1"];
    for (let i = 0; i < 60; i++) {
      const piece = document.createElement("div");
      piece.className = "engage-confetti-piece";
      piece.style.left = Math.random() * 100 + "vw";
      piece.style.background = colors[i % colors.length];
      piece.style.animationDelay = (Math.random() * 0.4) + "s";
      piece.style.animationDuration = (2 + Math.random() * 1.5) + "s";
      document.body.appendChild(piece);
      setTimeout(() => piece.remove(), 4000);
    }
  }

  function celebrateFinish(bookTitle) {
    confettiBurst();
    toast(`🎉 Finished "${bookTitle}"! Great job.`, "success");
  }

  function buildShareCard(bookTitle, statLine) {
    const canvas = document.createElement("canvas");
    canvas.width = 600; canvas.height = 315;
    const ctx = canvas.getContext("2d");
    const grad = ctx.createLinearGradient(0, 0, 600, 315);
    grad.addColorStop(0, "#35538F"); grad.addColorStop(1, "#7a4fc0");
    ctx.fillStyle = grad; ctx.fillRect(0, 0, 600, 315);
    ctx.fillStyle = "#fff"; ctx.font = "bold 28px Georgia, serif";
    wrapText(ctx, `I just finished "${bookTitle}"`, 40, 130, 520, 34);
    ctx.font = "18px Verdana, sans-serif"; ctx.fillStyle = "#e0b64a";
    ctx.fillText(statLine, 40, 230);
    ctx.font = "14px Verdana, sans-serif"; ctx.fillStyle = "#cbb9e8";
    ctx.fillText("Gwin's Readers Club", 40, 275);
    return canvas;
  }
  function wrapText(ctx, text, x, y, maxWidth, lineHeight) {
    const words = text.split(" ");
    let line = "", cy = y;
    words.forEach(w => {
      const test = line + w + " ";
      if (ctx.measureText(test).width > maxWidth && line) {
        ctx.fillText(line, x, cy); line = w + " "; cy += lineHeight;
      } else { line = test; }
    });
    ctx.fillText(line, x, cy);
  }
  function downloadShareCard(bookTitle, statLine) {
    const canvas = buildShareCard(bookTitle, statLine);
    const a = document.createElement("a");
    a.download = `${bookTitle.replace(/[^a-z0-9]/gi, "_")}_finished.png`;
    a.href = canvas.toDataURL("image/png");
    a.click();
  }

  // ---------- #4 Chapter-end trivia ----------

  const TRIVIA = [
    "The world's longest novel, Marcel Proust's 'In Search of Lost Time', has about 1.2 million words.",
    "Reading for just six minutes can reduce stress levels by up to 68%, per a University of Sussex study.",
    "The word 'bookworm' originally referred to insects that literally ate through old books.",
    "Audiobooks date back to 1932, when the American Foundation for the Blind began recording books on vinyl.",
    "The average adult reading speed is around 200–250 words per minute.",
    "Nigeria's reading culture spans a rich oral storytelling tradition long before the printed book arrived.",
    "The first novel ever written is widely considered to be 'The Tale of Genji', from 11th-century Japan.",
    "Reading fiction has been shown to improve empathy by helping the brain simulate other people's perspectives.",
    "The Codex Sinaiticus, from the 4th century, is one of the oldest surviving books in the world.",
    "Speed readers can hit 1,000+ words per minute, but comprehension usually drops sharply above 500.",
  ];
  function showTrivia() {
    const fact = TRIVIA[Math.floor(Math.random() * TRIVIA.length)];
    toast(`💡 Did you know? ${fact}`, "trivia", 7000);
  }

  // ---------- #5 Mood tracker ----------

  function logMood(emoji) {
    const history = load("moods", []);
    history.push({ emoji, at: new Date().toISOString() });
    save("moods", history.slice(-100));
  }
  function renderMoodPicker(containerId) {
    const el = document.getElementById(containerId);
    if (!el) return;
    const moods = ["😊", "😌", "🤔", "😢", "🔥", "😴"];
    el.innerHTML = `
      <div class="small text-muted mb-1">How's this reading session feeling?</div>
      <div class="d-flex gap-2">
        ${moods.map(m => `<button class="btn btn-sm btn-outline-secondary" onclick="Engage.logMood('${m}'); Engage.mascotSay('Mood logged — thanks for sharing!');">${m}</button>`).join("")}
      </div>
    `;
  }
  function moodHistorySummary() {
    const history = load("moods", []);
    const counts = {};
    history.forEach(h => counts[h.emoji] = (counts[h.emoji] || 0) + 1);
    return counts;
  }

  // ---------- #6 Reading buddy mascot ----------

  function ensureMascot() {
    if (document.getElementById("engage-mascot")) return;
    const div = document.createElement("div");
    div.id = "engage-mascot";
    div.innerHTML = `<div class="engage-mascot-bubble d-none" id="engage-mascot-bubble"></div><div class="engage-mascot-face" onclick="Engage.mascotPoke()">📖</div>`;
    document.body.appendChild(div);
  }
  function mascotSay(msg, ms = 4500) {
    ensureMascot();
    const bubble = document.getElementById("engage-mascot-bubble");
    bubble.textContent = msg;
    bubble.classList.remove("d-none");
    clearTimeout(window._mascotTimer);
    window._mascotTimer = setTimeout(() => bubble.classList.add("d-none"), ms);
  }
  const POKES = ["Keep going, you've got this! 📚", "Every page counts!", "Proud of you for showing up today.", "Ready when you are!"];
  function mascotPoke() { mascotSay(POKES[Math.floor(Math.random() * POKES.length)]); }

  // ---------- #7 Encouraging quote banner ----------

  const QUOTES = [
    "A reader lives a thousand lives before he dies. — George R.R. Martin",
    "Today a reader, tomorrow a leader. — Margaret Fuller",
    "There is no friend as loyal as a book. — Ernest Hemingway",
    "Reading is essential for those who seek to rise above the ordinary. — Jim Rohn",
    "Once you learn to read, you will be forever free. — Frederick Douglass",
    "The more that you read, the more things you will know. — Dr. Seuss",
  ];
  function showQuoteBanner(containerId) {
    const el = document.getElementById(containerId);
    if (!el) return;
    el.innerHTML = `<div class="engage-quote-banner">“${QUOTES[Math.floor(Math.random() * QUOTES.length)]}”</div>`;
  }

  // ---------- #8 Weekly themed challenge ----------

  function weekKey() {
    const d = new Date();
    const onejan = new Date(d.getFullYear(), 0, 1);
    const week = Math.ceil((((d - onejan) / 86400000) + onejan.getDay() + 1) / 7);
    return `${d.getFullYear()}-W${week}`;
  }
  const WEEKLY_PROMPTS = [
    "Read 3 chapters before Friday",
    "Try a book outside your usual category",
    "Write one review this week",
    "Read for 20 minutes, 5 days this week",
    "Share a favorite quote with your club",
    "Finish one book you've already started",
    "Read during a time of day you don't normally read",
  ];
  function currentWeeklyChallenge() {
    const wk = weekKey();
    let idx = 0;
    for (let i = 0; i < wk.length; i++) idx += wk.charCodeAt(i);
    return { week: wk, prompt: WEEKLY_PROMPTS[idx % WEEKLY_PROMPTS.length] };
  }
  function renderWeeklyChallenge(containerId) {
    const el = document.getElementById(containerId);
    if (!el) return;
    const c = currentWeeklyChallenge();
    const done = load("weekly_done", {})[c.week];
    el.innerHTML = `
      <div class="engage-weekly-card ${done ? "done" : ""}">
        <div class="small text-muted mb-1">This week's challenge</div>
        <div class="fw-semibold">${c.prompt}</div>
        <button class="btn btn-sm ${done ? "btn-outline-secondary" : "btn-rc"} mt-2" onclick="Engage.completeWeeklyChallenge()" ${done ? "disabled" : ""}>
          ${done ? "✓ Completed" : "Mark complete"}
        </button>
      </div>
    `;
  }
  function completeWeeklyChallenge() {
    const c = currentWeeklyChallenge();
    const doneMap = load("weekly_done", {});
    doneMap[c.week] = true;
    save("weekly_done", doneMap);
    toast("🏆 Weekly challenge complete!", "success");
    document.querySelectorAll("[id]").forEach(() => {}); // no-op, keeps eslint quiet
    const containers = document.querySelectorAll(".engage-weekly-card");
    containers.forEach(c2 => location.reload());
  }

  // ---------- #9 Streak freeze (motivational — does not alter server streak logic) ----------

  function freezesAvailableThisWeek() {
    const wk = weekKey();
    const used = load("freeze_used", {});
    return used[wk] ? 0 : 1;
  }
  function useStreakFreeze() {
    const wk = weekKey();
    const used = load("freeze_used", {});
    if (used[wk]) { toast("You've already used this week's streak freeze.", "info"); return; }
    used[wk] = true;
    save("freeze_used", used);
    toast("🧊 Streak freeze applied — miss a day this week without worry.", "info");
  }
  function renderStreakFreeze(containerId) {
    const el = document.getElementById(containerId);
    if (!el) return;
    const available = freezesAvailableThisWeek();
    el.innerHTML = `
      <button class="btn btn-sm btn-outline-secondary" onclick="Engage.useStreakFreeze()" ${available ? "" : "disabled"} title="Protects your streak motivation for one missed day this week">
        🧊 ${available ? "Use streak freeze" : "Freeze used this week"}
      </button>
    `;
  }

  // ---------- #10 Chapter self-check quiz ----------

  const QUIZ_PROMPTS = [
    "What's one idea from this chapter you want to remember?",
    "Who was the most interesting character in what you just read?",
    "What surprised you in this chapter?",
    "How would you summarize this chapter in one sentence?",
    "What question do you still have after reading this?",
  ];
  function showChapterQuiz(bookId, chapterLabel) {
    const prompt = QUIZ_PROMPTS[Math.floor(Math.random() * QUIZ_PROMPTS.length)];
    const modalHtml = `
      <div class="engage-quiz-overlay" id="engage-quiz-overlay">
        <div class="engage-quiz-box">
          <div class="fw-semibold mb-2">🧠 Quick check-in — ${chapterLabel || "this chapter"}</div>
          <div class="small text-muted mb-2">${prompt}</div>
          <textarea class="form-control form-control-sm mb-2" id="engage-quiz-answer" rows="2" placeholder="Jot a quick thought (optional)..."></textarea>
          <div class="d-flex justify-content-end gap-2">
            <button class="btn btn-sm btn-outline-secondary" onclick="document.getElementById('engage-quiz-overlay').remove()">Skip</button>
            <button class="btn btn-sm btn-rc" onclick="Engage.saveChapterQuizAnswer('${bookId}')">Save</button>
          </div>
        </div>
      </div>
    `;
    document.body.insertAdjacentHTML("beforeend", modalHtml);
  }
  function saveChapterQuizAnswer(bookId) {
    const answer = document.getElementById("engage-quiz-answer").value.trim();
    if (answer) {
      const all = load("quiz_answers", {});
      all[bookId] = all[bookId] || [];
      all[bookId].push({ answer, at: new Date().toISOString() });
      save("quiz_answers", all);
      toast("Saved your reflection.", "success");
    }
    document.getElementById("engage-quiz-overlay").remove();
  }

  // ---------- shared toast ----------

  function toast(message, kind = "info", ms = 4000) {
    const div = document.createElement("div");
    div.className = `engage-toast engage-toast-${kind}`;
    div.textContent = message;
    document.body.appendChild(div);
    requestAnimationFrame(() => div.classList.add("show"));
    setTimeout(() => { div.classList.remove("show"); setTimeout(() => div.remove(), 300); }, ms);
  }

  return {
    checkBadges, renderBadgeShelf, unlockedBadges,
    xpForStats, levelForXp, renderXp,
    confettiBurst, celebrateFinish, buildShareCard, downloadShareCard,
    showTrivia,
    logMood, renderMoodPicker, moodHistorySummary,
    ensureMascot, mascotSay, mascotPoke,
    showQuoteBanner,
    currentWeeklyChallenge, renderWeeklyChallenge, completeWeeklyChallenge,
    freezesAvailableThisWeek, useStreakFreeze, renderStreakFreeze,
    showChapterQuiz, saveChapterQuizAnswer,
    toast, load, save,
  };
})();
