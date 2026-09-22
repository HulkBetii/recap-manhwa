/**
 * Test Stage Studio: Frontend Controller v2.0
 * Handles independent testing for:
 * - Stage 2b: Smart Paging & PDF Generation
 * - Stage 5: Gemini Automation & Script Recap
 * - Stage 8: Local TTS & Subtitles
 * - Stage 10: Episode Video Rendering
 */

let activeTaskId = null;
let pollTimer = null;
let currentRawJson = null;
let currentRawText = null;
let currentSrtText = null;
let lastLogCount = 0;
let validateDebounceTimer = null;
let localComicsData = [];

// Initialize on DOM ready
document.addEventListener("DOMContentLoaded", () => {
    initStageSelector();
    fetchLocalComics();
    // Default folder input if empty
    const folderInput = document.getElementById("folder-path-input");
    if (folderInput && !folderInput.value) {
        folderInput.value = "downloads/the_forgotten_field_1_2_vi/episode_2";
        validateCurrentFolder();
    }
    if (window.lucide) lucide.createIcons();
});

// Stage Selector (4 Stages)
function initStageSelector() {
    const stageRadios = document.querySelectorAll('input[name="test-stage"]');
    const stageLabels = {
        "stage_2b": document.getElementById("label-stage-2b"),
        "stage_5": document.getElementById("label-stage-5"),
        "stage_8": document.getElementById("label-stage-8"),
        "stage_10": document.getElementById("label-stage-10")
    };
    const btnLabel = document.getElementById("btn-start-label");

    const stageNames = {
        "stage_2b": "Phase 1 — Thu Thập & Xử Lý Ảnh (Smart Paging)",
        "stage_5": "Phase 2 — Tạo Kịch Bản AI VLM (Gemini)",
        "stage_8": "Phase 3 & 4 — Giọng Đọc TTS & Phụ Đề",
        "stage_10": "Phase 5 — Render Video & Xuất Bản"
    };

    const btnNames = {
        "stage_2b": "Bắt đầu Test Phase 1 (Smart Paging)",
        "stage_5": "Bắt đầu Test Phase 2 (Gemini)",
        "stage_8": "Bắt đầu Test Phase 3 & 4 (TTS & SRT)",
        "stage_10": "Bắt đầu Test Phase 5 (Render Video)"
    };

    function updateSelection() {
        const checkedVal = document.querySelector('input[name="test-stage"]:checked').value;
        Object.keys(stageLabels).forEach(k => {
            if (stageLabels[k]) {
                if (k === checkedVal) {
                    stageLabels[k].classList.add("active");
                } else {
                    stageLabels[k].classList.remove("active");
                }
            }
        });
        if (btnLabel && btnNames[checkedVal]) {
            btnLabel.textContent = btnNames[checkedVal];
        }
        checkStageAssetCompatibility();
    }

    stageRadios.forEach(r => r.addEventListener("change", updateSelection));
    updateSelection();
}

// Input Tabs (Folder vs URL)
function switchInputTab(tab) {
    const btnFolder = document.getElementById("tab-btn-folder");
    const btnUrl = document.getElementById("tab-btn-url");
    const contentFolder = document.getElementById("tab-content-folder");
    const contentUrl = document.getElementById("tab-content-url");

    if (tab === "folder") {
        btnFolder.classList.add("active");
        btnUrl.classList.remove("active");
        contentFolder.classList.add("active");
        contentUrl.classList.remove("active");
    } else {
        btnFolder.classList.remove("active");
        btnUrl.classList.add("active");
        contentFolder.classList.remove("active");
        contentUrl.classList.add("active");
    }
}

// Switch Stage 2b Sub-tabs (Visual Frames vs Junk Audit)
function switchStage2bSubTab(sub) {
    const btnFrames = document.getElementById("tab-btn-visual-frames");
    const btnJunk = document.getElementById("tab-btn-junk-audit");
    const subFrames = document.getElementById("subtab-visual-frames");
    const subJunk = document.getElementById("subtab-junk-audit");

    if (sub === "frames") {
        btnFrames.classList.add("active");
        btnJunk.classList.remove("active");
        subFrames.classList.add("active");
        subJunk.classList.remove("active");
    } else {
        btnFrames.classList.remove("active");
        btnJunk.classList.add("active");
        subFrames.classList.remove("active");
        subJunk.classList.add("active");
    }
}

