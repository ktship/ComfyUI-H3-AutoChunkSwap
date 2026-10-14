"""
MiniMax H3 Long Video Swap Studio Suite (Unified Project Studio Edition)
- MiniMaxH3ProjectStudio: All-in-One Manager + Reviewer + Instant Muxer
- MiniMaxH3ChunkGenerator: Autonomous GPU worker saving takes directly to disk
- Seamless REST API for multi-project browsing, renaming, and lossless ffmpeg muxing
"""

import glob
import json
import math
import os
import signal
import subprocess
import sys
import time
import hashlib
from fractions import Fraction
from pathlib import Path
import torch

try:
    if hasattr(signal, 'SIGPIPE'):
        signal.signal(signal.SIGPIPE, signal.SIG_IGN)
except Exception as e:
    print(f"[H3-Studio] Warning: Failed to set SIGPIPE ignore: {e}")

import comfy.utils
import folder_paths
import comfy_extras.nodes_video as nv
import comfy_extras.nodes_custom_sampler as ncs
import comfy_extras.nodes_minimax_h3 as nmh


def _calc_h3_frame_count(duration_sec, fps=24):
    raw_frames = max(5, round(duration_sec * fps))
    remainder = raw_frames % 17
    adjusted = raw_frames + ((5 - remainder) % 17)
    return max(22, adjusted)


def _unwrap(obj, idx=0):
    if hasattr(obj, "args") and len(obj.args) > idx:
        return obj.args[idx]
    if isinstance(obj, (tuple, list)):
        return obj[idx]
    try:
        return obj[idx]
    except Exception:
        return obj


def _format_time(seconds: float) -> str:
    if seconds < 0 or math.isinf(seconds) or math.isnan(seconds):
        return "--:--"
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    if h > 0:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


def _parse_retry_indices(retry_str: str) -> set:
    res = set()
    if not retry_str or not retry_str.strip():
        return res
    for part in retry_str.replace(";", ",").split(","):
        part = part.strip()
        if not part:
            continue
        try:
            res.add(int(part))
        except ValueError:
            pass
    return res



def _get_video_file_res(file_path: str, fallback_res: str = "864x480") -> str:
    """Reads actual video file resolution using OpenCV or fallback."""
    if not file_path or not os.path.exists(file_path):
        return fallback_res
    try:
        import cv2
        cap = cv2.VideoCapture(str(file_path))
        if cap.isOpened():
            w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            cap.release()
            if w > 0 and h > 0:
                return f"{w}x{h}"
    except Exception:
        pass
    return fallback_res

def _get_ffmpeg_path():
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return "ffmpeg"


