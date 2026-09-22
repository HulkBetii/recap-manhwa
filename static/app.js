// DOM Elements
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
const btnToggleSubtitles = document.getElementById('btn-toggle-subtitles');
const subtitleToggleText = document.getElementById('subtitle-toggle-text');
const btnToggleTranscript = document.getElementById('btn-toggle-transcript');
const inputCustomSrt = document.getElementById('input-custom-srt');
const btnUploadSrt = document.getElementById('btn-upload-srt');
const btnDownloadSrt = document.getElementById('btn-download-srt');
const videoSubtitleOverlay = document.getElementById('video-subtitle-overlay');
const videoSubtitleText = document.getElementById('video-subtitle-text');
const subtitleStatusText = document.getElementById('subtitle-status-text');
const subtitleInfoBadge = document.getElementById('subtitle-info-badge');
const transcriptCountBadge = document.getElementById('transcript-count-badge');
const btnSubSizeDown = document.getElementById('btn-sub-size-down');
const btnSubSizeUp = document.getElementById('btn-sub-size-up');
const videoTranscriptSidebar = document.getElementById('video-transcript-sidebar');
const videoTranscriptList = document.getElementById('video-transcript-list');
const selectSubTranslateLang = document.getElementById('select-sub-translate-lang');
const btnTranslateSubtitles = document.getElementById('btn-translate-subtitles');
const btnTranslateSubText = document.getElementById('btn-translate-sub-text');
const selectSubDisplayMode = document.getElementById('select-sub-display-mode');
const btnStop = document.getElementById('btn-stop');

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

function getFriendlyStageName(stageName) {
    if (!stageName) return 'Đang xử lý';
    const s = stageName.toLowerCase();
    
    // 1. Check Phase 1 - 5 (SOLID Architecture)
    if (s.includes('phase 5') || s.includes('p5_export') || s.includes('assembly & export') || s.includes('ghép nối')) return 'Ghép Nối & Xuất Bản Video';
    if (s.includes('phase 4') || s.includes('p4_render') || s.includes('video rendering')) return 'Render Video Tập';
    if (s.includes('phase 3') || s.includes('p3_audio') || s.includes('giọng đọc tts')) return 'Giọng đọc & Phụ đề';
    if (s.includes('phase 2') || s.includes('p2_script') || s.includes('kịch bản ai')) return 'Tạo Kịch bản AI VLM';
    if (s.includes('phase 1') || s.includes('p1_visual') || s.includes('thu thập')) return 'Thu thập & Xử lý Ảnh';

    // 2. Specific Stages (Check two-digit stages 10-13 and 2b FIRST before single digits 1-9 to prevent 'stage 1' matching 'stage 10'!)
    if (/\bstage\s*13\b/i.test(s) || s.includes('cleanup')) return 'Dọn dẹp File tạm';
    if (/\bstage\s*12\b/i.test(s) || s.includes('metadata') || s.includes('reports')) return 'Tạo Báo cáo';
    if (/\bstage\s*11\b/i.test(s) || s.includes('final video assembly') || s.includes('ghép video')) return 'Ghép Video Hoàn chỉnh';
    if (/\bstage\s*10\b/i.test(s) || s.includes('episode video rendering') || s.includes('render video') || s.includes('video render')) return 'Render Video Tập';
    if (/\bstage\s*9\b/i.test(s) || s.includes('subtitle') || s.includes('srt') || s.includes('timeline')) return 'Tạo phụ đề SRT';
    if (/\bstage\s*8\b/i.test(s) || s.includes('local tts') || s.includes('omnivoice') || s.includes('tts') || s.includes('audio')) return 'Tạo giọng đọc TTS';
    if (/\bstage\s*7\b/i.test(s) || s.includes('narration') || s.includes('ssml')) return 'Tổng hợp thoại SSML';
    if (/\bstage\s*6\b/i.test(s) || s.includes('json extraction') || s.includes('json')) return 'Bóc tách JSON';
    if (/\bstage\s*5\b/i.test(s) || s.includes('gemini') || s.includes('vlm')) return 'Gemini VLM Kịch bản';
    if (/\bstage\s*4\b/i.test(s) || s.includes('pdf')) return 'Tạo PDF Truyện';
    if (/\bstage\s*3\b/i.test(s) || s.includes('nsfw')) return 'Kiểm duyệt NSFW';
    if (/\bstage\s*2b\b/i.test(s) || s.includes('re-pagination') || s.includes('phân trang')) return 'Cắt/Phân trang ảnh';
    if (/\bstage\s*2\b/i.test(s) || s.includes('image crawling') || s.includes('crawl')) return 'Tải ảnh truyện';
    if (/\bstage\s*1\b/i.test(s) || s.includes('comic parsing') || s.includes('parsing')) return 'Bóc tách Thông tin Truyện';
    if (/\bstage\s*0\b/i.test(s) || s.includes('project init')) return 'Khởi tạo Dự án';
    if (s.includes('completed')) return 'Hoàn tất';

    return stageName.replace(/^(Stage|Phase)\s*[\d]+[b]?\s*[-:]\s*/i, '');
}

const ALL_STAGE_PRIORITY = [
    "Stage 13 - Cleanup",
    "Stage 12 - Metadata & Reports",
    "Stage 12 - Metadata Reports",
    "Stage 11 - Final Video Assembly",
    "Phase 5 - Assembly & Export",
    "Phase 5 - Ghép Nối & Xuất Bản",
    "Stage 10 - Episode Video Rendering",
    "Phase 4 - Episode Video Rendering",
    "Phase 4 - Render Video Tập",
    "Stage 9 - Subtitle Normalization",
    "Stage 8 - Local TTS",
    "Phase 3 - Giọng đọc TTS & Phụ đề",
    "Stage 7 - Narration Aggregation",
    "Stage 6 - JSON Extraction",
    "Stage 5 - Gemini Automation",
    "Phase 2 - Tạo Kịch bản AI VLM",
    "Stage 4 - PDF Generation",
    "Stage 3 - NSFW Moderation",
    "Stage 2b - Intelligent Re-pagination",
    "Stage 2 - Async Image Crawling",
    "Stage 2 - Image Crawling",
    "Phase 1 - Thu thập & Xử lý Hình ảnh",
    "Stage 1 - Comic Parsing",
    "Stage 0 - Project Init"
];

function getEpisodeStatusInfo(w, ep) {
    const epKey = String(ep);
    const hasVideo = !!(w.artifacts && w.artifacts.final_videos && w.artifacts.final_videos[epKey]);
    const videoUrl = hasVideo ? w.artifacts.final_videos[epKey] : null;
    const srtUrl = (w.artifacts && w.artifacts.final_subtitles && w.artifacts.final_subtitles[epKey]) || '';

    // 1. If episode has video or whole task completed
    if (hasVideo || w.status === 'success') {
        return {
            status: 'success',
            icon: hasVideo ? '🎬' : '✔',
            label: hasVideo ? 'Đã có video' : 'Hoàn tất',
            hasVideo: hasVideo,
            videoUrl: videoUrl,
            srtUrl: srtUrl,
            detail: hasVideo ? 'Đã có video' : 'Hoàn tất'
        };
    }

    const epStages = (w.episode_progress && w.episode_progress[epKey]) || {};

    // 2. Check if any stage failed for this episode
    for (const [stName, stState] of Object.entries(epStages)) {
        if (stState === 'failed') {
            const friendly = getFriendlyStageName(stName);
            return {
                status: 'failed',
                icon: '❌',
                label: 'Lỗi',
                hasVideo: false,
                videoUrl: null,
                srtUrl: '',
                detail: `Lỗi: ${friendly}`
            };
        }
    }

    // 3. Check if any stage is currently running for this episode (check descending priority order)
    for (const stName of ALL_STAGE_PRIORITY) {
        if (epStages[stName] === 'running') {
            const friendly = getFriendlyStageName(stName);
            return {
                status: 'running',
                icon: '⚙',
                label: 'Đang chạy',
                hasVideo: false,
                videoUrl: null,
                srtUrl: '',
                detail: friendly
            };
        }
    }

    // 4. Check any other running stage key in epStages
    for (const [stName, stState] of Object.entries(epStages)) {
        if (stState === 'running') {
            const friendly = getFriendlyStageName(stName);
            return {
                status: 'running',
                icon: '⚙',
                label: 'Đang chạy',
                hasVideo: false,
                videoUrl: null,
                srtUrl: '',
                detail: friendly
            };
        }
    }

    // 5. Find latest completed stage in priority order
    for (const stName of ALL_STAGE_PRIORITY) {
        if (epStages[stName] === 'success') {
            const friendly = getFriendlyStageName(stName);
            if (stName.includes('Stage 10') || stName.includes('Completed')) {
                return {
                    status: 'success',
                    icon: hasVideo ? '🎬' : '✔',
                    label: 'Hoàn tất',
                    hasVideo: hasVideo,
                    videoUrl: videoUrl,
                    srtUrl: srtUrl,
                    detail: 'Đã render video'
                };
            }
            if (w.status === 'running') {
                return {
                    status: 'running',
                    icon: '⚙',
                    label: 'Đang xử lý',
                    hasVideo: false,
                    videoUrl: null,
                    srtUrl: '',
                    detail: `Xong ${friendly}`
                };
            }
        }
    }

    if (w.status === 'running' && String(w.current_episode) === epKey) {
        const friendly = getFriendlyStageName(w.current_stage);
        return {
            status: 'running',
            icon: '⚙',
            label: 'Đang chạy',
            hasVideo: false,
            videoUrl: null,
            srtUrl: '',
            detail: friendly
        };
    }

    if (w.status === 'failed' || w.status === 'cancelled') {
        return {
            status: w.status,
            icon: w.status === 'failed' ? '❌' : '⊘',
            label: w.status === 'failed' ? 'Thất bại' : 'Đã hủy',
            hasVideo: false,
            videoUrl: null,
            srtUrl: '',
            detail: w.error_message || 'Thất bại'
        };
    }

    return {
        status: 'waiting',
        icon: '⌛',
        label: 'Chờ xử lý',
        hasVideo: false,
        videoUrl: null,
        srtUrl: '',
        detail: 'Trong hàng đợi'
    };
}

function getEffectiveCurrentStage(task) {
    if (!task) return 'N/A';
    if (task.status !== 'running') return getFriendlyStageName(task.current_stage) || 'N/A';

    const epProg = task.episode_progress || {};
    const runningList = [];
    for (const epKey of Object.keys(epProg).sort((a, b) => parseInt(a) - parseInt(b))) {
        const epDict = epProg[epKey];
        if (!epDict) continue;
        for (const st of ALL_STAGE_PRIORITY) {
            if (epDict[st] === 'running') {
                runningList.push(`Tập ${epKey}: ${getFriendlyStageName(st)}`);
                break;
            }
        }
    }
    if (runningList.length > 0) {
        if (runningList.length <= 2) {
            return runningList.join(' | ');
        }
        return `${runningList[0]} (+${runningList.length - 1} tập khác)`;
    }

    if (Array.isArray(task.stages)) {
        for (const st of ALL_STAGE_PRIORITY) {
            const found = task.stages.find(s => (s.name === st || s.name.startsWith(st.split(' - ')[0])) && (s.status === 'running' || (s.progress > 0 && s.status !== 'success')));
            if (found) return getFriendlyStageName(found.name);
        }
    }

    return getFriendlyStageName(task.current_stage) || 'N/A';
}

