# -*- coding: utf-8 -*-
"""gprMax 서브프로세스 실행 + .out 결과 취합.

GUI 와 분리된 순수 엔진 계층 (Qt 의존 없음).
gprMax 는 venv 의 python -m gprMax 로 별도 프로세스 실행 —
OpenMP/전역상태로부터 GUI 프로세스를 격리한다.
"""

import os
import re
import subprocess
import sys

import numpy as np

_RE_MODEL = re.compile(r"---\s*Model\s+(\d+)\s*/\s*(\d+)")


def _python_exe() -> str:
    """gprMax 가 설치된 전용 venv python 우선 (앱을 다른 python 으로 띄워도 안전)."""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    venv_py = os.path.join(root, ".venv", "Scripts", "python.exe")
    if os.path.isfile(venv_py):
        return venv_py
    return sys.executable


def run_simulation(in_path: str, n_traces: int, progress_cb=None, log_cb=None,
                   cancel_flag=None) -> bool:
    """gprMax 실행. progress_cb(current, total), log_cb(line) 콜백.

    cancel_flag: callable() -> bool, True 반환 시 프로세스 중단.
    반환값: 정상 완료 여부.
    """
    cmd = [_python_exe(), "-m", "gprMax", os.path.basename(in_path)]
    if n_traces > 1:
        cmd += ["-n", str(n_traces)]

    creation = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    proc = subprocess.Popen(
        cmd,
        cwd=os.path.dirname(in_path),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=creation,
    )
    try:
        for raw in proc.stdout:
            # tqdm 캐리지리턴 라인 정리
            line = raw.rstrip("\n").split("\r")[-1]
            if cancel_flag is not None and cancel_flag():
                proc.kill()
                if log_cb:
                    log_cb("사용자 취소: 프로세스 중단")
                return False
            mm = _RE_MODEL.search(line)
            if mm and progress_cb:
                progress_cb(int(mm.group(1)), int(mm.group(2)))
            if log_cb and line.strip():
                log_cb(line)
    finally:
        proc.stdout.close()
        proc.wait()
    return proc.returncode == 0


def read_bscan(in_path: str, n_traces: int, component: str = "Ez"):
    """실행 결과 .out 취합 → (data[iterations, n_traces], dt초).

    gprMax 명명 규약: n=1 → base.out, n>1 → base1.out ... baseN.out
    GUI 프로세스에 h5py 가 없으면 venv python 에 위임 (npz 경유).
    """
    try:
        import h5py
    except ImportError:
        return _read_bscan_delegate(in_path, n_traces, component)

    base = os.path.splitext(in_path)[0]
    if n_traces <= 1:
        paths = [base + ".out"]
    else:
        paths = [f"{base}{i}.out" for i in range(1, n_traces + 1)]

    traces = []
    dt = None
    for p in paths:
        with h5py.File(p, "r") as f:
            traces.append(np.array(f[f"rxs/rx1/{component}"]))
            dt = float(f.attrs["dt"])
    data = np.column_stack(traces)
    return data, dt


_DELEGATE_CODE = """
import sys, os
import numpy as np
import h5py
inp, n, comp = sys.argv[1], int(sys.argv[2]), sys.argv[3]
base = os.path.splitext(inp)[0]
paths = [base + '.out'] if n <= 1 else [base + str(i) + '.out' for i in range(1, n + 1)]
traces = []
dt = 0.0
for p in paths:
    with h5py.File(p, 'r') as f:
        traces.append(np.array(f['rxs/rx1/' + comp]))
        dt = float(f.attrs['dt'])
np.savez(base + '_bscan.npz', data=np.column_stack(traces), dt=dt)
"""


def _read_bscan_delegate(in_path: str, n_traces: int, component: str):
    """h5py 취합을 venv python 서브프로세스로 수행하고 npz 로 회수."""
    creation = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    subprocess.run(
        [_python_exe(), "-c", _DELEGATE_CODE, in_path, str(n_traces), component],
        check=True, capture_output=True, creationflags=creation,
    )
    npz_path = os.path.splitext(in_path)[0] + "_bscan.npz"
    npz = np.load(npz_path)
    return npz["data"], float(npz["dt"])


def cleanup_outputs(in_path: str, n_traces: int) -> None:
    """이전 실행 잔여 .out 삭제 (파일 혼입 방지)."""
    base = os.path.splitext(in_path)[0]
    candidates = [base + ".out"] + [f"{base}{i}.out" for i in range(1, n_traces + 1)]
    for p in candidates:
        if os.path.isfile(p):
            try:
                os.remove(p)
            except OSError:
                pass
