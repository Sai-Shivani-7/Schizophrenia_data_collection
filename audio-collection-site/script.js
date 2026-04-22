document.addEventListener('DOMContentLoaded', () => {
    const API_BASE = 'https://your-backend-name.onrender.com' || 'http://localhost:8000' ;

    let currentStep = 0;
    let sessionId = '';
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

    const showStep = (stepIndex) => {
        steps.forEach((s, idx) => s.classList.toggle('active', idx === stepIndex));
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
            sessionId = crypto.randomUUID ? crypto.randomUUID() : String(Date.now());
            participantInput.value = sessionId;
        }
        showStep(1);
    });

    closeReportBtn.addEventListener('click', () => {
        reportOverlay.classList.remove('active');
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
        reportBtn.textContent = 'Generate Report';
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
    step4Section.querySelector('.finish-card').insertBefore(finalStatusDisplay, finalReportBtn);

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
});
