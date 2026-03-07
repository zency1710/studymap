/**
 * upload.js
 * =========
 * Three sections:
 *  1. setupTabs()        – switches between PDF and Manual panels
 *  2. setupUpload()      – original PDF upload logic (UNCHANGED)
 *  3. setupManualEntry() – new Unit → Topic → Subtopic builder with save
 */

/* ===========================================================
   SECTION 1 — TAB SWITCHER
   =========================================================== */
function setupTabs() {
    const tabPdf = document.getElementById('tab-pdf');
    const tabManual = document.getElementById('tab-manual');
    const panelPdf = document.getElementById('panel-pdf');
    const panelManual = document.getElementById('panel-manual');

    function activateTab(which) {
        const isPdf = (which === 'pdf');
        tabPdf.classList.toggle('active', isPdf);
        tabManual.classList.toggle('active', !isPdf);
        tabPdf.setAttribute('aria-selected', isPdf ? 'true' : 'false');
        tabManual.setAttribute('aria-selected', isPdf ? 'false' : 'true');
        panelPdf.classList.toggle('hidden', !isPdf);
        panelManual.classList.toggle('hidden', isPdf);
    }

    tabPdf.addEventListener('click', () => activateTab('pdf'));
    tabManual.addEventListener('click', () => activateTab('manual'));
}


/* ===========================================================
   SECTION 2 — PDF UPLOAD  (original code, 100% unchanged)
   =========================================================== */
function setupUpload() {
    const zone = document.getElementById('upload-zone');
    const zoneContent = document.getElementById('upload-zone-content');
    const filePreview = document.getElementById('file-preview');
    const fileInput = document.getElementById('file-input');
    const browseBtn = document.getElementById('browse-btn');
    const fileName = document.getElementById('file-name');
    const fileSize = document.getElementById('file-size');
    const removeFile = document.getElementById('remove-file');
    const uploadBtn = document.getElementById('upload-btn');
    const uploadProgress = document.getElementById('upload-progress');
    const uploadStatus = document.getElementById('upload-status');
    const uploadPercentage = document.getElementById('upload-percentage');
    const progressFill = document.getElementById('progress-fill');

    let selectedFile = null;

    browseBtn.onclick = () => fileInput.click();

    // Bind click on text area as well, but prevent double triggering if button inside is clicked
    zoneContent.onclick = (e) => {
        if (e.target !== browseBtn) {
            fileInput.click();
        }
    };

    if (zone) {
        zone.ondragover = (e) => {
            e.preventDefault();
            zone.classList.add('drag-over');
        };

        zone.ondragleave = (e) => {
            e.preventDefault();
            zone.classList.remove('drag-over');
        };

        zone.ondrop = (e) => {
            e.preventDefault();
            zone.classList.remove('drag-over');
            const file = e.dataTransfer.files[0];
            if (file && file.type === 'application/pdf') {
                selectFile(file);
            } else {
                Toast.show('Invalid file type', 'Please upload a PDF file', 'destructive');
            }
        };
    }

    fileInput.onchange = (e) => {
        const file = e.target.files[0];
        if (file && file.type === 'application/pdf') {
            selectFile(file);
        } else {
            Toast.show('Invalid file type', 'Please upload a PDF file', 'destructive');
        }
    };

    function selectFile(file) {
        selectedFile = file;
        fileName.textContent = file.name;
        fileSize.textContent = (file.size / 1024 / 1024).toFixed(2) + ' MB';
        zoneContent.classList.add('hidden');
        filePreview.classList.remove('hidden');
    }

    removeFile.onclick = (e) => {
        e.stopPropagation();
        selectedFile = null;
        zoneContent.classList.remove('hidden');
        filePreview.classList.add('hidden');
        fileInput.value = '';
    };

    uploadBtn.onclick = async () => {
        if (!selectedFile) return;

        const token = localStorage.getItem('studymap-token');
        if (!token) {
            Toast.show('Authentication error', 'Please log in again', 'destructive');
            setTimeout(() => window.location.href = '../auth/auth.html', 2000);
            return;
        }

        uploadBtn.classList.add('hidden');
        uploadProgress.classList.remove('hidden');
        removeFile.classList.add('hidden');

        const formData = new FormData();
        formData.append('file', selectedFile);

        let currentProgress = 0;
        uploadStatus.textContent = 'Uploading and analyzing...';
        const progressInterval = setInterval(() => {
            if (currentProgress < 90) {
                const increment = Math.max(0.5, (90 - currentProgress) * 0.1);
                currentProgress += increment;
                const displayValue = Math.min(99, Math.round(currentProgress));
                uploadPercentage.textContent = displayValue + '%';
                progressFill.style.width = displayValue + '%';
            }
        }, 500);

        try {
            // Use the API service
            const result = await API.uploadSyllabus(selectedFile, selectedFile.name.replace('.pdf', ''));

            clearInterval(progressInterval);

            if (result.error) {
                throw new Error(result.error);
            }

            uploadStatus.textContent = 'Upload successful!';
            uploadPercentage.textContent = '100%';
            progressFill.style.width = '100%';

            Toast.show('Success', 'Syllabus uploaded and analyzed!');

            setTimeout(() => {
                window.location.href = `../extract/extract.html?syllabus_id=${result.syllabus.id}`;
            }, 1500);

        } catch (error) {
            clearInterval(progressInterval);
            console.error('Upload error:', error);
            Toast.show('Upload failed', error.message, 'destructive');
            uploadBtn.classList.remove('hidden');
            uploadProgress.classList.add('hidden');
            removeFile.classList.remove('hidden');
            uploadPercentage.textContent = '0%';
            progressFill.style.width = '0%';
        }
    };
}


