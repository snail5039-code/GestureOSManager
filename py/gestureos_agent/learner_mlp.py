import os
import json
import time
import math
import shutil
from typing import Dict, List, Optional, Tuple, Any

import numpy as np


# 프로필별 모델 저장 폴더 설정 (환경변수 TEMP가 없으면 현재 디렉토리 사용)
_BASE_DIR = os.path.join(os.getenv("TEMP", "."), "GestureOS_learner_profiles")
# 해당 폴더가 없으면 생성
os.makedirs(_BASE_DIR, exist_ok=True)


# 한 라벨(제스처)당 최대 수집 가능한 샘플 수 제한
MAX_SAMPLES_PER_LABEL = 900


def _sanitize_profile(name: str) -> str:
    """파일명으로 사용하기 부적절한 문자를 제거하거나 변경하는 함수"""
    s = (name or "").strip().lower() # 공백 제거 및 소문자로 변환
    if not s:
        return "default"
    out = []
    for ch in s:
        if ch.isalnum() or ch in ("-", "_"): # 알파벳, 숫자, 하이픈, 언더바만 허용
            out.append(ch)
        else:
            out.append("-") # 그 외 문자는 하이픈으로 대체
    s = "".join(out).strip("-") # 앞뒤 하이픈 정리
    return s or "default"


def _l2(a: List[float], b: List[float]) -> float:
    """두 벡터 간의 유클리드 거리(L2 Distance) 계산"""
    s = 0.0
    for i in range(len(a)):
        d = a[i] - b[i]
        s += d * d
    return math.sqrt(s)


def _pinch_ratio(lm) -> Optional[float]:
    """
    엄지 끝(4번)과 검지 끝(8) 사이의 거리를 손바닥 크기(0번~9번)로 나눈 비율 계산.
    집게(Pinch) 제스처의 강도를 측정할 때 사용.
    """
    try:
        if lm is None or len(lm) != 21: # 랜드마크 데이터가 유효하지 않으면 None
            return None
        x0, y0, _ = lm[0] # 손목 좌표
        x9, y9, _ = lm[9] # 중지 시작 마디 좌표
        # 손바닥의 대략적인 크기 계산
        palm = math.sqrt((x0 - x9) ** 2 + (y0 - y9) ** 2)
        if palm < 1e-6: # 0으로 나누기 방지
            return None
        x4, y4, _ = lm[4] # 엄지 끝
        x8, y8, _ = lm[8] # 검지 끝
        # 엄지와 검지 사이의 거리 계산
        pinch = math.sqrt((x4 - x8) ** 2 + (y4 - y8) ** 2)
        return float(pinch / palm) # 비율 반환
    except Exception:
        return None


def _softmax(z: np.ndarray) -> np.ndarray:
    """뉴럴 네트워크의 출력값을 확률(0.0~1.0)로 변환하는 소프트맥스 함수"""
    z = z - np.max(z, axis=1, keepdims=True) # 수치 안정성을 위해 최대값 뺌
    e = np.exp(z)
    return e / np.sum(e, axis=1, keepdims=True)


