// DOM Elements
const btnSetup = document.getElementById('btn-setup');
const btnClearLog = document.getElementById('btn-clear-log');
const btnCopyLog = document.getElementById('btn-copy-log');
const logViewport = document.getElementById('log-viewport');
const inputUrl = document.getElementById('manhwa-url');
const appStatusText = document.getElementById('app-status');
const appStatusDot = document.querySelector('.status-dot');

const btnLoadEpisodes = document.getElementById('btn-load-episodes');
const episodeSelectionArea = document.getElementById('episode-selection-area');
const infoSeriesName = document.getElementById('info-series-name');
const infoTotalEps = document.getElementById('info-total-eps');
const inputFromEpisode = document.getElementById('from-episode');
const inputToEpisode = document.getElementById('to-episode');
const btnCrawl = document.getElementById('btn-crawl');



const editorModal = document.getElementById('editor-modal');
const modalSegmentsContainer = document.getElementById('modal-segments-container');
const btnCloseModal = document.getElementById('btn-close-modal');
const btnSaveSummary = document.getElementById('btn-save-summary');
const saveStatusMsg = document.getElementById('save-status-msg');

const videoModal = document.getElementById('video-modal');
const modalVideoPlayer = document.getElementById('modal-video-player');
const btnCloseVideoModal = document.getElementById('btn-close-video-modal');
const videoModalTitle = document.getElementById('video-modal-title');
const btnStop = document.getElementById('btn-stop');
const btnClearCache = document.getElementById('btn-clear-cache');

const btnClearQueue = document.getElementById('btn-clear-queue');
const btnRetryQueue = document.getElementById('btn-retry-queue');

// State variables for uploaded files
let uploadedLogoPath = null;
let uploadedOverlayPath = null;
let uploadedRefAudioPath = null;

// Logo and Overlay Elements
const logoFileInput = document.getElementById('logo-file');
const btnChooseLogo = document.getElementById('btn-choose-logo');
const logoFileStatus = document.getElementById('logo-file-status');

const overlayFileInput = document.getElementById('overlay-file');
const btnChooseOverlay = document.getElementById('btn-choose-overlay');
const overlayFileStatus = document.getElementById('overlay-file-status');

// Reference Audio Elements
const refAudioFileInput = document.getElementById('ref-audio-file');
const btnChooseRefAudio = document.getElementById('btn-choose-ref-audio');
const refAudioFileStatus = document.getElementById('ref-audio-file-status');


// Tab Elements
const tabWorkflow = document.getElementById('tab-workflow');
const tabLive = document.getElementById('tab-live');
const tabLogs = document.getElementById('tab-logs');

const workflowViewport = document.getElementById('workflow-viewport');
const liveViewport = document.getElementById('live-viewport');
const logActionButtons = document.getElementById('log-action-buttons');

// Workflows Dashboard State variables
let workflows = {};
let expandedWorkflowIds = new Set();

function activateTab(activeTab, activeViewport, showActions = false) {
    const tabs = [tabWorkflow, tabLive, tabLogs].filter(Boolean);
    const viewports = [workflowViewport, liveViewport, logViewport].filter(Boolean);
    
    tabs.forEach(tab => {
        if (tab === activeTab) {
            tab.classList.add('active');
            tab.style.background = 'var(--primary-gradient)';
            tab.style.color = 'white';
        } else {
            tab.classList.remove('active');
            tab.style.background = 'none';
            tab.style.color = 'var(--text-secondary)';
        }
    });

    viewports.forEach(vp => {
        if (vp === activeViewport) {
            vp.style.display = (vp === liveViewport || vp === workflowViewport) ? 'flex' : 'block';
        } else {
            vp.style.display = 'none';
        }
    });

    logActionButtons.style.display = showActions ? 'flex' : 'none';
}

tabWorkflow.addEventListener('click', () => activateTab(tabWorkflow, workflowViewport, false));
if (tabLive) {
    tabLive.addEventListener('click', () => activateTab(tabLive, liveViewport, false));
}
tabLogs.addEventListener('click', () => activateTab(tabLogs, logViewport, true));

function formatTime(seconds) {
    if (seconds === null || seconds === undefined) return 'N/A';
    const m = Math.floor(seconds / 60);
    const s = Math.floor(seconds % 60);
    return `${m}m ${s}s`;
}

function getStatusIcon(status) {
    if (status === 'success') return '<span style="color: var(--success); font-weight: bold;">✔</span>';
    if (status === 'running') return '<span class="status-dot running" style="background: #3b82f6; display: inline-block; width: 8px; height: 8px; border-radius: 50%; box-shadow: 0 0 6px #3b82f6; animation: dotPulse 1.5s infinite alternate;"></span>';
    if (status === 'failed') return '<span style="color: var(--error); font-weight: bold;">❌</span>';
    if (status === 'cancelled') return '<span style="color: var(--text-muted); font-weight: bold;">⊘</span>';
    return '<span style="color: var(--text-muted);">⌛</span>';
}

