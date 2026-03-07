/**
 * manual-syllabus.js
 * ==================
 * Loads the saved Unit → Topic → Subtopic syllabus structure from the backend
 * and renders it on the page, with a "Start Test" button for each subtopic.
 *
 * URL parameter: ?syllabus_id=<number>
 */

/* ── Helpers ──────────────────────────────────────────── */
function esc(str) {
    return String(str)
        .replace(/&/g, '&amp;').replace(/</g, '&lt;')
        .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

function getParam(name) {
    return new URLSearchParams(window.location.search).get(name);
}

/* ── Elements ─────────────────────────────────────────── */
const loadingEl = document.getElementById('ms-loading');
const errorEl = document.getElementById('ms-error');
const errorText = document.getElementById('ms-error-text');
const treeEl = document.getElementById('ms-tree');
const titleEl = document.getElementById('ms-title');
const subtitleEl = document.getElementById('ms-subtitle');

/* ── Show / hide helpers ──────────────────────────────── */
function showLoading() {
    loadingEl.classList.remove('hidden');
    errorEl.classList.add('hidden');
    treeEl.classList.add('hidden');
}

function showError(msg) {
    loadingEl.classList.add('hidden');
    errorEl.classList.remove('hidden');
    errorText.textContent = msg || 'Failed to load syllabus.';
    treeEl.classList.add('hidden');
}

function showTree() {
    loadingEl.classList.add('hidden');
    errorEl.classList.add('hidden');
    treeEl.classList.remove('hidden');
}

/* ── Render ───────────────────────────────────────────── */
function renderSyllabus(data) {
    const { syllabus, units } = data;

    titleEl.textContent = syllabus.name;

    const totalUnits = units.length;
    const totalTopics = units.reduce((a, u) => a + u.topics.length, 0);
    const totalSubs = units.reduce((a, u) =>
        a + u.topics.reduce((b, t) => b + t.subtopics.length, 0), 0);

    subtitleEl.textContent =
        `${totalUnits} unit${totalUnits !== 1 ? 's' : ''} · ` +
        `${totalTopics} topic${totalTopics !== 1 ? 's' : ''} · ` +
        `${totalSubs} subtopic${totalSubs !== 1 ? 's' : ''}`;

    treeEl.innerHTML = '';

    units.forEach((unit, uIdx) => {
        /* ── Unit card ───────────────────────── */
        const card = document.createElement('div');
        card.className = 'ms-unit-card animate-slide-up';
        card.style.animationDelay = `${uIdx * 0.08}s`;

        // Unit header
        const header = document.createElement('div');
        header.className = 'ms-unit-header';
        header.innerHTML = `
            <span class="ms-unit-badge">${uIdx + 1}</span>
            <span class="ms-unit-name">${esc(unit.name)}</span>`;
        card.appendChild(header);

        if (unit.topics.length === 0) {
            const empty = document.createElement('p');
            empty.className = 'ms-empty';
            empty.style.padding = '1rem 1.25rem';
            empty.textContent = 'No topics in this unit.';
            card.appendChild(empty);
        }

        /* ── Topics ─────────────────────────── */
        unit.topics.forEach(topic => {
            const block = document.createElement('div');
            block.className = 'ms-topic-block';

            // Topic heading
            const topicName = document.createElement('div');
            topicName.className = 'ms-topic-name';
            topicName.textContent = esc(topic.name);
            block.appendChild(topicName);

            // Subtopics
            const subsCont = document.createElement('div');
            subsCont.className = 'ms-subtopics';

            if (topic.subtopics.length === 0) {
                const empty = document.createElement('p');
                empty.className = 'ms-empty';
                empty.textContent = 'No subtopics.';
                subsCont.appendChild(empty);
            }

            topic.subtopics.forEach(sub => {
                const row = createSubtopicRow(sub);
                subsCont.appendChild(row);
            });

            block.appendChild(subsCont);
            card.appendChild(block);
        });

        treeEl.appendChild(card);
    });

    showTree();
}

/* ── Build a single subtopic row with Start Test button ── */
function createSubtopicRow(sub) {
    const row = document.createElement('div');
    row.className = 'ms-subtopic-row';
    row.id = `sub-row-${sub.id}`;

    // Left: name + status badge
    const nameWrap = document.createElement('span');
    nameWrap.className = 'ms-subtopic-name';
    nameWrap.innerHTML = `
        <span class="ms-subtopic-dot"></span>
        <span class="ms-subtopic-text">${esc(sub.name)}</span>`;

    const statusBadge = document.createElement('span');
    statusBadge.className = `ms-status-badge ${sub.status}`;
    statusBadge.id = `badge-${sub.id}`;
    statusBadge.textContent = sub.status === 'verified' ? '✓ Verified' : 'Pending';

    // Right: score chip (if already tested) + Start Test button
    const right = document.createElement('span');
    right.style.display = 'flex';
    right.style.alignItems = 'center';
    right.style.gap = '0.5rem';
    right.style.flexShrink = '0';

    if (sub.score !== null && sub.score !== undefined) {
        const scoreChip = document.createElement('span');
        scoreChip.className = 'ms-score-chip';
        scoreChip.id = `score-${sub.id}`;
        scoreChip.textContent = `${sub.score}%`;
        right.appendChild(scoreChip);
    }

    const startBtn = document.createElement('button');
    startBtn.className = 'ms-start-btn';
    startBtn.id = `start-btn-${sub.id}`;
    startBtn.innerHTML = `
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
            <polygon points="5 3 19 12 5 21 5 3"/>
        </svg>
        Start Test`;

    startBtn.addEventListener('click', () => {
        // Navigate to the existing test page with the subtopic's topic ID
        window.location.href = `../test/test.html?topic_id=${sub.id}`;
    });

    right.appendChild(startBtn);

    row.appendChild(nameWrap);
    row.appendChild(statusBadge);
    row.appendChild(right);

    return row;
}

/* ── Main load ────────────────────────────────────────── */
async function loadSyllabus() {
    const syllabusId = getParam('syllabus_id');
    if (!syllabusId) {
        showError('No syllabus ID provided. Please go back and select a syllabus.');
        return;
    }

    showLoading();

    try {
        const data = await API.getManualSyllabusStructure(syllabusId);
        if (data.error) throw new Error(data.error);
        renderSyllabus(data);
    } catch (err) {
        console.error('Load syllabus error:', err);
        showError(err.message || 'Failed to load the syllabus. Please try again.');
    }
}

/* ── Init ─────────────────────────────────────────────── */
document.addEventListener('DOMContentLoaded', () => {
    State.load();
    if (!State.user) {
        window.location.href = '../auth/auth.html';
        return;
    }
    initLayout();
    loadSyllabus();
});
