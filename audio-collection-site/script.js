document.addEventListener('DOMContentLoaded', () => {
    const API_BASE = window.location.origin.includes('localhost') ? 'http://localhost:8000' : window.location.origin;

    let currentStep = -1; // -1 is Auth, 0 is Registration, 0.5 is Instructions, 1+ is recording
    let sessionId = '';
    let userRole = '';
    let userName = '';
    let accessToken = localStorage.getItem('access_token') || '';
    
    let mediaRecorder;
    let audioChunks = [];
    let timerInterval;
    let startTime;
    let totalAudioSeconds = 0;
    const stepAudios = {};
    const savedQuestions = new Set();

    const steps = document.querySelectorAll('.step');
    const participantInput = document.getElementById('participant-id');
    const startBtn = document.getElementById('start-btn');
    const reportOverlay = document.getElementById('report-overlay');
    const closeReportBtn = document.getElementById('close-report');
    const dashboardOverlay = document.getElementById('dashboard-overlay');
    const closeDashboardBtn = document.getElementById('close-dashboard');
    const navDashboardBtn = document.getElementById('nav-dashboard-btn');
    const dashboardTbody = document.getElementById('dashboard-tbody');
    const syncBtn = document.getElementById('sync-btn');
    const transcriptPopup = document.getElementById('transcript-popup');
    const closeTranscriptBtn = document.getElementById('close-transcript');
    const copyTranscriptBtn = document.getElementById('copy-transcript');
    const fullTranscriptContent = document.getElementById('full-transcript-content');
    const transcriptMeta = document.getElementById('transcript-meta');

    // Auth Elements
    const authSection = document.getElementById('auth-section');
    const loginForm = document.getElementById('login-form-container');
    const signupForm = document.getElementById('signup-form-container');
    const authTabs = document.querySelectorAll('.auth-tab');
    const loginBtn = document.getElementById('login-btn');
    const signupBtn = document.getElementById('signup-btn');
    const logoutBtn = document.getElementById('logout-btn');
    const navInstructionsBtn = document.getElementById('nav-instructions-btn');
    const userDisplayName = document.getElementById('user-display-name');
    const instructionsStep = document.getElementById('instructions-step');
    const proceedBtn = document.getElementById('proceed-to-session-btn');

    const showStep = (stepIndex) => {
        // Handle fractional steps or named steps
        const stepMap = {
            '-1': 'auth-section',
            '0': 'step-0',
            '0.5': 'instructions-step',
            '1': 'step-1',
            '2': 'step-2',
            '3': 'step-3',
            '4': 'step-4'
        };
        
        steps.forEach(s => s.classList.remove('active'));
        const targetId = stepMap[String(stepIndex)];
        if (targetId) {
            document.getElementById(targetId).classList.add('active');
        }
        currentStep = stepIndex;
    };

    const setStatus = (element, message, tone = 'muted') => {
        element.style.display = 'block';
        element.textContent = message;
        element.style.color = tone === 'error' ? 'var(--danger)' : tone === 'success' ? 'var(--success)' : 'var(--text-muted)';
    };

    const updateTimer = (timerId) => {
        const now = Date.now();
        const diff = Math.floor((now - startTime) / 1000);
        const mins = Math.floor(diff / 60).toString().padStart(2, '0');
        const secs = (diff % 60).toString().padStart(2, '0');
        document.getElementById(timerId).textContent = `${mins}:${secs}`;
        return diff;
    };

    const formatSeconds = (totalSeconds) => {
        const mins = Math.floor(totalSeconds / 60);
        const secs = totalSeconds % 60;
        return `${mins}m ${secs}s`;
    };

    startBtn.addEventListener('click', () => {
        sessionId = participantInput.value.trim();
        if (!sessionId) {
            alert('Please enter a Participant ID to proceed.');
            return;
        }
        showStep(0.5); // Go to Instructions
    });

    proceedBtn.addEventListener('click', () => {
        if (!sessionId) {
            alert('Please enter a Participant ID to proceed.');
            showStep(0); // Redirect to PID entry
        } else {
            showStep(1); // Start Session
        }
    });

    navInstructionsBtn.addEventListener('click', () => {
        showStep(0.5);
    });

    logoutBtn.addEventListener('click', () => {
        localStorage.removeItem('access_token');
        accessToken = '';
        userRole = '';
        location.reload();
    });

    closeReportBtn.addEventListener('click', () => {
        reportOverlay.classList.remove('active');
    });

    const dashboardLogoutBtn = document.getElementById('dashboard-logout-btn');
    if (dashboardLogoutBtn) {
        dashboardLogoutBtn.addEventListener('click', () => {
            localStorage.removeItem('access_token');
            accessToken = '';
            userRole = '';
            location.reload();
        });
    }

    closeDashboardBtn?.addEventListener('click', () => {
        dashboardOverlay.classList.remove('active');
    });

    closeTranscriptBtn.addEventListener('click', () => {
        transcriptPopup.classList.remove('active');
    });

    copyTranscriptBtn.addEventListener('click', () => {
        const text = fullTranscriptContent.innerText;
        navigator.clipboard.writeText(text).then(() => {
            const originalText = copyTranscriptBtn.innerHTML;
            copyTranscriptBtn.textContent = 'Copied!';
            setTimeout(() => copyTranscriptBtn.innerHTML = originalText, 2000);
        });
    });

    transcriptPopup.addEventListener('click', (e) => {
        if (e.target === transcriptPopup) transcriptPopup.classList.remove('active');
    });

    navDashboardBtn.addEventListener('click', () => {
        fetchTranscripts();
        dashboardOverlay.classList.add('active');
    });

    const saveStepAudio = async (stepNum, statusDisplay) => {
        if (savedQuestions.has(stepNum)) {
            return { alreadySaved: true };
        }

        const audioInfo = stepAudios[stepNum];
        if (!audioInfo?.blob) {
            throw new Error('Please record audio before saving this question.');
        }

        const formData = new FormData();
        formData.append('audio', audioInfo.blob, `q${stepNum}.wav`);
        formData.append('question_number', String(stepNum));
        formData.append('session_id', sessionId);

        setStatus(statusDisplay, `Saving Q${stepNum} audio and transcript...`);
        const response = await fetch(`${API_BASE}/save-audio`, {
            method: 'POST',
            headers: { 'Authorization': `Bearer ${accessToken}` },
            body: formData
        });
        const data = await response.json();

        if (!response.ok) {
            throw new Error(data.detail || `Save failed for Q${stepNum}.`);
        }

        sessionId = data.session_id;
        savedQuestions.add(stepNum);
        setStatus(statusDisplay, `Saved Q${stepNum}. Combined transcript: ${data.combined_transcript}`, 'success');
        return data;
    };

    const generateStepReport = async (stepNum, statusDisplay) => {
        const formData = new FormData();
        formData.append('question_number', String(stepNum));
        formData.append('session_id', sessionId);

        setStatus(statusDisplay, `Generating report for Q${stepNum} from combined transcript...`);
        const response = await fetch(`${API_BASE}/generate-report`, {
            method: 'POST',
            headers: { 'Authorization': `Bearer ${accessToken}` },
            body: formData
        });
        const data = await response.json();

        if (!response.ok) {
            throw new Error(data.detail || `Report generation failed for Q${stepNum}.`);
        }

        const linkText = data.download_link
            ? ` ZIP uploaded: ${data.download_link}`
            : ' ZIP created locally; Drive upload will work after credentials are added.';
        setStatus(statusDisplay, `Report ready.${linkText}`, 'success');
        return data;
    };

    const setupRecorder = async (stepNum) => {
        const recordBtn = document.getElementById(`record-btn-${stepNum}`);
        const statusText = document.getElementById(`status-${stepNum}`);
        const timerText = document.getElementById(`timer-${stepNum}`);
        const nextBtn = document.getElementById(stepNum === 3 ? 'finish-btn' : `next-${stepNum}`);
        const previewContainer = document.getElementById(`preview-${stepNum}`);
        const audioElement = document.getElementById(`audio-${stepNum}`);

        const reportBtn = document.createElement('button');
        reportBtn.className = 'btn';
        reportBtn.style.marginTop = '1rem';
        reportBtn.style.backgroundColor = '#f1f5f9';
        reportBtn.style.color = 'var(--primary)';
        reportBtn.style.border = '1px solid var(--primary)';
        reportBtn.textContent = "Model's result";
        reportBtn.disabled = true;

        const statusDisplay = document.createElement('div');
        statusDisplay.className = 'prompt-box';
        statusDisplay.style.marginTop = '1rem';
        statusDisplay.style.fontSize = '0.9rem';
        statusDisplay.style.display = 'none';

        previewContainer.appendChild(reportBtn);
        previewContainer.appendChild(statusDisplay);

        recordBtn.addEventListener('click', async () => {
            if (!mediaRecorder || mediaRecorder.state === 'inactive') {
                try {
                    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
                    mediaRecorder = new MediaRecorder(stream);
                    audioChunks = [];

                    mediaRecorder.ondataavailable = (e) => audioChunks.push(e.data);

                    mediaRecorder.onstop = () => {
                        const audioBlob = new Blob(audioChunks, { type: 'audio/wav' });
                        const audioUrl = URL.createObjectURL(audioBlob);
                        const previousDuration = stepAudios[stepNum]?.duration || 0;
                        const duration = Math.floor((Date.now() - startTime) / 1000);

                        audioElement.src = audioUrl;
                        previewContainer.style.display = 'block';

                        let downloadLink = previewContainer.querySelector('.download-link');
                        if (!downloadLink) {
                            downloadLink = document.createElement('a');
                            downloadLink.className = 'download-link';
                            downloadLink.style.display = 'block';
                            downloadLink.style.marginTop = '0.5rem';
                            downloadLink.style.color = 'var(--primary)';
                            downloadLink.style.textDecoration = 'none';
                            downloadLink.style.fontSize = '0.9rem';
                            downloadLink.style.fontWeight = '500';
                            previewContainer.insertBefore(downloadLink, reportBtn);
                        }
                        downloadLink.textContent = 'Download Recording';
                        downloadLink.href = audioUrl;
                        downloadLink.download = `${sessionId || 'session'}_q${stepNum}.wav`;

                        stepAudios[stepNum] = { blob: audioBlob, duration };
                        savedQuestions.delete(stepNum);
                        totalAudioSeconds = totalAudioSeconds - previousDuration + duration;
                        nextBtn.disabled = false;
                        reportBtn.disabled = false;

                        stream.getTracks().forEach(track => track.stop());
                    };

                    mediaRecorder.start();
                    startTime = Date.now();
                    recordBtn.classList.add('recording');
                    statusText.textContent = 'Recording... click to stop';
                    statusText.style.color = 'var(--danger)';
                    statusText.style.fontWeight = '600';
                    timerInterval = setInterval(() => updateTimer(`timer-${stepNum}`), 1000);
                } catch (err) {
                    console.error('Error accessing microphone:', err);
                    alert('Could not access microphone. Please ensure you have given permission.');
                }
            } else {
                mediaRecorder.stop();
                recordBtn.classList.remove('recording');
                statusText.textContent = 'Recording stopped';
                statusText.style.color = 'var(--success)';
                clearInterval(timerInterval);
            }
        });

        nextBtn.textContent = stepNum === 3 ? 'Finish Session' : 'Save & Next';
        nextBtn.addEventListener('click', async () => {
            nextBtn.disabled = true;
            try {
                await saveStepAudio(stepNum, statusDisplay);
                if (stepNum < 3) {
                    showStep(stepNum + 1);
                } else {
                    document.getElementById('total-time').textContent = formatSeconds(totalAudioSeconds);
                    // Clear any old status in step 4 if we start over (though we use reload)
                    const finalStatus = document.getElementById('final-status');
                    if (finalStatus) finalStatus.style.display = 'none';
                    showStep(4);
                }
            } catch (err) {
                console.error(err);
                setStatus(statusDisplay, err.message, 'error');
                nextBtn.disabled = false;
            }
        });

        reportBtn.addEventListener('click', async () => {
            reportBtn.disabled = true;
            try {
                await saveStepAudio(stepNum, statusDisplay);
                const data = await generateStepReport(stepNum, statusDisplay);
                renderReport(data, sessionId, stepNum);
            } catch (err) {
                console.error(err);
                setStatus(statusDisplay, err.message, 'error');
            } finally {
                reportBtn.disabled = false;
            }
        });
    };

    const renderReport = (data, pId, stepNum) => {
        reportOverlay.classList.add('active');

        document.getElementById('rep-id').textContent = pId;
        document.getElementById('rep-file').textContent = `combined_upto_q${stepNum}.txt`;
        document.getElementById('rep-date').textContent = new Date().toLocaleDateString();

        const badge = document.getElementById('rep-status-badge');
        badge.textContent = data.prediction;
        badge.className = 'prediction-badge';
        if (data.prediction === 'SCHIZOPHRENIA') badge.classList.add('badge-schiz');
        else if (data.prediction === 'CONTROL') badge.classList.add('badge-control');
        else badge.classList.add('badge-uncertain');

        const probPercent = Math.round((data.probability || 0) * 100);
        document.getElementById('rep-prob-fill').style.width = `${probPercent}%`;
        document.getElementById('rep-prob-text').textContent = `${probPercent}%`;

        const grid = document.getElementById('biomarker-grid');
        grid.innerHTML = '';
        Object.keys(data.biomarkers || {}).slice(0, 12).forEach(key => {
            const val = data.biomarkers[key];
            const triggered = (data.triggered || []).find(t => t.feature === key);
            const flagHtml = triggered
                ? `<span class="bm-flag ${triggered.direction === 'high' ? 'flag-high' : 'flag-low'}">${triggered.direction.toUpperCase()}</span>`
                : '';

            let fillWidth = Math.min(Math.max(val * 100, 5), 95);
            if (key.includes('entropy')) fillWidth = (val / 5) * 100;
            if (key.includes('std') || key.includes('count')) fillWidth = (val / 20) * 100;

            const card = document.createElement('div');
            card.className = 'biomarker-card';
            card.innerHTML = `
                <div class="bm-name" title="${key}">${key.replace(/_/g, ' ')}</div>
                <div class="bm-value-row">
                    <div class="bm-value">${Number(val).toFixed(3)}</div>
                    ${flagHtml}
                </div>
                <div class="bm-viz">
                    <div class="bm-fill" style="width: ${Math.min(fillWidth, 100)}%"></div>
                </div>
            `;
            grid.appendChild(card);
        });

        const list = document.getElementById('interpretation-list');
        list.innerHTML = '';
        if (data.triggered && data.triggered.length > 0) {
            data.triggered.forEach(t => {
                const item = document.createElement('div');
                item.className = 'finding-item';
                item.innerHTML = `
                    <div class="finding-icon">
                        <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>
                    </div>
                    <div class="finding-content">
                        <h4>${t.finding}</h4>
                        <p>${t.clinical}</p>
                    </div>
                `;
                list.appendChild(item);
            });
        } else {
            list.innerHTML = '<div class="subtitle" style="text-align: left; margin: 0;">No significant clinical biomarkers flagged in this session.</div>';
        }

        const reportText = data.report || '';
        const impressionMatch = reportText.match(/4\. OVERALL IMPRESSION[\s\S]*?\n\s*(.*?)(?:\n[-=]{6,}|\n\s*DISCLAIMER|$)/);
        document.getElementById('rep-impression').textContent = impressionMatch
            ? impressionMatch[1].replace(/\s+/g, ' ').trim()
            : 'Report generated successfully from the cumulative transcript.';
    };

    [1, 2, 3].forEach(setupRecorder);

    // Step 4: Final Report Logic
    const finalReportBtn = document.getElementById('final-report-btn');
    const step4Section = document.getElementById('step-4');
    
    // Add a status display to Step 4
    const finalStatusDisplay = document.createElement('div');
    finalStatusDisplay.id = 'final-status';
    finalStatusDisplay.className = 'prompt-box';
    finalStatusDisplay.style.marginTop = '1rem';
    finalStatusDisplay.style.fontSize = '0.9rem';
    finalStatusDisplay.style.display = 'none';
    finalReportBtn.parentNode.insertBefore(finalStatusDisplay, finalReportBtn);

    finalReportBtn.addEventListener('click', async () => {
        console.log("DEBUG: Final Report Button Clicked");
        finalReportBtn.disabled = true;
        try {
            const data = await generateStepReport(3, finalStatusDisplay);
            console.log("DEBUG: Final Report Data Received", data);
            renderReport(data, sessionId, 3);
        } catch (err) {
            console.error("DEBUG: Final Report Error", err);
            setStatus(finalStatusDisplay, err.message, 'error');
        } finally {
            finalReportBtn.disabled = false;
        }
    });

    // --- Dashboard Logic ---

    async function fetchTranscripts() {
        dashboardTbody.innerHTML = '<tr><td colspan="5" style="text-align: center;">Loading transcripts...</td></tr>';
        try {
            const response = await fetch(`${API_BASE}/api/transcripts`, {
                headers: { 'Authorization': `Bearer ${accessToken}` }
            });
        const transcripts = await response.json();
        if (!response.ok) {
            throw new Error(transcripts.detail || 'Failed to fetch transcripts');
        }
        if (Array.isArray(transcripts)) {
            renderDashboard(transcripts);
        } else {
            console.error('Expected array of transcripts, got:', transcripts);
            dashboardTbody.innerHTML = '<tr><td colspan="5" style="text-align: center; color: var(--danger);">Invalid data format from server.</td></tr>';
        }
    } catch (err) {
        console.error('Failed to fetch transcripts:', err);
        dashboardTbody.innerHTML = `<tr><td colspan="5" style="text-align: center; color: var(--danger);">Failed to load transcripts: ${err.message}</td></tr>`;
    }
    }

    function renderDashboard(transcripts) {
        if (transcripts.length === 0) {
            dashboardTbody.innerHTML = '<tr><td colspan="5" style="text-align: center;">No transcripts found in database.</td></tr>';
            return;
        }

        dashboardTbody.innerHTML = '';
        transcripts.forEach(t => {
            const tr = document.createElement('tr');
            const date = new Date(t.created_at).toLocaleString();
            const snippet = t.transcript.substring(0, 100) + (t.transcript.length > 100 ? '...' : '');
            
            tr.innerHTML = `
                <td><strong>${t.session_id}</strong></td>
                <td style="font-size: 0.85rem; color: var(--text-muted);">${date}</td>
                <td><div class="transcript-snippet" data-id="${t._id}" title="Click to view full transcript">${snippet}</div></td>
                <td>
                    <label class="toggle-switch">
                        <input type="checkbox" ${t.can_be_used ? 'checked' : ''} data-id="${t._id}" class="status-toggle-input">
                        <span class="slider"></span>
                    </label>
                </td>
                <td>
                    <div class="action-btns" style="display: flex; gap: 8px;">
                        <button class="btn btn-primary btn-small analyze-btn" data-id="${t._id}" title="Re-run Analysis">Model's result</button>
                        <button class="btn btn-outline btn-small view-report-btn" data-id="${t._id}" style="border-color: var(--primary); color: var(--primary);">View Report</button>
                    </div>
                </td>
            `;
            dashboardTbody.appendChild(tr);
        });

        // Add event listeners for snippets
        document.querySelectorAll('.transcript-snippet').forEach(el => {
            el.addEventListener('click', (e) => {
                const tId = e.target.getAttribute('data-id');
                const t = transcripts.find(item => item._id === tId);
                if (t) {
                    transcriptMeta.textContent = `Session: ${t.session_id} | Date: ${new Date(t.created_at).toLocaleString()}`;
                    fullTranscriptContent.innerText = t.transcript; // innerText handles newlines and escapes correctly
                    transcriptPopup.classList.add('active');
                }
            });
        });

        // Add event listeners for toggles
        document.querySelectorAll('.status-toggle-input').forEach(input => {
            input.addEventListener('change', async (e) => {
                const tId = e.target.getAttribute('data-id');
                const canBeUsed = e.target.checked;
                try {
                    const formData = new FormData();
                    formData.append('can_be_used', canBeUsed);
                    await fetch(`${API_BASE}/api/transcripts/${tId}/status`, {
                        method: 'POST',
                        headers: { 'Authorization': `Bearer ${accessToken}` },
                        body: formData
                    });
                } catch (err) {
                    console.error('Failed to update status:', err);
                    e.target.checked = !canBeUsed; // revert on failure
                }
            });
        });

        // Add event listeners for analyze buttons
        document.querySelectorAll('.analyze-btn').forEach(btn => {
            btn.addEventListener('click', async (e) => {
                const tId = e.target.getAttribute('data-id');
                e.target.disabled = true;
                e.target.textContent = 'Processing...';
                try {
                    const response = await fetch(`${API_BASE}/api/transcripts/${tId}/analyze`, {
                        method: 'POST',
                        headers: { 'Authorization': `Bearer ${accessToken}` }
                    });
                    const data = await response.json();
                    if (!response.ok) throw new Error(data.detail || 'Analysis failed');
                    
                    const transcript = transcripts.find(tr => tr._id === tId);
                    renderReport(data, transcript.session_id, transcript.question_number);
                } catch (err) {
                    console.error('Analysis failed:', err);
                    alert('Analysis failed: ' + err.message);
                } finally {
                    e.target.disabled = false;
                    e.target.textContent = "Model's result";
                }
            });
        });

        // Add event listeners for view report buttons
        document.querySelectorAll('.view-report-btn').forEach(btn => {
            btn.addEventListener('click', async (e) => {
                const tId = e.target.getAttribute('data-id');
                const t = transcripts.find(item => item._id === tId);
                if (!t) return;

                // Case 1: Results already exist and have the new detailed structure
                if (t.prediction_result && t.prediction_result.report) {
                    renderReport(t.prediction_result, t.session_id, t.question_number);
                } 
                // Case 2: Results are missing or old format - trigger analysis automatically
                else {
                    const originalText = e.target.textContent;
                    e.target.disabled = true;
                    e.target.textContent = 'Analyzing...';
                    
                    try {
                        const response = await fetch(`${API_BASE}/api/transcripts/${tId}/analyze`, {
                            method: 'POST',
                            headers: { 'Authorization': `Bearer ${accessToken}` }
                        });
                        const data = await response.json();
                        if (!response.ok) throw new Error(data.detail || 'Analysis failed');
                        
                        // Update local data and render
                        t.prediction_result = data;
                        renderReport(data, t.session_id, t.question_number);
                    } catch (err) {
                        console.error('Auto-analysis failed:', err);
                        alert('Could not generate report: ' + err.message);
                    } finally {
                        e.target.disabled = false;
                        e.target.textContent = originalText;
                    }
                }
            });
        });
    }

    if (syncBtn) {
        syncBtn.addEventListener('click', async () => {
            syncBtn.disabled = true;
            const originalText = syncBtn.innerHTML;
            syncBtn.textContent = 'Syncing...';
            try {
                const response = await fetch(`${API_BASE}/api/sync-results`, { 
                    method: 'POST',
                    headers: { 
                        'Authorization': `Bearer ${accessToken}`,
                        'Accept': 'application/json'
                    }
                });
                const data = await response.json();
                if (!response.ok) throw new Error(data.detail || 'Sync failed on server');
                alert(`Successfully synced ${data.synced} results!`);
                fetchTranscripts();
            } catch (err) {
                console.error('Sync failed:', err);
                alert('Sync failed: ' + err.message);
            } finally {
                syncBtn.disabled = false;
                syncBtn.innerHTML = originalText;
            }
        });
    }

    // --- Authentication Logic ---

    authTabs.forEach(tab => {
        tab.addEventListener('click', () => {
            authTabs.forEach(t => t.classList.remove('active'));
            tab.classList.add('active');
            const target = tab.getAttribute('data-tab');
            if (target === 'login') {
                loginForm.style.display = 'block';
                signupForm.style.display = 'none';
            } else {
                loginForm.style.display = 'none';
                signupForm.style.display = 'block';
            }
        });
    });

    const handleLoginResponse = (data) => {
        accessToken = data.access_token;
        userRole = data.role;
        userName = data.name;
        localStorage.setItem('access_token', accessToken);
        
        userDisplayName.textContent = userName;
        updateUIForRole();
        
        if (userRole === 'admin') {
            fetchTranscripts();
            dashboardOverlay.classList.add('active');
        } else {
            showStep(0); // Participant ID entry
        }
    };

    loginBtn.addEventListener('click', async () => {
        const email = document.getElementById('login-email').value;
        const password = document.getElementById('login-password').value;
        
        if (!email || !password) return alert('Please fill in all fields');
        
        const formData = new FormData();
        formData.append('email', email);
        formData.append('password', password);
        
        try {
            const res = await fetch(`${API_BASE}/api/auth/login`, { method: 'POST', body: formData });
            const data = await res.json();
            if (!res.ok) throw new Error(data.detail || 'Login failed');
            handleLoginResponse(data);
        } catch (err) {
            alert(err.message);
        }
    });

    signupBtn.addEventListener('click', async () => {
        const name = document.getElementById('signup-name').value;
        const email = document.getElementById('signup-email').value;
        const password = document.getElementById('signup-password').value;
        
        if (!name || !email || !password) return alert('Please fill in all fields');
        
        const formData = new FormData();
        formData.append('name', name);
        formData.append('email', email);
        formData.append('password', password);
        
        try {
            const res = await fetch(`${API_BASE}/api/auth/signup`, { method: 'POST', body: formData });
            const data = await res.json();
            if (!res.ok) throw new Error(data.detail || 'Signup failed');
            alert('Account created! Please login.');
            authTabs[0].click(); // Switch to login
        } catch (err) {
            alert(err.message);
        }
    });

    window.handleGoogleLogin = async (response) => {
        const formData = new FormData();
        formData.append('credential', response.credential);
        
        try {
            const res = await fetch(`${API_BASE}/api/auth/google`, { method: 'POST', body: formData });
            const data = await res.json();
            if (!res.ok) throw new Error(data.detail || 'Google Login failed');
            handleLoginResponse(data);
        } catch (err) {
            alert(err.message);
        }
    };

    function updateUIForRole() {
        logoutBtn.style.display = 'block';
        if (userRole === 'admin') {
            navDashboardBtn.style.display = 'block';
            navInstructionsBtn.style.display = 'none';
        } else {
            navDashboardBtn.style.display = 'none';
            navInstructionsBtn.style.display = 'block';
        }
    }

    // Auto-login if token exists
    if (accessToken) {
        // We could verify the token here, but for now we'll just parse the role
        try {
            const payload = JSON.parse(atob(accessToken.split('.')[1]));
            userRole = payload.role;
            // Since we don't have the name in the token payload in this simple implementation, 
            // we'll just set it to 'User' or fetch it if needed.
            userDisplayName.textContent = 'User'; 
            updateUIForRole();
            if (userRole === 'admin') {
                showStep(0); // Admin can still use the collector
            } else {
                showStep(0);
            }
        } catch (e) {
            localStorage.removeItem('access_token');
            showStep(-1);
        }
    } else {
        showStep(-1);
    }
});