function renderWorkflowDashboard() {
    const list = Object.values(workflows).sort((a, b) => new Date(b.creation_time) - new Date(a.creation_time));
    
    // 1. Summaries
    let running = 0, waiting = 0, completed = 0, failed = 0;
    list.forEach(w => {
        if (w.status === 'running') running++;
        else if (w.status === 'waiting') waiting++;
        else if (w.status === 'success') completed++;
        else if (w.status === 'failed') failed++;
    });
    
    document.getElementById('summary-running').textContent = running;
    document.getElementById('summary-waiting').textContent = waiting;
    document.getElementById('summary-completed').textContent = completed;
    document.getElementById('summary-failed').textContent = failed;
    
    // 2. Select Active Workflow
    let activeTask = list.find(w => w.status === 'running');
    if (!activeTask && running + waiting > 0) {
        activeTask = list.find(w => w.status === 'waiting');
    }
    
    const activeContainer = document.getElementById('active-workflow-container');
    if (activeTask) {
        activeContainer.style.display = 'flex';
        document.getElementById('active-comic-title').textContent = activeTask.comic_title;
        document.getElementById('active-episodes').textContent = `Episodes: ${activeTask.from_episode} → ${activeTask.to_episode}`;
        
        const badge = document.getElementById('active-status-badge');
        badge.textContent = activeTask.status;
        badge.className = `badge ${activeTask.status}`;
        
        document.getElementById('active-progress-percent').textContent = `${activeTask.overall_progress}%`;
        document.getElementById('active-progress-fill').style.width = `${activeTask.overall_progress}%`;
        
        document.getElementById('active-current-stage').textContent = activeTask.current_stage || 'N/A';
        document.getElementById('active-current-episode').textContent = activeTask.current_episode ? `Episode ${activeTask.current_episode}` : 'N/A';
        document.getElementById('active-elapsed').textContent = formatTime(activeTask.elapsed_time);
        document.getElementById('active-remaining').textContent = formatTime(activeTask.estimated_remaining_time);
        
        document.getElementById('btn-active-cancel').onclick = (e) => {
            e.stopPropagation();
            if (confirm('Bạn có chắc chắn muốn hủy nhiệm vụ này?')) {
                cancelWorkflowTask(activeTask.id);
            }
        };
        
        document.getElementById('btn-active-logs').onclick = (e) => {
            e.stopPropagation();
            activateTab(tabLogs, logViewport, true);
        };
    } else {
        activeContainer.style.display = 'none';
    }
    
    // 3. Queue List
    const queueList = document.getElementById('workflow-queue-list');
    if (list.length === 0) {
        queueList.innerHTML = `<div style="text-align: center; color: var(--text-secondary); font-style: italic; padding: 3rem 0; font-size: 0.85rem;">Không có task nào trong hàng đợi. Nhấn "Bắt đầu chạy" bên trái để tạo task.</div>`;
        return;
    }
    
    queueList.innerHTML = '';
    list.forEach(w => {
        const card = document.createElement('div');
        card.className = 'workflow-card';
        
        const isExpanded = expandedWorkflowIds.has(w.id);
        
        let cardContent = `
            <div class="workflow-card-header">
                <div>
                    <span class="workflow-card-title">${w.comic_title}</span>
                    <div class="workflow-card-meta">Tập ${w.from_episode} → ${w.to_episode}${w.language ? ` | Ngôn ngữ: <span style="text-transform: uppercase; font-weight: bold; color: var(--primary);">${w.language}</span>` : ''}${w.elapsed_time ? ` | ⏱ ${formatTime(w.elapsed_time)}` : ''}</div>
                </div>
                <span class="badge ${w.status}">${w.status}</span>
            </div>
            
            <div style="display: flex; justify-content: space-between; align-items: center; font-size: 0.75rem; color: var(--text-secondary); margin-top: 0.5rem;">
                <span>Tiến độ</span>
                <span>${w.overall_progress}%</span>
            </div>
            <div class="progress-bar-container" style="width: 100%; height: 6px; background: rgba(255,255,255,0.06); border-radius: 3px; overflow: hidden; margin-top: 0.25rem;">
                <div style="width: ${w.overall_progress}%; height: 100%; background: var(--primary-gradient); border-radius: 3px;"></div>
            </div>
        `;
        
        if (w.artifacts && ((w.artifacts.final_videos && Object.keys(w.artifacts.final_videos).length > 0) || w.artifacts.final_video_url)) {
            cardContent += `
                <div style="margin-top: 0.75rem; display: flex; flex-direction: column; gap: 0.35rem;">
                    <div style="font-size: 0.7rem; color: var(--text-secondary); display: flex; align-items: center; gap: 0.25rem;">
                        <i data-lucide="video" style="width: 0.85rem; height: 0.85rem; color: #ef4444;"></i>
                        <span>Xem Video Recap:</span>
                    </div>
                    <div style="display: flex; flex-wrap: wrap; gap: 0.4rem; align-items: center;">
            `;
            
            if (w.artifacts.final_video_url && w.from_episode !== w.to_episode) {
                cardContent += `
                    <button class="btn btn-video-play" data-ep="${w.from_episode}-${w.to_episode}" data-url="${w.artifacts.final_video_url}" data-comic="${w.comic_title.replace(/"/g, '&quot;')}" style="font-size: 0.7rem; padding: 0.25rem 0.6rem; height: 24px; background: linear-gradient(135deg, #ef4444 0%, #b91c1c 100%); border: none; color: #fff; border-radius: 4px; cursor: pointer; display: flex; align-items: center; gap: 0.2rem; font-weight: bold; box-shadow: 0 2px 6px rgba(239,68,68,0.3); margin-right: 0.2rem;">
                        <span>🎬</span>
                        <span>Tổng hợp (${w.from_episode}-${w.to_episode})</span>
                    </button>
                `;
            }
            
            if (w.artifacts.final_videos) {
                Object.entries(w.artifacts.final_videos).sort((a,b) => parseInt(a[0]) - parseInt(b[0])).forEach(([ep, url]) => {
                    cardContent += `
                        <button class="btn btn-video-play" data-ep="${ep}" data-url="${url}" data-comic="${w.comic_title.replace(/"/g, '&quot;')}" style="font-size: 0.7rem; padding: 0.25rem 0.5rem; height: 24px; background: linear-gradient(135deg, rgba(239, 68, 68, 0.12) 0%, rgba(239, 68, 68, 0.25) 100%); border: 1px solid rgba(239, 68, 68, 0.35); color: #fff; border-radius: 4px; cursor: pointer; display: flex; align-items: center; gap: 0.2rem; transition: background 0.2s;">
                            <span>▶</span>
                            <span>Tập ${ep}</span>
                        </button>
                    `;
                });
            }
            
            cardContent += `
                    </div>
                </div>
            `;
        }
        
        if (isExpanded) {
            cardContent += `
                <div class="workflow-card-details expanded">
                    <div class="stage-checklist">
            `;
            
            w.stages.forEach(st => {
                cardContent += `
                    <div class="stage-item ${st.status === 'running' ? 'running' : ''}">
                        <span>${st.name}</span>
                        <div>
                            <span style="font-size: 0.75rem; color: var(--text-secondary); margin-right: 0.5rem;">${st.progress.toFixed(0)}%</span>
                            ${getStatusIcon(st.status)}
                        </div>
                    </div>
                `;
            });
            
            cardContent += `
                    </div>
                    
                    <div style="font-size: 0.8rem; font-weight: 600; margin-bottom: 0.5rem; color: var(--text-primary);">Tiến độ các tập (Stage: ${w.current_stage})</div>
                    <div class="episode-grid">
            `;
            
            const total = w.to_episode - w.from_episode + 1;
            let epSuccess = 0, epRunning = 0, epFailed = 0;
            
            for (let ep = w.from_episode; ep <= w.to_episode; ep++) {
                const epKey = String(ep);
                const epState = (w.episode_progress[epKey] && w.episode_progress[epKey][w.current_stage]) || 'waiting';
                
                let epClass = '';
                let epIcon = '⌛';
                if (epState === 'success') { epClass = 'success'; epIcon = '✔'; epSuccess++; }
                else if (epState === 'failed') { epClass = 'failed'; epIcon = '❌'; epFailed++; }
                else if (epState === 'running') { epClass = 'running'; epIcon = '⚙'; epRunning++; }
                
                cardContent += `
                    <div class="episode-badge ${epClass}">
                        <span>Tập ${ep}</span>
                        <span style="font-size: 0.75rem; font-weight: bold;">${epIcon}</span>
                    </div>
                `;
            }
            
            cardContent += `
                    </div>
                    
                    <div style="font-size: 0.75rem; color: var(--text-secondary); background: rgba(0,0,0,0.15); padding: 0.5rem 0.75rem; border-radius: 0.5rem; display: flex; flex-direction: column; gap: 0.25rem; margin-bottom: 1rem;">
                        <div>Hoàn thành: <strong>${epSuccess}/${total}</strong> | Chạy: <strong>${epRunning}</strong> | Lỗi: <strong>${epFailed}</strong></div>
                        ${w.error_message ? `<div style="color: var(--error);">Lỗi: ${w.error_message}</div>` : ''}
                    </div>
                    
                    <div class="workflow-card-actions">
                        <button class="btn btn-card-logs" style="font-size: 0.75rem; padding: 0.35rem 0.65rem; height: 28px; background: rgba(255,255,255,0.06); border: 1px solid var(--card-border); color: var(--text-primary);">Logs</button>
                        ${(w.status === 'running' || w.status === 'waiting') ? 
                            `<button class="btn btn-card-cancel" style="font-size: 0.75rem; padding: 0.35rem 0.65rem; height: 28px; background: #ef4444; border: none; color: white;">Hủy</button>` : 
                            `
                            ${(w.status === 'failed' || w.status === 'cancelled') ? 
                                `<button class="btn btn-card-retry" style="font-size: 0.75rem; padding: 0.35rem 0.65rem; height: 28px; background: #f97316; border: none; color: white; margin-right: 0.35rem;">Chạy lại</button>` : ''
                            }
                            <button class="btn btn-card-remove" style="font-size: 0.75rem; padding: 0.35rem 0.65rem; height: 28px; background: rgba(255,255,255,0.06); border: 1px solid var(--card-border); color: var(--text-primary);">Xóa</button>
                            `
                        }
                    </div>
                </div>
            `;
        } else {
            cardContent += `<div class="workflow-card-details"></div>`;
        }
        
        card.innerHTML = cardContent;
        
        card.onclick = (e) => {
            const playBtn = e.target.closest('.btn-video-play');
            if (playBtn) {
                e.stopPropagation();
                const ep = playBtn.getAttribute('data-ep');
                const url = playBtn.getAttribute('data-url');
                const comic = playBtn.getAttribute('data-comic');
                playVideo(url, ep, comic);
                return;
            }
            if (e.target.closest('.btn') || e.target.closest('button')) return;
            if (isExpanded) expandedWorkflowIds.delete(w.id);
            else expandedWorkflowIds.add(w.id);
            renderWorkflowDashboard();
        };
        
        if (isExpanded) {
            const btnLogs = card.querySelector('.btn-card-logs');
            if (btnLogs) {
                btnLogs.onclick = (e) => {
                    e.stopPropagation();
                    activateTab(tabLogs, logViewport, true);
                };
            }
            const btnCancel = card.querySelector('.btn-card-cancel');
            if (btnCancel) {
                btnCancel.onclick = (e) => {
                    e.stopPropagation();
                    if (confirm('Bạn có chắc chắn muốn hủy nhiệm vụ này?')) cancelWorkflowTask(w.id);
                };
            }
            const btnRetry = card.querySelector('.btn-card-retry');
            if (btnRetry) {
                btnRetry.onclick = (e) => {
                    e.stopPropagation();
                    retryWorkflowTask(w.id);
                };
            }
            const btnRemove = card.querySelector('.btn-card-remove');
            if (btnRemove) {
                btnRemove.onclick = (e) => {
                    e.stopPropagation();
                    removeWorkflowTask(w.id);
                };
            }
        }
        
        queueList.appendChild(card);
    });
    if (window.lucide) window.lucide.createIcons();
}