# =========================================================================
# 0. MiniMaxH3ProjectStudio (올인원 프로젝트 매니저 & 브랜치 트리 리뷰어)
# =========================================================================
class MiniMaxH3ProjectStudio:
    """
    H3 워크플로우를 한 화면에서 완결하는 올인원 중앙 스튜디오 노드.
    - 프로젝트명 유일 결정 (새 영상 입력 시 자동 생성 / 드롭다운 선택 / 직접 수정)
    - 디스크 기반 멀티 테이크 브랜치 트리 실시간 렌더링
    - 부분 재생성 대상 줄(행) 선택 관리
    - 1클릭 즉시 무손실 완성본 병합 (ffmpeg Concat)
    """
    @classmethod
    def INPUT_TYPES(s):
        projects_root = Path(folder_paths.get_output_directory()) / "H3Swap"
        projects_root.mkdir(parents=True, exist_ok=True)
        existing_projects = ["✨ [새 프로젝트 / 자동 생성]"]
        for p in sorted(projects_root.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True):
            if p.is_dir():
                existing_projects.append(p.name)

        return {
            "required": {
                "project_name": (existing_projects, {
                    "default": existing_projects[0],
                    "tooltip": "프로젝트를 드롭다운으로 선택하거나 직접 이름을 입력합니다. '✨ [새 프로젝트]' 상태면 영상 파일명으로 자동 생성됩니다."
                }),
            },
            "optional": {
                "video": ("VIDEO", {"tooltip": "원본 비디오 연결 (연결 시 파일명을 읽어 프로젝트명을 자동 생성합니다)."}),
                "retry_chunks": ("STRING", {
                    "default": "",
                    "tooltip": "트리 화면에서 선택된 재생성 대상 행 번호들 (자동 동기화됨)."
                }),
            }
        }

    RETURN_TYPES = ("H3_PROJECT", "STRING")
    RETURN_NAMES = ("project", "retry_chunks")
    OUTPUT_NODE = True
    FUNCTION = "manage_and_review"
    CATEGORY = "video/minimax_h3"
    DESCRIPTION = "Unified H3 Project Studio - Single source of truth for project management, multi-take tree review, and 1-click muxing."

    @classmethod
    def VALIDATE_INPUTS(s, **kwargs):
        return True

    def manage_and_review(self, project_name="", video=None, retry_chunks: str = "", project_selection: str = "", custom_project_name: str = "", **kwargs):
        if isinstance(project_name, (list, tuple)):
            project_name = project_name[0] if len(project_name) == 1 else "".join(str(x) for x in project_name)
        selected_proj = str(project_name or project_selection or custom_project_name or "").strip()

        # 1. 드롭다운에서 기존 프로젝트를 선택한 경우
        if selected_proj and not selected_proj.startswith("✨"):
            final_name = selected_proj
        # 2. 새 프로젝트 / 자동 생성 모드: 원본 비디오 객체에서 파일명 추출
        elif video is not None:
            raw_file = getattr(video, "_VideoFromFile__file", None)
            if raw_file:
                final_name = Path(raw_file).stem
            else:
                final_name = f"H3_Project_{time.strftime('%Y%m%d_%H%M%S')}"
        else:
            final_name = f"H3_Project_{time.strftime('%Y%m%d_%H%M%S')}"

        final_name = "".join(c for c in final_name if c.isalnum() or c in ('_', '-', ' ', '(', ')', '[', ']')).strip()
        if not final_name:
            final_name = f"H3_Project_{time.strftime('%Y%m%d_%H%M%S')}"

        project_dir = Path(folder_paths.get_output_directory()) / "H3Swap" / final_name
        project_dir.mkdir(parents=True, exist_ok=True)
        chunks_dir = project_dir / "chunks"
        chunks_dir.mkdir(parents=True, exist_ok=True)

        # Scan disk for scenes & takes
        info_file = project_dir / "project_info.json"
        info_data = {}
        if info_file.exists():
            try:
                with open(info_file, "r", encoding="utf-8") as f:
                    info_data = json.load(f)
            except Exception:
                pass

        chunks = info_data.get("chunks", [])
        res_str = info_data.get("resolution", "864x480")

        if not chunks:
            # Scan chunk files on disk
            found_files = sorted(glob.glob(str(chunks_dir / "chunk_*_take_*.mp4")))
            seen_indices = set()
            for ff in found_files:
                parts = Path(ff).stem.split("_")
                if len(parts) >= 2:
                    try:
                        seen_indices.add(int(parts[1]))
                    except ValueError:
                        pass
            total_chunks = max(seen_indices) if seen_indices else 0
            chunks = [(i * 5.0, 5.0) for i in range(total_chunks)]

        scenes = []
        for idx, (c_start, c_dur) in enumerate(chunks):
            chunk_num = idx + 1
            pattern = str(chunks_dir / f"chunk_{chunk_num:03d}_take_*.mp4")
            take_files = sorted(glob.glob(pattern))
            valid_take_files = [f for f in take_files if os.path.exists(f) and os.path.getsize(f) > 1024]

            takes_list = []
            for t_idx, t_file in enumerate(valid_take_files):
                mtime = os.path.getmtime(t_file)
                hash_tag = hashlib.md5(f"{t_file}_{mtime}".encode()).hexdigest()[:8]
                file_time = time.strftime('%Y. %m. %d. %H:%M:%S', time.localtime(mtime))
                rel_url = f"/api/view?filename={Path(t_file).name}&subfolder=H3Swap/{final_name}/chunks&type=output"
                actual_res = _get_video_file_res(t_file, res_str)
                takes_list.append({
                    "hash": hash_tag,
                    "takeIndex": t_idx + 1,
                    "timeStr": file_time,
                    "res": actual_res,
                    "url": rel_url,
                    "filePath": t_file
                })

            orig_file = chunks_dir / f"chunk_{chunk_num:03d}_orig.mp4"
            if not orig_file.exists() and os.path.exists(str(project_dir / "source_audio.mp4")):
                try:
                    ffmpeg_bin = "/home/ktship/ComfyUI/venv/bin/ffmpeg" if os.path.exists("/home/ktship/ComfyUI/venv/bin/ffmpeg") else "ffmpeg"
                    subprocess.run([
                        ffmpeg_bin, "-y",
                        "-ss", f"{c_start:.3f}",
                        "-t", f"{c_dur:.3f}",
                        "-i", str(project_dir / "source_audio.mp4"),
                        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "18",
                        "-c:a", "aac",
                        str(orig_file)
                    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
                except Exception:
                    pass

            orig_url = f"/api/view?filename={orig_file.name}&subfolder=H3Swap/{final_name}/chunks&type=output" if orig_file.exists() else ""
            orig_res = _get_video_file_res(str(orig_file), res_str) if orig_file.exists() else res_str
            orig_info = {
                "url": orig_url,
                "startTime": c_start,
                "duration": c_dur,
                "res": orig_res,
                "exists": orig_file.exists()
            }

            scenes.append({
                "index": chunk_num,
                "startTime": c_start,
                "duration": c_dur,
                "original": orig_info,
                "takes": takes_list
            })

        source_audio_file = info_data.get("source_audio_file", str(project_dir / "source_audio.mp4"))

        # Check if merged videos exist in project merged folder and build history list
        merged_files = sorted(glob.glob(str(project_dir / "merged" / "*.mp4")), key=os.path.getmtime)
        merged_history = []
        for mf in reversed(merged_files):
            p = Path(mf)
            mtime = os.path.getmtime(mf)
            mtime_str = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(mtime))
            f_size_mb = os.path.getsize(mf) / (1024 * 1024)
            m_res = _get_video_file_res(str(p), res_str)
            merged_history.append({
                "filename": p.name,
                "url": f"/api/view?filename={p.name}&subfolder=H3Swap/{final_name}/merged&type=output",
                "timeStr": mtime_str,
                "sizeMb": round(f_size_mb, 1),
                "res": m_res,
                "isInitial": "initial" in p.name
            })

        if merged_files:
            latest_merged_file = Path(merged_files[-1])
            full_video_url = f"/api/view?filename={latest_merged_file.name}&subfolder=H3Swap/{final_name}/merged&type=output"
        else:
            full_video_url = scenes[0]["takes"][-1]["url"] if (scenes and scenes[0]["takes"]) else ""

        session_tree_data = {
            "project_name": final_name,
            "project_dir": str(project_dir),
            "source_audio_file": source_audio_file,
            "scenes": scenes,
            "full_url": full_video_url,
            "merged_history": merged_history
        }

        project_payload = {
            "project_name": final_name,
            "project_dir": str(project_dir),
            "retry_chunks": retry_chunks,
            "video": video
        }

        print(f"\n[H3-ProjectStudio] 👑 Active Project: '{final_name}' (Total scenes: {len(scenes)})")
        print(f"[H3-ProjectStudio] 📂 Storage: {project_dir}")

        return {"ui": {"session_tree_data": session_tree_data, "active_project_name": [final_name]}, "result": (project_payload, retry_chunks)}


# =========================================================================
# 1. MiniMaxH3VideoChunker (영상 스마트 자동 분할기 - 메타데이터 지문 캐싱)
# =========================================================================
class MiniMaxH3VideoChunker:
    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "video": ("VIDEO", {"tooltip": "Source input video of any length."}),
                "chunk_duration": ("FLOAT", {
                    "default": 5.0,
                    "min": 1.0,
                    "max": 60.0,
                    "step": 0.5,
                    "tooltip": "Target duration for each chunk (Recommended: 4.0 ~ 5.0s)."
                }),
            }
        }

    RETURN_TYPES = ("H3_CHUNKS_DATA",)
    RETURN_NAMES = ("chunks_data",)
    FUNCTION = "split"
    CATEGORY = "video/minimax_h3"
    DESCRIPTION = "Divides input video into temporal chunk intervals with metadata fingerprint caching."

    def split(self, video, chunk_duration: float = 5.0):
        total_duration = video.get_duration()
        fps = video.get_frame_rate()
        dims = video.get_dimensions()
        frame_cnt = video.get_frame_count()

        raw_fingerprint = f"{dims[0]}x{dims[1]}_{total_duration:.3f}_{fps:.2f}_{frame_cnt}_{chunk_duration:.2f}"
        video_fingerprint = hashlib.md5(raw_fingerprint.encode("utf-8")).hexdigest()[:12]

        # 최소 유효 청크 길이 (1초 미만의 극소 잔여 시간은 독립 청크로 만들지 않고 직전 청크에 흡수)
        MIN_CHUNK_DUR = 1.0

        chunks = []
        curr_t = 0.0
        while curr_t < total_duration:
            rem = total_duration - curr_t
            if rem <= chunk_duration:
                if rem < MIN_CHUNK_DUR and chunks:
                    prev_start, _ = chunks[-1]
                    chunks[-1] = (prev_start, total_duration - prev_start)
                else:
                    chunks.append((curr_t, rem))
                break
            else:
                next_rem = rem - chunk_duration
                if 0 < next_rem < MIN_CHUNK_DUR:
                    chunks.append((curr_t, rem))
                    break
                else:
                    chunks.append((curr_t, chunk_duration))
                    curr_t += chunk_duration

        total_chunks = len(chunks)
        print(f"\n[H3-Chunker] Video ({total_duration:.2f}s, {dims[0]}x{dims[1]}, {fps:.2f}fps) -> {total_chunks} chunks ({chunk_duration}s target).")
        print(f"[H3-Chunker] Video Fingerprint: {video_fingerprint}")

        chunks_data = {
            "video": video,
            "video_fingerprint": video_fingerprint,
            "total_duration": total_duration,
            "chunk_duration": chunk_duration,
            "chunks": chunks,
            "total_chunks": total_chunks,
        }
        return (chunks_data,)


# =========================================================================
# 2. MiniMaxH3OriginalChunkViewer (쪼개진 5초 원본 비디오 전용 뷰어)
# =========================================================================
class MiniMaxH3OriginalChunkViewer:
    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "chunks_data": ("H3_CHUNKS_DATA", {"tooltip": "Chunks data from MiniMax H3 Video Chunker."}),
                "chunk_index": ("INT", {
                    "default": 1,
                    "min": 1,
                    "max": 9999,
                    "step": 1,
                    "tooltip": "확인할 원본 청크 번호 (1부터 시작)."
                }),
            }
        }

    RETURN_TYPES = ("VIDEO",)
    RETURN_NAMES = ("original_chunk_video",)
    FUNCTION = "view_chunk"
    CATEGORY = "video/minimax_h3"
    DESCRIPTION = "Extracts and displays a specific original 5-second slice directly."

    def view_chunk(self, chunks_data, chunk_index: int = 1):
        video = chunks_data["video"]
        chunks = chunks_data["chunks"]
        total_chunks = chunks_data["total_chunks"]

        target_idx = max(1, min(chunk_index, total_chunks)) - 1
        c_start, c_dur = chunks[target_idx]

        print(f"\n[H3-OriginalViewer] Previewing Chunk #{target_idx + 1}/{total_chunks} (Offset: {c_start:.2f}s ~ {c_start + c_dur:.2f}s)")
        chunk_slice = video.as_trimmed(start_time=c_start, duration=c_dur)
        return (chunk_slice,)


