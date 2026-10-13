import { app } from "../../scripts/app.js";

app.registerExtension({
    name: "H3.WatermarkTools",
    async nodeCreated(node) {
        if (node.comfyClass === "H3ExtractVideoFrame") {
            const btn = node.addWidget("button", "📸 프레임 즉시 추출 (Extract Frame)", null, async () => {
                let videoName = "";
                // Search for any VHS_LoadVideo in the graph
                if (app.graph && app.graph._nodes) {
                    for (const n of app.graph._nodes) {
                        if (n.type && (n.type.includes("VHS_LoadVideo") || n.type.includes("LoadVideo"))) {
                            const widget = n.widgets?.find(w => w.name === "video");
                            if (widget && widget.value) {
                                videoName = widget.value;
                                break;
                            }
                        }
                    }
                }
                const frameIdx = node.widgets?.find(w => w.name === "frame_index")?.value || 0;
                const filenameWidget = node.widgets?.find(w => w.name === "filename");
                const outFilename = filenameWidget ? filenameWidget.value : "watermark_frame.png";

                if (!videoName) {
                    videoName = prompt("비디오 파일명을 입력하세요 (ComfyUI input 폴더 내):", "sample.mp4");
                    if (!videoName) return;
                }

                try {
                    const resp = await fetch("/api/h3/extract_video_frame", {
                        method: "POST",
                        headers: { "Content-Type": "application/json" },
                        body: JSON.stringify({
                            video_file: videoName,
                            use_seconds: false,
                            frame_index: frameIdx,
                            output_filename: outFilename
                        })
                    });
                    const res = await resp.json();
                    if (res.success) {
                        alert(`✅ 성공: [${frameIdx}번 프레임]이 [${outFilename}]으로 저장되었습니다!\n\n이제 [Load Image] 노드에서 우클릭 ➔ 'Open in MaskEditor'를 눌러 워터마크를 칠하세요.`);
                        // Auto-refresh LoadImage node if present
                        if (app.graph && app.graph._nodes) {
                            for (const n of app.graph._nodes) {
                                if (n.type === "LoadImage") {
                                    const imgW = n.widgets?.find(w => w.name === "image");
                                    if (imgW) {
                                        imgW.value = outFilename;
                                        if (imgW.callback) imgW.callback(outFilename);
                                    }
                                }
                            }
                        }
                        app.graph.setDirtyCanvas(true);
                    } else {
                        alert("❌ 프레임 추출 실패: " + (res.error || "알 수 없는 오류"));
                    }
                } catch (err) {
                    alert("❌ 서버 통신 오류: " + err.message);
                }
            });
        }
    }
});