async function cancelWorkflowTask(id) {
    try {
        const response = await fetch(`/api/workflows/${id}/cancel`, { method: 'POST' });
        if (response.ok) {
            appendLog('Yêu cầu hủy bỏ đã được gửi.', 'warning');
            loadWorkflows();
        } else {
            const err = await response.json();
            alert(`Lỗi: ${err.detail}`);
        }
    } catch (e) {
        console.error(e);
    }
}

async function retryWorkflowTask(id) {
    try {
        const response = await fetch(`/api/workflows/${id}/retry`, { method: 'POST' });
        if (response.ok) {
            appendLog('Đã chạy lại tác vụ tiếp tục từ bước lỗi.', 'success');
            loadWorkflows();
        } else {
            const err = await response.json();
            alert(`Lỗi: ${err.detail}`);
        }
    } catch (e) {
        console.error(e);
    }
}

async function removeWorkflowTask(id) {
    try {
        const response = await fetch(`/api/workflows/${id}`, { method: 'DELETE' });
        if (response.ok) {
            appendLog('Nhiệm vụ đã được xóa khỏi hàng đợi.', 'info');
            expandedWorkflowIds.delete(id);
            loadWorkflows();
        } else {
            const err = await response.json();
            alert(`Lỗi: ${err.detail}`);
        }
    } catch (e) {
        console.error(e);
    }
}

async function clearAllWorkflows() {
    if (!confirm('Bạn có chắc chắn muốn xóa toàn bộ danh sách hàng đợi (kể cả các tác vụ đang chạy)?')) {
        return;
    }
    try {
        const response = await fetch('/api/workflows/clear-all', { method: 'POST' });
        if (response.ok) {
            appendLog('Đã xóa toàn bộ danh sách hàng đợi.', 'info');
            expandedWorkflowIds.clear();
            loadWorkflows();
        } else {
            const err = await response.json();
            alert(`Lỗi: ${err.detail}`);
        }
    } catch (e) {
        console.error(e);
    }
}