/* ===========================================================
   SECTION 3 — MANUAL ENTRY
   Unit name → stores as Subject row (unit label in UI)
   Topic name → stores as Topic row with parent_topic_id = NULL
   Subtopic name → stores as Topic row with parent_topic_id = topic_row.id

   In-memory data structure (mirroring DB):
   {
     unitName: string,
     topics: [
       { topicName: string, subtopics: [string, ...] }
     ]
   }[]
   =========================================================== */
function setupManualEntry() {

    /* ── DOM refs ───────────────────────────────────────────── */
    const inpSyllabusName = document.getElementById('inp-syllabus-name');
    const inpUnit = document.getElementById('inp-unit');
    const inpTopic = document.getElementById('inp-topic');
    const inpSubtopic = document.getElementById('inp-subtopic');
    const btnAddSubtopic = document.getElementById('btn-add-subtopic');
    const btnSave = document.getElementById('btn-save-syllabus');
    const previewCard = document.getElementById('preview-card');
    const treeEl = document.getElementById('man-tree');
    const badgeEl = document.getElementById('preview-badge');

    const errSyllabus = document.getElementById('err-syllabus-name');
    const errUnit = document.getElementById('err-unit');
    const errTopic = document.getElementById('err-topic');
    const errSubtopic = document.getElementById('err-subtopic');

    /* ── In-memory tree ─────────────────────────────────────── */
    // units = [{ unitName, topics: [{ topicName, subtopics: ['str',...] }] }]
    let units = [];

    /* ── Helpers ────────────────────────────────────────────── */

    /** Show or clear an inline validation error */
    function setErr(errEl, inputEl, msg) {
        if (msg) {
            errEl.textContent = msg;
            errEl.classList.remove('hidden');
            inputEl.classList.add('is-error');
        } else {
            errEl.classList.add('hidden');
            inputEl.classList.remove('is-error');
        }
    }

    /** Clear error on the moment the user starts typing */
    [inpSyllabusName, inpUnit, inpTopic, inpSubtopic].forEach(inp => {
        inp.addEventListener('input', () => {
            if (inp.value.trim()) inp.classList.remove('is-error');
        });
    });

    /** Escape HTML to prevent XSS in dynamically built tree */
    function esc(str) {
        return String(str)
            .replace(/&/g, '&amp;').replace(/</g, '&lt;')
            .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
    }

    /* ── Count total subtopics across all units ─────────────── */
    function totalSubtopics() {
        return units.reduce((acc, u) =>
            acc + u.topics.reduce((ta, t) => ta + t.subtopics.length, 0), 0);
    }

    /* ── Find-or-create helpers ─────────────────────────────── */
    function findOrCreateUnit(unitName) {
        let u = units.find(x => x.unitName.toLowerCase() === unitName.toLowerCase());
        if (!u) {
            u = { unitName, topics: [] };
            units.push(u);
        }
        return u;
    }

    function findOrCreateTopic(unit, topicName) {
        let t = unit.topics.find(x => x.topicName.toLowerCase() === topicName.toLowerCase());
        if (!t) {
            t = { topicName, subtopics: [] };
            unit.topics.push(t);
        }
        return t;
    }

    /* ── Re-render the preview tree ─────────────────────────── */
    function renderTree() {
        treeEl.innerHTML = '';

        units.forEach((unit, uIdx) => {
            // Unit block
            const unitDiv = document.createElement('div');
            unitDiv.className = 'tree-unit';

            // Unit header
            const header = document.createElement('div');
            header.className = 'tree-unit-header';
            header.innerHTML = `
                <span>${esc(unit.unitName)}</span>
                <button class="tree-unit-remove" title="Remove this unit" data-u="${uIdx}">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
                        <line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>
                    </svg>
                </button>`;
            unitDiv.appendChild(header);

            // Topics
            unit.topics.forEach((topic, tIdx) => {
                const topicDiv = document.createElement('div');
                topicDiv.className = 'tree-topic';

                // Topic heading
                const topicName = document.createElement('div');
                topicName.className = 'tree-topic-name';
                topicName.textContent = `Topic: ${topic.topicName}`;
                topicDiv.appendChild(topicName);

                // Subtopics list
                const subsContainer = document.createElement('div');
                subsContainer.className = 'tree-subtopics';

                topic.subtopics.forEach((sub, sIdx) => {
                    const row = document.createElement('div');
                    row.className = 'tree-subtopic-row';
                    row.innerHTML = `
                        <span class="tree-subtopic-name">
                            <span class="tree-subtopic-dot"></span>
                            <span class="tree-subtopic-text">${esc(sub)}</span>
                        </span>
                        <button class="tree-subtopic-remove"
                                title="Remove subtopic"
                                data-u="${uIdx}" data-t="${tIdx}" data-s="${sIdx}"
                                aria-label="Remove ${esc(sub)}">
                            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
                                <line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>
                            </svg>
                        </button>`;
                    subsContainer.appendChild(row);
                });

                topicDiv.appendChild(subsContainer);
                unitDiv.appendChild(topicDiv);
            });

            treeEl.appendChild(unitDiv);
        });

        // Bind remove buttons — unit
        treeEl.querySelectorAll('.tree-unit-remove').forEach(btn => {
            btn.addEventListener('click', () => {
                const uIdx = parseInt(btn.dataset.u, 10);
                units.splice(uIdx, 1);
                renderTree();
                updatePreview();
            });
        });

        // Bind remove buttons — subtopic
        treeEl.querySelectorAll('.tree-subtopic-remove').forEach(btn => {
            btn.addEventListener('click', () => {
                const uIdx = parseInt(btn.dataset.u, 10);
                const tIdx = parseInt(btn.dataset.t, 10);
                const sIdx = parseInt(btn.dataset.s, 10);
                units[uIdx].topics[tIdx].subtopics.splice(sIdx, 1);
                // Remove empty topics
                if (units[uIdx].topics[tIdx].subtopics.length === 0) {
                    units[uIdx].topics.splice(tIdx, 1);
                }
                // Remove empty units
                if (units[uIdx].topics.length === 0) {
                    units.splice(uIdx, 1);
                }
                renderTree();
                updatePreview();
            });
        });
    }

    /** Show/hide preview card, update badge count */
    function updatePreview() {
        const count = totalSubtopics();
        previewCard.style.display = count > 0 ? '' : 'none';
        badgeEl.textContent = `${count} ${count === 1 ? 'subtopic' : 'subtopics'}`;
    }

    /* ── ADD SUBTOPIC button ─────────────────────────────────── */
    btnAddSubtopic.addEventListener('click', () => {
        const unitVal = inpUnit.value.trim();
        const topicVal = inpTopic.value.trim();
        const subtopicVal = inpSubtopic.value.trim();

        // Validate all three
        let ok = true;
        if (!unitVal) { setErr(errUnit, inpUnit, 'Unit name cannot be empty.'); ok = false; }
        else { setErr(errUnit, inpUnit, ''); }
        if (!topicVal) { setErr(errTopic, inpTopic, 'Topic name cannot be empty.'); ok = false; }
        else { setErr(errTopic, inpTopic, ''); }
        if (!subtopicVal) { setErr(errSubtopic, inpSubtopic, 'Subtopic name cannot be empty.'); ok = false; }
        else { setErr(errSubtopic, inpSubtopic, ''); }

        if (!ok) return;

        // Build the in-memory tree
        const unit = findOrCreateUnit(unitVal);
        const topic = findOrCreateTopic(unit, topicVal);

        // Prevent duplicate subtopics under the same topic
        if (topic.subtopics.some(s => s.toLowerCase() === subtopicVal.toLowerCase())) {
            Toast.show('Duplicate', `"${subtopicVal}" already exists under "${topicVal}"`, 'destructive');
            return;
        }

        topic.subtopics.push(subtopicVal);

        // Clear only subtopic input; keep unit + topic so user can add more subtopics quickly
        inpSubtopic.value = '';
        inpSubtopic.focus();

        renderTree();
        updatePreview();

        Toast.show('Added', `Subtopic "${subtopicVal}" added under "${topicVal}"`, 'default');
    });

    /* Allow Enter key in all three inputs to trigger Add */
    [inpUnit, inpTopic, inpSubtopic].forEach(inp => {
        inp.addEventListener('keydown', e => {
            if (e.key === 'Enter') { e.preventDefault(); btnAddSubtopic.click(); }
        });
    });

    /* ── SAVE SYLLABUS button ────────────────────────────────── */
    btnSave.addEventListener('click', async () => {
        // Validate syllabus name
        const syllabusName = inpSyllabusName.value.trim();
        if (!syllabusName) {
            setErr(errSyllabus, inpSyllabusName, 'Syllabus name cannot be empty.');
            inpSyllabusName.focus();
            return;
        }
        setErr(errSyllabus, inpSyllabusName, '');

        if (totalSubtopics() === 0) {
            Toast.show('Nothing to save', 'Please add at least one subtopic.', 'destructive');
            return;
        }

        // Check auth
        const token = localStorage.getItem('studymap-token');
        if (!token) {
            Toast.show('Authentication error', 'Please log in again', 'destructive');
            setTimeout(() => window.location.href = '../auth/auth.html', 2000);
            return;
        }

        /*
         * Build the API payload:
         * {
         *   syllabusName: "...",
         *   units: [
         *     { name: "Unit 1", topics: [{ name: "Intro", subtopics: ["A","B"] }] }
         *   ]
         * }
         */
        const payload = units.map(u => ({
            name: u.unitName,
            topics: u.topics.map(t => ({
                name: t.topicName,
                subtopics: t.subtopics
            }))
        }));

        // Disable button & show saving state
        btnSave.disabled = true;
        btnSave.innerHTML = `
            <svg class="icon" style="width:1rem;height:1rem;">
                <use href="../assets/icons.svg#upload"></use>
            </svg>
            Saving…`;

        try {
            const result = await API.saveManualSyllabus(syllabusName, payload);

            if (result.error) throw new Error(result.error);

            Toast.show('Saved! 🎉', `"${syllabusName}" has been saved. Redirecting…`);

            // Redirect to the manual syllabus view page
            setTimeout(() => {
                window.location.href =
                    `../manual-syllabus/manual-syllabus.html?syllabus_id=${result.syllabus.id}`;
            }, 1500);

        } catch (err) {
            console.error('Save error:', err);
            Toast.show('Save failed', err.message || 'Unexpected error.', 'destructive');
            btnSave.disabled = false;
            btnSave.innerHTML = `
                <svg class="icon" style="width:1rem;height:1rem;">
                    <use href="../assets/icons.svg#upload"></use>
                </svg>
                Save Syllabus`;
        }
    });
}


/* ===========================================================
   SECTION 4 — INITIALIZATION
   =========================================================== */
document.addEventListener('DOMContentLoaded', () => {
    State.load();
    if (!State.user) {
        window.location.href = '../auth/auth.html';
        return;
    }

    initLayout();       // common sidebar / theme / user info
    setupTabs();        // PDF ↔ Manual tab switcher
    setupUpload();      // PDF upload (original, unchanged)
    setupManualEntry(); // New manual Unit → Topic → Subtopic builder
});
