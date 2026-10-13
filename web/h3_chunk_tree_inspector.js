import { app } from "/scripts/app.js";
import { api } from "/scripts/api.js";

/**
 * MiniMax H3 Chunk Tree Reviewer & Inspector Web Extension (Select All & Deselect Edition)
 * Includes:
 * - [전체 줄 선택] & [선택 해제] 원클릭 일괄 버튼
 * - Resizable Divider (좌우 분할 조절)
 * - Cycle-free Smart Synchronization
 */

app.registerExtension({
    name: "minimax.h3.chunk.tree.reviewer",
    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name !== "MiniMaxH3ProjectStudio" && nodeData.name !== "MiniMaxH3ChunkTreeReviewer") return;

        const onNodeCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            const r = onNodeCreated ? onNodeCreated.apply(this, arguments) : undefined;
            const node = this;

            const root = document.createElement("div");
            root.className = "h3-tree-inspector-container";
            root.style.cssText = `
                display: flex;
                flex-direction: row;
                width: 100%;
                height: 620px;
                min-height: 620px;
                background: #121215;
                color: #e2e8f0;
                font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
                border-radius: 8px;
                overflow: hidden;
                box-sizing: border-box;
                border: 1px solid #2d3748;
                position: relative;
                user-select: none;
                isolation: isolate;
                clip-path: none !important;
            `;

            // Prevent canvas node selection/drag bugs on interacting inside the studio,
            // but DO NOT block pointerup/mouseup so global drag release handlers always fire!
            for (const evName of ["pointerdown", "mousedown", "click", "dblclick"]) {
                root.addEventListener(evName, (e) => e.stopPropagation());
            }

            // Left: Tree Branch Panel
            const treePanel = document.createElement("div");
            treePanel.className = "h3-tree-panel";
            const initialWidth = localStorage.getItem("h3_tree_panel_width") || "48%";
            treePanel.style.cssText = `
                width: ${initialWidth};
                min-width: 280px;
                max-width: 70%;
                flex-shrink: 0;
                height: 100%;
                display: flex;
                flex-direction: column;
                background: #141416;
                overflow: hidden;
                box-sizing: border-box;
            `;

            // Tree Header with [전체 선택] & [선택 해제]
            const treeHeader = document.createElement("div");
            treeHeader.style.cssText = `
                padding: 10px 14px;
                background: #1f1f23;
                border-bottom: 1px solid #2d3748;
                display: flex;
                justify-content: space-between;
                align-items: center;
                flex-shrink: 0;
            `;
            treeHeader.innerHTML = `
                <div style="display: flex; align-items: center; gap: 8px;">
                    <span style="font-size: 13px; font-weight: 600; color: #60a5fa;">🌿 청크 브랜치 트리</span>
                    <button id="btnSelectAllRows" style="padding: 2px 7px; font-size: 10.5px; background: rgba(59,130,246,0.2); border: 1px solid rgba(59,130,246,0.4); border-radius: 4px; color: #93c5fd; cursor: pointer;" title="모든 줄 일괄 선택">전체 선택</button>
                    <button id="btnDeselectAllRows" style="padding: 2px 7px; font-size: 10.5px; background: rgba(100,116,139,0.2); border: 1px solid rgba(100,116,139,0.4); border-radius: 4px; color: #cbd5e1; cursor: pointer;" title="모든 줄 선택 해제">선택 해제</button>
                    <button id="btnRefreshTree" style="padding: 2px 7px; font-size: 10.5px; background: rgba(16,185,129,0.18); border: 1px solid rgba(16,185,129,0.45); border-radius: 4px; color: #6ee7b7; cursor: pointer;" title="디스크에서 현재 프로젝트 트리 강제 새로고침">🔄 새로고침</button>
                </div>
                <div id="retrySummary" style="font-size: 11px; color: #f59e0b; background: rgba(245,158,11,0.12); padding: 3px 8px; border-radius: 4px; border: 1px solid rgba(245,158,11,0.3);">
                    재생성 선택: 없음 (전체 유지)
                </div>
            `;
            treePanel.appendChild(treeHeader);

            // Tree Scrollable Content
            const treeContent = document.createElement("div");
            treeContent.id = "treeRowsContainer";
            treeContent.style.cssText = `
                flex: 1;
                overflow-y: auto;
                padding: 12px;
                display: flex;
                flex-direction: column;
                gap: 14px;
            `;
            treePanel.appendChild(treeContent);

            // Center: Resizable Divider
            const divider = document.createElement("div");
            divider.className = "h3-tree-divider";
            divider.style.cssText = `
                width: 7px;
                cursor: col-resize;
                background: #27272a;
                position: relative;
                flex-shrink: 0;
                transition: background 0.15s ease;
                display: flex;
                align-items: center;
                justify-content: center;
            `;
            divider.innerHTML = `<div style="width: 2px; height: 32px; background: #52525b; border-radius: 1px;"></div>`;
            divider.title = "드래그하여 좌우 너비 조절 (더블클릭 시 50:50 초기화)";

            divider.addEventListener("mouseenter", () => { divider.style.background = "#3b82f6"; });
            divider.addEventListener("mouseleave", () => { if (!isDragging) divider.style.background = "#27272a"; });
            divider.addEventListener("dblclick", () => {
                treePanel.style.width = "50%";
                localStorage.setItem("h3_tree_panel_width", "50%");
            });

            let isDragging = false;
            divider.addEventListener("mousedown", (e) => {
                e.preventDefault();
                e.stopPropagation();
                isDragging = true;
                divider.style.background = "#3b82f6";
                document.body.style.cursor = "col-resize";
                document.body.style.userSelect = "none";

                const onMouseMove = (moveEvent) => {
                    if (!isDragging) return;
                    const containerRect = root.getBoundingClientRect();
                    if (!containerRect || containerRect.width === 0) return;
                    const newWidthPx = moveEvent.clientX - containerRect.left;
                    const percent = Math.min(Math.max((newWidthPx / containerRect.width) * 100, 20), 80);
                    treePanel.style.width = `${percent.toFixed(1)}%`;
                    localStorage.setItem("h3_tree_panel_width", `${percent.toFixed(1)}%`);
                };

                const onMouseUp = () => {
                    isDragging = false;
                    divider.style.background = "#27272a";
                    document.body.style.cursor = "default";
                    document.body.style.userSelect = "";
                    document.removeEventListener("mousemove", onMouseMove, true);
                    document.removeEventListener("mouseup", onMouseUp, true);
                    window.removeEventListener("mouseup", onMouseUp, true);
                };

                document.addEventListener("mousemove", onMouseMove, true);
                document.addEventListener("mouseup", onMouseUp, true);
                window.addEventListener("mouseup", onMouseUp, true);
            });

            // Right: Video Player Panel
            const playerPanel = document.createElement("div");
            playerPanel.className = "h3-player-panel";
            playerPanel.style.cssText = `
                flex: 1;
                min-width: 260px;
                height: 100%;
                display: flex;
                flex-direction: column;
                background: #09090b;
                padding: 12px;
                box-sizing: border-box;
                overflow: hidden;
                position: relative;
            `;

            const videoInfoBar = document.createElement("div");
            videoInfoBar.id = "videoInfoBar";
            videoInfoBar.style.cssText = `
                width: 100%;
                box-sizing: border-box;
                font-size: 11.5px;
                color: #e2e8f0;
                margin-bottom: 6px;
                display: flex;
                flex-direction: column;
                gap: 5px;
                padding: 6px 10px;
                background: #18181b;
                border-radius: 4px;
                border: 1px solid #27272a;
                flex-shrink: 0;
            `;
            videoInfoBar.innerHTML = `
                <div style="display: flex; justify-content: space-between; align-items: center; width: 100%;">
                    <span id="playerTitle" style="font-weight: 600; color: #60a5fa; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">선택된 청크: 없음</span>
                    <a id="btnDownloadCurrentVideo" href="#" download="" target="_blank" style="padding: 2px 7px; font-size: 10.5px; background: rgba(59, 130, 246, 0.2); border: 1px solid #3b82f6; border-radius: 3px; color: #93c5fd; text-decoration: none; display: flex; align-items: center; gap: 3px; cursor: pointer; flex-shrink: 0; transition: all 0.15s ease;">
                        <span>⬇️</span><span>다운로드</span>
                    </a>
                </div>
                <div style="display: flex; justify-content: space-between; align-items: center; gap: 6px; width: 100%; font-size: 11px;">
                    <span id="playerSub" style="color: #a1a1aa; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; flex: 1;">클릭하여 미리보기</span>
                    <div id="mergedHistoryContainer" style="display: none; align-items: center; gap: 4px; flex-shrink: 0;">
                        <span style="color: #10b981; font-weight: 600; font-size: 10px;">📂 완성본:</span>
                        <select id="selectMergedHistory" style="padding: 2px 5px; font-size: 10.5px; background: #27272a; color: #f1f5f9; border: 1px solid #3f3f46; border-radius: 3px; max-width: 190px; cursor: pointer; outline: none;"></select>
                    </div>
                </div>
            `;
            playerPanel.appendChild(videoInfoBar);

            const videoEl = document.createElement("video");
            videoEl.id = "h3InspectorVideo";
            videoEl.controls = true;
            videoEl.autoplay = true;
            videoEl.loop = true;
            videoEl.style.cssText = `
                flex: 1;
                width: 100%;
                min-height: 0;
                max-height: 100%;
                background: #000;
                border-radius: 6px;
                border: 1px solid #3f3f46;
                box-shadow: 0 4px 16px rgba(0,0,0,0.6);
                object-fit: contain;
                box-sizing: border-box;
                display: block;
            `;
            playerPanel.appendChild(videoEl);

            const playControls = document.createElement("div");
            playControls.style.cssText = `
                margin-top: 6px;
                display: flex;
                flex-direction: column;
                gap: 5px;
                width: 100%;
                flex-shrink: 0;
                box-sizing: border-box;
            `;
            playControls.innerHTML = `
                <div style="display: flex; align-items: center; justify-content: flex-end; gap: 6px; font-size: 11px; color: #cbd5e1; padding: 0 2px;">
                    <input type="checkbox" id="cbTrimTrailingFrames" style="cursor: pointer; accent-color: #10b981;">
                    <label for="cbTrimTrailingFrames" style="cursor: pointer; user-select: none;" title="H3가 자체 연장한 마지막 4프레임(약 0.17초)을 잘라내어 원본 5.0초 및 오디오 립싱크를 정확히 일치시킵니다.">
                        ✂️ 청크 끝 4프레임 잘라내기 (오디오 싱크 일치)
                    </label>
                </div>
                <div style="display: flex; flex-direction: row; gap: 6px; width: 100%; align-items: stretch;">
                    <button id="btnPlayAllPath" style="flex: 1 1 65%; min-width: 0; padding: 8px 10px; font-size: 12px; background: #2563eb; color: #fff; border: none; border-radius: 4px; cursor: pointer; font-weight: 700; box-shadow: 0 1px 3px rgba(0,0,0,0.3); display: flex; align-items: center; justify-content: center; gap: 6px; transition: all 0.15s ease;">
                        <span>🎬</span><span style="white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">전체 비디오 연속 재생</span>
                    </button>
                    <button id="btnMuxProject" style="flex: 0 0 auto; padding: 8px 12px; font-size: 11.5px; background: linear-gradient(135deg, #059669 0%, #0d9488 100%); color: #fff; border: none; border-radius: 4px; cursor: pointer; font-weight: 600; box-shadow: 0 1px 3px rgba(0,0,0,0.3); display: flex; align-items: center; justify-content: center; gap: 5px; transition: all 0.15s ease;">
                        <span>⚡</span><span style="white-space: nowrap;">최종 병합</span>
                    </button>
                </div>
            `;
            playerPanel.appendChild(playControls);

            root.appendChild(treePanel);
            root.appendChild(divider);
            root.appendChild(playerPanel);

            const widget = node.addDOMWidget("h3_chunk_tree_inspector", "h3-tree-inspector", root, {
                serialize: false,
                hideOnZoom: false,
                selectOn: [], // Prevent clicking inside DOM from triggering graph selectNode re-clipping
                getMinHeight: () => 600,
            });
            widget.serialize = false;

            // Protect against outer Vue DOM clipping wrapper
            setTimeout(() => {
                if (root.parentElement) {
                    root.parentElement.style.clipPath = "none";
                    root.parentElement.style.willChange = "auto";
                }
            }, 50);

            // Make root dimensions dynamically follow node resize
            node.onResize = function(size) {
                if (root && size) {
                    if (size[1]) {
                        const h = Math.max(size[1] - 140, 520);
                        root.style.height = `${h}px`;
                    }
                }
            };

            node.setSize?.([
                Math.max(Number(node.size?.[0]) || 0, 1020),
                Math.max(Number(node.size?.[1]) || 0, 760),
            ]);

            let currentSessionData = null;
            let activeTakesByScene = {};
            let currentClickedTakeHash = null;
            let checkedRetryScenes = new Set();

            function syncRetryToGenerator() {
                const sorted = Array.from(checkedRetryScenes).sort((a,b)=>a-b);
                const val = sorted.length > 0 ? sorted.join(", ") : "";

                const retryWidget = node.widgets?.find(w => w.name === "retry_chunks");
                if (retryWidget) retryWidget.value = val;

                const genNode = app.graph?._nodes?.find(n => n.type === "MiniMaxH3ChunkGenerator");
                if (genNode) {
                    const genWidget = genNode.widgets?.find(w => w.name === "retry_chunks");
                    if (genWidget) genWidget.value = val;
                }

                const summaryEl = root.querySelector("#retrySummary");
                if (summaryEl) {
                    if (currentSessionData && currentSessionData.scenes && sorted.length === currentSessionData.scenes.length) {
                        summaryEl.textContent = "재생성 줄: [전체 모든 줄] 선택됨";
                    } else if (sorted.length > 0) {
                        summaryEl.textContent = `재생성 줄: [S${sorted.join(", S")}] 선택됨`;
                    } else {
                        summaryEl.textContent = "재생성 선택: 없음 (전체 유지)";
                    }
                }
            }

            // [전체 선택] 버튼 클릭 핸들러
            const btnSelectAll = root.querySelector("#btnSelectAllRows");
            if (btnSelectAll) {
                btnSelectAll.onclick = () => {
                    if (!currentSessionData || !currentSessionData.scenes) return;
                    currentSessionData.scenes.forEach(s => checkedRetryScenes.add(s.index));
                    root.querySelectorAll("input[type='checkbox'][id^='retry_cb_']").forEach(cb => {
                        cb.checked = true;
                        const row = cb.closest("div[id^='scene_row_']");
                        if (row) row.style.borderColor = "#f59e0b";
                    });
                    syncRetryToGenerator();
                };
            }

            // [선택 해제] 버튼 클릭 핸들러
            const btnDeselectAll = root.querySelector("#btnDeselectAllRows");
            if (btnDeselectAll) {
                btnDeselectAll.onclick = () => {
                    checkedRetryScenes.clear();
                    root.querySelectorAll("input[type='checkbox'][id^='retry_cb_']").forEach(cb => {
                        cb.checked = false;
                        const row = cb.closest("div[id^='scene_row_']");
                        if (row) row.style.borderColor = "#2e2e38";
                    });
                    syncRetryToGenerator();
                };
            }

            let currentViewingSceneIdx = 1;
            let isPlaylistMode = false;
            let playlistQueue = [];
            let playlistIndex = 0;

            function playVideoUrl(url, title, sub, loop = true) {
                if (!url) return;
                videoEl.loop = loop;
                videoEl.src = url;
                videoEl.load();
                videoEl.currentTime = 0;
                videoEl.play().catch(()=>{});
                const tEl = root.querySelector("#playerTitle");
                const sEl = root.querySelector("#playerSub");
                if (tEl) tEl.textContent = title || "";
                if (sEl) sEl.textContent = sub || "";

                const dlBtn = root.querySelector("#btnDownloadCurrentVideo");
                if (dlBtn) {
                    dlBtn.href = url;
                    // Extract clean filename from url query
                    try {
                        const u = new URL(url, window.location.origin);
                        const fn = u.searchParams.get("filename") || "video.mp4";
                        dlBtn.download = fn;
                    } catch(e) {
                        dlBtn.download = "video.mp4";
                    }
                }
            }

            const updatePlayAllBtnState = () => {
                const playAllBtn = root.querySelector("#btnPlayAllPath");
                if (playAllBtn) {
                    if (isPlaylistMode) {
                        playAllBtn.style.background = "#059669";
                        playAllBtn.innerHTML = `<span>⏹️</span><span style="white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">연속 재생 정지 (S${currentViewingSceneIdx})</span>`;
                    } else {
                        playAllBtn.style.background = "#2563eb";
                        const total = currentSessionData?.scenes?.length || 0;
                        playAllBtn.innerHTML = `<span>🎬</span><span style="white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">전체 비디오 연속 재생 (S1 ➔ S${total || '끝'})</span>`;
                    }
                }
            };

            const stopPlaylistMode = () => {
                if (isPlaylistMode) {
                    isPlaylistMode = false;
                    playlistQueue = [];
                    playlistIndex = 0;
                    videoEl.loop = true;
                    updatePlayAllBtnState();
                }
            };

            const playCurrentPlaylistItem = () => {
                if (!isPlaylistMode || playlistIndex >= playlistQueue.length) return;
                const item = playlistQueue[playlistIndex];
                currentViewingSceneIdx = item.sceneIndex;
                currentClickedTakeHash = item.hash;
                renderTree(currentSessionData);
                updatePlayAllBtnState();
                playVideoUrl(item.url, item.title, item.sub, false);
            };

            const startPlaylistMode = () => {
                if (!currentSessionData || !currentSessionData.scenes || currentSessionData.scenes.length === 0) return;
                
                playlistQueue = [];
                currentSessionData.scenes.forEach(scene => {
                    if (scene.takes && scene.takes.length > 0) {
                        const activeHash = activeTakesByScene[scene.index];
                        const take = scene.takes.find(t => t.hash === activeHash) || scene.takes[scene.takes.length - 1];
                        if (take && take.url) {
                            playlistQueue.push({
                                sceneIndex: scene.index,
                                takeIndex: take.takeIndex,
                                hash: take.hash,
                                url: take.url,
                                title: `🎬 S${scene.index} Take #${take.takeIndex} (연속 재생)`,
                                sub: `전체 연속 재생 중 (${scene.index}/${currentSessionData.scenes.length}) · 구간: ${scene.startTime.toFixed(1)}s ~ ${(scene.startTime + scene.duration).toFixed(1)}s`
                            });
                        }
                    }
                });

                if (playlistQueue.length === 0) return;

                isPlaylistMode = true;
                playlistIndex = 0;
                updatePlayAllBtnState();
                playCurrentPlaylistItem();
            };

            videoEl.onended = () => {
                if (isPlaylistMode) {
                    playlistIndex++;
                    if (playlistIndex < playlistQueue.length) {
                        playCurrentPlaylistItem();
                    } else {
                        // Loop entire continuous playlist from start
                        playlistIndex = 0;
                        playCurrentPlaylistItem();
                    }
                }
            };

            async function callEditTreeApi(payload) {
                if (!currentSessionData || !currentSessionData.project_name) return;
                stopPlaylistMode();
                try {
                    const res = await fetch("/api/h3/edit_tree", {
                        method: "POST",
                        headers: { "Content-Type": "application/json" },
                        body: JSON.stringify({
                            project_name: currentSessionData.project_name,
                            ...payload
                        })
                    });
                    const data = await res.json();
                    if (!res.ok || data.error) {
                        alert("⚠️ 작업 실패: " + (data.error || "알 수 없는 오류"));
                        return null;
                    }
                    if (data.session_tree_data) {
                        // Remap retry checkboxes & active takes cleanly
                        checkedRetryScenes.clear();
                        syncRetryToGenerator();
                        renderTree(data.session_tree_data, false);
                    }
                    return data;
                } catch (err) {
                    console.error("[H3-Tree] Edit tree error:", err);
                    alert("⚠️ 서버 통신 오류: " + err.message);
                    return null;
                }
            }

            function renderTree(sessionData, autoPlay = false) {
                if (Array.isArray(sessionData)) {
                    if (sessionData.length > 0 && typeof sessionData[0] === "object" && sessionData[0] !== null) {
                        sessionData = sessionData[0];
                    } else {
                        sessionData = null;
                    }
                }
                if (!sessionData || !Array.isArray(sessionData.scenes) || sessionData.scenes.length === 0) {
                    treeContent.innerHTML = `<div style="color: #94a3b8; font-size: 12.5px; text-align: center; margin-top: 50px; line-height: 1.6;">⏳ 아직 완료된 청크 테이크가 없거나 생성 중입니다.<br><span style="font-size: 11px; color: #64748b;">청크 생성이 완료되면 자동으로 여기에 표시됩니다. (또는 상단 🔄 새로고침 클릭)</span></div>`;
                    return;
                }

                treeContent.innerHTML = "";
                currentSessionData = sessionData;
                updatePlayAllBtnState();

                // Setup merged video history dropdown
                const mergedContainer = root.querySelector("#mergedHistoryContainer");
                const mergedSelect = root.querySelector("#selectMergedHistory");
                const historyList = sessionData.merged_history || [];

                if (mergedContainer && mergedSelect) {
                    if (historyList.length > 0) {
                        mergedContainer.style.display = "flex";
                        mergedSelect.innerHTML = "";
                        
                        historyList.forEach((m, mIdx) => {
                            const opt = document.createElement("option");
                            opt.value = m.url;
                            const label = m.isInitial ? `[최초] ${m.timeStr.slice(5, 16)} (${m.sizeMb}MB)` : `[병합 #${historyList.length - mIdx}] ${m.timeStr.slice(5, 16)} (${m.sizeMb}MB)`;
                            opt.textContent = label;
                            opt.title = `${m.filename} | ${m.res || ''}`;
                            mergedSelect.appendChild(opt);
                        });

                        // Select the current playing full_url or latest
                        if (sessionData.full_url) {
                            mergedSelect.value = sessionData.full_url;
                        }

                        mergedSelect.onchange = (e) => {
                            const selectedUrl = e.target.value;
                            if (selectedUrl) {
                                stopPlaylistMode();
                                currentSessionData.full_url = selectedUrl;
                                const selectedItem = historyList.find(h => h.url === selectedUrl);
                                const vTitle = selectedItem?.isInitial ? `🎬 최초 자동 병합 완성본` : `🎬 병합 완성본 (${sessionData.project_name})`;
                                const vSub = `${selectedItem?.filename || ''} (${selectedItem?.timeStr || ''}, ${selectedItem?.sizeMb || ''}MB)`;
                                playVideoUrl(selectedUrl, vTitle, vSub);
                            }
                        };
                    } else {
                        mergedContainer.style.display = "none";
                    }
                }

                sessionData.scenes.forEach((scene, sIdx) => {
                    const sceneIdx = scene.index;
                    const rowContainer = document.createElement("div");
                    rowContainer.id = `scene_row_${sceneIdx}`;
                    const isRowFav = Boolean(scene.favorite);
                    rowContainer.style.cssText = `
                        background: ${isRowFav ? "rgba(250, 204, 21, 0.05)" : "#1c1c21"};
                        border: 1px solid ${checkedRetryScenes.has(sceneIdx) ? "#f59e0b" : (isRowFav ? "rgba(250, 204, 21, 0.55)" : "#2e2e38")};
                        border-radius: 6px;
                        padding: 10px;
                        display: flex;
                        flex-direction: column;
                        gap: 8px;
                        transition: border 0.15s ease;
                    `;

                    const rowHeader = document.createElement("div");
                    rowHeader.style.cssText = "display: flex; justify-content: space-between; align-items: center; font-size: 12px;";

                    const leftHeader = document.createElement("div");
                    leftHeader.style.cssText = "display: flex; align-items: center; gap: 8px;";
                    
                    const cb = document.createElement("input");
                    cb.type = "checkbox";
                    cb.checked = checkedRetryScenes.has(sceneIdx);
                    cb.id = `retry_cb_${sceneIdx}`;
                    cb.onchange = (e) => {
                        if (e.target.checked) checkedRetryScenes.add(sceneIdx);
                        else checkedRetryScenes.delete(sceneIdx);
                        rowContainer.style.borderColor = checkedRetryScenes.has(sceneIdx) ? "#f59e0b" : (scene.favorite ? "rgba(250, 204, 21, 0.55)" : "#2e2e38");
                        syncRetryToGenerator();
                    };

                    const titleLabel = document.createElement("label");
                    titleLabel.htmlFor = `retry_cb_${sceneIdx}`;
                    titleLabel.style.cssText = "font-weight: 600; color: #f1f5f9; cursor: pointer; display: flex; align-items: center; gap: 5px;";
                    const copyBadge = scene.isCopy
                        ? `<span style="font-size: 9.5px; padding: 1px 5px; background: rgba(168, 85, 247, 0.22); border: 1px solid rgba(168, 85, 247, 0.5); color: #d8b4fe; border-radius: 3px; font-weight: 600;" title="원본 파일 복사 없이 타임라인 포인터로 끼워 넣은 복제 노드입니다 (원본 S${scene.sourceSlot || sceneIdx})">복제본 (원본 S${scene.sourceSlot || sceneIdx})</span>`
                        : "";
                    titleLabel.innerHTML = `<span>Scene ${sceneIdx} (${scene.duration.toFixed(1)}s 구간)</span>${copyBadge}`;

                    const btnViewOrig = document.createElement("button");
                    btnViewOrig.style.cssText = `
                        padding: 2px 7px;
                        font-size: 10px;
                        background: rgba(13, 148, 136, 0.2);
                        border: 1px solid rgba(13, 148, 136, 0.45);
                        border-radius: 4px;
                        color: #2dd4bf;
                        cursor: pointer;
                        display: flex;
                        align-items: center;
                        gap: 3px;
                        transition: all 0.15s ease;
                    `;
                    const origRes = scene.original?.res;
                    let origMpStr = "";
                    if (origRes && origRes.includes("x")) {
                        const [ow, oh] = origRes.split("x").map(Number);
                        if (ow && oh) origMpStr = ` (${(ow * oh / 1000000).toFixed(2)} MP)`;
                    }

                    btnViewOrig.title = `이 구간의 원본 영상 재생${origRes ? ' [' + origRes + origMpStr + ']' : ''}`;
                    btnViewOrig.innerHTML = `<span>🎞️</span><span>원본 보기${origRes ? ' (' + origRes + ')' : ''}</span>`;
                    btnViewOrig.onmouseenter = () => {
                        btnViewOrig.style.background = "rgba(13, 148, 136, 0.4)";
                        btnViewOrig.style.borderColor = "#14b8a6";
                    };
                    btnViewOrig.onmouseleave = () => {
                        btnViewOrig.style.background = "rgba(13, 148, 136, 0.2)";
                        btnViewOrig.style.borderColor = "rgba(13, 148, 136, 0.45)";
                    };
                    const origUrl = scene.original?.url || `/api/view?filename=chunk_${String(scene.sourceSlot || sceneIdx).padStart(3, '0')}_orig.mp4&subfolder=swapH3/${encodeURIComponent(sessionData.project_name)}/chunks&type=output`;
                    if (origUrl) {
                        const probeOrig = document.createElement("video");
                        probeOrig.preload = "metadata";
                        probeOrig.src = origUrl;
                        probeOrig.onloadedmetadata = () => {
                            const vw = probeOrig.videoWidth;
                            const vh = probeOrig.videoHeight;
                            if (vw > 0 && vh > 0) {
                                const actualRes = `${vw}x${vh}`;
                                const actualMp = (vw * vh / 1000000).toFixed(2);
                                if (scene.original) scene.original.res = actualRes;
                                btnViewOrig.title = `이 구간의 원본 영상 재생 [${actualRes} (${actualMp} MP)]`;
                                btnViewOrig.innerHTML = `<span>🎞️</span><span>원본 보기 (${actualRes})</span>`;
                            }
                            probeOrig.removeAttribute("src");
                            probeOrig.load();
                        };
                    }

                    btnViewOrig.onclick = (e) => {
                        e.stopPropagation();
                        stopPlaylistMode();
                        currentViewingSceneIdx = sceneIdx;
                        playVideoUrl(origUrl, `🎞️ S${sceneIdx} 원본 청크 비디오 (Original)`, `구간: ${scene.startTime.toFixed(1)}s ~ ${(scene.startTime + scene.duration).toFixed(1)}s (원본 비디오)`);
                    };

                    const btnFavRow = document.createElement("button");
                    btnFavRow.type = "button";
                    btnFavRow.innerHTML = isRowFav ? "★" : "☆";
                    btnFavRow.title = isRowFav ? "즐겨찾기 해제" : "이 줄(Scene)을 즐겨찾기 표시";
                    btnFavRow.style.cssText = `
                        padding: 0 5px;
                        font-size: 14px;
                        line-height: 18px;
                        background: ${isRowFav ? "rgba(250, 204, 21, 0.2)" : "transparent"};
                        border: 1px solid ${isRowFav ? "rgba(250, 204, 21, 0.6)" : "rgba(100, 116, 139, 0.35)"};
                        border-radius: 4px;
                        color: ${isRowFav ? "#facc15" : "#64748b"};
                        cursor: pointer;
                        transition: all 0.15s ease;
                    `;
                    btnFavRow.onclick = (e) => {
                        e.stopPropagation();
                        callEditTreeApi({ action: "toggle_favorite_scene", scene_index: sceneIdx });
                    };

                    leftHeader.appendChild(cb);
                    leftHeader.appendChild(btnFavRow);
                    leftHeader.appendChild(titleLabel);
                    leftHeader.appendChild(btnViewOrig);

                    const rightHeader = document.createElement("div");
                    rightHeader.style.cssText = "display: flex; align-items: center; gap: 5px;";

                    const takesCountSpan = document.createElement("span");
                    takesCountSpan.style.cssText = "font-size: 11px; color: #64748b; margin-right: 4px;";
                    takesCountSpan.textContent = `총 ${scene.takes.length}개 테이크`;
                    rightHeader.appendChild(takesCountSpan);

                    const makeRowActionBtn = (label, title, bg, border, color, onClick, disabled = false) => {
                        const b = document.createElement("button");
                        b.innerHTML = label;
                        b.title = title;
                        b.disabled = disabled;
                        b.style.cssText = `
                            padding: 2px 6px;
                            font-size: 10px;
                            background: ${bg};
                            border: 1px solid ${border};
                            border-radius: 4px;
                            color: ${color};
                            cursor: ${disabled ? "not-allowed" : "pointer"};
                            opacity: ${disabled ? "0.35" : "1"};
                            transition: all 0.15s ease;
                        `;
                        if (!disabled) {
                            b.onclick = (e) => {
                                e.stopPropagation();
                                onClick();
                            };
                        }
                        return b;
                    };

                    // [↑] 위로 이동
                    rightHeader.appendChild(makeRowActionBtn(
                        "↑",
                        "이 씬 행을 한 칸 위로 이동",
                        "rgba(100,116,139,0.18)",
                        "rgba(100,116,139,0.4)",
                        "#cbd5e1",
                        () => callEditTreeApi({ action: "move_scene", scene_index: sceneIdx, direction: -1 }),
                        sIdx === 0
                    ));

                    // [↓] 아래로 이동
                    rightHeader.appendChild(makeRowActionBtn(
                        "↓",
                        "이 씬 행을 한 칸 아래로 이동",
                        "rgba(100,116,139,0.18)",
                        "rgba(100,116,139,0.4)",
                        "#cbd5e1",
                        () => callEditTreeApi({ action: "move_scene", scene_index: sceneIdx, direction: 1 }),
                        sIdx === sessionData.scenes.length - 1
                    ));

                    // [➕ 복제 삽입] 현재 씬의 복사 노드를 바로 아래에 끼워 넣기 (파일 복사/이름 변경 없음)
                    rightHeader.appendChild(makeRowActionBtn(
                        "➕ 아래에 복제 끼워넣기",
                        "파일을 복사하거나 이름을 밀지 않고, 이 씬을 가리키는 복제 노드를 바로 다음 줄에 끼워 넣습니다.",
                        "rgba(139, 92, 246, 0.2)",
                        "rgba(139, 92, 246, 0.5)",
                        "#c4b5fd",
                        () => {
                            const activeHash = activeTakesByScene[sceneIdx];
                            const activeTakeObj = scene.takes.find(t => t.hash === activeHash) || scene.takes[scene.takes.length - 1];
                            callEditTreeApi({
                                action: "duplicate_scene",
                                scene_index: sceneIdx,
                                active_take_filename: activeTakeObj?.filename || ""
                            });
                        },
                        false
                    ));

                    // [🗑️ 행 삭제]
                    rightHeader.appendChild(makeRowActionBtn(
                        "🗑️ 행 삭제",
                        "타임라인에서 이 씬 행을 삭제합니다.",
                        "rgba(239, 68, 68, 0.16)",
                        "rgba(239, 68, 68, 0.45)",
                        "#fca5a5",
                        () => {
                            if (sessionData.scenes.length <= 1) {
                                alert("최소 1개의 씬 행은 남아 있어야 합니다.");
                                return;
                            }
                            if (!confirm(`Scene ${sceneIdx} 행을 타임라인에서 삭제하시겠습니까?`)) return;
                            callEditTreeApi({ action: "delete_scene", scene_index: sceneIdx });
                        },
                        sessionData.scenes.length <= 1
                    ));

                    rowHeader.appendChild(leftHeader);
                    rowHeader.appendChild(rightHeader);
                    rowContainer.appendChild(rowHeader);

                    const takesRow = document.createElement("div");
                    takesRow.style.cssText = `
                        display: flex;
                        flex-direction: row;
                        align-items: center;
                        gap: 10px;
                        overflow-x: auto;
                        padding-bottom: 4px;
                    `;

                    scene.takes.forEach((take, tIdx) => {
                        const defaultActiveHash = scene.activeHash || (scene.takes[scene.takes.length - 1]?.hash);
                        const isSelected = (activeTakesByScene[sceneIdx] === take.hash) || (!activeTakesByScene[sceneIdx] && take.hash === defaultActiveHash);
                        if (isSelected) activeTakesByScene[sceneIdx] = take.hash;

                        const isCurrentPlaying = (currentClickedTakeHash === take.hash);

                        const card = document.createElement("div");
                        card.className = "h3-take-card";
                        
                        let cardBg = "#23232a";
                        let cardBorder = "#374151";
                        let cardTitleColor = "#e2e8f0";

                        if (isCurrentPlaying) {
                            cardBg = "rgba(245, 158, 11, 0.25)";
                            cardBorder = "#f59e0b";
                            cardTitleColor = "#fbbf24";
                        } else if (isSelected) {
                            cardBg = "rgba(37, 99, 235, 0.2)";
                            cardBorder = "#3b82f6";
                            cardTitleColor = "#60a5fa";
                        }

                        card.style.cssText = `
                            min-width: 142px;
                            padding: 8px 10px;
                            background: ${cardBg};
                            border: 1px solid ${cardBorder};
                            border-radius: 5px;
                            cursor: pointer;
                            font-size: 11px;
                            display: flex;
                            flex-direction: column;
                            gap: 3px;
                            position: relative;
                            box-shadow: ${isCurrentPlaying ? "0 0 8px rgba(245, 158, 11, 0.35)" : "none"};
                            transition: all 0.15s ease;
                        `;

                        const resText = take.res || "864x480";
                        let mpText = "";
                        if (resText && resText.includes("x")) {
                            const [w, h] = resText.split("x").map(Number);
                            if (w && h) {
                                const mp = (w * h) / 1000000;
                                mpText = ` (${mp.toFixed(2)} MP)`;
                            }
                        }

                        const canDeleteTake = scene.takes.length > 1;
                        const isTakeFav = Boolean(take.favorite);
                        card.innerHTML = `
                            <div style="font-weight: 600; color: ${cardTitleColor}; display: flex; justify-content: space-between; align-items: center; gap: 4px;">
                                <span>${isCurrentPlaying ? '▶ ' : ''}S${sceneIdx} · ${take.hash.slice(0, 6)}</span>
                                <span style="display: flex; align-items: center; gap: 3px;">
                                    <button class="btn-fav-take" title="${isTakeFav ? '테이크 별표 해제' : '이 테이크에 별표(Favorite) 표시'}" style="padding: 0 3px; font-size: 11px; line-height: 14px; background: ${isTakeFav ? 'rgba(250,204,21,0.22)' : 'transparent'}; border: 1px solid ${isTakeFav ? 'rgba(250,204,21,0.6)' : 'rgba(100,116,139,0.35)'}; color: ${isTakeFav ? '#facc15' : '#64748b'}; border-radius: 3px; cursor: pointer;">${isTakeFav ? '★' : '☆'}</button>
                                    <span style="font-size: 9.5px; opacity: 0.8;">#${tIdx + 1}</span>
                                    ${canDeleteTake ? `<button class="btn-del-take" title="이 테이크 카드 삭제" style="padding: 0 4px; font-size: 10px; line-height: 14px; background: rgba(239,68,68,0.18); border: 1px solid rgba(239,68,68,0.4); color: #fca5a5; border-radius: 3px; cursor: pointer;">✕</button>` : ""}
                                </span>
                            </div>
                            <div style="font-size: 10px; color: #94a3b8;">${take.timeStr}</div>
                            <div class="take-res-label" style="font-size: 9.5px; color: ${isCurrentPlaying ? '#d97706' : '#64748b'};">${resText}${mpText}</div>
                        `;

                        const favTakeBtn = card.querySelector(".btn-fav-take");
                        if (favTakeBtn) {
                            favTakeBtn.onclick = (e) => {
                                e.stopPropagation();
                                const fn = take.filename || (take.filePath ? take.filePath.split("/").pop() : "");
                                if (!fn) return;
                                callEditTreeApi({
                                    action: "toggle_favorite_take",
                                    scene_index: sceneIdx,
                                    take_filename: fn
                                });
                            };
                        }

                        const delTakeBtn = card.querySelector(".btn-del-take");
                        if (delTakeBtn) {
                            delTakeBtn.onclick = (e) => {
                                e.stopPropagation();
                                const fn = take.filename || (take.filePath ? take.filePath.split("/").pop() : "");
                                if (!fn) return;
                                if (!confirm(`Scene ${sceneIdx}의 Take #${tIdx + 1} (${fn}) 노드를 삭제하시겠습니까?`)) return;
                                callEditTreeApi({
                                    action: "delete_take",
                                    scene_index: sceneIdx,
                                    take_filename: fn
                                });
                            };
                        }

                        if (take.url) {
                            const probeVideo = document.createElement("video");
                            probeVideo.preload = "metadata";
                            probeVideo.src = take.url;
                            probeVideo.onloadedmetadata = () => {
                                const vw = probeVideo.videoWidth;
                                const vh = probeVideo.videoHeight;
                                if (vw > 0 && vh > 0) {
                                    const actualRes = `${vw}x${vh}`;
                                    const actualMp = (vw * vh / 1000000).toFixed(2);
                                    take.res = actualRes;
                                    const label = card.querySelector(".take-res-label");
                                    if (label) {
                                        label.textContent = `${actualRes} (${actualMp} MP)`;
                                    }
                                }
                                probeVideo.removeAttribute("src");
                                probeVideo.load();
                            };
                        }

                        card.onclick = () => {
                            stopPlaylistMode();
                            currentViewingSceneIdx = sceneIdx;
                            activeTakesByScene[sceneIdx] = take.hash;
                            currentClickedTakeHash = take.hash;
                            renderTree(currentSessionData);
                            playVideoUrl(take.url, `S${sceneIdx} Take #${tIdx+1} (${take.hash.slice(0,6)})`, `구간: ${scene.startTime.toFixed(1)}s ~ ${(scene.startTime + scene.duration).toFixed(1)}s`);
                        };

                        takesRow.appendChild(card);
                    });

                    rowContainer.appendChild(takesRow);
                    treeContent.appendChild(rowContainer);

                    // Add vertical scene flow arrow (↓) between scenes
                    if (sIdx < sessionData.scenes.length - 1) {
                        const sceneFlowArrow = document.createElement("div");
                        sceneFlowArrow.style.cssText = `
                            display: flex;
                            align-items: center;
                            justify-content: flex-start;
                            padding-left: 20px;
                            color: #64748b;
                            font-size: 13px;
                            line-height: 1;
                            user-select: none;
                        `;
                        sceneFlowArrow.innerHTML = `<span>↓</span><span style="font-size: 10px; margin-left: 6px; opacity: 0.6;">다음 구간</span>`;
                        treeContent.appendChild(sceneFlowArrow);
                    }
                });

                // Auto-play on initial load or explicit switch
                if (autoPlay || !videoEl.src || videoEl.src === "" || videoEl.src.endsWith("#")) {
                    if (sessionData.full_url && sessionData.full_url.includes("merged")) {
                        playVideoUrl(sessionData.full_url, `🎬 최종 완성본 비디오 (${sessionData.project_name || "프로젝트"})`, "모든 청크가 무손실 연결된 완성본입니다.");
                    } else if (sessionData.scenes && sessionData.scenes.length > 0 && sessionData.scenes[0].takes && sessionData.scenes[0].takes.length > 0) {
                        const firstTake = sessionData.scenes[0].takes[0];
                        playVideoUrl(firstTake.url, `S1 Take #1 (${sessionData.project_name || "미리보기"})`, "첫 번째 컷 재생 중");
                    } else {
                        videoEl.removeAttribute("src");
                        videoEl.load();
                        const tEl = root.querySelector("#playerTitle");
                        const sEl = root.querySelector("#playerSub");
                        if (tEl) tEl.textContent = sessionData.project_name || "선택된 청크: 없음";
                        if (sEl) sEl.textContent = "생성된 청크 영상이 없습니다.";
                    }
                }
            }

            const muxBtn = root.querySelector("#btnMuxProject");
            if (muxBtn) {
                muxBtn.onclick = async () => {
                    if (!currentSessionData || !currentSessionData.scenes || currentSessionData.scenes.length === 0) return;
                    stopPlaylistMode();

                    const chunkFiles = [];
                    const chunkDurations = [];
                    const resMap = {};
                    let mismatchFound = false;
                    let firstRes = null;

                    currentSessionData.scenes.forEach(scene => {
                        if (scene.takes && scene.takes.length > 0) {
                            const activeHash = activeTakesByScene[scene.index];
                            const take = scene.takes.find(t => t.hash === activeHash) || scene.takes[scene.takes.length - 1];
                            if (take && take.filePath) {
                                chunkFiles.push(take.filePath);
                                chunkDurations.push(scene.duration || 5.0);
                                const curRes = take.res || "unknown";
                                resMap[`Scene ${scene.index}`] = curRes;
                                if (!firstRes && curRes !== "unknown") {
                                    firstRes = curRes;
                                } else if (firstRes && curRes !== "unknown" && curRes !== firstRes) {
                                    mismatchFound = true;
                                }
                            }
                        }
                    });

                    if (chunkFiles.length === 0) {
                        alert("병합할 생성 테이크 영상이 없습니다.");
                        return;
                    }

                    if (mismatchFound) {
                        const detailMsg = Object.entries(resMap).map(([s, r]) => `  • ${s}: ${r}`).join("\n");
                        alert(`⚠️ [해상도 불일치 오류]\n선택된 테이크들의 해상도가 서로 다릅니다!\nffmpeg 무손실 스트림 병합은 모든 영상의 해상도가 동일해야 합니다.\n\n각 씬의 해상도:\n${detailMsg}\n\n동일한 해상도의 테이크를 선택하거나 다시 생성해 주세요.`);
                        return;
                    }

                    const origHtml = muxBtn.innerHTML;
                    muxBtn.disabled = true;
                    muxBtn.innerHTML = `<span>⏳</span><span>무손실 병합 생성 중 (ffmpeg)...</span>`;

                    const trimTrailing = !!root.querySelector("#cbTrimTrailingFrames")?.checked;

                    try {
                        const res = await fetch("/api/h3/mux_project", {
                            method: "POST",
                            headers: { "Content-Type": "application/json" },
                            body: JSON.stringify({
                                project_name: currentSessionData.project_name,
                                chunk_files: chunkFiles,
                                chunk_durations: chunkDurations,
                                source_audio_file: currentSessionData.source_audio_file,
                                trim_trailing_frames: trimTrailing
                            })
                        });
                        const data = await res.json();
                        if (data.url) {
                            currentSessionData.full_url = data.url;
                            if (!currentSessionData.merged_history) currentSessionData.merged_history = [];
                            currentSessionData.merged_history.unshift({
                                filename: data.filename || `final_merged_${Date.now()}.mp4`,
                                url: data.url,
                                timeStr: new Date().toLocaleString(),
                                sizeMb: data.sizeMb || "-",
                                res: firstRes || "864x480",
                                isInitial: false
                            });
                            renderTree(currentSessionData);
                            muxBtn.innerHTML = `<span>✓</span><span>병합 완료! 완성본 재생 중</span>`;
                            playVideoUrl(data.url, `🎬 최종 완성본 비디오 (${currentSessionData.project_name})`, "모든 선택된 청크가 하나의 단일 MP4로 무손실 합성되었습니다.");
                        } else {
                            alert("병합 실패: " + (data.error || "알 수 없는 오류"));
                            muxBtn.innerHTML = origHtml;
                        }
                    } catch(e) {
                        console.error("[H3-Tree] Mux error:", e);
                        alert("병합 요청 중 오류가 발생했습니다: " + e);
                        muxBtn.innerHTML = origHtml;
                    } finally {
                        setTimeout(() => {
                            muxBtn.disabled = false;
                            muxBtn.innerHTML = origHtml;
                        }, 2500);
                    }
                };
            }

            const playAllBtn = root.querySelector("#btnPlayAllPath");
            if (playAllBtn) {
                playAllBtn.onclick = () => {
                    if (isPlaylistMode) {
                        stopPlaylistMode();
                        videoEl.pause();
                    } else {
                        startPlaylistMode();
                    }
                };
            }

            // Helper to get project selection widget across versions (project_selection vs project_name)
            const getProjectWidget = () => {
                return node.widgets?.find(w => w.name === "project_selection" || w.name === "project_name");
            };

            // Completely remove custom_project_name widget from node UI
            const removeCustomProjectWidget = () => {
                if (!node.widgets) return;
                const idx = node.widgets.findIndex(w => w.name === "custom_project_name");
                if (idx !== -1) {
                    node.widgets.splice(idx, 1);
                    if (node.inputs) {
                        const inIdx = node.inputs.findIndex(i => i.name === "custom_project_name");
                        if (inIdx !== -1 && !node.inputs[inIdx].link) {
                            node.removeInput?.(inIdx);
                        }
                    }
                    node.setSize?.(node.computeSize?.() || node.size);
                    app.graph?.setDirtyCanvas(true, true);
                }
            };
            removeCustomProjectWidget();

            // Function to load and render project in Studio
            const loadProjectIntoStudio = async (projName, forcePlayFirst = true) => {
                stopPlaylistMode();
                if (!projName) return;
                if (projName.startsWith("✨")) {
                    treeContent.innerHTML = `
                        <div style="color: #64748b; font-size: 13px; text-align: center; margin-top: 60px; line-height: 1.6;">
                            <span style="font-size: 26px;">✨</span><br>
                            <strong style="color: #94a3b8;">새 프로젝트 생성 대기 모드</strong><br>
                            새 비디오를 연결하고 실행(Queue)하면 새로운 프로젝트가 생성되어 여기에 표시됩니다.
                        </div>
                    `;
                    videoEl.removeAttribute("src");
                    videoEl.load();
                    const tEl = root.querySelector("#playerTitle");
                    const sEl = root.querySelector("#playerSub");
                    if (tEl) tEl.textContent = "새 프로젝트 대기 중";
                    if (sEl) sEl.textContent = "Queue Prompt를 실행하세요";
                    activeTakesByScene = {};
                    checkedRetryScenes.clear();
                    syncRetryToGenerator();
                    return;
                }

                try {
                    const treeRes = await fetch(`/api/h3/load_project?project_name=${encodeURIComponent(projName)}`);
                    const treeData = await treeRes.json();
                    if (treeRes.ok && treeData.session_tree_data && Array.isArray(treeData.session_tree_data.scenes) && treeData.session_tree_data.scenes.length > 0) {
                        activeTakesByScene = {};
                        checkedRetryScenes.clear();
                        syncRetryToGenerator();
                        renderTree(treeData.session_tree_data, forcePlayFirst);
                    } else {
                        // Fallback: check /api/h3/list_projects in case projName was deleted or renamed
                        const listRes = await fetch("/api/h3/list_projects");
                        const listData = await listRes.json();
                        if (listData.projects && listData.projects.length > 0) {
                            const fallbackName = listData.projects[0].name;
                            if (fallbackName && fallbackName !== projName) {
                                syncProjectNameToWidget(fallbackName);
                                const fbRes = await fetch(`/api/h3/load_project?project_name=${encodeURIComponent(fallbackName)}`);
                                const fbData = await fbRes.json();
                                if (fbData.session_tree_data) {
                                    activeTakesByScene = {};
                                    checkedRetryScenes.clear();
                                    syncRetryToGenerator();
                                    renderTree(fbData.session_tree_data, forcePlayFirst);
                                    return;
                                }
                            }
                        }
                        if (treeData.session_tree_data) {
                            renderTree(treeData.session_tree_data, forcePlayFirst);
                        }
                    }
                } catch(e) {
                    console.warn("[H3-Tree] Load project error:", e);
                }
            };

            // Bind callback & onWidgetChanged to guarantee project switching works in all ComfyUI frontends
            let lastObservedProject = null;

            const bindProjectWidgetCallback = () => {
                removeCustomProjectWidget();
                const projWidget = getProjectWidget();
                if (projWidget) {
                    if (!projWidget._h3Bound) {
                        projWidget._h3Bound = true;
                        const origCallback = projWidget.callback;
                        projWidget.callback = function(value) {
                            if (origCallback) origCallback.apply(this, arguments);
                            if (value && value !== lastObservedProject) {
                                lastObservedProject = value;
                                loadProjectIntoStudio(value, true);
                            }
                        };
                    }
                    if (projWidget.value) {
                        lastObservedProject = projWidget.value;
                    }
                }
            };
            bindProjectWidgetCallback();

            // LiteGraph node-level widget change hook
            const origOnWidgetChanged = node.onWidgetChanged;
            node.onWidgetChanged = function(name, value, oldValue, widget) {
                if (origOnWidgetChanged) origOnWidgetChanged.apply(this, arguments);
                if ((name === "project_selection" || name === "project_name") && value && value !== lastObservedProject) {
                    lastObservedProject = value;
                    loadProjectIntoStudio(value, true);
                }
            };

            // Active interval observer to catch changes even if ContextMenu directly assigns .value without triggering callback
            const watcherInterval = setInterval(() => {
                if (!node.graph) {
                    clearInterval(watcherInterval);
                    return;
                }
                removeCustomProjectWidget();
                const projWidget = getProjectWidget();
                if (projWidget && Array.isArray(projWidget.value)) {
                    projWidget.value = normalizeProjectName(projWidget.value);
                }
                if (projWidget && projWidget.value && projWidget.value !== lastObservedProject) {
                    const currentVal = projWidget.value;
                    lastObservedProject = currentVal;
                    loadProjectIntoStudio(currentVal, true);
                }
            }, 250);

            // Clean up interval when node is removed
            const origOnRemoved = node.onRemoved;
            node.onRemoved = function() {
                clearInterval(watcherInterval);
                return origOnRemoved ? origOnRemoved.apply(this, arguments) : undefined;
            };

            const origOnConfigure = node.onConfigure;
            node.onConfigure = function() {
                const r = origOnConfigure ? origOnConfigure.apply(this, arguments) : undefined;
                removeCustomProjectWidget();
                return r;
            };

            // Helper: sync project name into node widget
            const normalizeProjectName = (val) => {
                if (!val) return "";
                if (Array.isArray(val)) {
                    return val.length === 1 ? String(val[0]) : val.join("");
                }
                return String(val);
            };

            const syncProjectNameToWidget = (rawProjName) => {
                const projName = normalizeProjectName(rawProjName);
                if (!projName) return;
                const projWidget = getProjectWidget();
                if (projWidget) {
                    if (projWidget.options?.values && !projWidget.options.values.includes(projName)) {
                        projWidget.options.values.push(projName);
                    }
                    projWidget.value = projName;
                    lastObservedProject = projName;
                }
                app.graph?.setDirtyCanvas(true, true);
            };

            // Real-time WebSocket listener when generator completes on server!
            const onProjectUpdated = async (event) => {
                const proj = event.detail?.project_name;
                const projWidget = getProjectWidget();
                const target = proj || projWidget?.value;
                if (!target) return;
                syncProjectNameToWidget(proj);
                loadProjectIntoStudio(target, false);
            };
            api?.addEventListener?.("h3_project_updated", onProjectUpdated);
            if (app.api && app.api !== api) {
                app.api.addEventListener?.("h3_project_updated", onProjectUpdated);
            }

            const refreshBtn = root.querySelector("#btnRefreshTree");
            if (refreshBtn) {
                refreshBtn.onclick = async () => {
                    try {
                        const res = await fetch("/api/h3/list_projects");
                        const data = await res.json();
                        const projWidget = getProjectWidget();
                        if (projWidget && data.projects) {
                            const vals = ["✨ [새 프로젝트 / 자동 생성]"];
                            data.projects.forEach(p => vals.push(p.name));
                            projWidget.options = projWidget.options || {};
                            projWidget.options.values = vals;
                        }
                        const cur = projWidget?.value;
                        const validTarget = (cur && !cur.startsWith("✨") && data.projects?.some(p => p.name === cur))
                            ? cur
                            : (data.projects?.[0]?.name || cur);
                        if (validTarget) {
                            syncProjectNameToWidget(validTarget);
                            await loadProjectIntoStudio(validTarget, false);
                        }
                    } catch (err) {
                        console.warn("[H3-Tree] Refresh error:", err);
                    }
                };
            }

            node.onExecuted = function (message) {
                const actName = normalizeProjectName(message?.active_project_name || message?.ui?.active_project_name);
                if (actName) {
                    syncProjectNameToWidget(actName);
                }
                let treeData = message?.session_tree_data || message?.ui?.session_tree_data;
                if (Array.isArray(treeData)) {
                    // If ComfyUI wrapped the dict in [dict], unwrap it; if ComfyUI corrupted dict into ["project_name", ...], ignore and fetch from disk!
                    if (treeData.length > 0 && typeof treeData[0] === "object" && treeData[0] !== null) {
                        treeData = treeData[0];
                    } else {
                        treeData = null;
                    }
                }
                if (treeData && Array.isArray(treeData.scenes) && treeData.scenes.length > 0) {
                    renderTree(treeData, false);
                } else {
                    const target = actName || getProjectWidget()?.value;
                    if (target && !target.startsWith("✨")) {
                        loadProjectIntoStudio(target, false);
                    } else if (treeData) {
                        renderTree(treeData, false);
                    }
                }
            };

            // Also auto-load the latest active project on startup / node creation if default
            setTimeout(async () => {
                bindProjectWidgetCallback();
                try {
                    // Update dropdown values dynamically with server's current project list
                    const res = await fetch("/api/h3/list_projects");
                    const data = await res.json();
                    const projWidget = getProjectWidget();
                    if (projWidget && data.projects) {
                        const vals = ["✨ [새 프로젝트 / 자동 생성]"];
                        data.projects.forEach(p => vals.push(p.name));
                        projWidget.options = projWidget.options || {};
                        projWidget.options.values = vals;
                    }

                    const currentVal = projWidget?.value;
                    const existsOnServer = currentVal && data.projects?.some(p => p.name === currentVal);
                    let targetProj = (existsOnServer && !currentVal.startsWith("✨")) ? currentVal : null;
                    
                    if (!targetProj && data.projects && data.projects.length > 0) {
                        targetProj = data.projects[0].name;
                    }

                    if (targetProj) {
                        syncProjectNameToWidget(targetProj);
                        loadProjectIntoStudio(targetProj, false);
                    }
                } catch(e) {
                    console.warn("[H3-Tree] Auto-load error:", e);
                }
            }, 300);
        };
    }
});