async function retryAllWorkflows() {
    try {
        const response = await fetch('/api/workflows/retry-all', { method: 'POST' });
        if (response.ok) {
            const data = await response.json();
            appendLog(data.message || 'Đã đưa các tác vụ lỗi/hủy chạy lại.', 'info');
            loadWorkflows();
        } else {
            const err = await response.json();
            alert(`Lỗi: ${err.detail}`);
        }
    } catch (e) {
        console.error(e);
    }
}



async function loadWorkflows() {
    try {
        const response = await fetch('/api/workflows');
        const list = await response.json();
        workflows = {};
        list.forEach(w => { workflows[w.id] = w; });
        renderWorkflowDashboard();
    } catch (err) {
        console.error('Error loading workflows:', err);
    }
}




// Utility: Append line to log viewport
function appendLog(message, type = 'info') {
    const line = document.createElement('div');
    line.className = `log-line ${type}`;
    
    // Format timestamp
    const now = new Date();
    const timeStr = now.toTimeString().split(' ')[0];
    const ms = String(now.getMilliseconds()).padStart(3, '0');
    
    line.textContent = `[${timeStr}.${ms}] ${message}`;
    logViewport.appendChild(line);
    
    // Auto-scroll to bottom
    logViewport.scrollTop = logViewport.scrollHeight;
}

// Utility: Set Application Status
function setStatus(status, text) {
    appStatusText.textContent = text;
    appStatusDot.className = 'status-dot';
    
    if (status === 'idle') {
        appStatusDot.classList.add('idle');
    } else if (status === 'active') {
        appStatusDot.classList.add('active');
    } else if (status === 'warning') {
        appStatusDot.classList.add('warning');
    }
}

// Connect to Server-Sent Events (SSE) for logs
function connectLogStream() {
    appendLog('Đang kết nối tới máy chủ log...', 'system');
    
    const eventSource = new EventSource('/api/logs');
    
    eventSource.onmessage = function(event) {
        try {
            const data = JSON.parse(event.data);
            
            if (data.level === 'event') {
                if (data.event === 'WorkflowRemoved') {
                    delete workflows[data.task_id];
                } else {
                    workflows[data.task_id] = data.data;
                }
                renderWorkflowDashboard();
                return;
            }
            
            appendLog(data.message, data.level || 'info');
            
            // Adjust application status dynamically based on messages
            if (data.status) {
                setStatus(data.status, data.status_text || 'Đang xử lý...');
            }
            
            // Handle crawl success event
            if (data.message && data.message.includes('CRAWL THÀNH CÔNG!')) {
                const titleText = infoSeriesName.textContent.replace('Truyện: ', '').trim();
                if (titleText && titleText !== 'Chưa chọn') {
                    const sanitized = sanitizeTitle(titleText);
                    const fromEp = inputFromEpisode.value !== "" ? parseInt(inputFromEpisode.value) : 1;
                    const toEp = inputToEpisode.value !== "" ? parseInt(inputToEpisode.value) : 1;
                    currentComicFolder = `${sanitized}_${fromEp}_${toEp}`;
                }
                appendLog('Đã quét và tải chương truyện thành công! Đang tự động tiến hành các bước xử lý tiếp theo...', 'success');
            }
            
            // Handle VLM live visual progress events
            if (data.data) {
                handleLiveAiData(data.data);
            }
        } catch (e) {
            appendLog(event.data, 'info');
        }
    };
    
    eventSource.onerror = function() {
        appendLog('Mất kết nối với log stream. Đang thử kết nối lại...', 'warning');
        setStatus('warning', 'Mất kết nối');
    };
}

// Handle Live AI Preview data updates
function handleLiveAiData(payload) {
    if (payload.type === 'vlm_processing') {
        liveProcessingCard.style.display = 'flex';
        liveProcessingTitle.textContent = `Tập ${payload.episode}: Phân tích các panels từ ${payload.start} đến ${payload.end}...`;
        liveProcessingCarousel.innerHTML = '';
        
        payload.images.forEach(imgUrl => {
            const img = document.createElement('img');
            img.src = imgUrl;
            img.style.height = '80px';
            img.style.borderRadius = '0.35rem';
            img.style.border = '1px solid rgba(255,255,255,0.05)';
            liveProcessingCarousel.appendChild(img);
        });
        
        // Auto-switch is disabled to prevent disrupting user console logs view
    } else if (payload.type === 'vlm_completed') {
        liveProcessingCard.style.display = 'none';
        
        // Remove placeholder if still there
        const placeholder = liveCompletedScenes.querySelector('div[style*="italic"]');
        if (placeholder) placeholder.remove();
        
        payload.scenes.forEach(scene => {
            const sceneRow = document.createElement('div');
            sceneRow.style.display = 'flex';
            sceneRow.style.gap = '1rem';
            sceneRow.style.background = 'rgba(255, 255, 255, 0.02)';
            sceneRow.style.border = '1px solid var(--card-border)';
            sceneRow.style.padding = '0.75rem';
            sceneRow.style.borderRadius = '0.75rem';
            sceneRow.style.alignItems = 'flex-start';
            sceneRow.style.marginBottom = '0.5rem';
            
            const img = document.createElement('img');
            img.src = scene.key_image;
            img.style.width = '100px';
            img.style.height = '68px';
            img.style.objectFit = 'contain';
            img.style.background = '#000';
            img.style.borderRadius = '0.35rem';
            
            const txtCol = document.createElement('div');
            txtCol.style.flex = '1';
            txtCol.style.display = 'flex';
            txtCol.style.flexDirection = 'column';
            txtCol.style.gap = '0.25rem';
            
            const range = document.createElement('span');
            range.style.fontSize = '0.7rem';
            range.style.color = 'var(--text-secondary)';
            range.textContent = `Tập ${payload.episode} - Panels: ${scene.source_range.from} - ${scene.source_range.to}`;
            
            const speech = document.createElement('p');
            speech.style.fontSize = '0.8rem';
            speech.style.color = 'var(--text-primary)';
            speech.style.margin = '0';
            speech.style.lineHeight = '1.3';
            speech.textContent = scene.speech;
            
            txtCol.appendChild(range);
            txtCol.appendChild(speech);
            
            sceneRow.appendChild(img);
            sceneRow.appendChild(txtCol);
            
            liveCompletedScenes.appendChild(sceneRow);
        });
        
        // Scroll live viewport to bottom
        if (liveViewport) {
            liveViewport.scrollTop = liveViewport.scrollHeight;
        }
    }
}

