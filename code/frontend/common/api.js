// Backend API Configuration - Using SERVER_CONFIG from config.js
const API_BASE_URL = SERVER_CONFIG.backend.apiUrl;

// API Service Functions
const API = {
    // Authentication
    async register(email, password, name) {
        const response = await fetch(`${API_BASE_URL}/auth/register`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ email, password, name })
        });
        return response.json();
    },

    async login(email, password) {
        const response = await fetch(`${API_BASE_URL}/auth/login`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ email, password })
        });
        return response.json();
    },

    async getCurrentUser() {
        const token = localStorage.getItem('studymap-token');
        const response = await fetch(`${API_BASE_URL}/auth/me`, {
            headers: { 'Authorization': `Bearer ${token}` }
        });
        return response.json();
    },

    async updateProfile(name, email) {
        const token = localStorage.getItem('studymap-token');
        const response = await fetch(`${API_BASE_URL}/settings/profile`, {
            method: 'PUT',
            headers: {
                'Authorization': `Bearer ${token}`,
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ name, email })
        });
        return response.json();
    },

    async changePassword(currentPassword, newPassword) {
        const token = localStorage.getItem('studymap-token');
        const response = await fetch(`${API_BASE_URL}/settings/password`, {
            method: 'PUT',
            headers: {
                'Authorization': `Bearer ${token}`,
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ currentPassword, newPassword })
        });
        return response.json();
    },

    // Syllabus
    async getSyllabi() {
        const token = localStorage.getItem('studymap-token');
        const response = await fetch(`${API_BASE_URL}/syllabus`, {
            headers: { 'Authorization': `Bearer ${token}` }
        });
        return response.json();
    },

    async getActiveSyllabus() {
        const token = localStorage.getItem('studymap-token');
        const response = await fetch(`${API_BASE_URL}/syllabus/active`, {
            headers: { 'Authorization': `Bearer ${token}` }
        });
        return response.json();
    },

    async getSyllabus() {
        return this.getActiveSyllabus();
    },

    async getSyllabusStructure() {
        const token = localStorage.getItem('studymap-token');
        const response = await fetch(`${API_BASE_URL}/syllabus/structure`, {
            headers: { 'Authorization': `Bearer ${token}` }
        });
        return response.json();
    },

    async deleteSyllabus(id) {
        const token = localStorage.getItem('studymap-token');
        const response = await fetch(`${API_BASE_URL}/syllabus/${id}`, {
            method: 'DELETE',
            headers: { 'Authorization': `Bearer ${token}` }
        });
        return response.json();
    },

    async getSyllabusById(id) {
        const token = localStorage.getItem('studymap-token');
        const response = await fetch(`${API_BASE_URL}/syllabus/${id}`, {
            headers: { 'Authorization': `Bearer ${token}` }
        });
        return response.json();
    },

    async getSyllabusStructureById(id) {
        const token = localStorage.getItem('studymap-token');
        const response = await fetch(`${API_BASE_URL}/syllabus/structure/${id}`, {
            headers: { 'Authorization': `Bearer ${token}` }
        });
        return response.json();
    },

    async uploadSyllabus(file, name) {
        const token = localStorage.getItem('studymap-token');
        const formData = new FormData();
        formData.append('file', file);
        formData.append('name', name);

        const response = await fetch(`${API_BASE_URL}/syllabus/upload`, {
            method: 'POST',
            headers: { 'Authorization': `Bearer ${token}` },
            body: formData
        });
        return response.json();
    },

    // Standalone PDF extraction endpoint
    // Returns: { document_title, units: [ { unit_no, unit_name, topics: [ { topic_name, subtopics: [ { subtopic_name, note } ] } ] } ] }
    async uploadPdf(file) {
        const token = localStorage.getItem('studymap-token');
        const formData = new FormData();
        formData.append('file', file);

        const response = await fetch(`${API_BASE_URL}/upload_pdf`, {
            method: 'POST',
            headers: { 'Authorization': `Bearer ${token}` },
            body: formData
        });
        if (!response.ok) {
            const err = await response.json();
            throw new Error(err.error || 'PDF upload failed');
        }
        return response.json();
    },

    async extractSyllabus(syllabusId, subjects) {
        const token = localStorage.getItem('studymap-token');
        const response = await fetch(`${API_BASE_URL}/syllabus/extract`, {
            method: 'POST',
            headers: {
                'Authorization': `Bearer ${token}`,
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ syllabusId, subjects })
        });
        return response.json();
    },

    /**
     * Save a manually entered syllabus.
     * @param {string} syllabusName - Title of the syllabus
     * @param {Array}  units        - Array of { name, topics: [{ name, subtopics: ['str',...] }] }
     */
    async saveManualSyllabus(syllabusName, units) {
        const token = localStorage.getItem('studymap-token');
        const response = await fetch(`${API_BASE_URL}/syllabus/manual`, {
            method: 'POST',
            headers: {
                'Authorization': `Bearer ${token}`,
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ syllabusName, units })
        });
        return response.json();
    },

    /**
     * Get the Unit → Topic → Subtopic structure for a manually-entered syllabus.
     * @param {number} syllabusId
     */
    async getManualSyllabusStructure(syllabusId) {
        const token = localStorage.getItem('studymap-token');
        const response = await fetch(`${API_BASE_URL}/syllabus/manual/structure/${syllabusId}`, {
            headers: { 'Authorization': `Bearer ${token}` }
        });
        return response.json();
    },

    // Tests
    async getQuestions(topicId) {
        const token = localStorage.getItem('studymap-token');
        const response = await fetch(`${API_BASE_URL}/tests/questions/${topicId}`, {
            headers: { 'Authorization': `Bearer ${token}` }
        });
        return response.json();
    },

    async submitTest(topicId, answers) {
        const token = localStorage.getItem('studymap-token');
        const response = await fetch(`${API_BASE_URL}/tests/submit`, {
            method: 'POST',
            headers: {
                'Authorization': `Bearer ${token}`,
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ topicId, answers })
        });
        return response.json();
    },

    // Analytics
    async getStats() {
        const token = localStorage.getItem('studymap-token');
        const response = await fetch(`${API_BASE_URL}/analytics/stats`, {
            headers: { 'Authorization': `Bearer ${token}` }
        });
        return response.json();
    },

    // Streaks
    async getStreak() {
        const token = localStorage.getItem('studymap-token');
        const response = await fetch(`${API_BASE_URL}/streaks`, {
            headers: { 'Authorization': `Bearer ${token}` }
        });
        return response.json();
    },

    async updateStreak() {
        const token = localStorage.getItem('studymap-token');
        const response = await fetch(`${API_BASE_URL}/streaks/update`, {
            method: 'POST',
            headers: { 'Authorization': `Bearer ${token}` }
        });
        return response.json();
    },

    // Progress
    // Final Exam
    async getFinalExamStatus() {
        const token = localStorage.getItem('studymap-token');
        const response = await fetch(`${API_BASE_URL}/final-exam/status`, {
            headers: { 'Authorization': `Bearer ${token}` }
        });
        return response.json();
    },

    async getFinalExamQuestions() {
        const token = localStorage.getItem('studymap-token');
        const response = await fetch(`${API_BASE_URL}/final-exam/questions`, {
            headers: { 'Authorization': `Bearer ${token}` }
        });
        return response.json();
    },

    async submitFinalExam(answers) {
        const token = localStorage.getItem('studymap-token');
        const response = await fetch(`${API_BASE_URL}/final-exam/submit`, {
            method: 'POST',
            headers: {
                'Authorization': `Bearer ${token}`,
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ answers })
        });
        return response.json();
    },

    // Admin
    async getAllUsers() {
        const token = localStorage.getItem('studymap-token');
        const response = await fetch(`${API_BASE_URL}/admin/users`, {
            headers: { 'Authorization': `Bearer ${token}` }
        });
        return response.json();
    },

    async deleteUser(userId) {
        const token = localStorage.getItem('studymap-token');
        const response = await fetch(`${API_BASE_URL}/admin/users/${userId}`, {
            method: 'DELETE',
            headers: { 'Authorization': `Bearer ${token}` }
        });
        return response.json();
    }
};