// Fill Sample URL
function fillSampleUrl(url) {
    document.getElementById("comic-url").value = url;
    switchInputTab("url");
}

// Fill Sample Folder Path
function fillSampleFolder(path) {
    document.getElementById("folder-path-input").value = path;
    switchInputTab("folder");
    validateCurrentFolder();
}

// Toggle Advanced Settings
function toggleAdvancedSettings() {
    const body = document.getElementById("advanced-settings-body");
    const chevron = document.getElementById("advanced-chevron");
    const isHidden = body.style.display === "none";
    body.style.display = isHidden ? "flex" : "none";
    chevron.style.transform = isHidden ? "rotate(180deg)" : "rotate(0deg)";
}

// Fetch Local Comics from Backend
async function fetchLocalComics() {
    const select = document.getElementById("local-comic-select");
    const sampleGrid = document.getElementById("sample-folders-grid");

    try {
        const res = await fetch("/api/test_stage/local_comics");
        const data = await res.json();
        localComicsData = data.comics || [];

        if (localComicsData.length === 0) {
            select.innerHTML = '<option value="">-- Không có truyện trong downloads/ --</option>';
            return;
        }

        select.innerHTML = '<option value="">-- Chọn bộ truyện có sẵn --</option>';
        sampleGrid.innerHTML = "";

        localComicsData.forEach(c => {
            const opt = document.createElement("option");
            opt.value = c.folder_name;
            const epCount = c.episodes ? c.episodes.length : 0;
            opt.textContent = `${c.display_name} (${epCount} tập)`;
            select.appendChild(opt);

            // Add sample chips for first 1-2 episodes
            (c.episodes || []).slice(0, 2).forEach(ep => {
                const chip = document.createElement("div");
                chip.className = "sample-folder-chip";
                const relPath = `downloads/${c.folder_name}/episode_${ep.episode_num}`;
                chip.textContent = `${c.display_name} — Tập ${ep.episode_num}`;
                chip.onclick = () => fillSampleFolder(relPath);
                sampleGrid.appendChild(chip);
            });
        });
    } catch (err) {
        select.innerHTML = '<option value="">-- Không thể tải danh sách truyện local --</option>';
    }
}

// Comic Select Dropdown Change
function onComicSelectChange() {
    const comicFolder = document.getElementById("local-comic-select").value;
    const epSelect = document.getElementById("local-episode-select");
    epSelect.innerHTML = "";

    if (!comicFolder) {
        epSelect.innerHTML = '<option value="1">Tập 1</option>';
        return;
    }

    const comicObj = localComicsData.find(c => c.folder_name === comicFolder);
    if (!comicObj || !comicObj.episodes || comicObj.episodes.length === 0) {
        epSelect.innerHTML = '<option value="1">Tập 1</option>';
    } else {
        comicObj.episodes.forEach(ep => {
            const opt = document.createElement("option");
            opt.value = ep.episode_num;
            let badges = [];
            if (ep.has_raw_images) badges.push(`${ep.raw_images_count} ảnh raw`);
            if (ep.has_images) badges.push(`${ep.images_count} ảnh visual`);
            if (ep.has_pdf) badges.push("PDF");
            if (ep.has_recap) badges.push("recap.json");
            const badgeStr = badges.length > 0 ? ` [${badges.join(" | ")}]` : "";
            opt.textContent = `Tập ${ep.episode_num}${badgeStr}`;
            epSelect.appendChild(opt);
        });
    }

    onEpisodeSelectChange();
}

// Episode Select Dropdown Change
function onEpisodeSelectChange() {
    const comicFolder = document.getElementById("local-comic-select").value;
    const epNum = document.getElementById("local-episode-select").value || 1;
    if (comicFolder) {
        const fullRelPath = `downloads/${comicFolder}/episode_${epNum}`;
        document.getElementById("folder-path-input").value = fullRelPath;
        validateCurrentFolder();
    }
}

// Debounce Folder Validation
function debounceValidateFolder() {
    if (validateDebounceTimer) clearTimeout(validateDebounceTimer);
    validateDebounceTimer = setTimeout(() => {
        validateCurrentFolder();
    }, 400);
}

let lastValidatedData = null;