// Copy Log Functionality
btnCopyLog.addEventListener('click', async () => {
    const logText = Array.from(logViewport.children)
        .map(el => el.textContent)
        .join('\n');
    
    try {
        await navigator.clipboard.writeText(logText);
        
        // Visual indicator on copy success
        const originalHtml = btnCopyLog.innerHTML;
        btnCopyLog.innerHTML = '<i data-lucide="check" style="color: var(--success)"></i>';
        lucide.createIcons();
        setTimeout(() => {
            btnCopyLog.innerHTML = originalHtml;
            lucide.createIcons();
        }, 1500);
        
        appendLog('Đã sao chép toàn bộ log vào bộ nhớ tạm.', 'system');
    } catch (err) {
        appendLog('Không thể sao chép log: ' + err, 'error');
    }
});

// Clear Log Functionality
btnClearLog.addEventListener('click', () => {
    logViewport.innerHTML = '';
    appendLog('Đã xóa bảng log.', 'system');
});

// Setup Cookies Click Handler
btnSetup.addEventListener('click', async () => {
    const url = inputUrl.value.trim();
    
    appendLog('Bắt đầu quy trình thiết lập cookies...', 'system');
    btnSetup.disabled = true;
    setStatus('active', 'Thiết lập Cookies');
    
    try {
        const response = await fetch('/api/setup-cookies', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({ url: url })
        });
        
        const result = await response.json();
        
        if (response.ok) {
            appendLog(`Thành công: ${result.message}`, 'success');
        } else {
            appendLog(`Lỗi thiết lập cookies: ${result.detail || result.error}`, 'error');
        }
    } catch (error) {
        appendLog(`Lỗi kết nối tới server: ${error.message}`, 'error');
    } finally {
        btnSetup.disabled = false;
        setStatus('idle', 'Sẵn sàng');
    }
});

// Load Chrome Profiles Configuration
async function loadProfilesConfig() {
    try {
        const response = await fetch('/api/config');
        const config = await response.json();
        
        const textarea = document.getElementById('chrome-profiles-textarea');
        const select = document.getElementById('active-profile-select');
        
        if (textarea && config.chrome_profiles) {
            textarea.value = config.chrome_profiles.join('\n');
        }
        
        if (select) {
            updateProfileSelectOptions(config.chrome_profiles, config.current_profile_index);
        }
    } catch (err) {
        console.error('Lỗi tải cấu hình Chrome Profiles:', err);
    }
}

function updateProfileSelectOptions(profiles, selectedIndex) {
    const select = document.getElementById('active-profile-select');
    if (!select) return;
    
    select.innerHTML = '';
    if (!profiles || profiles.length === 0) {
        const opt = document.createElement('option');
        opt.value = 0;
        opt.textContent = 'Chưa cấu hình';
        select.appendChild(opt);
        return;
    }
    
    profiles.forEach((profile, idx) => {
        const opt = document.createElement('option');
        opt.value = idx;
        opt.textContent = `Tài khoản ${idx + 1} (${profile.split(/[\\/]/).pop()})`;
        if (idx === selectedIndex) {
            opt.selected = true;
        }
        select.appendChild(opt);
    });
}

// Initialize connection on load
connectLogStream();
activateTab(tabWorkflow, workflowViewport, false);
loadWorkflows();
loadProfilesConfig();

// Chrome Profiles Configuration Handlers
const btnSaveProfiles = document.getElementById('btn-save-profiles');
if (btnSaveProfiles) {
    btnSaveProfiles.addEventListener('click', async () => {
        const textarea = document.getElementById('chrome-profiles-textarea');
        const select = document.getElementById('active-profile-select');
        if (!textarea || !select) return;
        
        const lines = textarea.value.split('\n').map(l => l.trim()).filter(l => l !== '');
        const selectedIdx = parseInt(select.value) || 0;
        
        appendLog('Đang lưu cấu hình Chrome Profiles...', 'system');
        
        try {
            const response = await fetch('/api/config', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    chrome_profiles: lines,
                    current_profile_index: selectedIdx
                })
            });
            const result = await response.json();
            if (response.ok) {
                appendLog('Đã lưu cấu hình Chrome Profiles thành công!', 'success');
                updateProfileSelectOptions(result.config.chrome_profiles, result.config.current_profile_index);
            } else {
                appendLog(`Lỗi lưu cấu hình: ${result.detail || result.error}`, 'error');
            }
        } catch (err) {
            appendLog(`Lỗi kết nối: ${err.message}`, 'error');
        }
    });
}

const btnSetupActiveProfile = document.getElementById('btn-setup-active-profile');
if (btnSetupActiveProfile) {
    btnSetupActiveProfile.addEventListener('click', async () => {
        const select = document.getElementById('active-profile-select');
        const textarea = document.getElementById('chrome-profiles-textarea');
        if (!select || !textarea) return;
        
        const profiles = textarea.value.split('\n').map(l => l.trim()).filter(l => l !== '');
        const activeIdx = parseInt(select.value) || 0;
        
        if (profiles.length === 0) {
            appendLog('Vui lòng thêm ít nhất một đường dẫn Chrome Profile.', 'warning');
            return;
        }
        
        const targetProfile = profiles[activeIdx] || profiles[0];
        
        appendLog(`Đang khởi chạy trình duyệt login cho profile: ${targetProfile}...`, 'system');
        btnSetupActiveProfile.disabled = true;
        setStatus('active', 'Đang setup cookies');
        
        try {
            const response = await fetch('/api/setup-cookies', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    url: 'https://gemini.google.com/app',
                    profile_path: targetProfile
                })
            });
            const result = await response.json();
            if (response.ok) {
                appendLog('Thiết lập/Đăng nhập profile hoàn tất thành công.', 'success');
                await loadProfilesConfig();
            } else {
                appendLog(`Lỗi thiết lập: ${result.detail || result.error}`, 'error');
            }
        } catch (err) {
            appendLog(`Lỗi kết nối: ${err.message}`, 'error');
        } finally {
            btnSetupActiveProfile.disabled = false;
            setStatus('idle', 'Sẵn sàng');
        }
    });
}

