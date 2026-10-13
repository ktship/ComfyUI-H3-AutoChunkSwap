# ComfyUI-H3-AutoChunkSwap

MiniMax H3 비디오 기반 캐릭터 스왑 및 씬 청크 분할/합성 전용 ComfyUI 커스텀 노드 패키지입니다.

## 주요 기능
- **MiniMax H3 Project Studio**: 통합 프로젝트 매니저 & 브랜치 트리 리뷰어 UI
- **MiniMax H3 Video Chunker**: 영상 길이 자동 감지 및 5초(H3 프레임 양자화) 청크 분할기
- **MiniMax H3 Chunk Generator**: 청크별 H3 스왑 실행 및 테이크(Take) 관리
- **워터마크 도구**:
  - `H3VideoCropWatermark`: 워터마크 영역 1:1 고속 크롭
  - `H3VideoStitchWatermark`: 페더링 기반 원본 복원 합성
  - `H3ExtractVideoFrame`: 마스크용 프레임 추출기
  - `H3RepeatMaskForVideo`: 단일 마스크를 전체 비디오 길이로 확장