// Validate Folder with Backend
async function validateCurrentFolder() {
    const pathInput = document.getElementById("folder-path-input").value.trim();
    const box = document.getElementById("folder-inspector-box");
    const statusBadge = document.getElementById("inspector-status-badge");
    const statusText = document.getElementById("inspector-status-text");
    const targetName = document.getElementById("inspector-target-name");
    const pillsContainer = document.getElementById("inspector-pills");

    if (!pathInput) {
        box.style.display = "none";
        lastValidatedData = null;
        return;
    }

    try {
        const res = await fetch("/api/test_stage/validate_folder", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ folder_path: pathInput })
        });
        const data = await res.json();
        lastValidatedData = data;

        box.style.display = "flex";
        if (data.valid) {
            statusBadge.className = "inspector-status-badge valid";
            statusText.textContent = "Folder hợp lệ";
            targetName.textContent = `${data.comic_title} (Tập ${data.episode_num})`;

            pillsContainer.innerHTML = "";
            
            // Pill: Raw images
            const pillRaw = createInspectorPill(
                "Ảnh Raw",
                data.has_raw_images ? `${data.raw_images_count} ảnh` : "Chưa có",
                data.has_raw_images ? "success" : "muted"
            );
            pillsContainer.appendChild(pillRaw);

            // Pill: Visual frames
            const pillVisual = createInspectorPill(
                "Ảnh Visual",
                data.has_images ? `${data.images_count} ảnh` : "Chưa có",
                data.has_images ? "success" : "muted"
            );
            pillsContainer.appendChild(pillVisual);

            // Pill: PDF
            const pillPdf = createInspectorPill(
                "File PDF",
                data.has_pdf ? "Có sẵn" : "Chưa tạo",
                data.has_pdf ? "success" : "muted"
            );
            pillsContainer.appendChild(pillPdf);

            // Pill: Recap JSON
            const pillRecap = createInspectorPill(
                "recap.json",
                data.has_recap ? "Có sẵn" : "Chưa tạo",
                data.has_recap ? "success" : "muted"
            );
            pillsContainer.appendChild(pillRecap);

            // Pill: Audio
            const pillAudio = createInspectorPill(
                "Audio MP3",
                data.has_audio ? "Có sẵn" : "Chưa tạo",
                data.has_audio ? "success" : "muted"
            );
            pillsContainer.appendChild(pillAudio);

            // Pill: Video
            const pillVideo = createInspectorPill(
                "Video MP4",
                data.has_video ? "Có sẵn" : "Chưa tạo",
                data.has_video ? "success" : "muted"
            );
            pillsContainer.appendChild(pillVideo);

        } else {
            statusBadge.className = "inspector-status-badge invalid";
            statusText.textContent = "Không tìm thấy";
            targetName.textContent = data.error || "Thư mục không hợp lệ";
            pillsContainer.innerHTML = "";
        }

        checkStageAssetCompatibility();
        if (window.lucide) lucide.createIcons();
    } catch (err) {
        console.error("Lỗi validate folder:", err);
    }
}

function createInspectorPill(label, value, type) {
    const pill = document.createElement("div");
    pill.className = `inspector-pill ${type}`;
    pill.innerHTML = `<span class="pill-label">${label}:</span> <span class="pill-val">${value}</span>`;
    return pill;
}

// Check if current stage has required assets
function checkStageAssetCompatibility() {
    const warningBox = document.getElementById("inspector-warning");
    const warningText = document.getElementById("inspector-warning-text");
    if (!lastValidatedData || !lastValidatedData.valid) {
        warningBox.style.display = "none";
        return;
    }

    const selectedStage = document.querySelector('input[name="test-stage"]:checked').value;
    let warnMsg = null;

    if (selectedStage === "stage_2b") {
        if (!lastValidatedData.has_raw_images && !lastValidatedData.has_images && !lastValidatedData.has_pdf) {
            warnMsg = "Thư mục chưa có ảnh raw hoặc ảnh visual để cắt phân trang.";
        }
    } else if (selectedStage === "stage_5") {
        if (!lastValidatedData.has_pdf && !lastValidatedData.has_images) {
            warnMsg = "Cần file PDF hoặc các ảnh visual trước khi chạy Phase 2 (Gemini).";
        }
    } else if (selectedStage === "stage_8") {
        if (!lastValidatedData.has_recap) {
            warnMsg = "Chưa có file kịch bản recap.json để tạo giọng đọc TTS.";
        }
    } else if (selectedStage === "stage_10") {
        if (!lastValidatedData.has_images || !lastValidatedData.has_audio) {
            warnMsg = "Cần đầy đủ ảnh visual và file audio.mp3 để render video.";
        }
    }

    if (warnMsg) {
        warningText.textContent = warnMsg;
        warningBox.style.display = "flex";
    } else {
        warningBox.style.display = "none";
    }
}