// Load Episode Click Handler
btnLoadEpisodes.addEventListener('click', async () => {
    const url = inputUrl.value.trim();
    if (!url) {
        appendLog('Vui lòng nhập đường dẫn bộ truyện trước.', 'warning');
        return;
    }

    appendLog('Đang phân tích thông tin bộ truyện...', 'system');
    btnLoadEpisodes.disabled = true;
    setStatus('active', 'Phân tích truyện');
    episodeSelectionArea.style.display = 'none';

    try {
        const response = await fetch('/api/analyze', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({ url: url })
        });

        const result = await response.json();

        if (response.ok) {
            infoSeriesName.textContent = `Truyện: ${result.title}`;
            infoTotalEps.textContent = `${result.total_episodes}`;
            
            inputFromEpisode.value = 1;
            inputFromEpisode.max = result.total_episodes;
            
            inputToEpisode.value = result.total_episodes;
            inputToEpisode.max = result.total_episodes;
            
            const comixGroupArea = document.getElementById('comix-group-area');
            if (comixGroupArea) {
                if (url.includes('comix.to')) {
                    comixGroupArea.style.display = 'block';
                } else {
                    comixGroupArea.style.display = 'none';
                }
            }
            
            episodeSelectionArea.style.display = 'flex';
            appendLog(`Phân tích thành công: ${result.title} có tổng cộng ${result.total_episodes} tập.`, 'success');
        } else {
            appendLog(`Lỗi phân tích truyện: ${result.detail || result.error}`, 'error');
        }
    } catch (error) {
        appendLog(`Lỗi kết nối tới server: ${error.message}`, 'error');
    } finally {
        btnLoadEpisodes.disabled = false;
        setStatus('idle', 'Sẵn sàng');
    }
});

// Crawl Click Handler
btnCrawl.addEventListener('click', async () => {
    const url = inputUrl.value.trim();
    const fromEp = parseInt(inputFromEpisode.value);
    const toEp = parseInt(inputToEpisode.value);
    const ttsMode = document.getElementById('tts-voice-id').value;

    if (isNaN(fromEp) || isNaN(toEp) || fromEp < 1 || toEp < fromEp) {
        appendLog('Khoảng tập chọn để crawl không hợp lệ.', 'warning');
        return;
    }

    appendLog(`Gửi lệnh crawl tập từ ${fromEp} đến ${toEp}...`, 'system');
    btnCrawl.disabled = true;
    setStatus('active', 'Đang crawl truyện');

    try {
        const response = await fetch('/api/crawl', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                url: url,
                from_episode: fromEp,
                to_episode: toEp,
                safe_mode: document.getElementById('safe-mode').checked,
                nsfw_threshold: parseFloat(document.getElementById('nsfw-threshold').value),
                nsfw_mode: 'mask',
                timeout: parseInt(document.getElementById('vlm-timeout').value),
                retry_count: parseInt(document.getElementById('vlm-retries').value),
                concurrency: parseInt(document.getElementById('vlm-concurrency').value),
                image_quality: parseInt(document.getElementById('image-quality').value),
                pdf_quality: parseInt(document.getElementById('image-quality').value),
                language: document.getElementById('vlm-language').value,
                vlm_provider: 'gemini',
                voice_id: ttsMode === 'design' ? document.getElementById('omnivoice-instruct').value : ttsMode,
                ref_audio_path: ttsMode === 'clone' ? uploadedRefAudioPath : null,
                logo_path: uploadedLogoPath,
                overlay_path: uploadedOverlayPath,
                burn_subtitles: document.getElementById('burn-subtitles').checked,
                remove_text: true,
                remove_text_conf: 0.3,
                remove_text_radius: 3,
                comix_group_id: document.getElementById('comix-group-id') ? document.getElementById('comix-group-id').value.trim() || null : null
            })
        });

        const result = await response.json();

        if (response.ok) {
            appendLog(`Yêu cầu crawl đã được tiếp nhận: ${result.message}`, 'success');
            activateTab(tabWorkflow, workflowViewport, false);
            loadWorkflows();
        } else {
            appendLog(`Lỗi bắt đầu crawl: ${result.detail || result.error}`, 'error');
        }
    } catch (error) {
        appendLog(`Lỗi kết nối tới server: ${error.message}`, 'error');
    } finally {
        btnCrawl.disabled = false;
        setStatus('idle', 'Sẵn sàng');
    }
});

// Modal state variables
let currentComicFolder = '';
let currentSummaries = {};
let currentEditingEpisode = null;
let currentFromEpisode = 1;
let currentToEpisode = 1;

// Modal Close Handlers
btnCloseModal.addEventListener('click', () => {
    editorModal.style.display = 'none';
});

// Close modal when clicking outside content area
editorModal.addEventListener('click', (e) => {
    if (e.target === editorModal) {
        editorModal.style.display = 'none';
    }
});

// Video modal player functions
function playVideo(videoUrl, episodeNum, comicTitle) {
    videoModalTitle.textContent = `Phát Video Recap - ${comicTitle} - Tập ${episodeNum}`;
    modalVideoPlayer.src = videoUrl;
    modalVideoPlayer.load();
    videoModal.style.display = 'flex';
    modalVideoPlayer.play().catch(e => console.log('Autoplay blocked:', e));
}

btnCloseVideoModal.addEventListener('click', () => {
    modalVideoPlayer.pause();
    modalVideoPlayer.src = '';
    videoModal.style.display = 'none';
});

videoModal.addEventListener('click', (e) => {
    if (e.target === videoModal) {
        modalVideoPlayer.pause();
        modalVideoPlayer.src = '';
        videoModal.style.display = 'none';
    }
});

