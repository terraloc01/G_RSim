# G_RSim — GPR 시뮬레이터 (GPRSIM 계열)

> ## 현재 상태 (2026-07-09 시즌01 — 프로젝트 신설 + MVP 완성)
> - **목표**: GPR-SLICE 의 GPRSIM 같은 GPR 순방향 시뮬레이터.
>   2D 지하 모델(층/관로/공동) 작성 -> 합성 레이더그램(B-scan) 생성.
> - **엔진 = gprMax 3.1.7 (FDTD)** 연동 (세중님 결정, 레이트레이싱 아님).
> - **시즌01 MVP 완성**: 모델빌더 + B-scan 시뮬레이션/뷰어. 엔진 end-to-end
>   물리검증(금속관 하이퍼볼라 + 깊이 환산 일치) + GUI 오프스크린 스모크 통과.
> - 🔲 **세중님 실기동 검증 대기** (run.bat 실행 -> 그리기 -> 시뮬레이션 -> B-scan).

## 실행

```
run.bat            (또는 .venv\Scripts\python.exe G_RSim.py)
```

## ★환경 (G_OhmA 와 다름 — 전용 venv)

- **전용 venv `.venv\`** (Python 3.12). 시스템 python 아님!
  G_OhmA 가 시스템 python(numpy<2 필수)을 쓰므로 격리 목적.
- **gprMax 3.1.7 은 PyPI 미배포** — `external\gprMax\` 에 GitHub 소스 clone,
  venv 에 빌드 설치됨. 재설치:
  ```
  .venv\Scripts\python.exe -m pip install setuptools wheel
  .venv\Scripts\python.exe -m pip install external\gprMax --no-deps --no-build-isolation
  ```
  MSVC Build Tools 필요 (VS 18 BuildTools 설치돼 있음, OpenMP 사용).
- ⚠️ **external\gprMax 폴더 안에서 python -m gprMax 실행 금지** — 로컬 미빌드
  패키지를 잡아 ModuleNotFoundError(fields_updates_ext). 반드시 다른 cwd 에서.
- ⚠️ **PySide6==6.10.1 고정** — 6.11.1 은 shiboken 훅이 six.moves import 시
  크래시 (matplotlib qtagg -> dateutil -> six 경로, AttributeError _SixMetaPathImporter).
- jupyter 는 gprMax install_requires 에 있으나 불필요 (--no-deps 로 회피).

## 구조

```
G_RSim.py              엔트리포인트
config.py              APP_VERSION, 폰트, 광속 C0
core/model.py          Material(프리셋 13종)/LayerObject/BoxObject/CylinderObject/
                       AntennaConfig/GPRModel (검증 validate, 자동 time window,
                       권장 셀 λmin/10, n_traces)
engine/gprmax_writer.py  GPRModel -> gprMax .in 생성 (2D TMz, y=depth-d 변환,
                       painting 순서: 배경->층->사각->원. air/pec 은 내장 재질)
engine/gprmax_runner.py  서브프로세스 실행(python -m gprMax, 진행 콜백
                       '--- Model n/N' 파싱, 취소), .out(HDF5) 취합 read_bscan
gui/main_window.py     좌측 패널(도메인/안테나/모델구성/실행) + 탭(모델/B-scan)
                       SimThread(QThread) 로 비동기 실행
gui/model_canvas.py    모델 캔버스 — 도구(선택/사각형/원형) 드래그 그리기,
                       클릭 선택, 층/객체 렌더, 안테나 스캔라인
gui/bscan_widget.py    B-scan 뷰어 — 게인(원본/선형t/AGC), 컬러맵, 대비 clip,
                       우측 환산깊이 보조축, PNG 저장
output/                실행 산출물 (.in/.out, gitignore)
external/gprMax/       gprMax 소스 clone (gitignore)
```

## gprMax 좌표/규약 (writer 핵심)

- 2D TMz: domain z = 1셀(dz). 좌표 (x, y, z), y 위로 증가.
- 지하 y=[0, depth], 공기 y=[depth, depth+air_height], 지표 y=depth.
- 앱 좌표 깊이 d -> y = depth - d.
- Hertzian dipole z 편파, 지표면 배치. Ricker 파형.
- B-scan: #src_steps/#rx_steps + `-n N` (N = trace 수, N 모델 반복 실행).
- 출력: base1.out..baseN.out (N>1), rxs/rx1/Ez, attrs dt/Iterations.
- 기하 명령은 나중 것이 먼저 것을 덮어씀. PML 기본 10셀 — 안테나/객체는
  PML 밖에 있어야 함 (validate 가 검사).

## 시즌01 검증 기록 (2026-07-09)

- gprMax 예제 cylinder_Ascan_2D: 637 iter, 2.8s 정상 완료.
- 엔진 e2e: 건조모래(εr5) + 깊이 0.4m PEC 관(r5cm), 900MHz, 15 traces
  -> 하이퍼볼라 정점 x=1.0m/~7ns, v=c/√5 환산 깊이 일치. ✅
- GUI 오프스크린 스모크: 파라미터 동기화/객체 추가·선택·삭제/게인 3종/검증
  메시지 통과. 메인 윈도우 캡처 레이아웃 정상. ✅

## 미완/다음 후보 (시즌02+)

- 프로젝트 저장/로드 (.grs — JSON 포맷 권장)
- A-scan 뷰어 (trace 단일 표시), 시뮬레이션 로그 창
- 사용자 정의 재질 (εr/σ 직접 입력)
- 객체 속성 편집 (더블클릭), 이동/리사이즈
- 지형(비평탄 지표) — gprMax #triangle 조합
- 실측 비교용 데이터 import (DZT/SEG-Y), 결과 내보내기 확장
- 대형 모델 성능: gprMax GPU(CUDA) 옵션 검토
- 셀 크기 자동 설정 버튼 (권장값 원클릭 적용)
- ⚠️ 프로텍트+빌드 시즌 도래 시: G_OhmA 의 AxProtector 체크리스트 적용
  (scipy.stats 금지 등 — 현재 코드는 scipy 미사용, gprMax 내부는 서브프로세스라 무관할
  가능성 높으나 exe 검증 필수)

## G_Series 공통 규칙

상위 `C:\01_RnD\CLAUDE.md` 적용 — git 커밋 한국어, 맑은 고딕, 채팅전환 시
CLAUDE.md+memory 갱신 후 커밋+push.
- origin: github.com/terraloc01/G_RSim
- 보안훅 오탐 회피: `app.exec` -> `getattr(app, "exec")`, em dash(—) 코드 문자열 금지,
  이진 직렬화 모듈명 문서 표기 금지