// Log message to terminal
function appendLog(timeStr, msg, level = "info") {
    const terminal = document.getElementById("terminal-logs");
    const line = document.createElement("div");
    line.className = "log-line";

    const timeSpan = document.createElement("span");
    timeSpan.className = "log-time";
    timeSpan.textContent = `[${timeStr}]`;

    const msgSpan = document.createElement("span");
    msgSpan.className = `log-msg ${level}`;
    msgSpan.textContent = msg;

    line.appendChild(timeSpan);
    line.appendChild(msgSpan);
    terminal.appendChild(line);
    terminal.scrollTop = terminal.scrollHeight;
}

function clearLogs() {
    document.getElementById("terminal-logs").innerHTML = "";
}

// Start Test Stage Run
async function startTestStage() {
    const selectedStage = document.querySelector('input[name="test-stage"]:checked').value;
    const isFolderTab = document.getElementById("tab-content-folder").classList.contains("active");

    const folderPath = document.getElementById("folder-path-input").value.trim();
    const comicUrl = document.getElementById("comic-url").value.trim();
    const forceRecrawl = document.getElementById("setting-force-recrawl").checked;
    const geminiModel = document.getElementById("setting-gemini-model").value;
    const pdfQuality = parseInt(document.getElementById("setting-pdf-quality").value, 10);

    if (isFolderTab && !folderPath) {
        alert("Vui lòng nhập đường dẫn thư mục tập truyện hoặc chọn từ danh sách.");
        return;
    }
    if (!isFolderTab && !comicUrl) {
        alert("Vui lòng nhập Link bộ truyện để kiểm thử.");
        return;
    }

    // UI state: Running
    setRunningState(true);
    resetResults();
    clearLogs();

    const stageNames = {
        "stage_2b": "Phase 1 — Thu Thập & Xử Lý Ảnh (Smart Paging)",
        "stage_5": "Phase 2 — Tạo Kịch Bản AI VLM (Gemini)",
        "stage_8": "Phase 3 & 4 — Giọng Đọc TTS & Phụ Đề",
        "stage_10": "Phase 5 — Render Video & Xuất Bản"
    };

    appendLog(new Date().toLocaleTimeString(), `Khởi chạy test độc lập cho ${stageNames[selectedStage]}...`, "info");
    if (isFolderTab) {
        appendLog(new Date().toLocaleTimeString(), `Thư mục chỉ định: ${folderPath}`, "info");
    }

    const showBrowserToggle = document.getElementById('show-browser-toggle');
    const payload = {
        stage: selectedStage,
        folder_path: isFolderTab ? folderPath : null,
        comic_url: !isFolderTab ? comicUrl : null,
        force_recrawl: forceRecrawl,
        gemini_model: geminiModel,
        language: "vi",
        pdf_quality: pdfQuality,
        headless: showBrowserToggle ? !showBrowserToggle.checked : undefined
    };

    try {
        const res = await fetch("/api/test_stage/run", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload)
        });
        const data = await res.json();

        if (!res.ok || data.status !== "success") {
            throw new Error(data.detail || "Khởi chạy task thất bại.");
        }

        activeTaskId = data.task_id;
        appendLog(new Date().toLocaleTimeString(), `Task ID: ${activeTaskId}. Pipeline: ${JSON.stringify(data.target_pipeline)}`, "info");

        startPollingStatus();
    } catch (err) {
        appendLog(new Date().toLocaleTimeString(), `Lỗi: ${err.message}`, "error");
        setRunningState(false);
        updateStatusBadge("error", "Lỗi khởi chạy");
    }
}

// Cancel Test Stage
async function cancelTestStage() {
    if (!activeTaskId) return;
    if (!confirm("Bạn có chắc chắn muốn hủy tiến trình test đang chạy?")) return;

    try {
        await fetch(`/api/test_stage/cancel/${activeTaskId}`, { method: "POST" });
        appendLog(new Date().toLocaleTimeString(), "Đã gửi yêu cầu hủy tiến trình.", "warning");
    } catch (err) {
        console.error(err);
    }
}