# =========================================================================
# 3. MiniMaxH3ChunkGenerator (자율 GPU 작업 엔진)
# =========================================================================
class MiniMaxH3ChunkGenerator:
    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "project": ("H3_PROJECT", {"tooltip": "MiniMax H3 Project Studio에서 전달받은 프로젝트 연결."}),
                "chunks_data": ("H3_CHUNKS_DATA", {"tooltip": "Chunks data from MiniMax H3 Video Chunker."}),
                "replacement_character": ("IMAGE", {"tooltip": "Reference character image (<Picture 1>)."}),
                "model": ("MODEL", {"tooltip": "Loaded H3 Model with Character Swap LoRA applied."}),
                "clip": ("CLIP", {"tooltip": "Loaded Qwen3-VL text encoder."}),
                "vae": ("VAE", {"tooltip": "Loaded H3 Video VAE."}),
                "audio_vae": ("VAE", {"tooltip": "Loaded H3 Audio VAE."}),
                "sampler": ("SAMPLER", {"tooltip": "KSamplerSelect sampler."}),
                "sigmas": ("SIGMAS", {"tooltip": "BasicScheduler sigmas."}),
                "prompt": ("STRING", {
                    "multiline": True,
                    "default": (
                        "Replace only the woman in the foreground in <Video 1> with the character in <Picture 1>. "
                        "Keep the replacement character's identity, and art style from <Picture 1>. "
                        "Preserve the source video's camera, framing, background, lighting, objects, and all other people. "
                        "Match the selected woman's position, scale, pose, topless and movement throughout the clip. "
                        "Do not show the reference sheet or its background."
                    ),
                    "tooltip": "Swap prompt describing the character replacement."
                }),
                "seed": ("INT", {"default": 42, "min": 0, "max": 0xffffffffffffffff}),
            },
            "optional": {
                "width": ("INT", {"default": 864, "min": 256, "max": 2048, "step": 32, "forceInput": True}),
                "height": ("INT", {"default": 480, "min": 256, "max": 2048, "step": 32, "forceInput": True}),
                "retry_chunks": ("STRING", {"default": "", "tooltip": "Row/Chunk indices to regenerate (Studio에서 자동 전달됨)."}),
            }
        }

    RETURN_TYPES = ("H3_CHUNK_SESSION", "VIDEO")
    RETURN_NAMES = ("chunk_session", "initial_merged_video")
    OUTPUT_NODE = True
    FUNCTION = "generate"
    CATEGORY = "video/minimax_h3"
    DESCRIPTION = "Autonomous H3 generator saving takes directly to project disk storage."

    def generate(
        self,
        project,
        chunks_data,
        replacement_character,
        model,
        clip,
        vae,
        audio_vae,
        sampler,
        sigmas,
        prompt: str,
        seed: int = 42,
        width: int = 864,
        height: int = 480,
        retry_chunks: str = ""
    ):
        video = chunks_data["video"]
        video_fingerprint = chunks_data.get("video_fingerprint", "default_video")
        total_duration = chunks_data["total_duration"]
        chunk_duration = chunks_data["chunk_duration"]
        chunks = chunks_data["chunks"]
        total_chunks = chunks_data["total_chunks"]

        clean_name = project["project_name"]
        output_dir = Path(project["project_dir"])
        chunks_dir = output_dir / "chunks"
        chunks_dir.mkdir(parents=True, exist_ok=True)

        # Fallback to project's retry_chunks if widget is empty
        effective_retry = retry_chunks if retry_chunks.strip() else project.get("retry_chunks", "")
        retry_set = _parse_retry_indices(effective_retry)

        print("\n========================================================")
        print(f"[H3-Generator] 📁 Active Project: {clean_name}")
        print(f"[H3-Generator] 📂 Directory: {output_dir}")

        def get_existing_takes(chunk_idx):
            pattern = str(chunks_dir / f"chunk_{chunk_idx:03d}_take_*.mp4")
            files = sorted(glob.glob(pattern))
            valid_files = [f for f in files if os.path.exists(f) and os.path.getsize(f) > 1024]
            return valid_files

        if retry_set:
            has_any_base = False
            for idx in range(1, total_chunks + 1):
                if len(get_existing_takes(idx)) > 0:
                    has_any_base = True
                    break

            if not has_any_base:
                err_msg = (
                    f"⚠️ [H3-Generator 에러] 재생성 대상 ({sorted(list(retry_set))})이 지정되었으나, "
                    f"프로젝트 '{clean_name}'에 생성된 기존 베이스 테이크가 없습니다!\n"
                    f"먼저 재생성 번호를 비우고 전체 생성을 1회 완료해 주세요."
                )
                print(f"[H3-Generator] {err_msg}")
                raise RuntimeError(err_msg)

            print(f"[H3-Generator] 🎯 [선택적 부분 재생성] 대상 행: {sorted(list(retry_set))} 번호만 GPU 실행!")
        else:
            print(f"[H3-Generator] 🚀 [전체 생성 모드] 1~{total_chunks}번 전체 행 신규 테이크 생성 시작!")

        print("========================================================")

        steps_per_chunk = max(1, len(sigmas) - 1 if hasattr(sigmas, "__len__") else 4)
        # 모델 로딩 및 VAE/CLIP 인제스트 준비 구간을 위해 시작 버퍼(2단계)를 전체 프로그레스에 할당
        model_prep_steps = 2
        total_global_steps = model_prep_steps + (total_chunks * steps_per_chunk)
        global_pbar = comfy.utils.ProgressBar(total_global_steps)

        overall_start_time = time.time()
        print(f"[H3-Generator] ⏳ H3 모델 가중치 및 VAE/CLIP 인코더 준비 중...")
        global_pbar.update_absolute(1, total_global_steps)

        for idx, (c_start, c_dur) in enumerate(chunks):
            chunk_num = idx + 1
            existing = get_existing_takes(chunk_num)
            base_step_offset = model_prep_steps + (idx * steps_per_chunk)

            if retry_set:
                if chunk_num not in retry_set:
                    global_pbar.update_absolute(base_step_offset + steps_per_chunk, total_global_steps)
                    continue
                else:
                    new_take_idx = len(existing) + 1
                    target_file = chunks_dir / f"chunk_{chunk_num:03d}_take_{new_take_idx:02d}.mp4"
            else:
                new_take_idx = len(existing) + 1
                target_file = chunks_dir / f"chunk_{chunk_num:03d}_take_{new_take_idx:02d}.mp4"

            if c_dur < 0.5:
                print(f"\n[H3-Generator] ⚠️ 청크 {chunk_num}/{total_chunks}의 길이({c_dur:.3f}초)가 너무 짧아(0.5초 미만) 건너뜁니다.")
                global_pbar.update_absolute(base_step_offset + steps_per_chunk, total_global_steps)
                continue

            print(f"\n[H3-Generator] >>> Generating Chunk {chunk_num}/{total_chunks} (Take {new_take_idx}) [Start: {c_start:.2f}s, Dur: {c_dur:.2f}s] <<<")
            chunk_start_time = time.time()

            chunk_slice = video.as_trimmed(start_time=c_start, duration=c_dur, strict_duration=False)
            chunk_images = chunk_slice.get_components().images
            calc_len = _calc_h3_frame_count(c_dur, fps=24)

            # MiniMax H3 Reference-to-Video conditioning
            ref_vids = {"ref_video_0": chunk_images}
            cond_output = nmh.MiniMaxH3ReferenceToVideo.execute(
                clip=clip,
                prompt=prompt,
                width=width,
                height=height,
                length=calc_len,
                ref_image_size="match",
                vae=vae,
                audio_vae=audio_vae,
                ref_images={"ref_image_0": replacement_character},
                ref_videos=ref_vids,
                ref_video_audios=None,
                ref_audios=None
            )
            cond = _unwrap(cond_output, 0)
            latent = _unwrap(cond_output, 1)

            # Guider & Noise
            guider_out = ncs.BasicGuider.execute(model=model, conditioning=cond)
            guider = _unwrap(guider_out, 0)

            chunk_seed = (seed + chunk_num * 1000 + new_take_idx) & 0xffffffffffffffff
            noise_out = ncs.RandomNoise.execute(noise_seed=chunk_seed)
            noise = _unwrap(noise_out, 0)

            # Custom Sampling step with smooth real-time step callback
            latent_in = latent
            latent_samples_in = latent_in["samples"]
            latent_in = latent_in.copy()
            latent_samples_in = comfy.sample.fix_empty_latent_channels(
                guider.model_patcher, latent_samples_in,
                latent_in.get("downscale_ratio_spacial", None),
                latent_in.get("downscale_ratio_temporal", None)
            )
            latent_in["samples"] = latent_samples_in

            x0_output = {}
            steps_in_chunk = max(1, sigmas.shape[-1] - 1) if hasattr(sigmas, "shape") else 4

            def realtime_step_callback(step, x0, x, total_steps):
                current_global_step = base_step_offset + step + 1
                global_pbar.update_absolute(current_global_step, total_global_steps)
                elapsed_so_far = time.time() - overall_start_time
                done_ratio = max(0.001, current_global_step / float(total_global_steps))
                est_total = elapsed_so_far / done_ratio
                remain = max(0.0, est_total - elapsed_so_far)
                print(f"\r  * [청크 {chunk_num}/{total_chunks}] 디노이징 스텝 {step+1}/{total_steps} (총 {current_global_step}/{total_global_steps}) | 경과: {_format_time(elapsed_so_far)} | 남은 시간: {_format_time(remain)}", end="", flush=True)

            samples_tensor = guider.sample(
                noise.generate_noise(latent_in),
                latent_samples_in,
                sampler,
                sigmas,
                denoise_mask=latent_in.get("noise_mask", None),
                callback=realtime_step_callback,
                disable_pbar=False,
                seed=noise.seed
            )
            samples_tensor = samples_tensor.to(comfy.model_management.intermediate_device())
            print()

            samples = {"samples": samples_tensor}

            # VAE Decode Video
            latent_samples = samples["samples"]
            if getattr(latent_samples, "is_nested", False):
                latent_samples = latent_samples.unbind()[0]
            decoded_images = vae.decode(latent_samples)
            if len(decoded_images.shape) == 5:
                decoded_images = decoded_images.reshape(-1, decoded_images.shape[-3], decoded_images.shape[-2], decoded_images.shape[-1])

            # Output video chunk packaging
            chunk_video_out = nv.CreateVideo.execute(
                images=decoded_images,
                fps=24.0,
                audio=chunk_slice.get_components().audio,
                codec="h264"
            )
            chunk_video = _unwrap(chunk_video_out, 0)

            if target_file.exists():
                target_file.unlink()
            chunk_video.save_to(str(target_file))

            chunk_cost = time.time() - chunk_start_time
            print(f"[H3-Generator] ✓ Chunk {chunk_num} (Take {new_take_idx}) saved: {target_file.name} ({chunk_cost:.2f}s)")
            global_pbar.update_absolute(base_step_offset + steps_per_chunk, total_global_steps)

            # [메모리 최적화] 거대 비디오 프레임/텐서 및 임베딩 객체 즉시 해제하여 RAM 누적 방지
            try:
                del chunk_slice, chunk_images, ref_vids, cond_output, cond, latent
                del guider_out, guider, noise_out, noise, samples_tensor, samples
                del decoded_images, chunk_video_out, chunk_video
            except Exception:
                pass
            import gc
            gc.collect()
            comfy.model_management.soft_empty_cache()

        # Save source audio for instant muxing
        source_audio_path = output_dir / "source_audio.mp4"
        if not source_audio_path.exists():
            try:
                video.save_to(str(source_audio_path))
            except Exception as e:
                print(f"[H3-Generator] Note saving source audio: {e}")

        # Automatically slice and cache original chunks for tree review
        if source_audio_path.exists():
            ffmpeg_bin = "/home/ktship/ComfyUI/venv/bin/ffmpeg" if os.path.exists("/home/ktship/ComfyUI/venv/bin/ffmpeg") else "ffmpeg"
            for c_i, (c_s, c_d) in enumerate(chunks):
                orig_file = chunks_dir / f"chunk_{c_i+1:03d}_orig.mp4"
                if not orig_file.exists():
                    try:
                        subprocess.run([
                            ffmpeg_bin, "-y",
                            "-ss", f"{c_s:.3f}",
                            "-t", f"{c_d:.3f}",
                            "-i", str(source_audio_path),
                            "-c", "copy",
                            str(orig_file)
                        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5)
                    except Exception:
                        pass

        final_files_list = []
        for idx in range(1, total_chunks + 1):
            ex = get_existing_takes(idx)
            final_files_list.append(ex[-1] if ex else "")

        manifest_path = output_dir / "project_info.json"
        manifest_data = {
            "project_name": clean_name,
            "total_chunks": total_chunks,
            "chunk_duration": chunk_duration,
            "total_duration": total_duration,
            "prompt": prompt,
            "resolution": f"{width}x{height}",
            "video_fingerprint": video_fingerprint,
            "chunks": chunks,
            "source_audio_file": str(source_audio_path)
        }
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(manifest_data, f, indent=2, ensure_ascii=False)

        session_payload = {
            "project_name": clean_name,
            "project_dir": str(output_dir),
            "video": video,
            "total_chunks": total_chunks,
            "chunks": chunks,
            "chunk_files": final_files_list,
            "resolution": f"{width}x{height}",
            "source_audio_file": str(source_audio_path)
        }

        # =========================================================
        # 최초 전체 생성이 완료되면 ffmpeg 무손실 직접 병합 (RAM 소모 0MB)
        # =========================================================
        merged_video = None
        try:
            valid_paths = [p for p in final_files_list if p and os.path.exists(p) and os.path.getsize(p) > 1024]
            if len(valid_paths) == total_chunks:
                print(f"[H3-Generator] 🎬 최초 전체 생성 완료 -> ffmpeg 무손실 직접 병합 중 ({total_chunks}개 컷, RAM 소모 0MB)...")
                auto_merged_file = output_dir / "merged" / f"initial_full_merged_{time.strftime('%Y%m%d_%H%M%S')}.mp4"
                auto_merged_file.parent.mkdir(parents=True, exist_ok=True)

                concat_list_file = output_dir / "merged" / f"_concat_{int(time.time())}.txt"
                with open(concat_list_file, "w", encoding="utf-8") as f_cl:
                    for vp in valid_paths:
                        f_cl.write(f"file '{vp}'\n")

                ffmpeg_bin = "/home/ktship/ComfyUI/venv/bin/ffmpeg" if os.path.exists("/home/ktship/ComfyUI/venv/bin/ffmpeg") else "ffmpeg"
                res = subprocess.run([
                    ffmpeg_bin, "-y",
                    "-f", "concat",
                    "-safe", "0",
                    "-i", str(concat_list_file),
                    "-c", "copy",
                    str(auto_merged_file)
                ], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True, timeout=30)

                try:
                    concat_list_file.unlink()
                except Exception:
                    pass

                if auto_merged_file.exists() and auto_merged_file.stat().st_size > 1024:
                    print(f"[H3-Generator] ✓ 최초 완성본 무손실 직접 저장 완료: {auto_merged_file.name}")
                    merged_video = nv.InputImpl.VideoFromFile(str(auto_merged_file))
                else:
                    print(f"[H3-Generator] Note: fallback to first chunk after ffmpeg concat: {res.stderr[:150] if res else ''}")
                    merged_video = nv.InputImpl.VideoFromFile(valid_paths[0])
            else:
                if valid_paths:
                    merged_video = nv.InputImpl.VideoFromFile(valid_paths[0])
                else:
                    merged_video = video
        except Exception as e:
            print(f"[H3-Generator] Note on auto-mux: {e}")
            merged_video = video

        # Notify frontend via PromptServer websocket event
        try:
            from server import PromptServer
            if hasattr(PromptServer, "instance") and PromptServer.instance:
                PromptServer.instance.send_sync("h3_project_updated", {
                    "project_name": clean_name
                })
                print(f"[H3-Generator] 📡 Sent real-time tree update signal to UI for project: {clean_name}")
        except Exception as e:
            print(f"[H3-Generator] Note on websocket notify: {e}")

        print("\n========================================================")
        print(f"[H3-Generator] ✓ Generation complete! Project '{clean_name}' updated on disk.")
        print("========================================================\n")

        return (session_payload, merged_video)



class H3RepeatMaskForVideo:
    """Repeats a single drawn mask across all frames of a video batch."""
    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "image": ("IMAGE",),
                "mask": ("MASK",),
            }
        }

    RETURN_TYPES = ("MASK",)
    RETURN_NAMES = ("mask",)
    FUNCTION = "repeat_mask"
    CATEGORY = "mask/watermark"

    def repeat_mask(self, image, mask):
        import torch.nn.functional as F
        num_frames = image.shape[0]
        H, W = image.shape[1], image.shape[2]
        if len(mask.shape) == 2:
            single_mask = mask.unsqueeze(0)
        else:
            single_mask = mask[0:1]
        if single_mask.shape[1] != H or single_mask.shape[2] != W:
            print(f'[H3RepeatMask] Auto-resizing mask from ({single_mask.shape[1]},{single_mask.shape[2]}) to match image ({H},{W})')
            single_mask = F.interpolate(single_mask.unsqueeze(1), size=(H, W), mode='nearest').squeeze(1)
        repeated_mask = single_mask.repeat(num_frames, 1, 1)
        return (repeated_mask,)