class MLPLearner:
    """
    사용자 프로필별 MLP(다층 퍼셉트론) 학습기.
    - 입력: 손가락 21개 마디의 3D 좌표 (정규화된 상태)
    - 구조: 2개의 은닉층(ReLU 활성화함수) + 출력층(Softmax)
    """

    # 기본적으로 인식할 제스처 라벨 목록
    DEFAULT_LABELS = ["OPEN_PALM", "FIST", "V_SIGN", "PINCH_INDEX", "OTHER"]

    def __init__(self, profile: str = "default"):
        # 프로필 이름 정규화 및 설정
        self.profile: str = _sanitize_profile(profile)

        self.enabled: bool = False # 학습기 활성화 여부
        self.min_samples: int = 10 # 학습에 필요한 최소 샘플 수
        self.min_conf: float = 0.70 # 예측 결과의 최소 신뢰도 문턱값

        # 수집된 제스처 샘플 저장소 (cursor: 마우스 손, other: 반대 손)
        self.samples: Dict[str, Dict[str, List[List[float]]]] = {"cursor": {}, "other": {}}

        # 핀치 제스처 인식을 위한 보정용 버퍼
        self._pinch_pos: Dict[str, List[float]] = {"cursor": [], "other": []} # 핀치 중일 때의 비율들
        self._pinch_neg: Dict[str, List[float]] = {"cursor": [], "other": []} # 핀치가 아닐 때의 비율들
        self.pinch_ratio_thresh: Dict[str, float] = {"cursor": 0.35, "other": 0.35} # 핀치 판단 기준점

        # 실제 학습된 가중치와 파라미터가 저장되는 딕셔너리
        self.mlp: Dict[str, Dict[str, Any]] = {"cursor": {}, "other": {}}

        # MLP 학습 데이터가 부족할 때 사용하는 백업용 모델 (중심점 방식)
        self.proto: Dict[str, Dict[str, Dict[str, Any]]] = {"cursor": {}, "other": {}}

        self.last_pred: Optional[dict] = None # 마지막 예측 결과
        self.last_train_ts: Optional[float] = None # 마지막 학습 시간

        # 현재 데이터 수집(캡처) 중인 상태 정보
        self.capture: Optional[dict] = None

        self.load() # 초기화 시 저장된 모델 불러오기

    # ---------- 경로 헬퍼 함수 ----------
    def _model_path(self, profile: Optional[str] = None) -> str:
        """JSON 모델 파일이 저장될 전체 경로 반환"""
        p = _sanitize_profile(profile or self.profile)
        return os.path.join(_BASE_DIR, f"{p}.json")

    def _bak_path(self, profile: Optional[str] = None) -> str:
        """학습 전 백업용 파일(.bak) 경로 반환"""
        return self._model_path(profile) + ".bak"

    def has_backup(self) -> bool:
        """백업 파일 존재 여부 확인"""
        try:
            return os.path.exists(self._bak_path())
        except Exception:
            return False

    # ---------- 데이터 특징 추출 ----------
    def extract(self, lm) -> Optional[List[float]]:
        """
        손가락 좌표를 머신러닝 모델이 학습하기 좋은 형태로 가공(정규화).
        1. 모든 좌표를 손목(0번) 기준으로 이동 (Translation Invariance)
        2. 중지 마디(9번)까지의 거리를 기준으로 전체 크기 조절 (Scale Invariance)
        """
        if not lm or len(lm) != 21:
            return None

        # 1. 원점 이동: 손목을 (0,0,0)으로 만듦
        x0, y0, z0 = lm[0]
        pts = [(x - x0, y - y0, z - z0) for (x, y, z) in lm]

        # 2. 스케일 정규화: 손 크기에 상관없게 만듦
        sx, sy, sz = pts[9]  # 9번 마디 기준
        scale = math.sqrt(sx * sx + sy * sy + sz * sz)
        if scale < 1e-6: # 너무 작으면 대체 스케일링
            scale = max((math.sqrt(x * x + y * y + z * z) for (x, y, z) in pts), default=1.0)
            if scale < 1e-6:
                scale = 1.0

        inv = 1.0 / scale
        vec: List[float] = []
        for (x, y, z) in pts:
            # 모든 좌표에 역수를 곱해 정규화된 63개의 숫자 리스트 생성 (21개 마디 * 3차원)
            vec.extend([x * inv, y * inv, z * inv])
        return vec

    def _ensure(self, hand: str, label: str):
        """데이터를 저장하기 전 딕셔너리 구조가 있는지 확인 및 생성"""
        hand = "cursor" if hand != "other" else "other"
        self.samples.setdefault(hand, {})
        self.samples[hand].setdefault(label, [])

    def add_sample(self, hand: str, label: str, lm) -> bool:
        """실시간으로 들어오는 손 좌표(lm)를 학습용 데이터셋에 추가"""
        vec = self.extract(lm) # 특징 추출
        if vec is None:
            return False

        hand = "cursor" if hand != "other" else "other"
        label = str(label)
        self._ensure(hand, label)
        arr = self.samples[hand][label]
        arr.append(vec) # 리스트에 추가
        
        # 샘플 수가 너무 많아지면 오래된 것부터 삭제 (메모리 및 효율 관리)
        if len(arr) > MAX_SAMPLES_PER_LABEL:
            del arr[: len(arr) - MAX_SAMPLES_PER_LABEL]

        # 핀치 제스처일 경우 핀치 비율도 따로 저장하여 나중에 문턱값 계산에 사용
        r = _pinch_ratio(lm)
        if r is not None:
            if label == "PINCH_INDEX":
                self._pinch_pos[hand].append(float(r))
                if len(self._pinch_pos[hand]) > 2000:
                    del self._pinch_pos[hand][: len(self._pinch_pos[hand]) - 2000]
            else:
                self._pinch_neg[hand].append(float(r)) # 핀치가 아닌 모든 동작의 비율 저장
                if len(self._pinch_neg[hand]) > 2000:
                    del self._pinch_neg[hand][: len(self._pinch_neg[hand]) - 2000]

        return True

    def counts(self) -> Dict[str, Dict[str, int]]:
        """현재 각 제스처별로 수집된 샘플 개수 반환"""
        out: Dict[str, Dict[str, int]] = {}
        for hand, mp in self.samples.items():
            out[hand] = {lab: len(vs) for lab, vs in mp.items()}
        return out

    # ---------- 학습 로직 ----------
    def _backup_before_train(self):
        """학습이 잘못될 경우를 대비해 기존 모델을 .bak 파일로 복사"""
        try:
            src = self._model_path()
            if os.path.exists(src):
                shutil.copyfile(src, self._bak_path())
        except Exception:
            pass

    def _build_proto(self):
        """간단한 평균값 기반 모델 생성 (MLP가 동작 안할 때의 대비책)"""
        self.proto = {"cursor": {}, "other": {}}
        for hand, mp in self.samples.items():
            for label, vecs in mp.items():
                if len(vecs) < self.min_samples:
                    continue
                dim = len(vecs[0])
                # 1. 해당 제스처의 모든 샘플의 평균(Centroid) 계산
                c = [0.0] * dim
                for v in vecs:
                    for i in range(dim):
                        c[i] += v[i]
                n = float(len(vecs))
                for i in range(dim):
                    c[i] /= n

                # 2. 평균으로부터의 표준편차(Sigma) 계산 (얼마나 일관적인지)
                s2 = 0.0
                for v in vecs:
                    d = _l2(v, c)
                    s2 += d * d
                s2 /= max(1.0, n)
                sigma = math.sqrt(s2) + 1e-6

                self.proto[hand][label] = {"centroid": c, "sigma": float(sigma), "n": int(n)}

    def _train_mlp_for_hand(self, hand: str, mp: Dict[str, List[List[float]]]):
        """넘파이(Numpy)만을 이용해 직접 MLP 학습을 수행하는 핵심 로직"""
        # 학습 가능한 라벨 필터링 (최소 샘플 수 이상인 것들만)
        labels = []
        for l in self.DEFAULT_LABELS:
            if len(mp.get(l, [])) >= self.min_samples:
                labels.append(l)
        for l, vs in mp.items():
            if l not in labels and len(vs) >= self.min_samples:
                labels.append(l)

        # 분류할 클래스가 최소 2개는 있어야 학습 가능
        if len(labels) < 2:
            self.mlp[hand] = {}
            return

        # 데이터를 넘파이 배열로 변환
        X_list: List[List[float]] = []
        y_list: List[int] = []
        for yi, lab in enumerate(labels):
            for v in mp.get(lab, []):
                X_list.append(v)
                y_list.append(yi)

        X = np.asarray(X_list, dtype=np.float32)
        y = np.asarray(y_list, dtype=np.int64)
        n, d = X.shape # n: 샘플 수, d: 특징 차원(63)

        # 데이터 표준화 (평균 0, 표준편차 1로 변환)
        mean = X.mean(axis=0)
        std = X.std(axis=0) + 1e-6
        Xn = (X - mean) / std

        # 레이어 구조: 입력(63) -> 은닉1(128) -> 은닉2(64) -> 출력(라벨 수)
        h1, h2 = 128, 64
        k = len(labels)

        # 가중치 초기화 (Xavier/Glorot Initialization)
        rng = np.random.default_rng(42)
        def xavier(in_dim, out_dim):
            lim = math.sqrt(6.0 / float(in_dim + out_dim))
            return rng.uniform(-lim, lim, size=(in_dim, out_dim)).astype(np.float32)

        W1 = xavier(d, h1); b1 = np.zeros((h1,), dtype=np.float32)
        W2 = xavier(h1, h2); b2 = np.zeros((h2,), dtype=np.float32)
        W3 = xavier(h2, k); b3 = np.zeros((k,), dtype=np.float32)

        # Adam 최적화 알고리즘 파라미터
        lr = 0.01
        beta1, beta2 = 0.9, 0.999
        eps = 1e-8
        # 모멘텀 및 속도 변수 초기화
        mW1 = np.zeros_like(W1); vW1 = np.zeros_like(W1)
        mb1 = np.zeros_like(b1); vb1 = np.zeros_like(b1)
        mW2 = np.zeros_like(W2); vW2 = np.zeros_like(W2)
        mb2 = np.zeros_like(b2); vb2 = np.zeros_like(b2)
        mW3 = np.zeros_like(W3); vW3 = np.zeros_like(W3)
        mb3 = np.zeros_like(b3); vb3 = np.zeros_like(b3)

        def relu(a): return np.maximum(a, 0.0)

        def adam_step(param, grad, m, v, t):
            """가중치를 업데이트하는 Adam 한 단계 수행"""
            m[:] = beta1 * m + (1.0 - beta1) * grad
            v[:] = beta2 * v + (1.0 - beta2) * (grad * grad)
            mh = m / (1.0 - beta1 ** t)
            vh = v / (1.0 - beta2 ** t)
            param[:] = param - lr * mh / (np.sqrt(vh) + eps)

        # 220회 반복 학습 (Epochs)
        epochs = 220
        for t in range(1, epochs + 1):
            # 순전파 (Forward Pass)
            z1 = Xn @ W1 + b1
            a1 = relu(z1)
            z2 = a1 @ W2 + b2
            a2 = relu(z2)
            logits = a2 @ W3 + b3
            probs = _softmax(logits)

            # 역전파 (Backward Pass - 그레디언트 계산)
            dlog = probs
            dlog[np.arange(n), y] -= 1.0 # Cross Entropy 오차 계산
            dlog /= float(n)

            dW3 = a2.T @ dlog
            db3 = dlog.sum(axis=0)
            da2 = dlog @ W3.T
            dz2 = da2; dz2[z2 <= 0.0] = 0.0 # ReLU 미분

            dW2 = a1.T @ dz2
            db2 = dz2.sum(axis=0)
            da1 = dz2 @ W2.T
            dz1 = da1; dz1[z1 <= 0.0] = 0.0

            dW1 = Xn.T @ dz1
            db1 = dz1.sum(axis=0)

            # 가중치 업데이트
            adam_step(W1, dW1, mW1, vW1, t)
            adam_step(b1, db1, mb1, vb1, t)
            adam_step(W2, dW2, mW2, vW2, t)
            adam_step(b2, db2, mb2, vb2, t)
            adam_step(W3, dW3, mW3, vW3, t)
            adam_step(b3, db3, mb3, vb3, t)

        # 학습된 결과물 저장 (리스트 형태로 변환하여 JSON 저장 가능하게 함)
        self.mlp[hand] = {
            "labels": labels,
            "mean": mean.astype(np.float32).tolist(),
            "std": std.astype(np.float32).tolist(),
            "W1": W1.tolist(), "b1": b1.tolist(),
            "W2": W2.tolist(), "b2": b2.tolist(),
            "W3": W3.tolist(), "b3": b3.tolist(),
        }

    def _calibrate_pinch_ratio(self, hand: str):
        """핀치 제스처를 판단하는 기준점(Threshold)을 수집된 데이터를 바탕으로 자동 설정"""
        pos = self._pinch_pos.get(hand) or [] # 핀치 샘플들
        neg = self._pinch_neg.get(hand) or [] # 일반 샘플들
        if len(pos) < 10: return

        pos_arr = np.asarray(pos, dtype=np.float32)
        if len(neg) >= 10:
            neg_arr = np.asarray(neg, dtype=np.float32)
            # 핀치 데이터의 상위 85% 지점과 일반 데이터의 하위 15% 지점의 중간을 문턱값으로 설정
            pos_hi = float(np.quantile(pos_arr, 0.85))
            neg_lo = float(np.quantile(neg_arr, 0.15))
            thr = (pos_hi + neg_lo) * 0.5
        else:
            # 일반 데이터가 없으면 핀치 중간값의 120% 수준으로 설정
            thr = float(np.median(pos_arr) * 1.20)

        # 너무 작거나 큰 값이 되지 않도록 범위 제한 (0.12 ~ 0.60)
        thr = float(max(0.12, min(0.60, thr)))
        self.pinch_ratio_thresh[hand] = thr

    def train(self):
        """전체 학습 프로세스 실행 (백업 -> 보조모델 생성 -> 핀치 보정 -> MLP 학습 -> 저장)"""
        self._backup_before_train()
        self._build_proto()
        self._calibrate_pinch_ratio("cursor")
        self._calibrate_pinch_ratio("other")

        self.mlp = {"cursor": {}, "other": {}}
        for hand, mp in self.samples.items():
            self._train_mlp_for_hand(hand, mp)

        self.last_train_ts = time.time()
        self.save() # 학습 완료 후 파일로 저장

    # ---------- 예측(Inference) ----------
    def _predict_mlp(self, hand: str, vec: List[float]) -> Tuple[Optional[str], float]:
        """MLP 모델을 사용하여 제스처 예측"""
        m = self.mlp.get(hand) or {}
        if not m: return None, 0.0

        labels = m.get("labels") or []
        if not labels: return None, 0.0

        # 저장된 가중치들을 넘파이로 변환
        mean = np.asarray(m.get("mean"), dtype=np.float32)
        std = np.asarray(m.get("std"), dtype=np.float32)
        x = np.asarray(vec, dtype=np.float32)
        x = (x - mean) / (std + 1e-6) # 입력 데이터 정규화
        x = x.reshape(1, -1)

        W1 = np.asarray(m.get("W1"), dtype=np.float32); b1 = np.asarray(m.get("b1"), dtype=np.float32)
        W2 = np.asarray(m.get("W2"), dtype=np.float32); b2 = np.asarray(m.get("b2"), dtype=np.float32)
        W3 = np.asarray(m.get("W3"), dtype=np.float32); b3 = np.asarray(m.get("b3"), dtype=np.float32)

        # 신경망 계산 (Forward)
        z1 = x @ W1 + b1; a1 = np.maximum(z1, 0.0)
        z2 = a1 @ W2 + b2; a2 = np.maximum(z2, 0.0)
        logits = a2 @ W3 + b3
        p = _softmax(logits)[0] # 확률 계산

        idx = int(np.argmax(p)) # 가장 확률이 높은 인덱스
        conf = float(p[idx]) # 그때의 확률(신뢰도)
        lab = str(labels[idx]) # 해당 라벨 이름
        return lab, conf

    def _predict_proto(self, hand: str, vec: List[float]) -> Tuple[Optional[str], float]:
        """평균값 기반 모델로 제스처 예측 (MLP 미학습 시 사용)"""
        models = self.proto.get(hand) or {}
        if not models: return None, 0.0

        best_label = None
        best_score = 0.0
        for label, m in models.items():
            c = m.get("centroid")
            sigma = float(m.get("sigma", 1.0))
            if not c: continue
            dist = _l2(vec, c)
            # 거리가 가까울수록 점수가 높게 나옴 (가우시안 커널 스타일)
            score = math.exp(-dist / (sigma + 1e-6))
            if score > best_score:
                best_score = score
                best_label = label
        return (best_label, float(best_score))

    def predict(self, hand: str, lm) -> Tuple[Optional[str], float]:
        """공식 외부 인터페이스: 현재 손의 제스처와 신뢰도 반환"""
        if not self.enabled: return None, 0.0

        vec = self.extract(lm)
        if vec is None: return None, 0.0

        hand = "cursor" if hand != "other" else "other"

        # 1순위: MLP 모델 사용
        lab, conf = self._predict_mlp(hand, vec)
        # 2순위: MLP 결과가 없으면 프로토타입(평균) 모델 사용
        if lab is None:
            lab, conf = self._predict_proto(hand, vec)

        if lab is None: return None, float(conf)
        # 설정된 최소 신뢰도보다 낮으면 결과 무시
        if conf < self.min_conf: return None, float(conf)
        return str(lab), float(conf)

    # ---------- 데이터 수집(Capture) 관리 ----------
    def start_capture(self, hand: str, label: str, seconds: float = 2.0, hz: int = 15):
        """특정 라벨의 데이터를 일정 시간(seconds) 동안 일정 빈도(hz)로 수집 시작"""
        hand = "cursor" if hand != "other" else "other"
        hz = max(1, int(hz))
        seconds = max(0.3, float(seconds))

        now = time.time()
        self.capture = {
            "hand": hand,
            "label": str(label),
            "until": now + seconds, # 수집 종료 시간
            "interval": 1.0 / hz, # 수집 간격
            "next": 0.0,
            "collected": 0,
        }

    def tick_capture(self, cursor_lm, other_lm):
        """매 프레임마다 호출되어 캡처 시간이 되었을 때 샘플 저장"""
        if not self.capture: return

        now = time.time()
        # 수집 시간 종료 여부 확인
        if now >= float(self.capture.get("until", 0.0)):
            self.capture = None
            return

        if float(self.capture.get("next", 0.0)) == 0.0:
            self.capture["next"] = now

        if now < float(self.capture["next"]): return

        # 다음 수집 예약
        self.capture["next"] = now + float(self.capture["interval"])

        hand = self.capture["hand"]
        label = self.capture["label"]
        lm = cursor_lm if hand == "cursor" else other_lm
        if lm is None: return

        # 샘플 추가
        ok = self.add_sample(hand, label, lm)
        if ok:
            self.capture["collected"] = int(self.capture.get("collected", 0)) + 1

    # ---------- 프로필 관리 ----------
    def set_profile(self, profile: str):
        """다른 프로필로 변경 (변경 전 현재 상태 저장 및 새 상태 로드)"""
        p = _sanitize_profile(profile)
        if p == self.profile: return
        self.save()
        # 내부 메모리 데이터 초기화
        self.samples = {"cursor": {}, "other": {}}
        self._pinch_pos = {"cursor": [], "other": []}
        self._pinch_neg = {"cursor": [], "other": []}
        self.capture = None
        self.last_pred = None
        self.profile = p
        self.load()

    def list_profiles(self) -> List[str]:
        """저장된 모든 프로필 이름 목록 반환"""
        try:
            names: set[str] = set()
            for fn in os.listdir(_BASE_DIR):
                if not fn.endswith(".json"): continue
                if fn.endswith(".json.bak"): continue
                base = fn[:-5] # .json 확장자 제외
                if base: names.add(_sanitize_profile(base))
            names.add("default")
            names.add(_sanitize_profile(self.profile))
            out = sorted(names)
            return out if out else ["default"]
        except Exception:
            p = _sanitize_profile(getattr(self, "profile", "default"))
            return sorted({"default", p})

    def _write_empty_model(self, path: str, profile: str):
        """초기 상태의 빈 모델 파일을 생성"""
        obj = {
            "schema": "mlp_v1",
            "profile": _sanitize_profile(profile),
            "enabled": bool(self.enabled),
            "min_samples": int(self.min_samples),
            "min_conf": float(self.min_conf),
            "last_train_ts": None,
            "pinch_ratio_thresh": dict(self.pinch_ratio_thresh),
            "mlp": {"cursor": {}, "other": {}},
            "proto": {"cursor": {}, "other": {}},
        }
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False)

    def create_profile(self, profile: str, copy_from_current: bool = True, switch: bool = True) -> str:
        """새 프로필 생성 (현재 설정을 복사할 수도 있음)"""
        p = _sanitize_profile(profile)
        if not p: p = "default"

        try:
            if copy_from_current: self.save()
        except Exception: pass

        dst = self._model_path(p)
        try:
            if copy_from_current:
                src = self._model_path(self.profile)
                if os.path.exists(src): shutil.copyfile(src, dst)
                else: self._write_empty_model(dst, p)
            else: self._write_empty_model(dst, p)
        except Exception:
            try: self._write_empty_model(dst, p)
            except Exception: pass

        if switch:
            try: self.set_profile(p)
            except Exception: self.profile = p
        return p

    def delete_profile(self, profile: str) -> bool:
        """프로필 파일 및 백업 파일 삭제 (default 프로필은 삭제 불가)"""
        p = _sanitize_profile(profile)
        if p == "default": return False

        # 현재 사용 중인 프로필을 삭제하면 default로 전환
        if p == _sanitize_profile(self.profile):
            try: self.set_profile("default")
            except Exception: self.profile = "default"

        ok = False
        for path in (self._model_path(p), self._bak_path(p)):
            try:
                if os.path.exists(path):
                    os.remove(path)
                    ok = True
            except Exception: pass
        return ok

    def rename_profile(self, src: str, dst: str) -> bool:
        """프로필 이름(파일명) 변경"""
        s = _sanitize_profile(src)
        d = _sanitize_profile(dst)
        if s == "default" or d == "default": return False
        if s == d: return True

        try:
            if s == _sanitize_profile(self.profile): self.save()
        except Exception: pass

        src_path = self._model_path(s); dst_path = self._model_path(d)
        if not os.path.exists(src_path): return False
        if os.path.exists(dst_path): return False

        try:
            shutil.move(src_path, dst_path) # 메인 파일 이동
            src_bak = self._bak_path(s); dst_bak = self._bak_path(d)
            if os.path.exists(src_bak) and (not os.path.exists(dst_bak)):
                shutil.move(src_bak, dst_bak) # 백업 파일도 같이 이동
        except Exception: return False

        if s == _sanitize_profile(self.profile):
            self.profile = d
            try: self.load()
            except Exception: pass
        return True

    # ---------- 복구/저장/로드 ----------
    def rollback(self) -> bool:
        """학습이 마음에 들지 않을 때 이전 백업(.bak) 파일로 되돌림"""
        try:
            bak = self._bak_path()
            if not os.path.exists(bak): return False
            shutil.copyfile(bak, self._model_path())
            self.load()
            return True
        except Exception: return False

    def reset(self):
        """현재 프로필의 모든 학습 데이터 및 모델 초기화"""
        self.samples = {"cursor": {}, "other": {}}
        self._pinch_pos = {"cursor": [], "other": []}
        self._pinch_neg = {"cursor": [], "other": []}
        self.mlp = {"cursor": {}, "other": {}}
        self.proto = {"cursor": {}, "other": {}}
        self.last_pred = None
        self.last_train_ts = None
        self.capture = None
        self.save()

    def save(self):
        """현재의 모든 상태(MLP 가중치, 프로토타입 등)를 JSON 파일로 저장"""
        try:
            obj = {
                "schema": "mlp_v1",
                "profile": self.profile,
                "enabled": bool(self.enabled),
                "min_samples": int(self.min_samples),
                "min_conf": float(self.min_conf),
                "last_train_ts": self.last_train_ts,
                "pinch_ratio_thresh": dict(self.pinch_ratio_thresh),
                "mlp": self.mlp,
                "proto": self.proto,
            }
            with open(self._model_path(), "w", encoding="utf-8") as f:
                json.dump(obj, f, ensure_ascii=False)
        except Exception: pass

    def load(self):
        """JSON 파일로부터 모델과 설정을 불러와 현재 인스턴스에 적용"""
        try:
            path = self._model_path()
            if not os.path.exists(path): return
            with open(path, "r", encoding="utf-8") as f:
                obj = json.load(f)

            self.enabled = bool(obj.get("enabled", self.enabled))
            self.min_samples = int(obj.get("min_samples", self.min_samples))
            self.min_conf = float(obj.get("min_conf", self.min_conf))
            self.last_train_ts = obj.get("last_train_ts", None)

            # 핀치 문턱값 로드
            prt = obj.get("pinch_ratio_thresh")
            if isinstance(prt, dict):
                for k in ("cursor", "other"):
                    if k in prt:
                        try: self.pinch_ratio_thresh[k] = float(prt[k])
                        except Exception: pass

            self.mlp = obj.get("mlp", self.mlp) or self.mlp
            self.proto = obj.get("proto", self.proto) or self.proto
        except Exception: pass