// Polling status loop
function startPollingStatus() {
    if (pollTimer) clearInterval(pollTimer);
    lastLogCount = 0;

    pollTimer = setInterval(async () => {
        if (!activeTaskId) return;

        try {
            const res = await fetch(`/api/test_stage/status/${activeTaskId}`);
            if (!res.ok) return;
            const data = await res.json();

            updateProgressUI(data);

            // Print new logs
            const logs = data.logs || [];
            if (logs.length > lastLogCount) {
                for (let i = lastLogCount; i < logs.length; i++) {
                    const l = logs[i];
                    appendLog(l.timestamp || "00:00:00", l.message, l.level || "info");
                }
                lastLogCount = logs.length;
            }

            // Handle terminal states
            const statusUpper = (data.status || "").toUpperCase();
            if (statusUpper === "SUCCESS" || statusUpper === "COMPLETED") {
                clearInterval(pollTimer);
                pollTimer = null;
                setRunningState(false);
                updateStatusBadge("success", "Hoàn thành");
                appendLog(new Date().toLocaleTimeString(), "Quy trình test stage đã hoàn thành thành công!", "success");
                renderResults(data.stage_type, data.result);
                validateCurrentFolder(); // Refresh inspector pills
            } else if (statusUpper === "FAILED" || statusUpper === "CANCELLED" || statusUpper === "ERROR") {
                clearInterval(pollTimer);
                pollTimer = null;
                setRunningState(false);
                const isFail = statusUpper === "FAILED" || statusUpper === "ERROR";
                updateStatusBadge(isFail ? "error" : "idle", isFail ? "Thất bại" : "Đã hủy");
                appendLog(new Date().toLocaleTimeString(), `Quy trình kết thúc: ${data.error_message || data.status}`, isFail ? "error" : "warning");
                if (data.result) {
                    renderResults(data.stage_type, data.result);
                }
            }
        } catch (err) {
            console.error("Lỗi polling status:", err);
        }
    }, 1500);
}

// Update Progress UI
function updateProgressUI(data) {
    const stageLabel = document.getElementById("current-stage-label");
    const progressLabel = document.getElementById("current-progress-label");
    const fill = document.getElementById("progress-bar-fill");

    stageLabel.textContent = data.current_stage || "Đang xử lý...";
    const progress = Math.min(100, Math.max(0, Math.round(data.overall_progress || 0)));
    progressLabel.textContent = `${progress}%`;
    fill.style.width = `${progress}%`;

    updateStatusBadge("running", data.current_stage || "Đang chạy");
}

function updateStatusBadge(state, text) {
    const dot = document.getElementById("status-dot");
    const txt = document.getElementById("status-text");
    dot.className = `status-dot ${state}`;
    txt.textContent = text;
}

function setRunningState(isRunning) {
    document.getElementById("btn-start-test").disabled = isRunning;
    document.getElementById("btn-cancel-test").disabled = !isRunning;
}

function resetResults() {
    document.getElementById("result-stage-2b").style.display = "none";
    document.getElementById("result-stage-5").style.display = "none";
    document.getElementById("result-stage-8").style.display = "none";
    document.getElementById("result-stage-10").style.display = "none";
    document.getElementById("pages-grid").innerHTML = "";
    document.getElementById("junk-audit-tbody").innerHTML = "";
    document.getElementById("image-speech-list").innerHTML = "";
}

// Render Results based on Stage
function renderResults(stageType, result) {
    if (!result) {
        appendLog(new Date().toLocaleTimeString(), "Không tìm thấy dữ liệu kết quả xuất ra của tập này.", "warning");
        return;
    }

    if (stageType === "stage_2b" || stageType === "smart_paging") {
        renderSmartPagingResult(result);
    } else if (stageType === "stage_5" || stageType === "gemini_automation") {
        renderGeminiAutomationResult(result);
    } else if (stageType === "stage_8" || stageType === "tts") {
        renderTtsResult(result);
    } else if (stageType === "stage_10" || stageType === "video_render") {
        renderVideoResult(result);
    }

    if (window.lucide) lucide.createIcons();
}