class H3WatermarkRectMask:
    """Generate a clean rectangular mask for watermark removal."""
    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "image": ("IMAGE",),
                "x": ("INT", {"default": 20, "min": 0, "max": 4096, "step": 1}),
                "y": ("INT", {"default": 20, "min": 0, "max": 4096, "step": 1}),
                "width": ("INT", {"default": 180, "min": 1, "max": 4096, "step": 1}),
                "height": ("INT", {"default": 60, "min": 1, "max": 4096, "step": 1}),
            }
        }

    RETURN_TYPES = ("MASK",)
    RETURN_NAMES = ("mask",)
    FUNCTION = "generate_mask"
    CATEGORY = "mask/watermark"

    def generate_mask(self, image, x, y, width, height):
        b, h, w, c = image.shape
        mask = torch.zeros((b, h, w), dtype=torch.float32)
        x2 = min(w, x + width)
        y2 = min(h, y + height)
        x1 = max(0, x)
        y1 = max(0, y)
        if x2 > x1 and y2 > y1:
            mask[:, y1:y2, x1:x2] = 1.0
        return (mask,)



class H3ExtractVideoFrame:
    """Extract a single frame from video frames and save to input directory for Mask Editor."""
    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "images": ("IMAGE",),
                "frame_index": ("INT", {"default": 0, "min": 0, "max": 999999, "step": 1}),
                "filename": ("STRING", {"default": "watermark_frame.png"}),
            }
        }

    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("frame_image",)
    OUTPUT_NODE = True
    FUNCTION = "extract_frame"
    CATEGORY = "mask/watermark"

    def extract_frame(self, images, frame_index, filename):
        import numpy as np
        from PIL import Image
        num_frames = images.shape[0]
        idx = max(0, min(frame_index, num_frames - 1))
        single_frame = images[idx:idx+1]

        input_dir = folder_paths.get_input_directory()
        out_path = os.path.join(input_dir, filename)

        frame_np = (single_frame[0].cpu().numpy() * 255.0).clip(0, 255).astype(np.uint8)
        pil_img = Image.fromarray(frame_np)
        pil_img.save(out_path, format="PNG")
        print(f"[H3ExtractVideoFrame] Saved frame {idx}/{num_frames} to {out_path}")

        temp_dir = folder_paths.get_temp_directory()
        ts = int(time.time() * 1000)
        temp_filename = f"extracted_frame_{ts}.png"
        pil_img.save(os.path.join(temp_dir, temp_filename), format="PNG")

        return {
            "ui": {"images": [{"filename": temp_filename, "subfolder": "", "type": "temp"}]},
            "result": (single_frame,)
        }