// Function to render episode segments in Editor Modal
function openSummaryEditor(episodeNum) {
    currentEditingEpisode = episodeNum;
    const data = currentSummaries[episodeNum];
    if (!data) return;
    
    // Update modal title
    document.getElementById('editor-modal-title').textContent = `Tập ${episodeNum} - Chỉnh sửa & Xác nhận Summary`;
    
    // Clear container
    modalSegmentsContainer.innerHTML = '';
    
    // Populate segments
    data.segments.forEach((seg, idx) => {
        const card = document.createElement('div');
        card.className = 'segment-card';
        card.style.display = 'flex';
        card.style.gap = '1.5rem';
        card.style.background = 'rgba(255, 255, 255, 0.02)';
        card.style.border = '1px solid var(--card-border)';
        card.style.padding = '1.25rem';
        card.style.borderRadius = '1rem';
        
        // Image column
        const imgCol = document.createElement('div');
        imgCol.style.width = '180px';
        imgCol.style.minWidth = '180px';
        imgCol.style.height = '120px';
        imgCol.style.background = '#0a0a10';
        imgCol.style.borderRadius = '0.5rem';
        imgCol.style.overflow = 'hidden';
        imgCol.style.border = '1px solid rgba(255,255,255,0.05)';
        
        const img = document.createElement('img');
        img.src = '/downloads/' + currentComicFolder + '/' + seg.key_image;
        img.alt = `Key panel ${seg.key_image}`;
        img.style.width = '100%';
        img.style.height = '100%';
        img.style.objectFit = 'contain';
        imgCol.appendChild(img);
        
        // Content column
        const contentCol = document.createElement('div');
        contentCol.style.flex = '1';
        contentCol.style.display = 'flex';
        contentCol.style.flexDirection = 'column';
        contentCol.style.gap = '0.5rem';
        
        const infoLine = document.createElement('div');
        infoLine.style.display = 'flex';
        infoLine.style.justifyContent = 'space-between';
        infoLine.style.fontSize = '0.8rem';
        infoLine.style.color = 'var(--text-secondary)';
        infoLine.innerHTML = `<span><strong>Cảnh ${idx + 1}</strong> (Panels: ${seg.source_range.from} - ${seg.source_range.to})</span>`;
        
        const textarea = document.createElement('textarea');
        textarea.value = seg.speech;
        textarea.rows = 3;
        textarea.style.width = '100%';
        textarea.style.background = 'rgba(0, 0, 0, 0.3)';
        textarea.style.border = '1px solid var(--card-border)';
        textarea.style.borderRadius = '0.5rem';
        textarea.style.padding = '0.5rem 0.75rem';
        textarea.style.color = 'var(--text-primary)';
        textarea.style.fontSize = '0.85rem';
        textarea.style.resize = 'vertical';
        textarea.style.outline = 'none';
        
        // Update model value on change
        textarea.addEventListener('input', (e) => {
            seg.speech = e.target.value;
        });
        
        contentCol.appendChild(infoLine);
        contentCol.appendChild(textarea);
        
        card.appendChild(imgCol);
        card.appendChild(contentCol);
        modalSegmentsContainer.appendChild(card);
    });
    
    editorModal.style.display = 'flex';
}

// Save & Next Episode Button Handler
btnSaveSummary.addEventListener('click', async () => {
    if (!currentEditingEpisode || !currentComicFolder) return;
    
    btnSaveSummary.disabled = true;
    saveStatusMsg.textContent = 'Đang lưu...';
    saveStatusMsg.style.color = 'var(--text-secondary)';
    saveStatusMsg.style.display = 'inline';
    
    try {
        const response = await fetch('/api/save-summary', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                comic_folder: currentComicFolder,
                episode: currentEditingEpisode,
                summary_data: currentSummaries[currentEditingEpisode]
            })
        });
        
        const result = await response.json();
        
        if (response.ok) {
            saveStatusMsg.textContent = 'Đã lưu thành công!';
            saveStatusMsg.style.color = 'var(--success)';
            
            // Wait 1 second, then proceed
            setTimeout(() => {
                saveStatusMsg.style.display = 'none';
                btnSaveSummary.disabled = false;
                
                // If there are more episodes, open the next one
                if (currentEditingEpisode < currentToEpisode) {
                    openSummaryEditor(currentEditingEpisode + 1);
                } else {
                    // All summaries confirmed!
                    editorModal.style.display = 'none';
                    appendLog('Tất cả summary đã được kiểm duyệt và lưu thành công.', 'success');
                }
            }, 1000);
            
        } else {
            saveStatusMsg.textContent = 'Lỗi khi lưu!';
            saveStatusMsg.style.color = 'var(--error)';
            btnSaveSummary.disabled = false;
            appendLog(`Lỗi lưu summary tập ${currentEditingEpisode}: ${result.detail || result.error}`, 'error');
        }
    } catch (error) {
        saveStatusMsg.textContent = 'Lỗi kết nối!';
        saveStatusMsg.style.color = 'var(--error)';
        btnSaveSummary.disabled = false;
        appendLog(`Lỗi kết nối lưu summary: ${error.message}`, 'error');
    }
});

function sanitizeTitle(title) {
    return title.toLowerCase()
        .replace(/\s+/g, '_')
        .replace(/[^\w]/g, '')
        .replace(/_+/g, '_')
        .replace(/^_+|_+$/g, '');
}



// Stop Execution Event Listener
btnStop.addEventListener('click', async () => {
    appendLog('Đang gửi yêu cầu dừng tiến trình...', 'system');
    try {
        const response = await fetch('/api/stop', {
            method: 'POST'
        });
        const result = await response.json();
        if (response.ok) {
            appendLog(`Thành công: ${result.message}`, 'success');
        } else {
            appendLog(`Lỗi khi dừng: ${result.detail || result.error}`, 'error');
        }
    } catch (error) {
        appendLog(`Lỗi kết nối tới server: ${error.message}`, 'error');
    }
});

// Clear Cache Event Listener
btnClearCache.addEventListener('click', async () => {
    if (!confirm('Bạn có chắc chắn muốn xóa toàn bộ cache file (observations.json, events.json, narrations.json) của tất cả các tập truyện (kể cả cache test)?')) {
        return;
    }
    
    appendLog('Đang gửi yêu cầu xóa cache...', 'system');
    try {
        const response = await fetch('/api/clear-cache', {
            method: 'POST'
        });
        const result = await response.json();
        if (response.ok) {
            appendLog(`Thành công: ${result.message}`, 'success');
        } else {
            appendLog(`Lỗi khi xóa cache: ${result.detail || result.error}`, 'error');
        }
    } catch (error) {
        appendLog(`Lỗi kết nối tới server: ${error.message}`, 'error');
    }
});





// Toggle Safe Mode config styling
const safeModeCheckbox = document.getElementById('safe-mode');
const nsfwSettings = document.getElementById('nsfw-settings');
const safeModeStatus = document.getElementById('safe-mode-status');
const nsfwThresholdInput = document.getElementById('nsfw-threshold');
if (safeModeCheckbox && nsfwSettings && safeModeStatus) {
    const syncSafeModeUI = () => {
        const enabled = safeModeCheckbox.checked;
        safeModeCheckbox.setAttribute('aria-checked', String(enabled));
        safeModeStatus.textContent = enabled ? 'Đang bật' : 'Đang tắt';
        safeModeStatus.classList.toggle('on', enabled);
        safeModeStatus.classList.toggle('off', !enabled);
        nsfwSettings.classList.toggle('is-disabled', !enabled);
        if (nsfwThresholdInput) nsfwThresholdInput.disabled = !enabled;
    };

    safeModeCheckbox.addEventListener('change', syncSafeModeUI);
    syncSafeModeUI();
}