// Render Smart Paging / Stage 2b Result (Metrics, PDF, Visual Frames, Junk Audit)
function renderSmartPagingResult(result) {
    const container = document.getElementById("result-stage-2b");
    container.style.display = "flex";

    // Title
    const titleEl = document.getElementById("stage-2b-result-title");
    titleEl.textContent = `Kết Quả Phân Trang Visual & PDF (Tập ${result.episode || 1})`;

    // Metrics
    document.getElementById("meta-candidates").textContent = result.total_candidates || 0;
    document.getElementById("meta-exported").textContent = result.total_exported || (result.pages ? result.pages.length : 0);
    document.getElementById("meta-junk-dropped").textContent = result.total_junk_dropped || (result.dropped_junk ? result.dropped_junk.length : 0);

    document.getElementById("tab-count-frames").textContent = result.pages ? result.pages.length : 0;
    document.getElementById("tab-count-junk").textContent = result.dropped_junk ? result.dropped_junk.length : 0;

    // PDF hero card
    if (result.has_pdf && result.pdf_url) {
        document.getElementById("pdf-hero-title").textContent = result.pdf_filename;
        document.getElementById("pdf-meta-pages").textContent = `${result.pages ? result.pages.length : 0} trang`;
        document.getElementById("pdf-meta-size").textContent = `${result.pdf_size_mb} MB`;
        document.getElementById("btn-open-pdf").href = result.pdf_url;
        document.getElementById("btn-download-pdf").href = result.pdf_url;
        document.getElementById("pdf-hero-card").style.display = "flex";
    } else {
        document.getElementById("pdf-hero-card").style.display = "none";
    }

    // Sliced pages gallery
    const grid = document.getElementById("pages-grid");
    grid.innerHTML = "";
    const pages = result.pages || [];

    if (pages.length === 0) {
        grid.innerHTML = '<div style="color: var(--text-muted); grid-column: 1/-1; text-align: center; padding: 2rem;">Chưa có ảnh visual nào được xuất.</div>';
    } else {
        pages.forEach(p => {
            const card = document.createElement("div");
            card.className = "page-card";
            card.onclick = () => openLightbox(p.image_url, `${p.region_id || ('Trang ' + p.page_index)} — ${p.width}x${p.height}px | Visual: ${p.visual_score}% | Faces: ${p.face_count}`);

            card.innerHTML = `
                <div class="page-thumbnail-box">
                    <img src="${p.image_url}" alt="Frame ${p.page_index}" loading="lazy">
                    <span class="page-badge-num">${p.region_id || ('R' + p.page_index)}</span>
                    <span class="page-badge-score">${p.visual_score}%</span>
                </div>
                <div class="page-card-footer">
                    <span class="page-tag-badge">${p.face_count > 0 ? p.face_count + ' Nhân vật' : 'Visual Scene'}</span>
                    <span>${p.width}x${p.height}</span>
                </div>
            `;
            grid.appendChild(card);
        });
    }

    // Dropped Junk Audit Log Table
    const tbody = document.getElementById("junk-audit-tbody");
    tbody.innerHTML = "";
    const junkList = result.dropped_junk || [];

    if (junkList.length === 0) {
        tbody.innerHTML = `<tr><td colspan="6" style="text-align: center; color: var(--text-muted); padding: 1.5rem;">Không có khung rác nào bị loại bỏ (Toàn bộ frame đạt chuẩn visual).</td></tr>`;
    } else {
        junkList.forEach(j => {
            const tr = document.createElement("tr");
            const reasonClass = getJunkReasonClass(j.reason);
            const comp = j.complexity || {};

            tr.innerHTML = `
                <td style="font-family: 'JetBrains Mono', monospace; font-weight: 600; color: var(--primary);">${j.region_id || 'N/A'}</td>
                <td><span class="junk-reason-pill ${reasonClass}">${formatJunkReason(j.reason)}</span></td>
                <td style="font-family: 'JetBrains Mono', monospace;">${j.width || 0} x ${j.height || 0}</td>
                <td style="font-family: 'JetBrains Mono', monospace;">${((j.visual_ratio || 0) * 100).toFixed(1)}%</td>
                <td style="font-family: 'JetBrains Mono', monospace;">${(comp.edge_density || 0).toFixed(4)}</td>
                <td style="font-family: 'JetBrains Mono', monospace;">${(comp.laplacian_variance || 0).toFixed(1)}</td>
            `;
            tbody.appendChild(tr);
        });
    }

    container.scrollIntoView({ behavior: "smooth" });
}