function getEpisodeProgressPercent(w, ep) {
    if (!w) return 0;
    const epKey = String(ep);
    const hasVideo = !!(w.artifacts && w.artifacts.final_videos && w.artifacts.final_videos[epKey]);
    if (hasVideo || w.status === 'success') return 100;

    const epStages = (w.episode_progress && w.episode_progress[epKey]) || {};
    let total = 0;
    const stageWeights = [
        { test: (s) => (/\bstage\s*2\b/i.test(s) && !/2b/i.test(s)) || s.includes("image crawling") || s.includes("phase 1"), weight: 15 },
        { test: (s) => /2b/i.test(s) || s.includes("re-pagination") || s.includes("phân trang"), weight: 10 },
        { test: (s) => /\bstage\s*3\b/i.test(s) || s.includes("nsfw"), weight: 10 },
        { test: (s) => (/\bstage\s*4\b/i.test(s) && !s.includes("phase 4")) || s.includes("pdf"), weight: 10 },
        { test: (s) => (/\bstage\s*5\b/i.test(s) && !s.includes("phase 5")) || s.includes("gemini") || s.includes("phase 2"), weight: 20 },
        { test: (s) => /\bstage\s*6\b/i.test(s) || s.includes("json"), weight: 5 },
        { test: (s) => /\bstage\s*7\b/i.test(s) || s.includes("narration"), weight: 5 },
        { test: (s) => (/\bstage\s*8\b/i.test(s)) || s.includes("local tts") || s.includes("omnivoice") || s.includes("phase 3"), weight: 15 },
        { test: (s) => /\bstage\s*9\b/i.test(s) || s.includes("subtitle") || s.includes("srt"), weight: 5 },
        { test: (s) => (/\bstage\s*10\b/i.test(s)) || s.includes("episode video") || s.includes("phase 4") || s.includes("render"), weight: 5 }
    ];

    for (const sw of stageWeights) {
        let matchedStatus = null;
        for (const [stName, stState] of Object.entries(epStages)) {
            if (sw.test(stName)) {
                matchedStatus = stState;
                break;
            }
        }
        if (matchedStatus === 'success') {
            total += sw.weight;
        } else if (matchedStatus === 'running') {
            total += sw.weight * 0.5;
        }
    }

    if (total > 0) return Math.min(99, Math.round(total));
    if (w.status === 'running' && String(w.current_episode) === epKey) return 10;
    return 0;
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
        
        document.getElementById('active-current-stage').textContent = getEffectiveCurrentStage(activeTask);
        document.getElementById('active-current-episode').textContent = activeTask.current_episode ? `Episode ${activeTask.current_episode}` : 'N/A';
        document.getElementById('active-elapsed').textContent = formatTime(activeTask.elapsed_time);
        document.getElementById('active-remaining').textContent = formatTime(activeTask.estimated_remaining_time);
        
        // Render Active Task Episode Pipeline Matrix
        const matrixEl = document.getElementById('active-episodes-matrix');
        const gridEl = document.getElementById('active-episodes-grid');
        const summaryTxtEl = document.getElementById('active-episodes-summary-txt');
        if (matrixEl && gridEl) {
            matrixEl.style.display = 'flex';
            gridEl.innerHTML = '';
            let aSuccess = 0, aRunning = 0, aFailed = 0;
            const aTotal = activeTask.to_episode - activeTask.from_episode + 1;
            const activeOrFailed = [];

            for (let ep = activeTask.from_episode; ep <= activeTask.to_episode; ep++) {
                const info = getEpisodeStatusInfo(activeTask, ep);
                if (info.status === 'success') aSuccess++;
                else if (info.status === 'running') {
                    aRunning++;
                    activeOrFailed.push({ ep, info });
                } else if (info.status === 'failed') {
                    aFailed++;
                    activeOrFailed.push({ ep, info });
                }
            }

            // For <= 12 episodes show all, for > 12 only show active/failed to avoid UI clutter
            const listToShow = aTotal <= 12 ? 
                Array.from({ length: aTotal }, (_, i) => {
                    const ep = activeTask.from_episode + i;
                    return { ep, info: getEpisodeStatusInfo(activeTask, ep) };
                }) : 
                activeOrFailed;

            if (listToShow.length === 0) {
                gridEl.innerHTML = `
                    <div style="grid-column: 1 / -1; text-align: center; color: var(--text-muted); font-size: 0.75rem; padding: 0.75rem 0.5rem;">
                        Toàn bộ ${aTotal} tập đã hoàn thành bước hiện tại hoặc đang chờ chuyển tiếp.
                    </div>
                `;
            } else {
                listToShow.forEach(({ ep, info }) => {
                    const epCard = document.createElement('div');
                    epCard.className = `active-ep-card ${info.status}`;
                    const pct = getEpisodeProgressPercent(activeTask, ep);
                    let barColor = 'var(--primary-gradient)';
                    if (info.status === 'success') barColor = '#10b981';
                    else if (info.status === 'failed') barColor = '#ef4444';
                    else if (info.status === 'waiting') barColor = 'rgba(255,255,255,0.15)';

                    epCard.innerHTML = `
                        <div style="display: flex; justify-content: space-between; align-items: center;">
                            <span style="font-weight: 600; font-size: 0.8rem; color: var(--text-primary);">Tập ${ep}</span>
                            <div style="display: flex; align-items: center; gap: 0.25rem;">
                                <span style="font-size: 0.7rem; font-weight: 600; color: ${info.status === 'success' ? '#10b981' : (info.status === 'failed' ? '#ef4444' : 'var(--primary)')};">${pct}%</span>
                                <span style="font-size: 0.8rem;">${info.icon}</span>
                            </div>
                        </div>
                        <div style="font-size: 0.7rem; color: var(--text-secondary); text-overflow: ellipsis; overflow: hidden; white-space: nowrap;" title="${info.detail}">${info.detail}</div>
                        <div style="width: 100%; height: 4px; background: rgba(255,255,255,0.08); border-radius: 2px; margin-top: 0.3rem; overflow: hidden;">
                            <div style="width: ${pct}%; height: 100%; background: ${barColor}; border-radius: 2px; transition: width 0.3s ease;"></div>
                        </div>
                        ${info.hasVideo ? `
                            <button class="btn btn-video-play" data-ep="${ep}" data-url="${info.videoUrl}" data-srt="${info.srtUrl}" data-comic="${activeTask.comic_title.replace(/"/g, '&quot;')}" style="font-size: 0.68rem; padding: 0.2rem 0.4rem; height: 22px; margin-top: 0.3rem; background: rgba(16, 185, 129, 0.2); border: 1px solid rgba(16, 185, 129, 0.4); color: #6ee7b7; border-radius: 4px; cursor: pointer; display: flex; align-items: center; justify-content: center; gap: 0.2rem;">
                                <span>▶ Xem Video</span>
                            </button>
                        ` : ''}
                    `;
                    gridEl.appendChild(epCard);
                });
            }
            if (summaryTxtEl) {
                summaryTxtEl.textContent = `Hoàn thành: ${aSuccess}/${aTotal} | Đang chạy: ${aRunning} | Lỗi: ${aFailed}`;
            }
        }

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

        activeContainer.onclick = (e) => {
            const playBtn = e.target.closest('.btn-video-play');
            if (playBtn) {
                e.stopPropagation();
                const ep = playBtn.getAttribute('data-ep');
                const url = playBtn.getAttribute('data-url');
                const comic = playBtn.getAttribute('data-comic');
                const srt = playBtn.getAttribute('data-srt');
                playVideo(url, ep, comic, srt);
            }
        };
    } else {
        activeContainer.style.display = 'none';
    }
    
    // 3. Queue List
    const queueList = document.getElementById('workflow-queue-list');
    if (list.length === 0) {
        queueList.innerHTML = `<div style="text-align: center; color: var(--text-secondary); font-style: italic; padding: 3rem 0; font-size: 0.85rem;">Chưa có nhiệm vụ nào trong danh sách. Nhấn "Bắt đầu chạy" bên trái để tạo task.</div>`;
        return;
    }
    
    queueList.innerHTML = '';
    list.forEach(w => {
        const card = document.createElement('div');
        card.className = 'workflow-card';
        card.style.cursor = 'default';
        
        // Compute episode status information for this task
        const total = w.to_episode - w.from_episode + 1;
        let epSuccess = 0, epRunning = 0, epFailed = 0;
        const activeEpisodes = [];
        const failedEpisodes = [];

        for (let ep = w.from_episode; ep <= w.to_episode; ep++) {
            const info = getEpisodeStatusInfo(w, ep);
            if (info.status === 'success') epSuccess++;
            else if (info.status === 'running') {
                epRunning++;
                activeEpisodes.push({ ep, ...info });
            } else if (info.status === 'failed') {
                epFailed++;
                failedEpisodes.push({ ep, ...info });
            }
        }

        // 1. Video Actions (Clean 1-line recap player)
        let videoActionsHtml = '';
        const hasCombined = w.artifacts && w.artifacts.final_video_url && w.from_episode !== w.to_episode;
        const hasSingleVideo = w.artifacts && w.artifacts.final_video_url && w.from_episode === w.to_episode;
        const hasEpisodeVideos = w.artifacts && w.artifacts.final_videos && Object.keys(w.artifacts.final_videos).length > 0;

        if (hasCombined || hasSingleVideo || hasEpisodeVideos) {
            let combinedBtnHtml = '';
            if (hasCombined) {
                combinedBtnHtml = `
                    <button class="btn btn-video-play" data-ep="${w.from_episode}-${w.to_episode}" data-url="${w.artifacts.final_video_url}" data-srt="${w.artifacts.final_subtitle_url || ''}" data-comic="${w.comic_title.replace(/"/g, '&quot;')}" style="font-size: 0.72rem; padding: 0.25rem 0.65rem; height: 26px; background: linear-gradient(135deg, #ef4444 0%, #b91c1c 100%); border: none; color: #fff; border-radius: 5px; cursor: pointer; display: inline-flex; align-items: center; gap: 0.3rem; font-weight: 600; box-shadow: 0 2px 6px rgba(239,68,68,0.35);">
                        <span>🎬</span>
                        <span>Tổng hợp (${w.from_episode}-${w.to_episode})</span>
                    </button>
                `;
            } else if (hasSingleVideo) {
                combinedBtnHtml = `
                    <button class="btn btn-video-play" data-ep="${w.from_episode}" data-url="${w.artifacts.final_video_url}" data-srt="${w.artifacts.final_subtitle_url || ''}" data-comic="${w.comic_title.replace(/"/g, '&quot;')}" style="font-size: 0.72rem; padding: 0.25rem 0.65rem; height: 26px; background: linear-gradient(135deg, #ef4444 0%, #b91c1c 100%); border: none; color: #fff; border-radius: 5px; cursor: pointer; display: inline-flex; align-items: center; gap: 0.3rem; font-weight: 600; box-shadow: 0 2px 6px rgba(239,68,68,0.35);">
                        <span>🎬</span>
                        <span>Xem Video Tập ${w.from_episode}</span>
                    </button>
                `;
            }

            let epSelectHtml = '';
            if (hasEpisodeVideos) {
                const epEntries = Object.entries(w.artifacts.final_videos)
                    .map(([ep, url]) => ({
                        ep: parseInt(ep),
                        url,
                        srt: (w.artifacts.final_subtitles && w.artifacts.final_subtitles[ep]) || ''
                    }))
                    .sort((a, b) => a.ep - b.ep);

                if (epEntries.length <= 4) {
                    epSelectHtml = epEntries.map(v => `
                        <button class="btn btn-video-play" data-ep="${v.ep}" data-url="${v.url}" data-srt="${v.srt}" data-comic="${w.comic_title.replace(/"/g, '&quot;')}" style="font-size: 0.7rem; padding: 0.2rem 0.5rem; height: 24px; background: rgba(239, 68, 68, 0.15); border: 1px solid rgba(239, 68, 68, 0.35); color: #fca5a5; border-radius: 4px; cursor: pointer; display: inline-flex; align-items: center; gap: 0.2rem;">
                            <span>▶</span>
                            <span>Tập ${v.ep}</span>
                        </button>
                    `).join('');
                } else {
                    const selectId = `select-ep-play-${w.id}`;
                    const options = epEntries.map(v => `
                        <option value="${v.ep}" data-url="${v.url}" data-srt="${v.srt}">Tập ${v.ep}</option>
                    `).join('');

                    epSelectHtml = `
                        <div class="ep-select-group" style="display: inline-flex; align-items: center; gap: 0.3rem; background: rgba(255,255,255,0.04); padding: 0.1rem 0.25rem; border-radius: 5px; border: 1px solid var(--card-border);">
                            <span style="font-size: 0.7rem; color: var(--text-secondary); padding-left: 0.25rem;">Tập lẻ:</span>
                            <select id="${selectId}" style="height: 24px; font-size: 0.72rem; padding: 0 0.35rem; background: #1a1614; color: #fff; border: 1px solid var(--card-border); border-radius: 4px; outline: none; cursor: pointer;" onclick="event.stopPropagation();">
                                ${options}
                            </select>
                            <button class="btn btn-play-from-select" data-select-id="${selectId}" data-comic="${w.comic_title.replace(/"/g, '&quot;')}" style="font-size: 0.7rem; padding: 0.2rem 0.5rem; height: 24px; background: rgba(239, 68, 68, 0.2); border: 1px solid rgba(239, 68, 68, 0.4); color: #fca5a5; border-radius: 4px; cursor: pointer; display: inline-flex; align-items: center; gap: 0.2rem; font-weight: 500;">
                                <span>▶ Xem</span>
                            </button>
                        </div>
                    `;
                }
            }

            videoActionsHtml = `
                <div style="margin-top: 0.6rem; display: flex; align-items: center; flex-wrap: wrap; gap: 0.4rem;">
                    ${combinedBtnHtml}
                    ${epSelectHtml}
                </div>
            `;
        }

        // 2. Active / Error Notice (Only shown if running or failed!)
        let statusNoticeHtml = '';
        if (w.status === 'running' && activeEpisodes.length > 0) {
            statusNoticeHtml = `
                <div style="margin-top: 0.5rem; font-size: 0.73rem; color: #93c5fd; display: flex; align-items: flex-start; gap: 0.4rem; background: rgba(59, 130, 246, 0.08); padding: 0.35rem 0.6rem; border-radius: 6px; border: 1px solid rgba(59, 130, 246, 0.22);">
                    <i data-lucide="loader" style="width: 0.85rem; height: 0.85rem; animation: spin 1s linear infinite; margin-top: 2px; flex-shrink: 0;"></i>
                    <div style="display: flex; flex-wrap: wrap; gap: 0.35rem; align-items: center;">
                        <span style="font-weight: 600; color: #bfdbfe;">Đang xử lý:</span>
                        ${activeEpisodes.map(e => `
                            <span style="display: inline-flex; align-items: center; gap: 0.2rem; background: rgba(59, 130, 246, 0.18); border: 1px solid rgba(59, 130, 246, 0.35); padding: 0.1rem 0.45rem; border-radius: 4px; font-size: 0.72rem; color: #ffffff;">
                                <strong>Tập ${e.ep}</strong>: <span style="color: #93c5fd;">${e.detail}</span>
                            </span>
                        `).slice(0, 4).join('')}${activeEpisodes.length > 4 ? `<span style="font-size: 0.7rem; color: #93c5fd;">+${activeEpisodes.length - 4} tập khác</span>` : ''}
                    </div>
                </div>
            `;
        } else if (failedEpisodes.length > 0) {
            statusNoticeHtml = `
                <div style="margin-top: 0.5rem; font-size: 0.73rem; color: #fca5a5; display: flex; align-items: flex-start; gap: 0.4rem; background: rgba(239, 68, 68, 0.08); padding: 0.35rem 0.6rem; border-radius: 6px; border: 1px solid rgba(239, 68, 68, 0.22);">
                    <i data-lucide="alert-circle" style="width: 0.85rem; height: 0.85rem; color: #ef4444; margin-top: 2px; flex-shrink: 0;"></i>
                    <div style="display: flex; flex-wrap: wrap; gap: 0.35rem; align-items: center;">
                        <span style="font-weight: 600; color: #fecaca;">Gặp lỗi:</span>
                        ${failedEpisodes.map(e => `
                            <span style="display: inline-flex; align-items: center; gap: 0.2rem; background: rgba(239, 68, 68, 0.18); border: 1px solid rgba(239, 68, 68, 0.35); padding: 0.1rem 0.45rem; border-radius: 4px; font-size: 0.72rem; color: #ffffff;">
                                <strong>Tập ${e.ep}</strong>: <span style="color: #fca5a5;">${e.detail}</span>
                            </span>
                        `).join('')}
                    </div>
                </div>
            `;
        }

        // Build per-episode mini progress cards grid
        let episodeBarsHtml = '';
        const epList = [];
        for (let ep = w.from_episode; ep <= w.to_episode; ep++) {
            const info = getEpisodeStatusInfo(w, ep);
            const pct = getEpisodeProgressPercent(w, ep);
            epList.push({ ep, info, pct });
        }

        // Always render as a neat, responsive Grid
        const gridColsStyle = total === 1 ? 'grid-template-columns: 1fr;' : 
                              total === 2 ? 'grid-template-columns: repeat(auto-fill, minmax(160px, 1fr));' :
                              'grid-template-columns: repeat(auto-fill, minmax(130px, 1fr));';

        episodeBarsHtml = `
            <div class="ep-progress-grid" style="display: grid; ${gridColsStyle} gap: 0.4rem; margin-top: 0.45rem;">
                ${epList.map(({ ep, info, pct }) => {
                    let barColor = 'var(--primary-gradient)';
                    let pctColor = 'var(--primary)';

                    if (info.status === 'success') {
                        barColor = '#10b981';
                        pctColor = '#10b981';
                    } else if (info.status === 'failed') {
                        barColor = '#ef4444';
                        pctColor = '#ef4444';
                    } else if (info.status === 'running') {
                        pctColor = '#FFAE6E';
                    } else if (info.status === 'waiting') {
                        barColor = 'rgba(255,255,255,0.18)';
                        pctColor = 'var(--text-muted)';
                    }

                    return `
                        <div class="ep-grid-card ${info.status}" title="Tập ${ep}: ${info.detail} (${pct}%)">
                            <div style="display: flex; justify-content: space-between; align-items: center;">
                                <span style="font-weight: 600; font-size: 0.76rem; color: var(--text-primary);">Tập ${ep}</span>
                                <div style="display: flex; align-items: center; gap: 0.25rem;">
                                    <span style="font-size: 0.7rem; font-weight: 600; color: ${pctColor};">${pct}%</span>
                                    <span style="font-size: 0.74rem;">${info.icon}</span>
                                </div>
                            </div>
                            <div style="font-size: 0.67rem; color: var(--text-secondary); overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">${info.detail}</div>
                            <div style="width: 100%; height: 4px; background: rgba(255,255,255,0.06); border-radius: 2px; overflow: hidden; margin-top: 2px;">
                                <div style="width: ${pct}%; height: 100%; background: ${barColor}; border-radius: 2px; transition: width 0.3s ease;"></div>
                            </div>
                            ${info.hasVideo ? `
                                <button class="btn btn-video-play" data-ep="${ep}" data-url="${info.videoUrl}" data-srt="${info.srtUrl}" data-comic="${w.comic_title.replace(/"/g, '&quot;')}" style="font-size: 0.65rem; padding: 0.15rem 0.35rem; height: 20px; margin-top: 0.2rem; background: rgba(16, 185, 129, 0.18); border: 1px solid rgba(16, 185, 129, 0.35); color: #6ee7b7; border-radius: 3px; cursor: pointer; display: flex; align-items: center; justify-content: center; gap: 0.2rem;">
                                    <span>▶ Xem Video</span>
                                </button>
                            ` : ''}
                        </div>
                    `;
                }).join('')}
            </div>
        `;

        // 3. Compact Card Layout
        card.innerHTML = `
            <div class="workflow-card-header" style="margin-bottom: 0.35rem;">
                <div>
                    <span class="workflow-card-title">${w.comic_title}</span>
                    <div class="workflow-card-meta">
                        Tập ${w.from_episode} → ${w.to_episode}${w.language ? ` | Ngôn ngữ: <span style="text-transform: uppercase; font-weight: bold; color: var(--primary);">${w.language}</span>` : ''}${w.elapsed_time ? ` | ⏱ ${formatTime(w.elapsed_time)}` : ''}
                    </div>
                </div>
                <div style="display: flex; align-items: center; gap: 0.4rem;">
                    <span class="badge ${w.status}">${w.status}</span>
                </div>
            </div>

            <!-- Episode Progress List / Grid -->
            <div style="display: flex; justify-content: space-between; align-items: center; font-size: 0.75rem; color: var(--text-secondary); margin-top: 0.35rem;">
                <span>Tiến độ từng tập: <strong style="color: var(--text-primary);">${epSuccess}/${total} tập hoàn thành</strong></span>
                <span style="font-size: 0.72rem; color: var(--text-muted);">${w.status === 'running' ? 'Đang chạy song song' : ''}</span>
            </div>
            ${episodeBarsHtml}

            <!-- Active / Error Notice (if any) -->
            ${statusNoticeHtml}

            <!-- Video Actions (Compact, 1 Line) -->
            ${videoActionsHtml}

            <!-- Footer Actions -->
            <div style="margin-top: 0.65rem; padding-top: 0.45rem; border-top: 1px solid rgba(255,255,255,0.05); display: flex; justify-content: space-between; align-items: center;">
                <div style="font-size: 0.7rem; color: var(--text-muted);">
                    ${w.status === 'running' ? `Giai đoạn: <span style="color: var(--primary);">${getEffectiveCurrentStage(w)}</span>` : ''}
                </div>
                <div class="workflow-card-actions" style="display: flex; gap: 0.35rem;" onclick="event.stopPropagation();">
                    <button class="btn btn-card-logs" style="font-size: 0.72rem; padding: 0.25rem 0.55rem; height: 26px; background: rgba(255,255,255,0.06); border: 1px solid var(--card-border); color: var(--text-primary); border-radius: 4px; cursor: pointer;">Logs</button>
                    ${(w.status === 'running' || w.status === 'waiting') ? 
                        `<button class="btn btn-card-cancel" style="font-size: 0.72rem; padding: 0.25rem 0.55rem; height: 26px; background: #ef4444; border: none; color: white; border-radius: 4px; cursor: pointer;">Hủy</button>` : 
                        `
                        ${(w.status === 'failed' || w.status === 'cancelled') ? 
                            `<button class="btn btn-card-retry" style="font-size: 0.72rem; padding: 0.25rem 0.55rem; height: 26px; background: #f97316; border: none; color: white; border-radius: 4px; cursor: pointer;">Chạy lại</button>` : ''
                        }
                        <button class="btn btn-card-remove" style="font-size: 0.72rem; padding: 0.25rem 0.55rem; height: 26px; background: rgba(255,255,255,0.06); border: 1px solid var(--card-border); color: var(--text-primary); border-radius: 4px; cursor: pointer;">Xóa</button>
                        `
                    }
                </div>
            </div>
        `;

        card.onclick = (e) => {
            const playBtn = e.target.closest('.btn-video-play');
            if (playBtn) {
                e.stopPropagation();
                const ep = playBtn.getAttribute('data-ep');
                const url = playBtn.getAttribute('data-url');
                const comic = playBtn.getAttribute('data-comic');
                const srt = playBtn.getAttribute('data-srt');
                playVideo(url, ep, comic, srt);
                return;
            }

            const playFromSelectBtn = e.target.closest('.btn-play-from-select');
            if (playFromSelectBtn) {
                e.stopPropagation();
                const selectId = playFromSelectBtn.getAttribute('data-select-id');
                const sel = document.getElementById(selectId);
                if (sel && sel.selectedOptions.length > 0) {
                    const opt = sel.selectedOptions[0];
                    const ep = opt.value;
                    const url = opt.getAttribute('data-url');
                    const srt = opt.getAttribute('data-srt') || '';
                    const comic = playFromSelectBtn.getAttribute('data-comic') || '';
                    playVideo(url, ep, comic, srt);
                }
                return;
            }
        };

        card.querySelectorAll('.btn-play-from-select').forEach(btn => {
            btn.onclick = (e) => {
                e.stopPropagation();
                const selectId = btn.getAttribute('data-select-id');
                const sel = document.getElementById(selectId);
                if (sel && sel.selectedOptions.length > 0) {
                    const opt = sel.selectedOptions[0];
                    const ep = opt.value;
                    const url = opt.getAttribute('data-url');
                    const srt = opt.getAttribute('data-srt') || '';
                    const comic = btn.getAttribute('data-comic') || '';
                    playVideo(url, ep, comic, srt);
                }
            };
        });

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



// Load Chrome Profiles Configuration
async function loadProfilesConfig() {
    try {
        const response = await fetch('/api/config');
        const config = await response.json();
        
        const textarea = document.getElementById('chrome-profiles-textarea');
        const select = document.getElementById('active-profile-select');
        const showBrowserToggle = document.getElementById('show-browser-toggle');
        
        if (textarea && config.chrome_profiles) {
            textarea.value = config.chrome_profiles.join('\n');
        }
        
        if (select) {
            updateProfileSelectOptions(config.chrome_profiles, config.current_profile_index);
        }

        if (showBrowserToggle) {
            if (typeof config.headless !== 'undefined') {
                showBrowserToggle.checked = !config.headless;
            } else {
                showBrowserToggle.checked = true;
            }
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

// Auto-sync headless mode on toggle change
const showBrowserToggle = document.getElementById('show-browser-toggle');
if (showBrowserToggle) {
    showBrowserToggle.addEventListener('change', async () => {
        const isHeadless = !showBrowserToggle.checked;
        try {
            await fetch('/api/config', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    headless: isHeadless
                })
            });
            appendLog(`Chế độ Chrome: ${isHeadless ? 'Chạy nền ẩn cửa sổ (Headless)' : 'Hiển thị cửa sổ (Headed)'}`, 'system');
        } catch (err) {
            console.error('Lỗi cập nhật cấu hình headless:', err);
        }
    });
}

// Chrome Profiles Configuration Handlers
const btnSaveProfiles = document.getElementById('btn-save-profiles');
if (btnSaveProfiles) {
    btnSaveProfiles.addEventListener('click', async () => {
        const textarea = document.getElementById('chrome-profiles-textarea');
        const select = document.getElementById('active-profile-select');
        const showBrowserToggle = document.getElementById('show-browser-toggle');
        if (!textarea || !select) return;
        
        const lines = textarea.value.split('\n').map(l => l.trim()).filter(l => l !== '');
        const selectedIdx = parseInt(select.value) || 0;
        const isHeadless = showBrowserToggle ? !showBrowserToggle.checked : false;
        
        appendLog('Đang lưu cấu hình Chrome Profiles...', 'system');
        
        try {
            const response = await fetch('/api/config', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    chrome_profiles: lines,
                    current_profile_index: selectedIdx,
                    headless: isHeadless
                })
            });
            const result = await response.json();
            if (response.ok) {
                appendLog('Đã lưu cấu hình Chrome Profiles thành công!', 'success');
                updateProfileSelectOptions(result.config.chrome_profiles, result.config.current_profile_index);
                if (showBrowserToggle && typeof result.config.headless !== 'undefined') {
                    showBrowserToggle.checked = !result.config.headless;
                }
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

// Handle comix-group-area visibility based on input URL
if (inputUrl) {
    inputUrl.addEventListener('input', () => {
        const url = inputUrl.value.trim();
        const comixGroupArea = document.getElementById('comix-group-area');
        if (comixGroupArea) {
            if (url.includes('comix.to')) {
                comixGroupArea.style.display = 'block';
            } else {
                comixGroupArea.style.display = 'none';
            }
        }
    });
}

// Load Episode Click Handler (if present in DOM)
if (btnLoadEpisodes) {
    btnLoadEpisodes.addEventListener('click', async () => {
        const url = inputUrl.value.trim();
        if (!url) {
            appendLog('Vui lòng nhập đường dẫn bộ truyện trước.', 'warning');
            return;
        }

        appendLog('Đang phân tích thông tin bộ truyện...', 'system');
        btnLoadEpisodes.disabled = true;
        setStatus('active', 'Phân tích truyện');

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
                if (infoSeriesName) infoSeriesName.textContent = `Truyện: ${result.title}`;
                if (infoTotalEps) infoTotalEps.textContent = `${result.total_episodes}`;
                
                if (inputFromEpisode) {
                    inputFromEpisode.value = 1;
                    inputFromEpisode.max = result.total_episodes;
                }
                
                if (inputToEpisode) {
                    inputToEpisode.value = result.total_episodes;
                    inputToEpisode.max = result.total_episodes;
                }
                
                const comixGroupArea = document.getElementById('comix-group-area');
                if (comixGroupArea) {
                    if (url.includes('comix.to')) {
                        comixGroupArea.style.display = 'block';
                    } else {
                        comixGroupArea.style.display = 'none';
                    }
                }
                
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
}

// Crawl Click Handler
btnCrawl.addEventListener('click', async () => {
    const url = inputUrl.value.trim();
    const fromEp = parseInt(inputFromEpisode.value);
    const toEp = parseInt(inputToEpisode.value);

    if (!url) {
        appendLog('Vui lòng nhập đường link (URL) truyện trước khi bắt đầu.', 'warning');
        if (inputUrl) inputUrl.focus();
        return;
    }

    if (!url.startsWith('http://') && !url.startsWith('https://')) {
        appendLog('URL truyện không hợp lệ (phải bắt đầu bằng http:// hoặc https://).', 'warning');
        if (inputUrl) inputUrl.focus();
        return;
    }

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
                safe_mode: document.getElementById('safe-mode') ? document.getElementById('safe-mode').checked : false,
                nsfw_threshold: document.getElementById('nsfw-threshold') ? parseFloat(document.getElementById('nsfw-threshold').value) : 0.3,
                nsfw_mode: 'blur',
                gemini_model: document.getElementById('gemini-model') ? document.getElementById('gemini-model').value : 'flash',
                temperature: document.getElementById('vlm-temperature') ? parseFloat(document.getElementById('vlm-temperature').value) : 0.7,
                max_output_tokens: 2048,
                timeout: document.getElementById('vlm-timeout') ? parseInt(document.getElementById('vlm-timeout').value) : 160,
                retry_count: document.getElementById('vlm-retries') ? parseInt(document.getElementById('vlm-retries').value) : 3,
                concurrency: document.getElementById('vlm-concurrency') ? parseInt(document.getElementById('vlm-concurrency').value) : 5,
                image_quality: document.getElementById('image-quality') ? parseInt(document.getElementById('image-quality').value) : 20,
                pdf_quality: document.getElementById('image-quality') ? parseInt(document.getElementById('image-quality').value) : 20,
                language: document.getElementById('vlm-language').value,
                vlm_provider: document.getElementById('vlm-provider') ? document.getElementById('vlm-provider').value : 'gemini',
                voice_id: document.getElementById('tts-voice-id').value === 'design' ? (document.getElementById('omnivoice-instruct') ? document.getElementById('omnivoice-instruct').value : 'female, low pitch, american accent') : document.getElementById('tts-voice-id').value,
                ref_audio_path: document.getElementById('tts-voice-id').value === 'clone' ? uploadedRefAudioPath : (document.getElementById('tts-voice-id').value === 'auto' ? (document.getElementById('auto-voice-selected-path') ? document.getElementById('auto-voice-selected-path').value || null : null) : null),
                ai33pro_api_key: document.getElementById('tts-voice-id').value === 'ai33pro' && document.getElementById('ai33pro-api-key') ? document.getElementById('ai33pro-api-key').value.trim() : null,
                logo_path: uploadedLogoPath,
                overlay_path: uploadedOverlayPath,
                remove_text: false,
                remove_text_conf: 0.3,
                remove_text_radius: 3,
                flip_horizontal: document.getElementById('flip-horizontal') ? document.getElementById('flip-horizontal').checked : false,
                headless: document.getElementById('show-browser-toggle') ? !document.getElementById('show-browser-toggle').checked : false,
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

// Video modal player and subtitle state variables
let currentComicTitle = '';
let currentEpisodeNum = '';
let currentSrtCues = [];
let currentSrtOriginalCues = [];
let currentSrtTranslatedCues = [];
let currentSrtDisplayMode = 'translated'; // 'translated', 'bilingual', 'original'
let currentTranslatedLang = '';
let isTranslatingSubtitles = false;
let currentSrtRaw = '';
let isSubtitlesEnabled = true;
let isTranscriptOpen = true;
let subtitleFontSize = 1.15; // rem
let activeCueIndex = -1;

function escapeHtml(str) {
    if (!str) return '';
    return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#039;');
}

function srtTimeToSeconds(tStr) {
    if (!tStr) return 0;
    const clean = tStr.trim().replace(',', '.');
    const parts = clean.split(':');
    if (parts.length === 3) {
        return parseFloat(parts[0]) * 3600 + parseFloat(parts[1]) * 60 + parseFloat(parts[2]);
    } else if (parts.length === 2) {
        return parseFloat(parts[0]) * 60 + parseFloat(parts[1]);
    }
    return parseFloat(clean) || 0;
}

function parseSRT(srtText) {
    if (!srtText) return [];
    const cues = [];
    const text = srtText.replace(/^\ufeff/, '').replace(/\r\n/g, '\n').replace(/\r/g, '\n').trim();
    const blocks = text.split(/\n\s*\n/);
    
    for (const block of blocks) {
        const lines = block.trim().split('\n');
        if (lines.length < 2) continue;
        
        let timeIndex = -1;
        for (let i = 0; i < lines.length; i++) {
            if (lines[i].includes('-->')) {
                timeIndex = i;
                break;
            }
        }
        
        if (timeIndex !== -1) {
            const timeLine = lines[timeIndex];
            const match = timeLine.match(/(\d{1,2}:\d{2}:\d{2}[,\.]\d{1,3})\s*-->\s*(\d{1,2}:\d{2}:\d{2}[,\.]\d{1,3})/);
            if (match) {
                const startStr = match[1].trim();
                const endStr = match[2].trim();
                const startSec = srtTimeToSeconds(startStr);
                const endSec = srtTimeToSeconds(endStr);
                const cueText = lines.slice(timeIndex + 1).join('\n').trim();
                if (cueText) {
                    cues.push({
                        id: cues.length + 1,
                        start: startSec,
                        end: endSec,
                        startStr: startStr.split(/[,.]/)[0],
                        endStr: endStr.split(/[,.]/)[0],
                        fullStartStr: startStr,
                        fullEndStr: endStr,
                        text: cueText,
                        originalText: cueText,
                        translatedText: ''
                    });
                }
            }
        }
    }
    return cues;
}

function generateSrtFromCues(cues) {
    if (!cues || !cues.length) return '';
    return cues.map((cue, idx) => {
        const startStr = cue.fullStartStr || cue.startStr || '00:00:00,000';
        const endStr = cue.fullEndStr || cue.endStr || '00:00:00,000';
        return `${idx + 1}\n${startStr} --> ${endStr}\n${cue.text}\n`;
    }).join('\n');
}

function srtToWebVTT(srtText) {
    if (!srtText) return '';
    let cleaned = srtText.replace(/\r\n/g, '\n').replace(/\r/g, '\n').trim();
    cleaned = cleaned.replace(/(\d{2}:\d{2}:\d{2}),(\d{3})/g, '$1.$2');
    return "WEBVTT\n\n" + cleaned;
}

function updateVideoTrack(srtText) {
    modalVideoPlayer.querySelectorAll('track').forEach(t => t.remove());
    if (!srtText || !srtText.trim() || !currentSrtCues.length) return;
    try {
        const vtt = srtToWebVTT(srtText);
        const blob = new Blob([vtt], { type: 'text/vtt' });
        const trackUrl = URL.createObjectURL(blob);
        const track = document.createElement('track');
        track.kind = 'subtitles';
        track.label = currentTranslatedLang ? `Phụ đề (${currentTranslatedLang.toUpperCase()})` : 'Tiếng Việt';
        track.srclang = currentTranslatedLang || 'vi';
        track.src = trackUrl;
        track.default = true;
        modalVideoPlayer.appendChild(track);
        if (track.track) {
            track.track.mode = (isSubtitlesEnabled && !!document.fullscreenElement) ? 'showing' : 'hidden';
        }
    } catch (e) {
        console.warn('Lỗi cập nhật track WebVTT:', e);
    }
}

function updateSubtitleToggleState() {
    if (!btnToggleSubtitles) return;
    if (isSubtitlesEnabled) {
        btnToggleSubtitles.style.background = 'rgba(255, 174, 110, 0.15)';
        btnToggleSubtitles.style.borderColor = 'var(--primary)';
        btnToggleSubtitles.style.color = 'var(--primary)';
        if (subtitleToggleText) subtitleToggleText.textContent = 'Phụ đề: Bật';
        if (currentSrtCues.length > 0 && activeCueIndex !== -1 && !document.fullscreenElement) {
            if (videoSubtitleOverlay) videoSubtitleOverlay.style.display = 'block';
        }
    } else {
        btnToggleSubtitles.style.background = 'rgba(255, 255, 255, 0.05)';
        btnToggleSubtitles.style.borderColor = 'var(--card-border)';
        btnToggleSubtitles.style.color = 'var(--text-muted)';
        if (subtitleToggleText) subtitleToggleText.textContent = 'Phụ đề: Tắt';
        if (videoSubtitleOverlay) videoSubtitleOverlay.style.display = 'none';
    }
    const track = modalVideoPlayer.querySelector('track');
    if (track && track.track) {
        track.track.mode = (isSubtitlesEnabled && !!document.fullscreenElement) ? 'showing' : 'hidden';
    }
}

function updateActiveSubtitleOverlay() {
    if (!currentSrtCues.length || activeCueIndex === -1) {
        if (videoSubtitleOverlay && videoSubtitleOverlay.style.display !== 'none') {
            videoSubtitleOverlay.style.display = 'none';
        }
        if (videoSubtitleText) videoSubtitleText.innerHTML = '';
        return;
    }

    const cue = currentSrtCues[activeCueIndex];
    if (!cue) return;

    if (isSubtitlesEnabled && videoSubtitleText) {
        if (currentSrtDisplayMode === 'bilingual' && cue.originalText && cue.translatedText) {
            videoSubtitleText.innerHTML = `
                <div class="sub-bilingual-orig">${escapeHtml(cue.originalText).replace(/\n/g, '<br>')}</div>
                <div class="sub-bilingual-trans">${escapeHtml(cue.translatedText).replace(/\n/g, '<br>')}</div>
            `;
        } else {
            videoSubtitleText.innerHTML = escapeHtml(cue.text).replace(/\n/g, '<br>');
        }
        if (!document.fullscreenElement && videoSubtitleOverlay) {
            videoSubtitleOverlay.style.display = 'block';
        }
    } else {
        if (videoSubtitleOverlay) videoSubtitleOverlay.style.display = 'none';
    }
}

function renderTranscriptList() {
    if (!videoTranscriptList) return;
    videoTranscriptList.innerHTML = '';
    if (currentSrtCues.length === 0) {
        videoTranscriptList.innerHTML = `
            <div style="text-align: center; color: var(--text-muted); font-size: 0.8rem; padding: 2rem 1rem;">
                Không tìm thấy câu thoại hợp lệ trong tệp.
            </div>
        `;
        return;
    }

    const fragment = document.createDocumentFragment();
    currentSrtCues.forEach((cue, index) => {
        const item = document.createElement('div');
        item.className = 'transcript-cue-item';
        if (index === activeCueIndex) {
            item.classList.add('active');
        }
        item.setAttribute('data-cue-idx', index);

        let textHtml = '';
        if (currentSrtDisplayMode === 'bilingual' && cue.originalText && cue.translatedText) {
            textHtml = `
                <div class="sub-bilingual-orig">${escapeHtml(cue.originalText).replace(/\n/g, '<br>')}</div>
                <div class="sub-bilingual-trans">${escapeHtml(cue.translatedText).replace(/\n/g, '<br>')}</div>
            `;
        } else {
            textHtml = `<div class="cue-text">${escapeHtml(cue.text).replace(/\n/g, '<br>')}</div>`;
        }

        item.innerHTML = `
            <div class="cue-time">
                <svg style="width: 0.75rem; height: 0.75rem; flex-shrink: 0; opacity: 0.7;" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>
                <span>${cue.startStr} &rarr; ${cue.endStr}</span>
            </div>
            ${textHtml}
        `;
        item.addEventListener('click', () => {
            modalVideoPlayer.currentTime = Math.max(0, cue.start - 0.05);
            modalVideoPlayer.play().catch(() => {});
        });
        fragment.appendChild(item);
    });
    videoTranscriptList.appendChild(fragment);
}

function applySrtDisplayMode(mode = 'translated') {
    currentSrtDisplayMode = mode;
    if (!currentSrtOriginalCues.length) return;

    if (mode === 'original' || !currentSrtTranslatedCues.length) {
        currentSrtCues = currentSrtOriginalCues.map(c => ({
            ...c,
            text: c.originalText || c.text
        }));
    } else if (mode === 'translated') {
        currentSrtCues = currentSrtTranslatedCues.map(c => ({
            ...c,
            text: c.translatedText || c.text
        }));
    } else if (mode === 'bilingual') {
        currentSrtCues = currentSrtOriginalCues.map((c, i) => {
            const trans = currentSrtTranslatedCues[i];
            const orig = c.originalText || c.text;
            const transText = trans ? (trans.translatedText || trans.text) : orig;
            return {
                ...c,
                originalText: orig,
                translatedText: transText,
                text: `${orig}\n${transText}`
            };
        });
    }

    const activeSrt = generateSrtFromCues(currentSrtCues);
    currentSrtRaw = activeSrt;
    updateVideoTrack(activeSrt);
    renderTranscriptList();
    updateActiveSubtitleOverlay();
}

function applySrtContent(srtText, sourceName = 'transcript.srt') {
    currentSrtRaw = srtText;
    currentSrtCues = parseSRT(srtText);
    currentSrtOriginalCues = currentSrtCues.map(c => ({ ...c }));
    currentSrtTranslatedCues = [];
    currentTranslatedLang = '';
    currentSrtDisplayMode = 'original';
    if (selectSubDisplayMode) {
        selectSubDisplayMode.style.display = 'none';
        selectSubDisplayMode.value = 'translated';
    }
    if (btnTranslateSubText) {
        btnTranslateSubText.textContent = 'Dịch Live';
    }
    activeCueIndex = -1;

    // 1. Setup native HTML5 WebVTT track
    updateVideoTrack(srtText);

    if (currentSrtCues.length > 0) {
        if (subtitleStatusText) {
            subtitleStatusText.textContent = `Phụ đề: ${sourceName} (${currentSrtCues.length} câu thoại)`;
        }
        if (transcriptCountBadge) {
            transcriptCountBadge.textContent = `${currentSrtCues.length} câu`;
        }
    } else {
        if (subtitleStatusText) {
            subtitleStatusText.textContent = `Tệp phụ đề trống hoặc không đúng chuẩn SRT`;
        }
        if (transcriptCountBadge) {
            transcriptCountBadge.textContent = `0 câu`;
        }
    }

    // 2. Render transcript list
    renderTranscriptList();
}

async function playVideo(videoUrl, episodeNum, comicTitle, explicitSrtUrl = null) {
    currentComicTitle = comicTitle || 'recap';
    currentEpisodeNum = episodeNum || '';
    if (videoModalTitle) {
        videoModalTitle.textContent = `Phát Video Recap - ${comicTitle || 'Recap'} - Tập ${episodeNum || ''}`;
    }
    
    // 1. Normalize videoUrl & explicitSrtUrl
    let normVideo = (videoUrl || '').replace(/\\/g, '/').trim();
    const dIdx = normVideo.toLowerCase().indexOf('downloads/');
    if (dIdx !== -1) {
        normVideo = '/downloads/' + normVideo.substring(dIdx + 10).replace(/^\/+/, '');
    } else if (normVideo && !normVideo.startsWith('http://') && !normVideo.startsWith('https://') && !normVideo.startsWith('/')) {
        normVideo = '/' + normVideo;
    }

    let normSrt = (explicitSrtUrl || '').replace(/\\/g, '/').trim();
    const srtDIdx = normSrt.toLowerCase().indexOf('downloads/');
    if (srtDIdx !== -1) {
        normSrt = '/downloads/' + normSrt.substring(srtDIdx + 10).replace(/^\/+/, '');
    } else if (normSrt && !normSrt.startsWith('http://') && !normSrt.startsWith('https://') && !normSrt.startsWith('/')) {
        normSrt = '/' + normSrt;
    }

    // 2. Extract comic folder
    let matchFolder = normVideo.match(/\/downloads\/([^\/]+)/i);
    let comicFolder = (matchFolder && matchFolder[1] && matchFolder[1].toLowerCase() !== 'none') ? matchFolder[1] : '';
    if (!comicFolder && currentComicFolder) {
        comicFolder = currentComicFolder;
    }
    if (!comicFolder && comicTitle && typeof workflows === 'object') {
        const matchedWf = Object.values(workflows).find(w => w.comic_title === comicTitle);
        if (matchedWf && matchedWf.artifacts && matchedWf.artifacts.download_folder_name) {
            comicFolder = matchedWf.artifacts.download_folder_name;
        }
    }

    // Repair video URL if it contained 'None'
    if (normVideo.includes('/downloads/None/') && comicFolder) {
        normVideo = normVideo.replace('/downloads/None/', `/downloads/${comicFolder}/`);
    }

    // 3. Reset video src
    modalVideoPlayer.src = normVideo;
    modalVideoPlayer.load();
    videoModal.style.display = 'flex';

    // 4. Reset subtitle state
    currentSrtCues = [];
    currentSrtOriginalCues = [];
    currentSrtTranslatedCues = [];
    currentSrtDisplayMode = 'original';
    currentTranslatedLang = '';
    isTranslatingSubtitles = false;
    currentSrtRaw = '';
    activeCueIndex = -1;
    if (selectSubDisplayMode) {
        selectSubDisplayMode.style.display = 'none';
        selectSubDisplayMode.value = 'translated';
    }
    if (btnTranslateSubtitles) {
        btnTranslateSubtitles.disabled = false;
    }
    if (btnTranslateSubText) {
        btnTranslateSubText.textContent = 'Dịch Live';
    }
    if (videoSubtitleOverlay) videoSubtitleOverlay.style.display = 'none';
    if (videoSubtitleText) {
        videoSubtitleText.textContent = '';
        videoSubtitleText.style.fontSize = `${subtitleFontSize}rem`;
    }
    modalVideoPlayer.querySelectorAll('track').forEach(t => t.remove());

    if (subtitleStatusText) subtitleStatusText.textContent = 'Đang tìm kiếm tệp phụ đề SRT...';
    if (transcriptCountBadge) transcriptCountBadge.textContent = '0 câu';
    if (videoTranscriptList) {
        videoTranscriptList.innerHTML = `
            <div style="text-align: center; color: var(--text-muted); font-size: 0.8rem; padding: 2.5rem 1rem; display: flex; flex-direction: column; align-items: center; gap: 0.6rem;">
                <div class="spinner" style="width: 22px; height: 22px; border: 2px solid rgba(255,174,110,0.2); border-top-color: var(--primary); border-radius: 50%; animation: spin 0.8s linear infinite;"></div>
                <span>Đang tìm và tải tệp phụ đề...</span>
            </div>
        `;
    }

    updateSubtitleToggleState();

    // 5. Auto-resolve candidate SRT paths with smart priority
    const candidates = [];
    if (normSrt && !normSrt.includes('/downloads/None/')) {
        candidates.push(normSrt);
    }

    const isSingleEp = episodeNum && !String(episodeNum).includes('-');

    // 1. If single episode, prioritize episode directory transcript.srt first
    if (isSingleEp && comicFolder) {
        candidates.push(`/downloads/${comicFolder}/episode_${episodeNum}/transcript.srt`);
        candidates.push(`/downloads/${comicFolder}/episode_${episodeNum}/${comicFolder}_ep${episodeNum}.srt`);
        candidates.push(`/downloads/${comicFolder}/episode_${episodeNum}/transcript_raw.srt`);
        candidates.push(`/downloads/${comicFolder}/episode_${episodeNum}/video.srt`);
    }

    // 2. Direct 1-to-1 matching SRT with same name as the video file (e.g. the_genius_professor_wants_to_take_it_easy_1_2_vi.srt)
    if (normVideo.toLowerCase().endsWith('.mp4')) {
        candidates.push(normVideo.replace(/\.mp4$/i, '.srt'));
    }

    // 3. Video directory candidates
    const lastSlashIdx = normVideo.lastIndexOf('/');
    if (lastSlashIdx !== -1) {
        const videoDir = normVideo.substring(0, lastSlashIdx);
        candidates.push(`${videoDir}/transcript.srt`);
        if (comicFolder) {
            candidates.push(`${videoDir}/${comicFolder}.srt`);
        }
        candidates.push(`${videoDir}/transcript_raw.srt`);
    }

    // 4. Task / comic folder output matching
    if (comicFolder) {
        if (!isSingleEp) {
            candidates.push(`/downloads/${comicFolder}/output/${comicFolder}.srt`);
            candidates.push(`/downloads/${comicFolder}/output/transcript.srt`);
        }
        candidates.push(`/downloads/${comicFolder}/${comicFolder}.srt`);
        candidates.push(`/downloads/${comicFolder}/transcript.srt`);
        if (isSingleEp) {
            candidates.push(`/downloads/${comicFolder}/output/${comicFolder}.srt`);
            candidates.push(`/downloads/${comicFolder}/output/transcript.srt`);
        }
    }

    const uniqueCandidates = [...new Set(candidates.filter(c => c && typeof c === 'string' && !c.includes('/downloads/None/')))];
    let loadedSuccess = false;
    let foundCandidate = null;
    let foundText = null;

    for (const srtCandidate of uniqueCandidates) {
        try {
            console.log('[playVideo] Checking SRT candidate:', srtCandidate);
            const resp = await fetch(srtCandidate);
            if (resp.ok) {
                const text = await resp.text();
                if (text && text.includes('-->')) {
                    foundCandidate = srtCandidate;
                    foundText = text;
                    console.log('[playVideo] Found valid SRT at:', srtCandidate);
                    break;
                }
            }
        } catch (e) {
            console.warn('[playVideo] Error checking candidate:', srtCandidate, e);
        }
    }

    // 6. Backend endpoint fallback resolver
    if (!foundCandidate) {
        try {
            const queryParams = new URLSearchParams();
            if (comicFolder) queryParams.set('folder', comicFolder);
            if (episodeNum) queryParams.set('episode', String(episodeNum));
            if (normVideo) queryParams.set('video', normVideo);
            if (videoUrl && videoUrl !== normVideo) queryParams.set('raw_path', videoUrl);

            console.log('[playVideo] Trying backend /api/subtitles resolver...');
            const apiResp = await fetch(`/api/subtitles?${queryParams.toString()}`);
            if (apiResp.ok) {
                const apiData = await apiResp.json();
                if (apiData.status === 'success' && apiData.content && apiData.content.includes('-->')) {
                    foundCandidate = apiData.url || apiData.filename || 'transcript.srt';
                    foundText = apiData.content;
                    console.log('[playVideo] Backend resolved SRT successfully:', foundCandidate);
                }
            }
        } catch (apiErr) {
            console.warn('[playVideo] Subtitle API resolve error:', apiErr);
        }
    }

    if (foundCandidate && foundText) {
        try {
            const fileName = foundCandidate.split('/').pop();
            applySrtContent(foundText, fileName);
            updateSubtitleToggleState();
            updateActiveSubtitleOverlay();
            loadedSuccess = true;
        } catch (err) {
            console.error('[playVideo] Error applying SRT content:', err);
        }
    }

    if (!loadedSuccess) {
        if (subtitleStatusText) subtitleStatusText.textContent = 'Chưa có file phụ đề SRT tự động';
        if (videoTranscriptList) {
            videoTranscriptList.innerHTML = `
                <div style="text-align: center; color: var(--text-muted); font-size: 0.8rem; padding: 2rem 1rem; display: flex; flex-direction: column; gap: 0.75rem; align-items: center;">
                    <span style="line-height: 1.5;">Không tìm thấy file <code>transcript.srt</code> tự động cho video này.</span>
                    <div style="display: flex; gap: 0.5rem; flex-wrap: wrap; justify-content: center;">
                        <button id="btn-empty-load-srt" class="btn" style="font-size: 0.75rem; padding: 0.35rem 0.75rem; background: rgba(255,174,110,0.15); border: 1px solid var(--primary); color: var(--primary); border-radius: 6px; cursor: pointer; display: flex; align-items: center; gap: 0.35rem;">
                            <i data-lucide="upload" style="width: 0.85rem; height: 0.85rem;"></i>
                            <span>Tải file .srt từ máy tính</span>
                        </button>
                        <button id="btn-retry-load-srt" class="btn" style="font-size: 0.75rem; padding: 0.35rem 0.75rem; background: rgba(255,255,255,0.06); border: 1px solid var(--card-border); color: var(--text-secondary); border-radius: 6px; cursor: pointer; display: flex; align-items: center; gap: 0.35rem;">
                            <i data-lucide="refresh-cw" style="width: 0.85rem; height: 0.85rem;"></i>
                            <span>Thử tìm lại</span>
                        </button>
                    </div>
                </div>
            `;
            const emptyLoadBtn = document.getElementById('btn-empty-load-srt');
            if (emptyLoadBtn && inputCustomSrt) {
                emptyLoadBtn.onclick = () => inputCustomSrt.click();
            }
            const retryBtn = document.getElementById('btn-retry-load-srt');
            if (retryBtn) {
                retryBtn.onclick = () => playVideo(videoUrl, episodeNum, comicTitle, explicitSrtUrl);
            }
            if (window.lucide && lucide.createIcons) {
                lucide.createIcons({ root: videoTranscriptList });
            }
        }
    }

    modalVideoPlayer.play().catch(e => console.log('Autoplay blocked:', e));
    if (window.lucide && lucide.createIcons) {
        lucide.createIcons({ root: videoModal });
    }
}

// Synchronize subtitles during playback
modalVideoPlayer.addEventListener('timeupdate', () => {
    if (!currentSrtCues.length) return;
    const curTime = modalVideoPlayer.currentTime;
    let foundIdx = -1;

    for (let i = 0; i < currentSrtCues.length; i++) {
        const c = currentSrtCues[i];
        if (curTime >= c.start && curTime <= c.end) {
            foundIdx = i;
            break;
        }
    }

    if (foundIdx !== -1) {
        if (activeCueIndex !== foundIdx) {
            activeCueIndex = foundIdx;
            updateActiveSubtitleOverlay();
            if (videoTranscriptList) {
                const prev = videoTranscriptList.querySelector('.transcript-cue-item.active');
                if (prev) prev.classList.remove('active');
                const target = videoTranscriptList.querySelector(`[data-cue-idx="${foundIdx}"]`);
                if (target) {
                    target.classList.add('active');
                    target.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
                }
            }
        }
    } else {
        if (activeCueIndex !== -1) {
            activeCueIndex = -1;
            updateActiveSubtitleOverlay();
            if (videoTranscriptList) {
                const prev = videoTranscriptList.querySelector('.transcript-cue-item.active');
                if (prev) prev.classList.remove('active');
            }
        }
    }
});

// Fullscreen toggle event
document.addEventListener('fullscreenchange', () => {
    const isFullscreen = !!document.fullscreenElement;
    const track = modalVideoPlayer.querySelector('track');
    if (track && track.track) {
        track.track.mode = (isFullscreen && isSubtitlesEnabled) ? 'showing' : 'hidden';
    }
    if (videoSubtitleOverlay) {
        if (isFullscreen) {
            videoSubtitleOverlay.style.display = 'none';
        } else if (isSubtitlesEnabled && activeCueIndex !== -1) {
            videoSubtitleOverlay.style.display = 'block';
        }
    }
});

// Subtitle toolbar button events
if (btnToggleSubtitles) {
    btnToggleSubtitles.addEventListener('click', () => {
        isSubtitlesEnabled = !isSubtitlesEnabled;
        updateSubtitleToggleState();
        updateActiveSubtitleOverlay();
    });
}

if (btnToggleTranscript && videoTranscriptSidebar) {
    btnToggleTranscript.addEventListener('click', () => {
        isTranscriptOpen = !isTranscriptOpen;
        videoTranscriptSidebar.style.display = isTranscriptOpen ? 'flex' : 'none';
        if (isTranscriptOpen) {
            btnToggleTranscript.style.background = 'rgba(255, 174, 110, 0.12)';
            btnToggleTranscript.style.borderColor = 'rgba(255, 174, 110, 0.4)';
            btnToggleTranscript.style.color = 'var(--primary)';
        } else {
            btnToggleTranscript.style.background = 'rgba(255, 255, 255, 0.05)';
            btnToggleTranscript.style.borderColor = 'var(--card-border)';
            btnToggleTranscript.style.color = 'var(--text-secondary)';
        }
    });
}

if (btnUploadSrt && inputCustomSrt) {
    btnUploadSrt.addEventListener('click', () => {
        inputCustomSrt.click();
    });
}

if (inputCustomSrt) {
    inputCustomSrt.addEventListener('change', (e) => {
        const file = e.target.files[0];
        if (!file) return;
        const reader = new FileReader();
        reader.onload = (re) => {
            applySrtContent(re.target.result, file.name);
        };
        reader.readAsText(file);
        inputCustomSrt.value = '';
    });
}

if (btnTranslateSubtitles) {
    btnTranslateSubtitles.addEventListener('click', async () => {
        if (isTranslatingSubtitles) return;
        const sourceCues = (currentSrtOriginalCues && currentSrtOriginalCues.length) ? currentSrtOriginalCues : currentSrtCues;
        if (!sourceCues || !sourceCues.length) {
            alert('Chưa có nội dung phụ đề SRT để dịch.');
            return;
        }

        const targetLang = selectSubTranslateLang ? selectSubTranslateLang.value : 'vi';
        const targetLangName = selectSubTranslateLang ? (selectSubTranslateLang.options[selectSubTranslateLang.selectedIndex]?.text || targetLang) : targetLang;

        isTranslatingSubtitles = true;
        btnTranslateSubtitles.disabled = true;
        if (btnTranslateSubText) {
            btnTranslateSubText.textContent = `Đang dịch (${targetLang.toUpperCase()})...`;
        }

        try {
            const payload = {
                cues: sourceCues.map((c, i) => ({
                    index: c.id || c.index || (i + 1),
                    start: c.fullStartStr || c.startStr || '00:00:00,000',
                    end: c.fullEndStr || c.endStr || '00:00:00,000',
                    startStr: c.startStr || '00:00:00',
                    endStr: c.endStr || '00:00:00',
                    fullStartStr: c.fullStartStr || c.startStr || '00:00:00,000',
                    fullEndStr: c.fullEndStr || c.endStr || '00:00:00,000',
                    text: c.originalText || c.text || ''
                })),
                target_lang: targetLang,
                source_lang: 'auto'
            };

            const resp = await fetch('/api/subtitles/translate', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });

            const data = await resp.json();
            if (!resp.ok || data.status !== 'success') {
                throw new Error(data.message || data.detail || 'Không thể dịch phụ đề.');
            }

            // Save translated cues
            currentSrtTranslatedCues = data.cues.map((tc, idx) => {
                const origCue = sourceCues[idx] || {};
                const transTxt = tc.translated_text || tc.text || '';
                return {
                    ...origCue,
                    translatedText: transTxt,
                    text: transTxt
                };
            });
            currentTranslatedLang = targetLang;

            if (selectSubDisplayMode) {
                selectSubDisplayMode.style.display = 'inline-block';
                selectSubDisplayMode.value = 'translated';
            }

            applySrtDisplayMode('translated');

            if (subtitleStatusText) {
                subtitleStatusText.textContent = `Phụ đề: Đã dịch sang ${targetLangName} (${currentSrtCues.length} câu)`;
            }
        } catch (err) {
            console.error('Lỗi khi dịch phụ đề:', err);
            alert(`Lỗi khi dịch phụ đề: ${err.message || err}`);
        } finally {
            isTranslatingSubtitles = false;
            btnTranslateSubtitles.disabled = false;
            if (btnTranslateSubText) {
                btnTranslateSubText.textContent = 'Dịch Live';
            }
        }
    });
}

if (selectSubDisplayMode) {
    selectSubDisplayMode.addEventListener('change', (e) => {
        applySrtDisplayMode(e.target.value);
    });
}

if (btnDownloadSrt) {
    btnDownloadSrt.addEventListener('click', () => {
        if (!currentSrtRaw) {
            alert('Chưa có nội dung phụ đề SRT để tải về.');
            return;
        }
        const blob = new Blob([currentSrtRaw], { type: 'text/plain;charset=utf-8' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        const safeTitle = (currentComicTitle || 'recap').replace(/[^a-zA-Z0-9_\-]/g, '_');
        let suffix = '';
        if (currentSrtDisplayMode === 'translated' && currentTranslatedLang) {
            suffix = `_${currentTranslatedLang}`;
        } else if (currentSrtDisplayMode === 'bilingual') {
            suffix = `_bilingual_${currentTranslatedLang || 'vi'}`;
        }
        a.download = `${safeTitle}_tap_${currentEpisodeNum || 'video'}${suffix}.srt`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
    });
}

if (btnSubSizeDown && videoSubtitleText) {
    btnSubSizeDown.addEventListener('click', () => {
        if (subtitleFontSize > 0.85) {
            subtitleFontSize = Math.max(0.85, +(subtitleFontSize - 0.15).toFixed(2));
            videoSubtitleText.style.fontSize = `${subtitleFontSize}rem`;
        }
    });
}

if (btnSubSizeUp && videoSubtitleText) {
    btnSubSizeUp.addEventListener('click', () => {
        if (subtitleFontSize < 2.2) {
            subtitleFontSize = Math.min(2.2, +(subtitleFontSize + 0.15).toFixed(2));
            videoSubtitleText.style.fontSize = `${subtitleFontSize}rem`;
        }
    });
}

function closeVideoModal() {
    modalVideoPlayer.pause();
    modalVideoPlayer.src = '';
    modalVideoPlayer.querySelectorAll('track').forEach(t => t.remove());
    currentSrtCues = [];
    currentSrtOriginalCues = [];
    currentSrtTranslatedCues = [];
    currentSrtRaw = '';
    activeCueIndex = -1;
    if (videoSubtitleOverlay) videoSubtitleOverlay.style.display = 'none';
    if (videoSubtitleText) videoSubtitleText.textContent = '';
    if (videoTranscriptList) {
        videoTranscriptList.innerHTML = `
            <div style="text-align: center; color: var(--text-muted); font-size: 0.8rem; padding: 2rem 1rem; display: flex; flex-direction: column; align-items: center; gap: 0.5rem;">
                <i data-lucide="file-text" style="width: 1.5rem; height: 1.5rem; opacity: 0.4;"></i>
                <span>Chưa chọn video để xem phụ đề.</span>
            </div>
        `;
        if (window.lucide && lucide.createIcons) {
            lucide.createIcons({ root: videoTranscriptList });
        }
    }
    videoModal.style.display = 'none';
}

btnCloseVideoModal.addEventListener('click', closeVideoModal);

videoModal.addEventListener('click', (e) => {
    if (e.target === videoModal) {
        closeVideoModal();
    }
});

// Drag-and-drop support for .srt and video files onto video modal
videoModal.addEventListener('dragover', (e) => {
    e.preventDefault();
    e.dataTransfer.dropEffect = 'copy';
});

videoModal.addEventListener('drop', (e) => {
    e.preventDefault();
    const files = e.dataTransfer.files;
    if (!files || !files.length) return;
    for (const f of files) {
        const lowerName = f.name.toLowerCase();
        if (lowerName.endsWith('.srt') || lowerName.endsWith('.vtt')) {
            const reader = new FileReader();
            reader.onload = (re) => {
                applySrtContent(re.target.result, f.name);
            };
            reader.readAsText(f);
        } else if (lowerName.endsWith('.mp4') || lowerName.endsWith('.webm') || lowerName.endsWith('.mkv')) {
            modalVideoPlayer.src = URL.createObjectURL(f);
            modalVideoPlayer.play().catch(() => {});
        }
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







// Toggle Safe Mode config styling
const safeModeCheckbox = document.getElementById('safe-mode');
const nsfwSettings = document.getElementById('nsfw-settings');
if (safeModeCheckbox && nsfwSettings) {
    safeModeCheckbox.addEventListener('change', () => {
        if (safeModeCheckbox.checked) {
            nsfwSettings.style.opacity = '1';
            nsfwSettings.style.pointerEvents = 'auto';
        } else {
            nsfwSettings.style.opacity = '0.5';
            nsfwSettings.style.pointerEvents = 'none';
        }
    });
}

if (btnClearQueue) {
    btnClearQueue.addEventListener('click', clearAllWorkflows);
}
if (btnRetryQueue) {
    btnRetryQueue.addEventListener('click', retryAllWorkflows);
}

// Toggle OmniVoice inputs based on selected mode
const ttsVoiceIdInput = document.getElementById('tts-voice-id');
const omnivoiceAutoArea = document.getElementById('omnivoice-auto-area');
const omnivoiceDesignArea = document.getElementById('omnivoice-design-area');
const omnivoiceCloneArea = document.getElementById('omnivoice-clone-area');
const ai33proApiArea = document.getElementById('ai33pro-api-area');

if (ttsVoiceIdInput) {
    ttsVoiceIdInput.addEventListener('change', () => {
        const mode = ttsVoiceIdInput.value;
        if (mode === 'auto') {
            if (omnivoiceAutoArea) omnivoiceAutoArea.style.display = 'block';
            if (omnivoiceDesignArea) omnivoiceDesignArea.style.display = 'none';
            if (omnivoiceCloneArea) omnivoiceCloneArea.style.display = 'none';
            if (ai33proApiArea) ai33proApiArea.style.display = 'none';
        } else if (mode === 'design') {
            if (omnivoiceAutoArea) omnivoiceAutoArea.style.display = 'none';
            if (omnivoiceDesignArea) omnivoiceDesignArea.style.display = 'block';
            if (omnivoiceCloneArea) omnivoiceCloneArea.style.display = 'none';
            if (ai33proApiArea) ai33proApiArea.style.display = 'none';
        } else if (mode === 'clone') {
            if (omnivoiceAutoArea) omnivoiceAutoArea.style.display = 'none';
            if (omnivoiceDesignArea) omnivoiceDesignArea.style.display = 'none';
            if (omnivoiceCloneArea) omnivoiceCloneArea.style.display = 'block';
            if (ai33proApiArea) ai33proApiArea.style.display = 'none';
        } else if (mode === 'ai33pro') {
            if (omnivoiceAutoArea) omnivoiceAutoArea.style.display = 'none';
            if (omnivoiceDesignArea) omnivoiceDesignArea.style.display = 'none';
            if (omnivoiceCloneArea) omnivoiceCloneArea.style.display = 'none';
            if (ai33proApiArea) ai33proApiArea.style.display = 'block';
        } else {
            if (omnivoiceAutoArea) omnivoiceAutoArea.style.display = 'block';
            if (omnivoiceDesignArea) omnivoiceDesignArea.style.display = 'none';
            if (omnivoiceCloneArea) omnivoiceCloneArea.style.display = 'none';
            if (ai33proApiArea) ai33proApiArea.style.display = 'none';
        }
    });
    // Trigger initial state mapping on load
    ttsVoiceIdInput.dispatchEvent(new Event('change'));
}

// --- AUTO VOICE CLONE MANAGER ---
const autoVoiceDropdownBtn = document.getElementById('auto-voice-dropdown-btn');
const autoVoiceDropdownMenu = document.getElementById('auto-voice-dropdown-menu');
const autoVoiceChevron = document.getElementById('auto-voice-chevron');
const autoVoiceSelectedName = document.getElementById('auto-voice-selected-name');
const autoVoiceSelectedPath = document.getElementById('auto-voice-selected-path');
const autoVoiceCount = document.getElementById('auto-voice-count');
const autoVoiceList = document.getElementById('auto-voice-list');
const btnAddAutoVoice = document.getElementById('btn-add-auto-voice');
const autoVoiceFileInput = document.getElementById('auto-voice-file-input');

let currentVoicesList = [];
let activePreviewAudio = null;
let activePlayingBtn = null;

function stopCurrentVoiceAudio() {
    if (activePreviewAudio) {
        activePreviewAudio.pause();
        activePreviewAudio.currentTime = 0;
        activePreviewAudio = null;
    }
    if (activePlayingBtn) {
        activePlayingBtn.classList.remove('playing');
        activePlayingBtn.innerHTML = '<i data-lucide="play" style="width: 0.85rem; height: 0.85rem;"></i>';
        if (window.lucide) lucide.createIcons();
        activePlayingBtn = null;
    }
}

async function loadAutoVoices(autoSelectFilename = null) {
    if (!autoVoiceList) return;
    try {
        const resp = await fetch('/api/voices');
        const data = await resp.json();
        if (data.status === 'success') {
            currentVoicesList = data.voices || [];
            renderAutoVoices(autoSelectFilename);
        }
    } catch (e) {
        console.error('Lỗi tải danh sách voices:', e);
    }
}

function renderAutoVoices(preferFilename = null) {
    if (!autoVoiceList) return;
    autoVoiceList.innerHTML = '';
    
    if (autoVoiceCount) {
        autoVoiceCount.textContent = `${currentVoicesList.length} voices`;
    }

    if (currentVoicesList.length === 0) {
        autoVoiceList.innerHTML = '<div style="padding: 0.6rem; font-size: 0.75rem; color: var(--text-muted); text-align: center;">Chưa có voice mẫu nào. Hãy thêm voice bên dưới!</div>';
        if (autoVoiceSelectedName) autoVoiceSelectedName.textContent = 'Chưa có voice nào';
        if (autoVoiceSelectedPath) autoVoiceSelectedPath.value = '';
        return;
    }

    let selectedPath = autoVoiceSelectedPath ? autoVoiceSelectedPath.value : '';
    const currentLang = document.getElementById('vlm-language') ? document.getElementById('vlm-language').value : 'vi';
    const andrewVoice = currentVoicesList.find(v => v.filename && v.filename.toLowerCase().includes('andrew'));

    let selectedVoice = null;
    if (preferFilename) {
        selectedVoice = currentVoicesList.find(v => v.filename === preferFilename || v.path === preferFilename);
    }
    if (!selectedVoice && currentLang === 'en' && andrewVoice) {
        selectedVoice = andrewVoice;
    }
    if (!selectedVoice && selectedPath) {
        selectedVoice = currentVoicesList.find(v => v.path === selectedPath);
    }
    if (!selectedVoice) {
        selectedVoice = andrewVoice || currentVoicesList[0];
    }

    if (selectedVoice) {
        if (autoVoiceSelectedName) autoVoiceSelectedName.textContent = selectedVoice.name;
        if (autoVoiceSelectedPath) autoVoiceSelectedPath.value = selectedVoice.path;
    }

    currentVoicesList.forEach((voice) => {
        const isSelected = selectedVoice && selectedVoice.filename === voice.filename;
        const itemEl = document.createElement('div');
        itemEl.className = `auto-voice-item ${isSelected ? 'active' : ''}`;
        
        itemEl.innerHTML = `
            <div class="voice-info-wrap" style="display: flex; align-items: center; gap: 0.45rem; flex: 1; min-width: 0; user-select: none;">
                <i data-lucide="${isSelected ? 'check-circle' : 'circle'}" style="width: 0.85rem; height: 0.85rem; color: ${isSelected ? '#FFAE6E' : 'var(--text-muted)'}; flex-shrink: 0;"></i>
                <div style="overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">
                    <div style="font-size: 0.78rem; font-weight: ${isSelected ? '600' : '400'}; color: ${isSelected ? '#FFAE6E' : 'var(--text-primary)'}; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">
                        ${voice.name}
                    </div>
                    <div style="font-size: 0.65rem; color: var(--text-muted);">
                        ${voice.size_formatted || ''}
                    </div>
                </div>
            </div>
            <div style="display: flex; align-items: center; gap: 0.3rem; flex-shrink: 0;" onclick="event.stopPropagation();">
                <button type="button" class="voice-action-btn preview" title="Nghe thử" data-url="${voice.url}">
                    <i data-lucide="play" style="width: 0.85rem; height: 0.85rem;"></i>
                </button>
                <button type="button" class="voice-action-btn delete" title="Xóa voice" data-filename="${voice.filename}" data-name="${voice.name}">
                    <i data-lucide="trash-2" style="width: 0.85rem; height: 0.85rem;"></i>
                </button>
            </div>
        `;

        // Select voice on item click
        itemEl.querySelector('.voice-info-wrap').addEventListener('click', () => {
            if (autoVoiceSelectedName) autoVoiceSelectedName.textContent = voice.name;
            if (autoVoiceSelectedPath) autoVoiceSelectedPath.value = voice.path;
            renderAutoVoices(voice.filename);
            if (autoVoiceDropdownMenu) autoVoiceDropdownMenu.style.display = 'none';
            if (autoVoiceChevron) autoVoiceChevron.style.transform = 'rotate(0deg)';
        });

        // Play/Preview Audio
        const previewBtn = itemEl.querySelector('.voice-action-btn.preview');
        previewBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            if (activePlayingBtn === previewBtn && activePreviewAudio) {
                stopCurrentVoiceAudio();
            } else {
                stopCurrentVoiceAudio();
                activePlayingBtn = previewBtn;
                previewBtn.classList.add('playing');
                previewBtn.innerHTML = '<i data-lucide="square" style="width: 0.85rem; height: 0.85rem;"></i>';
                if (window.lucide) lucide.createIcons();

                activePreviewAudio = new Audio(voice.url);
                activePreviewAudio.play().catch(err => {
                    console.error("Lỗi phát audio:", err);
                    stopCurrentVoiceAudio();
                });
                activePreviewAudio.onended = () => {
                    stopCurrentVoiceAudio();
                };
            }
        });

        // Delete Voice
        const deleteBtn = itemEl.querySelector('.voice-action-btn.delete');
        deleteBtn.addEventListener('click', async (e) => {
            e.stopPropagation();
            if (!confirm(`Bạn có chắc muốn xóa voice "${voice.name}" khỏi danh sách?`)) return;
            stopCurrentVoiceAudio();
            try {
                const resp = await fetch(`/api/voices/${encodeURIComponent(voice.filename)}`, { method: 'DELETE' });
                const resData = await resp.json();
                if (resp.ok) {
                    appendLog(`Đã xóa voice: ${voice.name}`, 'info');
                    loadAutoVoices();
                } else {
                    appendLog(`Lỗi khi xóa voice: ${resData.detail || 'Không thể xóa'}`, 'error');
                }
            } catch (err) {
                appendLog(`Lỗi kết nối khi xóa voice: ${err.message}`, 'error');
            }
        });

        autoVoiceList.appendChild(itemEl);
    });

    if (window.lucide) lucide.createIcons();
}

// Toggle Auto Voice Dropdown Menu
if (autoVoiceDropdownBtn && autoVoiceDropdownMenu) {
    autoVoiceDropdownBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        const isOpen = autoVoiceDropdownMenu.style.display === 'block';
        autoVoiceDropdownMenu.style.display = isOpen ? 'none' : 'block';
        if (autoVoiceChevron) {
            autoVoiceChevron.style.transform = isOpen ? 'rotate(0deg)' : 'rotate(180deg)';
        }
    });

    document.addEventListener('click', (e) => {
        if (omnivoiceAutoArea && !omnivoiceAutoArea.contains(e.target)) {
            if (autoVoiceDropdownMenu) autoVoiceDropdownMenu.style.display = 'none';
            if (autoVoiceChevron) autoVoiceChevron.style.transform = 'rotate(0deg)';
        }
    });
}

// Add Voice Button & File Input Handling
if (btnAddAutoVoice && autoVoiceFileInput) {
    btnAddAutoVoice.addEventListener('click', (e) => {
        e.stopPropagation();
        autoVoiceFileInput.click();
    });

    autoVoiceFileInput.addEventListener('change', async () => {
        const file = autoVoiceFileInput.files[0];
        if (!file) return;

        const originalBtnHtml = btnAddAutoVoice.innerHTML;
        btnAddAutoVoice.disabled = true;
        btnAddAutoVoice.innerHTML = '<span style="display: inline-block; animation: spin 1s linear infinite;"><i data-lucide="loader-2" style="width: 0.85rem; height: 0.85rem;"></i></span> Đang tải lên...';
        if (window.lucide) lucide.createIcons();

        const formData = new FormData();
        formData.append('file', file);

        try {
            const resp = await fetch('/api/voices/upload', {
                method: 'POST',
                body: formData
            });
            const data = await resp.json();
            if (resp.ok && data.status === 'success') {
                appendLog(`Đã tải lên voice mới: ${data.voice.name}`, 'success');
                await loadAutoVoices(data.voice.filename);
                autoVoiceFileInput.value = '';
            } else {
                appendLog(`Lỗi tải lên voice: ${data.detail || 'Không thể upload'}`, 'error');
            }
        } catch (err) {
            appendLog(`Lỗi kết nối khi tải voice: ${err.message}`, 'error');
        } finally {
            btnAddAutoVoice.disabled = false;
            btnAddAutoVoice.innerHTML = originalBtnHtml;
            if (window.lucide) lucide.createIcons();
        }
    });
}

// Initial load of auto voices
loadAutoVoices();

// Auto-switch default voice on language change
const vlmLangSelect = document.getElementById('vlm-language');
if (vlmLangSelect) {
    vlmLangSelect.addEventListener('change', (e) => {
        if (e.target.value === 'en') {
            const andrewVoice = currentVoicesList.find(v => v.filename && v.filename.toLowerCase().includes('andrew'));
            if (andrewVoice) {
                renderAutoVoices(andrewVoice.filename);
            }
        }
    });
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

// Supported host chips click handler: Open main website in a new tab
document.querySelectorAll('.host-chip').forEach(chip => {
    chip.addEventListener('click', () => {
        const targetUrl = chip.getAttribute('data-url') || chip.getAttribute('data-sample');
        if (targetUrl) {
            let homeUrl = targetUrl;
            try {
                const parsed = new URL(targetUrl);
                homeUrl = parsed.origin;
            } catch (e) {}
            window.open(homeUrl, '_blank', 'noopener,noreferrer');
            const hostName = chip.querySelector('.host-name')?.textContent || 'website';
            appendLog(`Đang mở trang chủ ${hostName} (${homeUrl}) trong tab mới...`, 'info');
        }
    });
});

// ==========================================================================
// PRESETS CONFIGURATION MANAGER
// ==========================================================================
const presetsSectionWrapper = document.getElementById('presets-section-wrapper');
const presetsDropdownBtn = document.getElementById('presets-dropdown-btn');
const presetsDropdownMenu = document.getElementById('presets-dropdown-menu');
const presetChevron = document.getElementById('preset-chevron');
const presetSelectedName = document.getElementById('preset-selected-name');
const presetSelectedSummary = document.getElementById('preset-selected-summary');
const presetsCountBadge = document.getElementById('presets-count-badge');
const presetsList = document.getElementById('presets-list');
const btnAddPreset = document.getElementById('btn-add-preset');

const newPresetModal = document.getElementById('new-preset-modal');
const btnCloseNewPresetModal = document.getElementById('btn-close-new-preset-modal');
const btnCancelNewPreset = document.getElementById('btn-cancel-new-preset');
const btnConfirmSavePreset = document.getElementById('btn-confirm-save-preset');
const newPresetNameInput = document.getElementById('new-preset-name-input');
const newPresetSummaryPreview = document.getElementById('new-preset-summary-preview');

let presetsState = {
    active_preset_id: null,
    presets: []
};

function getPresetSummaryText(preset) {
    if (!preset) return '';
    const parts = [];
    // Language
    const langMap = { vi: 'Tiếng Việt', en: 'English', ja: 'Japanese', zh: 'Chinese' };
    parts.push(langMap[preset.language] || (preset.language || 'VI').toUpperCase());

    // Gemini Model
    const modelMap = { 'flash-lite': '3.5 Flash-Lite', 'flash': '3.8 Flash', 'pro': '3.1 Pro' };
    parts.push(modelMap[preset.gemini_model] || preset.gemini_model || 'Flash');

    // Headless
    const isHeadlessSummary = (preset.headless === true || preset.headless === 'true' || preset.headless === 1 || preset.headless === '1');
    parts.push(isHeadlessSummary ? 'Headless' : 'Headed');

    // TTS Mode
    const ttsMap = {
        'auto': 'Auto Voice',
        'design': 'Voice Design',
        'clone': 'Voice Clone',
        'ai33pro': 'AI33Pro'
    };
    parts.push(ttsMap[preset.tts_voice_id] || 'TTS');

    // Flip horizontal
    if (preset.flip_horizontal) {
        parts.push('Lật ảnh');
    }

    // Voice sample
    if (preset.voice_sample_name) {
        parts.push(`Voice: ${preset.voice_sample_name}`);
    }

    return parts.join(' • ');
}

async function loadPresets(autoSelectId = null, applyOnLoad = false) {
    if (!presetsList) return;
    try {
        const resp = await fetch('/api/presets');
        const data = await resp.json();
        if (data.status === 'success') {
            presetsState = {
                active_preset_id: data.active_preset_id,
                presets: data.presets || []
            };
            renderPresets(autoSelectId || presetsState.active_preset_id);
            if (applyOnLoad && presetsState.presets.length > 0) {
                const targetPreset = presetsState.presets.find(p => p.id === presetsState.active_preset_id) || presetsState.presets[0];
                if (targetPreset) {
                    applyPreset(targetPreset, false);
                }
            }
        }
    } catch (e) {
        console.error('Lỗi khi tải danh sách presets:', e);
    }
}

function renderPresets(activeId = null) {
    if (!presetsList) return;
    presetsList.innerHTML = '';

    const list = presetsState.presets || [];
    if (presetsCountBadge) {
        presetsCountBadge.textContent = `${list.length} presets`;
    }

    if (list.length === 0) {
        presetsList.innerHTML = '<div style="padding: 0.75rem; font-size: 0.75rem; color: var(--text-muted); text-align: center;">Chưa có preset nào. Nhấn "+ Thêm mới" bên dưới để tạo!</div>';
        if (presetSelectedName) presetSelectedName.textContent = 'Chưa có preset';
        if (presetSelectedSummary) presetSelectedSummary.textContent = 'Nhấn thêm mới để lưu cấu hình hiện tại';
        return;
    }

    const currentId = activeId || presetsState.active_preset_id || (list[0] && list[0].id);
    const activePreset = list.find(p => p.id === currentId) || list[0];

    if (activePreset) {
        if (presetSelectedName) presetSelectedName.textContent = activePreset.name;
        if (presetSelectedSummary) presetSelectedSummary.textContent = getPresetSummaryText(activePreset);
    }

    list.forEach(preset => {
        const isSelected = activePreset && activePreset.id === preset.id;
        const itemEl = document.createElement('div');
        itemEl.className = `preset-item ${isSelected ? 'active' : ''}`;
        
        const langCode = (preset.language || 'vi').toUpperCase();
        const modelLabel = preset.gemini_model === 'pro' ? '3.1 Pro' : (preset.gemini_model === 'flash-lite' ? 'Lite' : 'Flash');
        const isHeadless = (preset.headless === true || preset.headless === 'true' || preset.headless === 1 || preset.headless === '1');
        const modeLabel = isHeadless ? 'Ẩn Chrome' : 'Hiện Chrome';
        
        itemEl.innerHTML = `
            <div class="preset-item-info">
                <div class="preset-item-title-row">
                    <i data-lucide="${isSelected ? 'check-circle' : 'circle'}" style="width: 0.85rem; height: 0.85rem; color: ${isSelected ? '#FFAE6E' : 'var(--text-muted)'}; flex-shrink: 0;"></i>
                    <span class="preset-item-name">${escapeHtml(preset.name)}</span>
                </div>
                <div class="preset-item-tags">
                    <span class="preset-tag highlight">${langCode}</span>
                    <span class="preset-tag">${modelLabel}</span>
                    <span class="preset-tag">${modeLabel}</span>
                    ${preset.flip_horizontal ? '<span class="preset-tag highlight">Lật ảnh</span>' : ''}
                    ${preset.voice_sample_name ? `<span class="preset-tag">${escapeHtml(preset.voice_sample_name)}</span>` : ''}
                </div>
            </div>
            <div class="preset-item-actions" onclick="event.stopPropagation();">
                <button type="button" class="preset-delete-btn" title="Xóa preset này" data-id="${preset.id}">
                    <i data-lucide="trash-2" style="width: 0.85rem; height: 0.85rem;"></i>
                </button>
            </div>
        `;

        // Click on preset item to apply
        itemEl.addEventListener('click', () => {
            applyPreset(preset, true);
            if (presetsDropdownMenu) presetsDropdownMenu.style.display = 'none';
            if (presetChevron) presetChevron.style.transform = 'rotate(0deg)';
        });

        // Delete button
        const delBtn = itemEl.querySelector('.preset-delete-btn');
        if (delBtn) {
            delBtn.addEventListener('click', async (e) => {
                e.stopPropagation();
                if (!confirm(`Bạn có chắc muốn xóa preset "${preset.name}"?`)) return;
                try {
                    const res = await fetch(`/api/presets/${encodeURIComponent(preset.id)}`, { method: 'DELETE' });
                    const resData = await res.json();
                    if (res.ok) {
                        appendLog(`Đã xóa preset: ${preset.name}`, 'info');
                        await loadPresets();
                    } else {
                        appendLog(`Lỗi khi xóa preset: ${resData.detail || 'Không thể xóa'}`, 'error');
                    }
                } catch (err) {
                    appendLog(`Lỗi kết nối khi xóa preset: ${err.message}`, 'error');
                }
            });
        }

        presetsList.appendChild(itemEl);
    });

    if (window.lucide) lucide.createIcons();
}

async function applyPreset(preset, notify = false) {
    if (!preset) return;

    // 1. Headless mode -> sync checkbox and backend
    const showBrowserToggleEl = document.getElementById('show-browser-toggle');
    if (showBrowserToggleEl) {
        const isHeadless = (preset.headless === true || preset.headless === 'true' || preset.headless === 1 || preset.headless === '1');
        showBrowserToggleEl.checked = !isHeadless;
        try {
            fetch('/api/config', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ headless: isHeadless })
            }).catch(() => {});
        } catch (e) {}
    }

    // 2. Language
    const vlmLangEl = document.getElementById('vlm-language');
    if (vlmLangEl && preset.language) {
        vlmLangEl.value = preset.language;
    }

    // 3. Gemini Model
    const geminiModelEl = document.getElementById('gemini-model');
    if (geminiModelEl && preset.gemini_model) {
        geminiModelEl.value = preset.gemini_model;
    }

    // 4. TTS Voice Mode
    const ttsVoiceIdEl = document.getElementById('tts-voice-id');
    if (ttsVoiceIdEl && preset.tts_voice_id) {
        ttsVoiceIdEl.value = preset.tts_voice_id;
        ttsVoiceIdEl.dispatchEvent(new Event('change'));
    }

    // 5. Flip horizontal
    const flipHorizEl = document.getElementById('flip-horizontal');
    if (flipHorizEl) {
        flipHorizEl.checked = !!preset.flip_horizontal;
    }

    // 6. Voice Sample (Clone / Auto)
    if (preset.voice_sample_path) {
        const autoVoiceSelectedPathEl = document.getElementById('auto-voice-selected-path');
        const autoVoiceSelectedNameEl = document.getElementById('auto-voice-selected-name');
        if (autoVoiceSelectedPathEl) autoVoiceSelectedPathEl.value = preset.voice_sample_path;
        if (autoVoiceSelectedNameEl && preset.voice_sample_name) {
            autoVoiceSelectedNameEl.textContent = preset.voice_sample_name;
        }
        if (typeof renderAutoVoices === 'function') {
            renderAutoVoices(preset.voice_sample_path);
        }
    }

    // Update active preset state
    presetsState.active_preset_id = preset.id;
    try {
        fetch(`/api/presets/active/${encodeURIComponent(preset.id)}`, { method: 'POST' }).catch(() => {});
    } catch (e) {}

    renderPresets(preset.id);

    if (notify) {
        appendLog(`Đã áp dụng Preset: "${preset.name}" (${getPresetSummaryText(preset)})`, 'success');
    }
}

function getCurrentConfigSnapshot() {
    const showBrowserToggleEl = document.getElementById('show-browser-toggle');
    const vlmLangEl = document.getElementById('vlm-language');
    const geminiModelEl = document.getElementById('gemini-model');
    const ttsVoiceIdEl = document.getElementById('tts-voice-id');
    const flipHorizEl = document.getElementById('flip-horizontal');
    const autoVoiceSelectedPathEl = document.getElementById('auto-voice-selected-path');
    const autoVoiceSelectedNameEl = document.getElementById('auto-voice-selected-name');

    return {
        headless: showBrowserToggleEl ? !showBrowserToggleEl.checked : false,
        language: vlmLangEl ? vlmLangEl.value : 'vi',
        gemini_model: geminiModelEl ? geminiModelEl.value : 'flash',
        tts_voice_id: ttsVoiceIdEl ? ttsVoiceIdEl.value : 'auto',
        flip_horizontal: flipHorizEl ? flipHorizEl.checked : false,
        voice_sample_path: autoVoiceSelectedPathEl ? autoVoiceSelectedPathEl.value || '' : '',
        voice_sample_name: autoVoiceSelectedNameEl ? (autoVoiceSelectedNameEl.textContent || '').trim() : ''
    };
}

function openNewPresetModal() {
    if (!newPresetModal) return;
    const current = getCurrentConfigSnapshot();
    
    if (newPresetSummaryPreview) {
        const langMap = { vi: 'Tiếng Việt', en: 'English', ja: 'Japanese', zh: 'Chinese' };
        const modelMap = { 'flash-lite': '3.5 Flash-Lite', 'flash': '3.8 Flash', 'pro': '3.1 Pro' };
        const ttsMap = { 'auto': 'Auto Voice', 'design': 'Voice Design', 'clone': 'Voice Clone', 'ai33pro': 'AI33Pro' };
        
        newPresetSummaryPreview.innerHTML = `
            <div><strong>• Ngôn ngữ:</strong> ${langMap[current.language] || current.language}</div>
            <div><strong>• Gemini Model:</strong> ${modelMap[current.gemini_model] || current.gemini_model}</div>
            <div><strong>• Chrome Mode:</strong> ${current.headless ? 'Ẩn nền (Headless)' : 'Hiển thị (Headed)'}</div>
            <div><strong>• Giọng đọc TTS:</strong> ${ttsMap[current.tts_voice_id] || current.tts_voice_id}</div>
            <div><strong>• Lật ảnh ngang:</strong> ${current.flip_horizontal ? 'Bật (Flip)' : 'Tắt'}</div>
            ${current.voice_sample_name ? `<div><strong>• Voice mẫu:</strong> ${escapeHtml(current.voice_sample_name)}</div>` : ''}
        `;
    }

    if (newPresetNameInput) {
        newPresetNameInput.value = '';
        setTimeout(() => newPresetNameInput.focus(), 50);
    }

    newPresetModal.style.display = 'flex';
    if (presetsDropdownMenu) presetsDropdownMenu.style.display = 'none';
    if (presetChevron) presetChevron.style.transform = 'rotate(0deg)';
    if (window.lucide) lucide.createIcons();
}

function closeNewPresetModal() {
    if (newPresetModal) newPresetModal.style.display = 'none';
}

// Dropdown Button Toggle Handler
if (presetsDropdownBtn && presetsDropdownMenu) {
    presetsDropdownBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        const isOpen = presetsDropdownMenu.style.display === 'block';
        presetsDropdownMenu.style.display = isOpen ? 'none' : 'block';
        if (presetChevron) {
            presetChevron.style.transform = isOpen ? 'rotate(0deg)' : 'rotate(180deg)';
        }
    });

    document.addEventListener('click', (e) => {
        if (presetsSectionWrapper && !presetsSectionWrapper.contains(e.target)) {
            if (presetsDropdownMenu) presetsDropdownMenu.style.display = 'none';
            if (presetChevron) presetChevron.style.transform = 'rotate(0deg)';
        }
    });
}

// Add Preset Button
if (btnAddPreset) {
    btnAddPreset.addEventListener('click', (e) => {
        e.stopPropagation();
        openNewPresetModal();
    });
}

// Modal Handlers
if (btnCloseNewPresetModal) {
    btnCloseNewPresetModal.addEventListener('click', closeNewPresetModal);
}
if (btnCancelNewPreset) {
    btnCancelNewPreset.addEventListener('click', closeNewPresetModal);
}
if (newPresetModal) {
    newPresetModal.addEventListener('click', (e) => {
        if (e.target === newPresetModal) {
            closeNewPresetModal();
        }
    });
}

if (btnConfirmSavePreset) {
    btnConfirmSavePreset.addEventListener('click', async () => {
        const name = newPresetNameInput ? newPresetNameInput.value.trim() : '';
        if (!name) {
            alert('Vui lòng nhập tên cho Preset!');
            if (newPresetNameInput) newPresetNameInput.focus();
            return;
        }

        const snapshot = getCurrentConfigSnapshot();
        const newPresetPayload = {
            name: name,
            ...snapshot
        };

        const originalBtnHtml = btnConfirmSavePreset.innerHTML;
        btnConfirmSavePreset.disabled = true;
        btnConfirmSavePreset.innerHTML = '<span style="display: inline-block; animation: spin 1s linear infinite;"><i data-lucide="loader-2" style="width: 0.85rem; height: 0.85rem;"></i></span> Đang lưu...';
        if (window.lucide) lucide.createIcons();

        try {
            const resp = await fetch('/api/presets', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(newPresetPayload)
            });
            const data = await resp.json();
            if (resp.ok && data.status === 'success') {
                appendLog(`Đã lưu Preset mới: "${name}"`, 'success');
                closeNewPresetModal();
                await loadPresets(data.active_preset_id);
            } else {
                alert(`Lỗi khi lưu preset: ${data.detail || 'Không thể lưu'}`);
            }
        } catch (err) {
            alert(`Lỗi kết nối: ${err.message}`);
        } finally {
            btnConfirmSavePreset.disabled = false;
            btnConfirmSavePreset.innerHTML = originalBtnHtml;
            if (window.lucide) lucide.createIcons();
        }
    });
}

// Initial load of Presets
loadPresets(null, true);