if (btnClearQueue) {
    btnClearQueue.addEventListener('click', clearAllWorkflows);
}
if (btnRetryQueue) {
    btnRetryQueue.addEventListener('click', retryAllWorkflows);
}

// Toggle OmniVoice inputs based on selected mode
const ttsVoiceIdInput = document.getElementById('tts-voice-id');
const omnivoiceDesignArea = document.getElementById('omnivoice-design-area');
const omnivoiceCloneArea = document.getElementById('omnivoice-clone-area');
const ai33proApiArea = document.getElementById('ai33pro-api-area');

if (ttsVoiceIdInput) {
    ttsVoiceIdInput.addEventListener('change', () => {
        const mode = ttsVoiceIdInput.value;
        if (mode === 'design') {
            if (omnivoiceDesignArea) omnivoiceDesignArea.style.display = 'block';
            if (omnivoiceCloneArea) omnivoiceCloneArea.style.display = 'none';
            if (ai33proApiArea) ai33proApiArea.style.display = 'none';
        } else if (mode === 'clone') {
            if (omnivoiceDesignArea) omnivoiceDesignArea.style.display = 'none';
            if (omnivoiceCloneArea) omnivoiceCloneArea.style.display = 'block';
            if (ai33proApiArea) ai33proApiArea.style.display = 'none';
        } else if (mode === 'ai33pro') {
            if (omnivoiceDesignArea) omnivoiceDesignArea.style.display = 'none';
            if (omnivoiceCloneArea) omnivoiceCloneArea.style.display = 'none';
            if (ai33proApiArea) ai33proApiArea.style.display = 'block';
            const languageSelect = document.getElementById('vlm-language');
            if (languageSelect) languageSelect.value = 'en';
        } else {
            if (omnivoiceDesignArea) omnivoiceDesignArea.style.display = 'none';
            if (omnivoiceCloneArea) omnivoiceCloneArea.style.display = 'none';
            if (ai33proApiArea) ai33proApiArea.style.display = 'none';
        }
    });
    // Trigger initial state mapping on load
    ttsVoiceIdInput.dispatchEvent(new Event('change'));
}

// Custom Logo & Overlay Upload Logic
if (btnChooseLogo && logoFileInput) {
    btnChooseLogo.addEventListener('click', () => {
        logoFileInput.click();
    });

    logoFileInput.addEventListener('change', async () => {
        const file = logoFileInput.files[0];
        if (!file) return;

        logoFileStatus.textContent = 'Đang tải lên...';
        logoFileStatus.style.color = 'var(--warning)';

        const formData = new FormData();
        formData.append('file', file);

        try {
            const response = await fetch('/api/upload-logo', {
                method: 'POST',
                body: formData
            });

            const result = await response.json();
            if (response.ok) {
                uploadedLogoPath = result.file_path;
                logoFileStatus.textContent = file.name;
                logoFileStatus.style.color = 'var(--success)';
                appendLog(`Đã tải lên logo tùy chỉnh: ${file.name}`, 'success');
            } else {
                logoFileStatus.textContent = 'Lỗi tải lên';
                logoFileStatus.style.color = 'var(--error)';
                appendLog(`Lỗi tải lên logo: ${result.detail || 'Lỗi không xác định'}`, 'error');
            }
        } catch (err) {
            logoFileStatus.textContent = 'Lỗi kết nối';
            logoFileStatus.style.color = 'var(--error)';
            appendLog(`Lỗi kết nối khi tải lên logo: ${err.message}`, 'error');
        }
    });
}

if (btnChooseOverlay && overlayFileInput) {
    btnChooseOverlay.addEventListener('click', () => {
        overlayFileInput.click();
    });

    overlayFileInput.addEventListener('change', async () => {
        const file = overlayFileInput.files[0];
        if (!file) return;

        overlayFileStatus.textContent = 'Đang tải lên...';
        overlayFileStatus.style.color = 'var(--warning)';

        const formData = new FormData();
        formData.append('file', file);

        try {
            const response = await fetch('/api/upload-overlay', {
                method: 'POST',
                body: formData
            });

            const result = await response.json();
            if (response.ok) {
                uploadedOverlayPath = result.file_path;
                overlayFileStatus.textContent = file.name;
                overlayFileStatus.style.color = 'var(--success)';
                appendLog(`Đã tải lên overlay tùy chỉnh: ${file.name}`, 'success');
            } else {
                overlayFileStatus.textContent = 'Lỗi tải lên';
                overlayFileStatus.style.color = 'var(--error)';
                appendLog(`Lỗi tải lên overlay: ${result.detail || 'Lỗi không xác định'}`, 'error');
            }
        } catch (err) {
            overlayFileStatus.textContent = 'Lỗi kết nối';
            overlayFileStatus.style.color = 'var(--error)';
            appendLog(`Lỗi kết nối khi tải lên overlay: ${err.message}`, 'error');
        }
    });
}

if (btnChooseRefAudio && refAudioFileInput) {
    btnChooseRefAudio.addEventListener('click', () => {
        refAudioFileInput.click();
    });

    refAudioFileInput.addEventListener('change', async () => {
        const file = refAudioFileInput.files[0];
        if (!file) return;

        refAudioFileStatus.textContent = 'Đang tải lên...';
        refAudioFileStatus.style.color = 'var(--warning)';

        const formData = new FormData();
        formData.append('file', file);

        try {
            const response = await fetch('/api/upload-ref-audio', {
                method: 'POST',
                body: formData
            });

            const result = await response.json();
            if (response.ok) {
                uploadedRefAudioPath = result.file_path;
                refAudioFileStatus.textContent = file.name;
                refAudioFileStatus.style.color = 'var(--success)';
                appendLog(`Đã tải lên âm thanh mẫu: ${file.name}`, 'success');
            } else {
                refAudioFileStatus.textContent = 'Lỗi tải lên';
                refAudioFileStatus.style.color = 'var(--error)';
                appendLog(`Lỗi tải lên âm thanh mẫu: ${result.detail || 'Lỗi không xác định'}`, 'error');
            }
        } catch (err) {
            refAudioFileStatus.textContent = 'Lỗi kết nối';
            refAudioFileStatus.style.color = 'var(--error)';
            appendLog(`Lỗi kết nối khi tải lên âm thanh mẫu: ${err.message}`, 'error');
        }
    });
}