function getJunkReasonClass(reason) {
    if (!reason) return "default";
    if (reason.includes("SPEECH_BUBBLE")) return "speech";
    if (reason.includes("MICRO_SFX") || reason.includes("FRAGILE")) return "micro";
    if (reason.includes("GUTTER") || reason.includes("MONOCHROME")) return "gutter";
    if (reason.includes("LOW_VISUAL")) return "low-visual";
    return "default";
}

function formatJunkReason(reason) {
    if (!reason) return "Khung rác không xác định";
    const map = {
        "DROP_ISOLATED_SPEECH_BUBBLE": "Bong bóng thoại đơn độc (Speech Bubble)",
        "DROP_MICRO_SFX_FRAGMENT": "Mảnh SFX / Vụn hiệu ứng siêu nhỏ",
        "DROP_MONOCHROME_GUTTER": "Khoảng trắng ngăn cách viền đơn sắc",
        "DROP_LOW_VISUAL_WEIGHT": "Mật độ hình ảnh thấp (Low Visual)",
        "DROP_EMPTY_BLANK": "Khung rỗng / Không có nội dung"
    };
    return map[reason] || reason;
}

// Render Gemini Automation Result (Image Page — Speech list)
function renderGeminiAutomationResult(result) {
    const container = document.getElementById("result-stage-5");
    container.style.display = "flex";

    document.getElementById("stage-5-result-title").textContent = `Kết Quả Gemini Automation (Kịch Bản Recap Tập ${result.episode || 1})`;

    currentRawJson = result.raw_json;
    currentRawText = result.raw_text;

    const segments = result.segments || [];
    document.getElementById("recap-stat-segments").textContent = segments.length;
    document.getElementById("recap-stat-words").textContent = result.total_words || 0;

    // Download button
    if (result.recap_json_url) {
        document.getElementById("btn-download-recap").href = result.recap_json_url;
    }

    // Build the core list: Image Page — Speech
    const listEl = document.getElementById("image-speech-list");
    listEl.innerHTML = "";

    if (segments.length === 0) {
        listEl.innerHTML = '<div style="color: var(--text-muted); text-align: center; padding: 2rem;">Không có đoạn thoại nào được trích xuất từ recap.json.</div>';
        return;
    }

    segments.forEach(seg => {
        const row = document.createElement("div");
        row.className = "image-speech-card";

        const imgHtml = seg.image_url
            ? `<div class="segment-image-container" onclick="openLightbox('${seg.image_url}', 'Trang ${seg.page_num} (${seg.frame_label})')">
                 <img src="${seg.image_url}" alt="Trang ${seg.page_num}" loading="lazy">
                 <div class="segment-page-pill">
                     <i data-lucide="image" style="width: 0.8rem; height: 0.8rem;"></i>
                     <span>${seg.frame_label || ('Trang ' + seg.page_num)}</span>
                 </div>
               </div>`
            : `<div class="segment-image-container" style="display: flex; align-items: center; justify-content: center; color: var(--text-muted); font-size: 0.8rem;">
                 <span>Không có ảnh</span>
               </div>`;

        row.innerHTML = `
            ${imgHtml}
            <div class="segment-speech-container">
                <div class="speech-header">
                    <span class="speech-index">Đoạn #${seg.segment_index} • ${seg.frame_label} (Trang ${seg.page_num})</span>
                    <button class="speech-copy-btn" onclick="copySpeechText(this, \`${escapeJsText(seg.speech)}\`)">
                        <i data-lucide="copy" style="width: 0.85rem; height: 0.85rem;"></i>
                        <span>Copy</span>
                    </button>
                </div>
                <div class="speech-bubble-box">
                    ${seg.speech || '<span style="color: var(--text-muted);">(Trống)</span>'}
                </div>
            </div>
        `;
        listEl.appendChild(row);
    });

    container.scrollIntoView({ behavior: "smooth" });
}

