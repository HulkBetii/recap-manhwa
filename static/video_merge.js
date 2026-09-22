/**
 * Studio Tách & Gộp Video — Frontend Controller
 * Supports stream-copy fast concatenation of episode ranges and time-synced SRT subtitle playback.
 */

document.addEventListener('DOMContentLoaded', () => {
    // DOM Elements
    const selectComic = document.getElementById('select-comic');
    const comicInfoBadge = document.getElementById('comic-info-badge');
    const badgeComicTitle = document.getElementById('badge-comic-title');
    const badgeTotalEps = document.getElementById('badge-total-eps');
    const badgeRangeEps = document.getElementById('badge-range-eps');
    const badgeFolderName = document.getElementById('badge-folder-name');
    
    const rangesContainer = document.getElementById('ranges-container');
    const btnAddRange = document.getElementById('btn-add-range');
    const btnClearRanges = document.getElementById('btn-clear-ranges');
    const presetButtons = document.querySelectorAll('.btn-preset[data-size]');
    
    const btnStartMerge = document.getElementById('btn-start-merge');
    const mergeProgressStatus = document.getElementById('merge-progress-status');
    const statusDot = document.getElementById('status-dot');
    const statusText = document.getElementById('status-text');
    
    const mergedVideosList = document.getElementById('merged-videos-list');
    const mergedCountPill = document.getElementById('merged-count-pill');
    
    // Player Elements
    const studioVideoPlayer = document.getElementById('studio-video-player');
    const subtitleOverlay = document.getElementById('subtitle-overlay');
    const subtitleText = document.getElementById('subtitle-text');
    const playerTitle = document.getElementById('player-title');
    const subStatusText = document.getElementById('sub-status-text');
    const btnToggleSub = document.getElementById('btn-toggle-sub');
    const btnSubLabel = document.getElementById('btn-sub-label');
    
    // State
    let currentComicInfo = null;
    let parsedSrtCues = [];
    let subtitlesEnabled = true;

    // Helper: format duration in seconds to MM:SS or HH:MM:SS
    function formatDuration(sec) {
        if (!sec || isNaN(sec)) return '00:00';
        const s = Math.floor(sec);
        const hours = Math.floor(s / 3600);
        const minutes = Math.floor((s % 3600) / 60);
        const seconds = s % 60;
        if (hours > 0) {
            return `${hours}:${minutes.toString().padStart(2, '0')}:${seconds.toString().padStart(2, '0')}`;
        }
        return `${minutes.toString().padStart(2, '0')}:${seconds.toString().padStart(2, '0')}`;
    }

    // Helper: format timestamp to seconds (00:01:23,450 -> seconds)
    function parseSrtTimestamp(timeStr) {
        const parts = timeStr.trim().replace(',', '.').split(':');
        if (parts.length === 3) {
            return parseFloat(parts[0]) * 3600 + parseFloat(parts[1]) * 60 + parseFloat(parts[2]);
        }
        return 0;
    }

    // Parse raw SRT string into cues
    function parseSRT(srtContent) {
        const cues = [];
        if (!srtContent) return cues;
        
        const cleanContent = srtContent.replace(/^\ufeff/, '').replace(/\r\n/g, '\n').replace(/\r/g, '\n').trim();
        const blocks = cleanContent.split(/\n\s*\n/);
        for (const block of blocks) {
            const lines = block.trim().split('\n');
            if (lines.length >= 2) {
                let timeLineIndex = 0;
                if (!lines[0].includes('-->') && lines.length > 1 && lines[1].includes('-->')) {
                    timeLineIndex = 1;
                }
                
                const timeMatch = lines[timeLineIndex].match(/(\d{1,2}:\d{2}:\d{2}[,\.]\d{1,3})\s*-->\s*(\d{1,2}:\d{2}:\d{2}[,\.]\d{1,3})/);
                if (timeMatch) {
                    const start = parseSrtTimestamp(timeMatch[1]);
                    const end = parseSrtTimestamp(timeMatch[2]);
                    const text = lines.slice(timeLineIndex + 1).join('\n');
                    cues.push({ start, end, text });
                }
            }
        }
        return cues;
    }

    // Load available comics
    async function loadComicsList() {
        try {
            const res = await fetch('/api/video_merge/comics');
            if (!res.ok) throw new Error('Không thể tải danh sách truyện');
            const data = await res.json();
            const comics = data.comics || [];

            selectComic.innerHTML = '';
            if (comics.length === 0) {
                const opt = document.createElement('option');
                opt.value = '';
                opt.textContent = '-- Chưa có bộ truyện nào render video --';
                selectComic.appendChild(opt);
                return;
            }

            const defaultOpt = document.createElement('option');
            defaultOpt.value = '';
            defaultOpt.textContent = '-- Chọn một bộ truyện --';
            selectComic.appendChild(defaultOpt);

            comics.forEach(c => {
                const opt = document.createElement('option');
                opt.value = c.identifier;
                opt.textContent = `📖 ${c.title} (${c.total_episodes} tập)`;
                selectComic.appendChild(opt);
            });

            // Check URL query param for auto-select
            const urlParams = new URLSearchParams(window.location.search);
            const autoSelectId = urlParams.get('comic') || urlParams.get('task_id');
            if (autoSelectId) {
                const match = comics.find(c => c.identifier === autoSelectId || c.task_id === autoSelectId || c.folder_name === autoSelectId);
                if (match) {
                    selectComic.value = match.identifier;
                    await selectComicChanged(match.identifier);
                }
            }
        } catch (err) {
            console.error('Error loading comics:', err);
            selectComic.innerHTML = `<option value="">Lỗi: ${err.message}</option>`;
        }
    }

    // Handle Comic Selection
    async function selectComicChanged(identifier) {
        if (!identifier) {
            comicInfoBadge.style.display = 'none';
            currentComicInfo = null;
            rangesContainer.innerHTML = '';
            renderMergedVideos([]);
            return;
        }

        try {
            statusDot.className = 'status-dot processing';
            statusText.textContent = 'Đang tải thông tin...';

            const res = await fetch(`/api/video_merge/info/${encodeURIComponent(identifier)}`);
            if (!res.ok) {
                const errData = await res.json().catch(() => ({}));
                throw new Error(errData.detail || 'Không lấy được thông tin bộ truyện');
            }

            currentComicInfo = await res.json();
            
            // Update info badge
            badgeComicTitle.textContent = currentComicInfo.title || currentComicInfo.folder_name;
            badgeTotalEps.textContent = `Đã render ${currentComicInfo.total_episodes} tập`;
            
            if (currentComicInfo.available_episodes && currentComicInfo.available_episodes.length > 0) {
                const minEp = currentComicInfo.available_episodes[0].episode_num;
                const maxEp = currentComicInfo.available_episodes[currentComicInfo.available_episodes.length - 1].episode_num;
                badgeRangeEps.textContent = `Tập ${minEp} → ${maxEp}`;
            } else {
                badgeRangeEps.textContent = `0 tập`;
            }
            badgeFolderName.textContent = currentComicInfo.folder_name;
            comicInfoBadge.style.display = 'block';

            // Render merged videos list
            renderMergedVideos(currentComicInfo.merged_videos || []);

            // Set default preset (Mỗi 10 tập hoặc Gộp tất cả nếu ít tập)
            if (rangesContainer.children.length === 0) {
                if (currentComicInfo.total_episodes <= 10) {
                    applyPreset('all');
                } else {
                    applyPreset(10);
                }
            }

            statusDot.className = 'status-dot idle';
            statusText.textContent = 'Sẵn sàng';
            lucide.createIcons();
        } catch (err) {
            console.error('Error fetching comic info:', err);
            alert(`Lỗi: ${err.message}`);
            statusDot.className = 'status-dot idle';
            statusText.textContent = 'Sẵn sàng';
        }
    }

    selectComic.addEventListener('change', (e) => {
        selectComicChanged(e.target.value);
    });

    // Preset generation
    function applyPreset(size) {
        if (!currentComicInfo || !currentComicInfo.available_episodes || currentComicInfo.available_episodes.length === 0) {
            return;
        }

        const eps = currentComicInfo.available_episodes.map(e => e.episode_num).sort((a, b) => a - b);
        const minEp = eps[0];
        const maxEp = eps[eps.length - 1];

        rangesContainer.innerHTML = '';

        if (size === 'all') {
            addRangeRow(minEp, maxEp, `Gộp Tập ${minEp} - ${maxEp}`);
            return;
        }

        const chunkSize = parseInt(size, 10);
        if (isNaN(chunkSize) || chunkSize <= 0) return;

        let curStart = minEp;
        let index = 1;
        while (curStart <= maxEp) {
            let curEnd = Math.min(curStart + chunkSize - 1, maxEp);
            addRangeRow(curStart, curEnd, `Tập ${curStart} - ${curEnd}`);
            curStart = curEnd + 1;
            index++;
        }
    }

    presetButtons.forEach(btn => {
        btn.addEventListener('click', () => {
            const size = btn.getAttribute('data-size');
            applyPreset(size);
        });
    });

    btnClearRanges.addEventListener('click', () => {
        rangesContainer.innerHTML = '';
        mergeProgressStatus.className = 'status-msg';
        mergeProgressStatus.innerHTML = '<span>Đã xóa toàn bộ khoảng tập. Hãy thêm khoảng mới.</span>';
    });

    // Add Range Row
    function addRangeRow(start = 1, end = 1, title = '') {
        const rowIndex = rangesContainer.children.length + 1;
        const row = document.createElement('div');
        row.className = 'range-row';
        row.innerHTML = `
            <div class="range-index-badge">${rowIndex}</div>
            <div class="range-input-group">
                <label>Từ</label>
                <input type="number" class="range-num-input range-start" min="1" value="${start}">
                <span class="range-sep">→</span>
                <label>Đến</label>
                <input type="number" class="range-num-input range-end" min="1" value="${end}">
            </div>
            <input type="text" class="range-title-input" placeholder="Tên video (tùy chọn)" value="${title || `Tập ${start} - ${end}`}">
            <div class="range-count-badge">${Math.max(0, end - start + 1)} tập</div>
            <button type="button" class="btn-remove-range" title="Xóa khoảng này">
                <i data-lucide="trash-2"></i>
            </button>
        `;

        const startInput = row.querySelector('.range-start');
        const endInput = row.querySelector('.range-end');
        const titleInput = row.querySelector('.range-title-input');
        const countBadge = row.querySelector('.range-count-badge');
        const removeBtn = row.querySelector('.btn-remove-range');

        function updateRowStats() {
            const s = parseInt(startInput.value, 10) || 0;
            const e = parseInt(endInput.value, 10) || 0;
            const count = Math.max(0, e - s + 1);
            countBadge.textContent = `${count} tập`;
            if (!titleInput.dataset.customized) {
                titleInput.value = `Tập ${s} - ${e}`;
            }
        }

        startInput.addEventListener('input', updateRowStats);
        endInput.addEventListener('input', updateRowStats);
        titleInput.addEventListener('input', () => {
            titleInput.dataset.customized = 'true';
        });

        removeBtn.addEventListener('click', () => {
            row.remove();
            reindexRows();
        });

        rangesContainer.appendChild(row);
        lucide.createIcons();
    }

    function reindexRows() {
        Array.from(rangesContainer.children).forEach((row, idx) => {
            const badge = row.querySelector('.range-index-badge');
            if (badge) badge.textContent = idx + 1;
        });
    }

    btnAddRange.addEventListener('click', () => {
        let lastEnd = 0;
        const lastRow = rangesContainer.lastElementChild;
        if (lastRow) {
            const endInput = lastRow.querySelector('.range-end');
            if (endInput) lastEnd = parseInt(endInput.value, 10) || 0;
        }

        let maxEp = 100;
        if (currentComicInfo && currentComicInfo.available_episodes && currentComicInfo.available_episodes.length > 0) {
            maxEp = currentComicInfo.available_episodes[currentComicInfo.available_episodes.length - 1].episode_num;
        }

        const newStart = lastEnd > 0 ? lastEnd + 1 : 1;
        const newEnd = Math.min(newStart + 9, maxEp);
        addRangeRow(newStart, newEnd, `Tập ${newStart} - ${newEnd}`);
    });

    // Render Merged Videos List
    function renderMergedVideos(mergedVideos) {
        mergedVideosList.innerHTML = '';
        mergedCountPill.textContent = `${mergedVideos.length} video`;

        if (!mergedVideos || mergedVideos.length === 0) {
            mergedVideosList.innerHTML = `
                <div class="empty-state">
                    <i data-lucide="video-off"></i>
                    <span>Chưa có video gộp nào cho bộ truyện này.</span>
                </div>
            `;
            lucide.createIcons();
            return;
        }

        mergedVideos.forEach(mv => {
            const card = document.createElement('div');
            card.className = 'merged-item-card';
            
            // Extract range if match
            const rangeMatch = mv.file_name.match(/ep_?(\d+)_?(?:to_)?(\d+)/i);
            const rangeTag = rangeMatch ? `<span class="merged-range-tag">Tập ${rangeMatch[1]}–${rangeMatch[2]}</span>` : '';
            const videoUrl = mv.video_url || mv.url || '';
            const srtUrl = mv.subtitle_url || mv.srt_url || '';
            const sizeMb = (mv.size_mb !== undefined ? mv.size_mb : (mv.file_size_mb || 0));
            const hasSrt = mv.has_srt || !!srtUrl;

            card.innerHTML = `
                <div class="merged-item-info">
                    <div class="merged-item-title" title="${mv.file_name}">
                        ${rangeTag}
                        <span>${mv.file_name}</span>
                    </div>
                    <div class="merged-item-meta">
                        ${mv.duration_seconds ? `<span>⏱ ${formatDuration(mv.duration_seconds)}</span>` : ''}
                        <span>💾 ${Number(sizeMb).toFixed(1)} MB</span>
                        ${hasSrt ? '<span>📝 Có phụ đề</span>' : ''}
                    </div>
                </div>
                <div class="merged-item-actions">
                    <button type="button" class="btn-card-action play" title="Xem video và phụ đề">
                        <i data-lucide="play"></i>
                        <span>Xem</span>
                    </button>
                    <a href="${videoUrl}" download="${mv.file_name}" class="btn-card-action" title="Tải video">
                        <i data-lucide="download"></i>
                    </a>
                    <button type="button" class="btn-card-action danger" title="Xóa video gộp này">
                        <i data-lucide="trash-2"></i>
                    </button>
                </div>
            `;

            // Actions
            const btnPlay = card.querySelector('.btn-card-action.play');
            const btnDelete = card.querySelector('.btn-card-action.danger');

            btnPlay.addEventListener('click', () => {
                playMergedVideo(mv);
            });

            btnDelete.addEventListener('click', async () => {
                if (!confirm(`Bạn có chắc chắn muốn xóa video "${mv.file_name}" không?`)) return;
                try {
                    const delRes = await fetch(`/api/video_merge/merged-videos/${encodeURIComponent(currentComicInfo.identifier)}/${encodeURIComponent(mv.file_name)}`, {
                        method: 'DELETE'
                    });
                    if (!delRes.ok) throw new Error('Xóa file thất bại');
                    // Refresh comic info
                    await selectComicChanged(currentComicInfo.identifier);
                } catch (err) {
                    alert(`Lỗi khi xóa: ${err.message}`);
                }
            });

            mergedVideosList.appendChild(card);
        });

        lucide.createIcons();
    }

    function updateMergedSubtitleOverlay() {
        if (!subtitlesEnabled || parsedSrtCues.length === 0) {
            subtitleOverlay.style.display = 'none';
            return;
        }

        const curTime = studioVideoPlayer.currentTime || 0;
        const activeCue = parsedSrtCues.find(c => curTime >= c.start && curTime <= c.end);

        if (activeCue && activeCue.text) {
            subtitleText.innerHTML = activeCue.text.replace(/\n/g, '<br>');
            subtitleOverlay.style.display = 'block';
        } else {
            subtitleOverlay.style.display = 'none';
        }
    }

    // Play Merged Video with Subtitle Sync
    async function playMergedVideo(mv) {
        const videoUrl = mv.video_url || mv.url || '';
        let srtUrl = mv.subtitle_url || mv.srt_url || '';

        playerTitle.textContent = `Đang xem: ${mv.file_name}`;
        studioVideoPlayer.src = videoUrl;
        studioVideoPlayer.load();

        parsedSrtCues = [];
        subtitleText.textContent = '';
        subtitleOverlay.style.display = 'none';

        // Subtitle candidate URLs
        const srtCandidates = [];
        if (srtUrl) srtCandidates.push(srtUrl);
        if (videoUrl && videoUrl.toLowerCase().endsWith('.mp4')) {
            srtCandidates.push(videoUrl.replace(/\.mp4$/i, '.srt'));
            srtCandidates.push(`/api/subtitles?video=${encodeURIComponent(videoUrl)}`);
        }

        let loaded = false;
        for (const candidate of srtCandidates) {
            if (!candidate) continue;
            try {
                const srtRes = await fetch(candidate);
                if (srtRes.ok) {
                    const srtRaw = await srtRes.text();
                    parsedSrtCues = parseSRT(srtRaw);
                    if (parsedSrtCues.length > 0) {
                        subStatusText.textContent = `Phụ đề: ${parsedSrtCues.length} câu đã đồng bộ`;
                        loaded = true;
                        updateMergedSubtitleOverlay();
                        break;
                    }
                }
            } catch (err) {
                console.warn('Cannot load SRT candidate:', candidate, err);
            }
        }

        if (!loaded) {
            subStatusText.textContent = `Không có phụ đề kèm theo`;
        }

        try {
            await studioVideoPlayer.play();
        } catch (e) {
            console.log('Auto-play waiting for user interaction:', e);
        }
    }

    // Video Timeupdate listener for Subtitles
    studioVideoPlayer.addEventListener('timeupdate', updateMergedSubtitleOverlay);
    studioVideoPlayer.addEventListener('seeked', updateMergedSubtitleOverlay);

    // Toggle Subtitles
    btnToggleSub.addEventListener('click', () => {
        subtitlesEnabled = !subtitlesEnabled;
        btnSubLabel.textContent = subtitlesEnabled ? 'Phụ đề: Bật' : 'Phụ đề: Tắt';
        updateMergedSubtitleOverlay();
    });

    // Start Merge Execution
    btnStartMerge.addEventListener('click', async () => {
        if (!currentComicInfo) {
            alert('Vui lòng chọn một bộ truyện trước!');
            return;
        }

        const rows = Array.from(rangesContainer.children);
        if (rows.length === 0) {
            alert('Vui lòng thêm ít nhất một khoảng tập cần gộp!');
            return;
        }

        const ranges = [];
        for (const row of rows) {
            const start = parseInt(row.querySelector('.range-start').value, 10);
            const end = parseInt(row.querySelector('.range-end').value, 10);
            const title = row.querySelector('.range-title-input').value.trim();

            if (isNaN(start) || isNaN(end) || start <= 0 || end <= 0) {
                alert('Tập bắt đầu và tập kết thúc phải là số nguyên dương!');
                return;
            }
            if (start > end) {
                alert(`Khoảng không hợp lệ: Tập bắt đầu (${start}) lớn hơn tập kết thúc (${end})!`);
                return;
            }

            ranges.push({
                from_ep: start,
                to_ep: end,
                custom_name: title || `Tập ${start} - ${end}`
            });
        }

        // Start processing
        btnStartMerge.disabled = true;
        statusDot.className = 'status-dot processing';
        statusText.textContent = 'Đang gộp video...';
        mergeProgressStatus.className = 'status-msg';
        mergeProgressStatus.innerHTML = `<span>⚡ Đang thực hiện gộp ${ranges.length} video bằng Stream Copy...</span>`;

        try {
            const res = await fetch('/api/video_merge/merge', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    identifier: currentComicInfo.identifier || currentComicInfo.task_id || currentComicInfo.folder_name,
                    ranges: ranges
                })
            });

            const result = await res.json();
            if (!res.ok || result.status !== 'success') {
                throw new Error(result.error || result.detail || 'Quá trình gộp video gặp sự cố');
            }

            // Success
            mergeProgressStatus.className = 'status-msg success';
            mergeProgressStatus.innerHTML = `<span>🎉 Đã gộp thành công ${result.created_count || (result.merged_videos || []).length} video! Tốc độ Stream Copy hoàn tất tức thì.</span>`;


            // Reload comic info to refresh list
            await selectComicChanged(currentComicInfo.identifier);

            // If any merged video produced, auto play the first one
            if (result.merged_videos && result.merged_videos.length > 0) {
                const firstOne = currentComicInfo.merged_videos.find(m => m.file_name === result.merged_videos[0].file_name);
                if (firstOne) {
                    playMergedVideo(firstOne);
                }
            }
        } catch (err) {
            console.error('Merge error:', err);
            mergeProgressStatus.className = 'status-msg error';
            mergeProgressStatus.innerHTML = `<span>❌ Lỗi gộp video: ${err.message}</span>`;
            alert(`Lỗi: ${err.message}`);
        } finally {
            btnStartMerge.disabled = false;
            statusDot.className = 'status-dot idle';
            statusText.textContent = 'Sẵn sàng';
        }
    });

    // Initialize
    loadComicsList();
});