import torch
import torch.nn.functional as F
import numpy as np

class H3VideoCropWatermark:
    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "image": ("IMAGE",),
                "mask": ("MASK",),
                "padding": ("INT", {"default": 64, "min": 0, "max": 512, "step": 8}),
            }
        }

    RETURN_TYPES = ("IMAGE", "MASK", "H3_CROP_DATA")
    RETURN_NAMES = ("cropped_image", "cropped_mask", "crop_data")
    FUNCTION = "crop"
    CATEGORY = "MiniMax_H3/Watermark"

    def crop(self, image, mask, padding):
        import torch.nn.functional as F
        B, H, W, C = image.shape
        if mask.dim() == 2:
            mask = mask.unsqueeze(0)
        if mask.shape[1] != H or mask.shape[2] != W:
            print(f'[H3Crop] Auto-resizing mask ({mask.shape[1]}x{mask.shape[2]}) to image ({H}x{W})')
            mask = F.interpolate(mask.unsqueeze(1), size=(H, W), mode='nearest').squeeze(1)
        if mask.shape[0] != B:
            mask = mask.repeat(B, 1, 1) if mask.shape[0] == 1 else mask[:B]
        combined_mask = (mask > 0.05).any(dim=0).float() # [H, W]
        nz = torch.nonzero(combined_mask)

        if len(nz) == 0:
            print("[H3Crop] Warning: Mask is empty. Returning full image.")
            crop_data = {"y1": 0, "y2": H, "x1": 0, "x2": W, "orig_h": H, "orig_w": W}
            return (image, mask, crop_data)

        y_min = int(nz[:, 0].min().item())
        y_max = int(nz[:, 0].max().item())
        x_min = int(nz[:, 1].min().item())
        x_max = int(nz[:, 1].max().item())

        y1 = max(0, y_min - padding)
        y2 = min(H, y_max + padding)
        x1 = max(0, x_min - padding)
        x2 = min(W, x_max + padding)

        # Snap width and height to multiples of 8 (for ProPainter / optical flow compatibility)
        crop_w = x2 - x1
        crop_h = y2 - y1

        rem_w = crop_w % 8
        if rem_w != 0:
            add_w = 8 - rem_w
            if x2 + add_w <= W:
                x2 += add_w
            elif x1 - add_w >= 0:
                x1 -= add_w
            else:
                x2 = min(W, x2 + add_w)
                crop_w = x2 - x1
                x1 = max(0, x2 - (crop_w // 8) * 8)

        rem_h = crop_h % 8
        if rem_h != 0:
            add_h = 8 - rem_h
            if y2 + add_h <= H:
                y2 += add_h
            elif y1 - add_h >= 0:
                y1 -= add_h
            else:
                y2 = min(H, y2 + add_h)
                crop_h = y2 - y1
                y1 = max(0, y2 - (crop_h // 8) * 8)

        print(f"[H3Crop] Watermark box: ({x_min},{y_min})-({x_max},{y_max}) -> 1:1 Natural Crop: ({x1},{y1})-({x2},{y2}) [{x2-x1}x{y2-y1}]")

        cropped_image = image[:, y1:y2, x1:x2, :]
        cropped_mask = mask[:, y1:y2, x1:x2]
        if cropped_mask.shape[1] != cropped_image.shape[1] or cropped_mask.shape[2] != cropped_image.shape[2]:
            cropped_mask = F.interpolate(cropped_mask.unsqueeze(1), size=(cropped_image.shape[1], cropped_image.shape[2]), mode='nearest').squeeze(1)

        crop_data = {
            "y1": y1,
            "y2": y2,
            "x1": x1,
            "x2": x2,
            "orig_h": H,
            "orig_w": W
        }
        return (cropped_image, cropped_mask, crop_data)


class H3VideoStitchWatermark:
    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "original_image": ("IMAGE",),
                "inpainted_image": ("IMAGE",),
                "crop_data": ("H3_CROP_DATA",),
                "feather_radius": ("INT", {"default": 16, "min": 0, "max": 128, "step": 2}),
            }
        }

    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("image",)
    FUNCTION = "stitch"
    CATEGORY = "MiniMax_H3/Watermark"

    def stitch(self, original_image, inpainted_image, crop_data, feather_radius):
        # original_image: [B, H, W, C]
        # inpainted_image: [B, ch, cw, C]
        y1 = crop_data["y1"]
        y2 = crop_data["y2"]
        x1 = crop_data["x1"]
        x2 = crop_data["x2"]
        orig_h = crop_data["orig_h"]
        orig_w = crop_data["orig_w"]

        out_image = original_image.clone()
        B, H, W, C = out_image.shape
        ch = y2 - y1
        cw = x2 - x1

        # Check if inpainted image size matches crop exactly
        inpaint_b, inpaint_h, inpaint_w, _ = inpainted_image.shape
        if inpaint_h != ch or inpaint_w != cw:
            # If slightly resized by downstream node, resize back to exact crop box
            print(f"[H3Stitch] Warning: Size mismatch ({inpaint_w}x{inpaint_h} vs {cw}x{ch}). Resizing back to 1:1 crop size.")
            inpainted_image = inpainted_image.permute(0, 3, 1, 2)
            inpainted_image = F.interpolate(inpainted_image, size=(ch, cw), mode="bilinear", align_corners=False)
            inpainted_image = inpainted_image.permute(0, 2, 3, 1)

        # Match batch sizes
        if inpaint_b < B:
            print(f"[H3Stitch] Warning: Inpainted batch {inpaint_b} < Original batch {B}. Repeating frames.")
            inpainted_image = inpainted_image.repeat((B + inpaint_b - 1) // inpaint_b, 1, 1, 1)[:B]

        if feather_radius <= 0:
            out_image[:, y1:y2, x1:x2, :] = inpainted_image[:B]
        else:
            # Smart boundary feathering:
            # Do NOT feather on the outer screen edges (y1=0, y2=H, x1=0, x2=W)
            # because feathering on screen edges causes watermarks stuck to the borders to leak back!
            at_top = (y1 <= 0)
            at_bottom = (y2 >= H)
            at_left = (x1 <= 0)
            at_right = (x2 >= W)

            fy = torch.ones(ch, device=out_image.device, dtype=out_image.dtype)
            fx = torch.ones(cw, device=out_image.device, dtype=out_image.dtype)

            r = min(feather_radius, ch // 2, cw // 2)
            if r > 0:
                ramp = torch.linspace(0.0, 1.0, r, device=out_image.device, dtype=out_image.dtype)
                if not at_top:
                    fy[:r] = ramp
                if not at_bottom:
                    fy[-r:] = torch.flip(ramp, dims=[0])
                if not at_left:
                    fx[:r] = ramp
                if not at_right:
                    fx[-r:] = torch.flip(ramp, dims=[0])

            # Outer product to create 2D mask [ch, cw, 1]
            feather_mask = (fy.unsqueeze(1) * fx.unsqueeze(0)).unsqueeze(-1) # [ch, cw, 1]
            feather_mask = feather_mask.unsqueeze(0) # [1, ch, cw, 1]

            orig_crop = out_image[:, y1:y2, x1:x2, :]
            inpaint_crop = inpainted_image[:B]
            stitched_crop = orig_crop * (1.0 - feather_mask) + inpaint_crop * feather_mask

            out_image[:, y1:y2, x1:x2, :] = stitched_crop

        print(f"[H3Stitch] ✓ Successfully stitched back into original frame with feather={feather_radius}px.")
        return (out_image,)


NODE_CLASS_MAPPINGS = {
    "H3VideoCropWatermark": H3VideoCropWatermark,
    "H3VideoStitchWatermark": H3VideoStitchWatermark,
    "MiniMaxH3ProjectStudio": MiniMaxH3ProjectStudio,
    "MiniMaxH3VideoChunker": MiniMaxH3VideoChunker,
    "MiniMaxH3OriginalChunkViewer": MiniMaxH3OriginalChunkViewer,
    "MiniMaxH3ChunkGenerator": MiniMaxH3ChunkGenerator,
    "H3WatermarkRectMask": H3WatermarkRectMask,
    "H3RepeatMaskForVideo": H3RepeatMaskForVideo,
    "H3ExtractVideoFrame": H3ExtractVideoFrame,
    "MiniMaxH3ChunkTreeReviewer": MiniMaxH3ProjectStudio, # Alias for backwards compatibility
    "MiniMaxH3ProjectManager": MiniMaxH3ProjectStudio,    # Alias for backwards compatibility
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "H3VideoCropWatermark": "✂️ H3 워터마크 영역 1:1 고속 크롭 (Crop)",
    "H3VideoStitchWatermark": "🩹 H3 워터마크 영역 페더링 복원 합성 (Stitch)",
    "MiniMaxH3ProjectStudio": "0. MiniMax H3 Project Studio (통합 매니저 & 브랜치 트리 리뷰어)",
    "MiniMaxH3VideoChunker": "1-A. MiniMax H3 Video Chunker",
    "MiniMaxH3OriginalChunkViewer": "1-B. MiniMax H3 Original Chunk Viewer",
    "MiniMaxH3ChunkGenerator": "2. MiniMax H3 Chunk Generator",
    "MiniMaxH3ChunkTreeReviewer": "3. MiniMax H3 Chunk Tree Reviewer (Legacy)",
    "MiniMaxH3ProjectManager": "0. MiniMax H3 Project Manager (Legacy)",
    "H3ExtractVideoFrame": "📸 H3 영상 프레임 추출기 (Frame Extractor for Mask)",
    "H3RepeatMaskForVideo": "🔄 H3 단일 마스크 ➔ 전체 비디오 확장기",
}

WEB_DIRECTORY = "./web"


# =========================================================================
# REST API Handlers (/api/h3/...)
# =========================================================================
try:
    from aiohttp import web
    from server import PromptServer

    async def handle_mux_project(request):
        try:
            data = await request.json()
            project_name = data.get("project_name", "")
            chunk_files = data.get("chunk_files", [])
            source_audio_file = data.get("source_audio_file", "")
            trim_trailing_frames = bool(data.get("trim_trailing_frames", False))

            if not project_name or not chunk_files:
                return web.json_response({"error": "Missing project_name or chunk_files"}, status=400)

            # Validate that all chunks have identical resolution for lossless mux
            chunk_resolutions = {}
            for cf in chunk_files:
                if os.path.exists(cf):
                    chunk_resolutions[Path(cf).name] = _get_video_file_res(cf, "unknown")
            
            unique_res = set(r for r in chunk_resolutions.values() if r != "unknown")
            if len(unique_res) > 1:
                res_details = ", ".join(f"{k}: {v}" for k, v in chunk_resolutions.items())
                err_msg = f"해상도 불일치: 선택된 파일들의 해상도가 서로 다릅니다 ({res_details}). 무손실 병합은 동일 해상도만 가능합니다."
                print(f"[H3-API] Mux rejected: {err_msg}")
                return web.json_response({"error": err_msg, "details": chunk_resolutions}, status=400)

            project_dir = Path(folder_paths.get_output_directory()) / "H3Swap" / project_name
            merged_dir = project_dir / "merged"
            merged_dir.mkdir(parents=True, exist_ok=True)

            ffmpeg_bin = _get_ffmpeg_path()
            timestamp = time.strftime('%Y%m%d_%H%M%S')
            final_mp4 = merged_dir / f"final_merged_{timestamp}.mp4"

            processed_chunk_files = []
            if trim_trailing_frames:
                trim_dir = merged_dir / f"trimmed_{timestamp}"
                trim_dir.mkdir(parents=True, exist_ok=True)
                for idx, c_file in enumerate(chunk_files):
                    if os.path.exists(c_file):
                        trimmed_file = trim_dir / f"trim_{idx:03d}_{Path(c_file).name}"
                        # Trim last 4 frames (keep exact 5.00s / 120 frames at 24fps)
                        subprocess.run([
                            ffmpeg_bin, "-y",
                            "-i", str(c_file),
                            "-t", "5.000",
                            "-c:v", "libx264", "-preset", "ultrafast", "-crf", "18",
                            "-an",
                            str(trimmed_file)
                        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=15)
                        if trimmed_file.exists() and os.path.getsize(trimmed_file) > 1024:
                            processed_chunk_files.append(str(trimmed_file))
                        else:
                            processed_chunk_files.append(c_file)
            else:
                processed_chunk_files = chunk_files

            concat_txt = merged_dir / f"concat_list_{timestamp}.txt"
            with open(concat_txt, "w", encoding="utf-8") as f:
                for c_file in processed_chunk_files:
                    if os.path.exists(c_file):
                        f.write(f"file '{c_file}'\n")

            if source_audio_file and os.path.exists(source_audio_file):
                cmd = [
                    ffmpeg_bin, "-y",
                    "-f", "concat", "-safe", "0", "-i", str(concat_txt),
                    "-i", str(source_audio_file),
                    "-map", "0:v:0", "-map", "1:a:0?",
                    "-c:v", "copy", "-c:a", "aac",
                    "-shortest",
                    str(final_mp4)
                ]
            else:
                cmd = [
                    ffmpeg_bin, "-y",
                    "-f", "concat", "-safe", "0", "-i", str(concat_txt),
                    "-c", "copy",
                    str(final_mp4)
                ]

            proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            if proc.returncode != 0:
                print(f"[H3-API] FFmpeg error: {proc.stderr}")
                return web.json_response({"error": "FFmpeg merge failed", "details": proc.stderr}, status=500)

            rel_url = f"/api/view?filename={final_mp4.name}&subfolder=H3Swap/{project_name}/merged&type=output"
            print(f"[H3-API] ✓ Project '{project_name}' successfully merged -> {final_mp4.name}")

            return web.json_response({
                "success": True,
                "url": rel_url,
                "filename": final_mp4.name,
                "path": str(final_mp4)
            })
        except Exception as e:
            print(f"[H3-API] Exception in handle_mux_project: {e}")
            return web.json_response({"error": str(e)}, status=500)

    async def handle_list_projects(request):
        try:
            projects_root = Path(folder_paths.get_output_directory()) / "H3Swap"
            projects_root.mkdir(parents=True, exist_ok=True)
            projects = []
            for item in sorted(projects_root.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
                if item.is_dir():
                    total_takes = len(glob.glob(str(item / "chunks" / "*.mp4")))
                    projects.append({
                        "name": item.name,
                        "mtime": item.stat().st_mtime,
                        "mtimeStr": time.strftime('%Y-%m-%d %H:%M', time.localtime(item.stat().st_mtime)),
                        "totalTakes": total_takes
                    })
            return web.json_response({"projects": projects})
        except Exception as e:
            return web.json_response({"error": str(e)}, status=500)

    async def handle_load_project(request):
        try:
            project_name = request.query.get("project_name", "")
            if not project_name:
                return web.json_response({"error": "Missing project_name"}, status=400)

            project_dir = Path(folder_paths.get_output_directory()) / "H3Swap" / project_name
            if not project_dir.exists():
                return web.json_response({"error": "Project not found"}, status=404)

            chunks_dir = project_dir / "chunks"
            info_file = project_dir / "project_info.json"
            info_data = {}
            if info_file.exists():
                try:
                    with open(info_file, "r", encoding="utf-8") as f:
                        info_data = json.load(f)
                except Exception:
                    pass

            chunks = info_data.get("chunks", [])
            total_chunks = info_data.get("total_chunks", len(chunks))
            res_str = info_data.get("resolution", "864x480")

            if not chunks:
                found_files = sorted(glob.glob(str(chunks_dir / "chunk_*_take_*.mp4")))
                seen_indices = set()
                for ff in found_files:
                    stem = Path(ff).stem
                    parts = stem.split("_")
                    if len(parts) >= 2:
                        try:
                            seen_indices.add(int(parts[1]))
                        except ValueError:
                            pass
                total_chunks = max(seen_indices) if seen_indices else 0
                chunks = [(i * 5.0, 5.0) for i in range(total_chunks)]

            scenes = []
            for idx, (c_start, c_dur) in enumerate(chunks):
                chunk_num = idx + 1
                pattern = str(chunks_dir / f"chunk_{chunk_num:03d}_take_*.mp4")
                take_files = sorted(glob.glob(pattern))
                valid_take_files = [f for f in take_files if os.path.exists(f) and os.path.getsize(f) > 1024]

                takes_list = []
                for t_idx, t_file in enumerate(valid_take_files):
                    mtime = os.path.getmtime(t_file)
                    hash_tag = hashlib.md5(f"{t_file}_{mtime}".encode()).hexdigest()[:8]
                    file_time = time.strftime('%Y. %m. %d. %H:%M:%S', time.localtime(mtime))
                    rel_url = f"/api/view?filename={Path(t_file).name}&subfolder=H3Swap/{project_name}/chunks&type=output"
                    actual_res = _get_video_file_res(t_file, res_str)
                    takes_list.append({
                        "hash": hash_tag,
                        "takeIndex": t_idx + 1,
                        "timeStr": file_time,
                        "res": actual_res,
                        "url": rel_url,
                        "filePath": t_file
                    })

                orig_file = chunks_dir / f"chunk_{chunk_num:03d}_orig.mp4"
                if not orig_file.exists() and os.path.exists(str(project_dir / "source_audio.mp4")):
                    try:
                        ffmpeg_bin = "/home/ktship/ComfyUI/venv/bin/ffmpeg" if os.path.exists("/home/ktship/ComfyUI/venv/bin/ffmpeg") else "ffmpeg"
                        subprocess.run([
                            ffmpeg_bin, "-y",
                            "-ss", f"{c_start:.3f}",
                            "-t", f"{c_dur:.3f}",
                            "-i", str(project_dir / "source_audio.mp4"),
                            "-c", "copy",
                            str(orig_file)
                        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5)
                    except Exception:
                        pass

                orig_url = f"/api/view?filename={orig_file.name}&subfolder=H3Swap/{project_name}/chunks&type=output" if orig_file.exists() else ""
                orig_res = _get_video_file_res(str(orig_file), res_str) if orig_file.exists() else res_str
                orig_info = {
                    "url": orig_url,
                    "startTime": c_start,
                    "duration": c_dur,
                    "res": orig_res,
                    "exists": orig_file.exists()
                }

                scenes.append({
                    "index": chunk_num,
                    "startTime": c_start,
                    "duration": c_dur,
                    "original": orig_info,
                    "takes": takes_list
                })

            source_audio_file = info_data.get("source_audio_file", str(project_dir / "source_audio.mp4"))

            merged_files = sorted(glob.glob(str(project_dir / "merged" / "*.mp4")), key=os.path.getmtime)
            merged_history = []
            for mf in reversed(merged_files):
                p = Path(mf)
                mtime = os.path.getmtime(mf)
                mtime_str = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(mtime))
                f_size_mb = os.path.getsize(mf) / (1024 * 1024)
                m_res = _get_video_file_res(str(p), res_str)
                merged_history.append({
                    "filename": p.name,
                    "url": f"/api/view?filename={p.name}&subfolder=H3Swap/{project_name}/merged&type=output",
                    "timeStr": mtime_str,
                    "sizeMb": round(f_size_mb, 1),
                    "res": m_res,
                    "isInitial": "initial" in p.name
                })

            if merged_files:
                latest_merged_file = Path(merged_files[-1])
                full_video_url = f"/api/view?filename={latest_merged_file.name}&subfolder=H3Swap/{project_name}/merged&type=output"
            else:
                full_video_url = scenes[0]["takes"][-1]["url"] if (scenes and scenes[0]["takes"]) else ""

            session_tree_data = {
                "project_name": project_name,
                "project_dir": str(project_dir),
                "source_audio_file": source_audio_file,
                "scenes": scenes,
                "full_url": full_video_url,
                "merged_history": merged_history
            }
            return web.json_response({"session_tree_data": session_tree_data})
        except Exception as e:
            return web.json_response({"error": str(e)}, status=500)

    async def handle_rename_project(request):
        try:
            data = await request.json()
            old_name = data.get("old_name", "").strip()
            new_name = data.get("new_name", "").strip()

            if not old_name or not new_name:
                return web.json_response({"error": "이전 이름과 새 이름을 모두 입력해야 합니다."}, status=400)

            clean_new_name = "".join(c for c in new_name if c.isalnum() or c in ('_', '-', ' ', '(', ')', '[', ']')).strip()
            if not clean_new_name:
                return web.json_response({"error": "유효하지 않은 새 프로젝트 이름입니다."}, status=400)

            projects_root = Path(folder_paths.get_output_directory()) / "H3Swap"
            old_dir = projects_root / old_name
            new_dir = projects_root / clean_new_name

            if not old_dir.exists():
                return web.json_response({"error": f"이전 프로젝트 폴더를 찾을 수 없습니다: {old_name}"}, status=404)

            if new_dir.exists() and old_name != clean_new_name:
                return web.json_response({"error": f"이미 동일한 이름의 프로젝트가 존재합니다: {clean_new_name}"}, status=400)

            if old_name != clean_new_name:
                old_dir.rename(new_dir)

            info_file = new_dir / "project_info.json"
            if info_file.exists():
                try:
                    with open(info_file, "r", encoding="utf-8") as f:
                        info_data = json.load(f)
                    info_data["project_name"] = clean_new_name
                    with open(info_file, "w", encoding="utf-8") as f:
                        json.dump(info_data, f, indent=2, ensure_ascii=False)
                except Exception as e:
                    print(f"[H3-API] Warning updating project_info.json: {e}")

            print(f"[H3-API] ✓ Project renamed: '{old_name}' -> '{clean_new_name}'")
            return web.json_response({
                "success": True,
                "old_name": old_name,
                "new_name": clean_new_name
            })
        except Exception as e:
            print(f"[H3-API] Exception in handle_rename_project: {e}")
            return web.json_response({"error": str(e)}, status=500)

    
    async def handle_extract_video_frame(request):
        try:
            data = await request.json()
            video_file = data.get("video_file", "").strip()
            timestamp_sec = float(data.get("timestamp_sec", 0.0))
            frame_index = int(data.get("frame_index", 0))
            use_seconds = bool(data.get("use_seconds", True))
            output_filename = data.get("output_filename", "watermark_frame.png").strip()

            if not video_file:
                return web.json_response({"error": "동영상 파일을 지정해야 합니다."}, status=400)

            input_dir = folder_paths.get_input_directory()
            possible_path = os.path.join(input_dir, video_file)
            if os.path.exists(possible_path):
                video_path = possible_path
            elif os.path.exists(video_file):
                video_path = video_file
            else:
                return web.json_response({"error": f"비디오 파일을 찾을 수 없습니다: {video_file}"}, status=404)

            import cv2
            cap = cv2.VideoCapture(video_path)
            if not cap.isOpened():
                return web.json_response({"error": f"비디오를 열 수 없습니다: {video_path}"}, status=400)

            fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
            total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 1)

            if use_seconds:
                target_frame = int(timestamp_sec * fps)
            else:
                target_frame = frame_index
            target_frame = max(0, min(target_frame, total_frames - 1))

            cap.set(cv2.CAP_PROP_POS_FRAMES, target_frame)
            ret, frame = cap.read()
            cap.release()

            if not ret or frame is None:
                return web.json_response({"error": "프레임을 읽을 수 없습니다."}, status=500)

            out_path = os.path.join(input_dir, output_filename)
            cv2.imwrite(out_path, frame)
            print(f"[H3-API] ✓ Extracted frame {target_frame}/{total_frames} ({timestamp_sec}s) to {out_path}")

            return web.json_response({
                "success": True,
                "filename": output_filename,
                "frame": target_frame,
                "fps": fps,
                "total_frames": total_frames
            })
        except Exception as e:
            print(f"[H3-API] Exception in handle_extract_video_frame: {e}")
            return web.json_response({"error": str(e)}, status=500)

    if hasattr(PromptServer, "instance") and hasattr(PromptServer.instance, "app"):
        if not PromptServer.instance.app.router.frozen:
            PromptServer.instance.app.add_routes([
                web.post("/api/h3/mux_project", handle_mux_project),
                web.get("/api/h3/list_projects", handle_list_projects),
                web.get("/api/h3/load_project", handle_load_project),
                web.post("/api/h3/rename_project", handle_rename_project),
                web.post("/api/h3/extract_video_frame", handle_extract_video_frame)
            ])
            print("[H3-Studio] Registered unified studio REST API routes!")
except Exception as e:
    print(f"[H3-Studio] Note on API route registration: {e}")