// Render TTS Result
function renderTtsResult(result) {
    const container = document.getElementById("result-stage-8");
    container.style.display = "flex";

    const audioPlayer = document.getElementById("tts-audio-player");
    if (result.audio_url) {
        audioPlayer.src = result.audio_url;
        document.getElementById("btn-download-audio").href = result.audio_url;
        document.getElementById("audio-meta-size").textContent = `${result.audio_size_mb || 0} MB`;
    }

    currentSrtText = result.srt_content || "";
    document.getElementById("srt-body-text").textContent = currentSrtText || "(Không có file phụ đề transcript.srt)";

    container.scrollIntoView({ behavior: "smooth" });
}

function srtToWebVTT(srtText) {
    if (!srtText) return '';
    let cleaned = srtText.replace(/^\ufeff/, '').replace(/\r\n/g, '\n').replace(/\r/g, '\n').trim();
    cleaned = cleaned.replace(/(\d{1,2}:\d{2}:\d{2}),(\d{1,3})/g, '$1.$2');
    return "WEBVTT\n\n" + cleaned;
}

// Render Video Result
function renderVideoResult(result) {
    const container = document.getElementById("result-stage-10");
    container.style.display = "flex";

    const videoPlayer = document.getElementById("rendered-video-player");
    videoPlayer.querySelectorAll("track").forEach(t => t.remove());

    if (result.video_url) {
        videoPlayer.src = result.video_url;
        document.getElementById("btn-download-video").href = result.video_url;
        document.getElementById("video-meta-size").textContent = `${result.video_size_mb || 0} MB`;
    }

    if (result.srt_content) {
        try {
            const vtt = srtToWebVTT(result.srt_content);
            const blob = new Blob([vtt], { type: "text/vtt" });
            const track = document.createElement("track");
            track.kind = "subtitles";
            track.label = "Tiếng Việt";
            track.srclang = "vi";
            track.src = URL.createObjectURL(blob);
            track.default = true;
            videoPlayer.appendChild(track);
            if (track.track) track.track.mode = "showing";
        } catch (e) {
            console.warn("Lỗi nạp track phụ đề vào test_stage:", e);
        }
    }

    container.scrollIntoView({ behavior: "smooth" });
}

// Lightbox
function openLightbox(imgUrl, caption = "") {
    const modal = document.getElementById("lightbox-modal");
    const img = document.getElementById("lightbox-img");
    const cap = document.getElementById("lightbox-caption");
    img.src = imgUrl;
    cap.textContent = caption;
    modal.classList.add("active");
}

function closeLightbox() {
    document.getElementById("lightbox-modal").classList.remove("active");
}

// Modals
function openRawJsonModal() {
    if (!currentRawJson) return;
    const modal = document.getElementById("raw-json-modal");
    document.getElementById("raw-json-body").textContent = JSON.stringify(currentRawJson, null, 2);
    modal.classList.add("active");
}

function closeRawJsonModal() {
    document.getElementById("raw-json-modal").classList.remove("active");
}

function openRawTextModal() {
    const modal = document.getElementById("raw-text-modal");
    document.getElementById("raw-text-body").textContent = currentRawText || "(Không có response dạng raw text)";
    modal.classList.add("active");
}

function closeRawTextModal() {
    document.getElementById("raw-text-modal").classList.remove("active");
}

// Copy Speech Text
function copySpeechText(btn, text) {
    navigator.clipboard.writeText(text).then(() => {
        const span = btn.querySelector("span");
        const oldText = span.textContent;
        span.textContent = "Đã copy!";
        setTimeout(() => span.textContent = oldText, 1500);
    });
}

// Copy Full Recap Script
function copyFullRecapScript() {
    if (!currentRawJson || !Array.isArray(currentRawJson)) return;
    const fullText = currentRawJson.map((item, idx) => {
        const page = (item.images && item.images[0] && item.images[0].page) || (idx + 1);
        return `[Trang ${page}]: ${item.speech || ''}`;
    }).join("\n\n");

    navigator.clipboard.writeText(fullText).then(() => {
        alert("Đã sao chép toàn bộ kịch bản vào bộ nhớ tạm!");
    });
}

// Copy SRT Text
function copySrtText() {
    if (!currentSrtText) return;
    navigator.clipboard.writeText(currentSrtText).then(() => {
        alert("Đã sao chép file phụ đề SRT vào bộ nhớ tạm!");
    });
}

function escapeJsText(text) {
    if (!text) return "";
    return text.replace(/\\/g, "\\\\").replace(/`/g, "\\`").replace(/\$/g, "\\$");
}
