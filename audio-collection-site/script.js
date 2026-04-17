document.addEventListener('DOMContentLoaded', () => {
    let currentStep = 0;
    let participantId = "";
    let mediaRecorder;
    let audioChunks = [];
    let timerInterval;
    let startTime;
    let totalAudioSeconds = 0;
    let stepAudios = {};

    const steps = document.querySelectorAll('.step');
    const participantInput = document.getElementById('participant-id');
    const startBtn = document.getElementById('start-btn');
    const reportOverlay = document.getElementById('report-overlay');
    const closeReportBtn = document.getElementById('close-report');

    // Navigation function
    const showStep = (stepIndex) => {
        steps.forEach((s, idx) => {
            s.classList.toggle('active', idx === stepIndex);
        });
        currentStep = stepIndex;
    };

    // Timer logic
    const updateTimer = (timerId) => {
        const now = Date.now();
        const diff = Math.floor((now - startTime) / 1000);
        const mins = Math.floor(diff / 60).toString().padStart(2, '0');
        const secs = (diff % 60).toString().padStart(2, '0');
        document.getElementById(timerId).textContent = `${mins}:${secs}`;
        return diff;
    };

    // Registration
    startBtn.addEventListener('click', () => {
        participantId = participantInput.value.trim();
        if (participantId) {
            showStep(1);
        } else {
            alert('Please enter a Participant ID');
        }
    });

    // Close Report
    closeReportBtn.addEventListener('click', () => {
        reportOverlay.classList.remove('active');
    });

    // Recording Logic
    const setupRecorder = async (stepNum) => {
        const recordBtn = document.getElementById(`record-btn-${stepNum}`);
        const statusText = document.getElementById(`status-${stepNum}`);
        const timerText = document.getElementById(`timer-${stepNum}`);
        const nextBtn = document.getElementById(stepNum === 3 ? 'finish-btn' : `next-${stepNum}`);
        const previewContainer = document.getElementById(`preview-${stepNum}`);
        const audioElement = document.getElementById(`audio-${stepNum}`);

        recordBtn.addEventListener('click', async () => {
            if (!mediaRecorder || mediaRecorder.state === 'inactive') {
                try {
                    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
                    mediaRecorder = new MediaRecorder(stream);
                    audioChunks = [];

                    mediaRecorder.ondataavailable = (e) => {
                        audioChunks.push(e.data);
                    };

                    mediaRecorder.onstop = () => {
                        const audioBlob = new Blob(audioChunks, { type: 'audio/wav' });
                        const audioUrl = URL.createObjectURL(audioBlob);
                        audioElement.src = audioUrl;
                        previewContainer.style.display = 'block';
                        
                        // Add download link
                        let downloadLink = previewContainer.querySelector('.download-link');
                        if (!downloadLink) {
                            downloadLink = document.createElement('a');
                            downloadLink.className = 'download-link';
                            downloadLink.textContent = 'Download Recording';
                            downloadLink.style.display = 'block';
                            downloadLink.style.marginTop = '0.5rem';
                            downloadLink.style.color = 'var(--primary)';
                            downloadLink.style.textDecoration = 'none';
                            downloadLink.style.fontSize = '0.9rem';
                            downloadLink.style.fontWeight = '500';
                            previewContainer.appendChild(downloadLink);
                        }
                        downloadLink.href = audioUrl;
                        downloadLink.download = `${participantId}_step${stepNum}.wav`;

                        nextBtn.disabled = false;
                        
                        const duration = Math.floor((Date.now() - startTime) / 1000);
                        stepAudios[stepNum] = { blob: audioBlob, duration: duration };
                        totalAudioSeconds += duration;

                        // Stop all tracks
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

        nextBtn.addEventListener('click', () => {
            if (stepNum < 3) {
                showStep(stepNum + 1);
            } else {
                document.getElementById('total-time').textContent = formatSeconds(totalAudioSeconds);
                showStep(4);
            }
        });

        // Add Analysis Button
        const analyzeBtn = document.createElement('button');
        analyzeBtn.className = 'btn';
        analyzeBtn.style.marginTop = '1rem';
        analyzeBtn.style.backgroundColor = '#f1f5f9';
        analyzeBtn.style.color = 'var(--primary)';
        analyzeBtn.style.border = '1px solid var(--primary)';
        analyzeBtn.innerHTML = '🔬 View Research Report';
        analyzeBtn.style.display = 'none';
        
        previewContainer.appendChild(analyzeBtn);

        const statusDisplay = document.createElement('div');
        statusDisplay.className = 'prompt-box';
        statusDisplay.style.marginTop = '1rem';
        statusDisplay.style.fontSize = '0.9rem';
        statusDisplay.style.display = 'none';
        previewContainer.appendChild(statusDisplay);

        recordBtn.addEventListener('click', () => {
            if (mediaRecorder && mediaRecorder.state === 'inactive') {
                analyzeBtn.style.display = 'block';
                statusDisplay.style.display = 'none';
            }
        });

        analyzeBtn.addEventListener('click', async () => {
            const audioBlob = stepAudios[stepNum].blob;
            const formData = new FormData();
            formData.append('file', audioBlob, 'recording.wav');
            formData.append('participant_id', participantId || 'anonymous'); // Pass Participant ID to backend

            analyzeBtn.disabled = true;
            analyzeBtn.textContent = '⌛ Running Diagnostics...';
            statusDisplay.style.display = 'block';
            statusDisplay.textContent = 'Processing... saving to secure research directory...';

            try {
                const response = await fetch('http://localhost:8000/analyze', {
                    method: 'POST',
                    body: formData
                });
                const data = await response.json();
                
                if (data.report) {
                    renderReport(data, participantId, stepNum);
                    statusDisplay.style.display = 'none';
                } else {
                    statusDisplay.textContent = 'Analysis complete, but no report was generated.';
                }
            } catch (err) {
                console.error('Backend error:', err);
                statusDisplay.textContent = '⚠️ Backend unreachable. Ensure server is running at port 8000.';
            } finally {
                analyzeBtn.disabled = false;
                analyzeBtn.innerHTML = '🔬 Re-run Analysis';
            }
        });
    };

    const renderReport = (data, pId, stepNum) => {
        // Show overlay
        reportOverlay.classList.add('active');

        // Header
        document.getElementById('rep-id').textContent = pId;
        document.getElementById('rep-file').textContent = 'audio_step' + stepNum + '_' + stepAudios[stepNum]?.duration + 's.wav';
        document.getElementById('rep-date').textContent = new Date().toLocaleDateString();

        const badge = document.getElementById('rep-status-badge');
        badge.textContent = data.prediction;
        badge.className = 'prediction-badge';
        if (data.prediction === 'SCHIZOPHRENIA') badge.classList.add('badge-schiz');
        else if (data.prediction === 'CONTROL') badge.classList.add('badge-control');
        else badge.classList.add('badge-uncertain');

        const probPercent = Math.round(data.probability * 100);
        document.getElementById('rep-prob-fill').style.width = probPercent + '%';
        document.getElementById('rep-prob-text').textContent = probPercent + '%';

        // Biomarkers
        const grid = document.getElementById('biomarker-grid');
        grid.innerHTML = '';
        
        // Use biomarkers from backend
        const keys = Object.keys(data.biomarkers).slice(0, 12);
        keys.forEach(key => {
            const val = data.biomarkers[key];
            const card = document.createElement('div');
            card.className = 'biomarker-card';
            
            const isTriggered = data.triggered.find(t => t.feature === key);
            const flagHtml = isTriggered ? 
                `<span class="bm-flag ${isTriggered.direction === 'high' ? 'flag-high' : 'flag-low'}">${isTriggered.direction === 'high' ? '↑ HIGH' : '↓ LOW'}</span>` : 
                '';

            let fillWidth = Math.min(Math.max(val * 100, 5), 95);
            if (key.includes('entropy')) fillWidth = (val / 5) * 100;
            if (key.includes('std') || key.includes('count')) fillWidth = (val / 20) * 100;

            card.innerHTML = `
                <div class="bm-name" title="${key}">${key.replace(/_/g, ' ')}</div>
                <div class="bm-value-row">
                    <div class="bm-value">${val.toFixed(3)}</div>
                    ${flagHtml}
                </div>
                <div class="bm-viz">
                    <div class="bm-fill" style="width: ${fillWidth}%"></div>
                </div>
            `;
            grid.appendChild(card);
        });

        // Findings
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
            list.innerHTML = `<div class="subtitle" style="text-align: left; margin: 0;">No significant clinical biomarkers flagged in this session.</div>`;
        }

        // Impression
        const reportParts = data.report.split('4. OVERALL IMPRESSION\n  ──────────────────────────────────────────\n');
        let impression = "No summary available.";
        if (reportParts.length > 1) {
            impression = reportParts[1].split('────────────────────────────────────────────────────────────────────────')[0].replace(/  /g, '').trim();
        }
        document.getElementById('rep-impression').textContent = impression;
    };

    const formatSeconds = (totalSeconds) => {
        const mins = Math.floor(totalSeconds / 60);
        const secs = totalSeconds % 60;
        return `${mins}m ${secs}s`;
    };

    [1, 2, 3].forEach(setupRecorder);
});
