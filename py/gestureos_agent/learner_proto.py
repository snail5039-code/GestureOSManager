import os
import json
import time
import math
import shutil
from typing import Dict, List, Optional, Tuple, Any

# 프로필별 모델 저장 폴더
_BASE_DIR = os.path.join(os.getenv("TEMP", "."), "GestureOS_learner_profiles")
os.makedirs(_BASE_DIR, exist_ok=True)

MAX_SAMPLES_PER_LABEL = 600


def _sanitize_profile(name: str) -> str:
    s = (name or "").strip().lower()
    if not s:
        return "default"
    out = []
    for ch in s:
        if ch.isalnum() or ch in ("-", "_"):
            out.append(ch)
        else:
            out.append("-")
    s = "".join(out).strip("-")
    return s or "default"


def _l2(a: List[float], b: List[float]) -> float:
    s = 0.0
    for i in range(len(a)):
        d = a[i] - b[i]
        s += d * d
    return math.sqrt(s)


class ProtoLearner:
    """
    Prototype(centroid) learner.
    - profile 별로 model 파일 분리 저장
    - train() 직전에 자동 백업(.bak) 1개 저장
    - rollback() 으로 직전 모델 복구
    """

    def __init__(self, profile: str = "default"):
        self.profile: str = _sanitize_profile(profile)

        # 전역 토글(모드 바뀌어도 유지되는 게 사용자 경험 좋음)
        self.enabled: bool = False
        self.min_samples: int = 10
        self.min_conf: float = 0.55

        # samples[hand][label] = [vec, vec, ...]
        self.samples: Dict[str, Dict[str, List[List[float]]]] = {"cursor": {}, "other": {}}

        # model[hand][label] = {"centroid":[...], "sigma":float, "n":int}
        self.model: Dict[str, Dict[str, Dict[str, Any]]] = {"cursor": {}, "other": {}}

        self.last_pred: Optional[dict] = None
        self.last_train_ts: Optional[float] = None

        # capture state
        self.capture: Optional[dict] = None

        # load profile model
        self.load()

    # ---------- path helpers ----------
    def _model_path(self, profile: Optional[str] = None) -> str:
        p = _sanitize_profile(profile or self.profile)
        return os.path.join(_BASE_DIR, f"{p}.json")

    def _bak_path(self, profile: Optional[str] = None) -> str:
        return self._model_path(profile) + ".bak"

    def has_backup(self) -> bool:
        try:
            return os.path.exists(self._bak_path())
        except Exception:
            return False

    # ---------- core ----------
    def extract(self, lm) -> Optional[List[float]]:
        """lm: [(x,y,z), ...] length 21"""
        if not lm or len(lm) != 21:
            return None

        x0, y0, z0 = lm[0]
        pts = [(x - x0, y - y0, z - z0) for (x, y, z) in lm]

        sx, sy, sz = pts[9]  # middle_mcp
        scale = math.sqrt(sx * sx + sy * sy + sz * sz)
        if scale < 1e-6:
            scale = max((math.sqrt(x*x + y*y + z*z) for (x, y, z) in pts), default=1.0)
            if scale < 1e-6:
                scale = 1.0

        inv = 1.0 / scale
        vec: List[float] = []
        for (x, y, z) in pts:
            vec.extend([x * inv, y * inv, z * inv])
        return vec

    def _ensure(self, hand: str, label: str):
        hand = "cursor" if hand != "other" else "other"
        self.samples.setdefault(hand, {})
        self.samples[hand].setdefault(label, [])

    def add_sample(self, hand: str, label: str, lm) -> bool:
        vec = self.extract(lm)
        if vec is None:
            return False
        hand = "cursor" if hand != "other" else "other"
        self._ensure(hand, label)
        arr = self.samples[hand][label]
        arr.append(vec)
        if len(arr) > MAX_SAMPLES_PER_LABEL:
            del arr[: len(arr) - MAX_SAMPLES_PER_LABEL]
        return True

    def counts(self) -> Dict[str, Dict[str, int]]:
        out: Dict[str, Dict[str, int]] = {}
        for hand, mp in self.samples.items():
            out[hand] = {lab: len(vs) for lab, vs in mp.items()}
        return out

    def _backup_before_train(self):
        """
        Train 직전 1회 백업.
        (save()마다 백업하면 reset/enable에도 .bak 덮여서 의미 없어짐)
        """
        try:
            src = self._model_path()
            if os.path.exists(src):
                shutil.copyfile(src, self._bak_path())
        except Exception:
            pass

    def train(self):
        # ✅ 롤백용 백업
        self._backup_before_train()

        self.model = {"cursor": {}, "other": {}}

        for hand, mp in self.samples.items():
            for label, vecs in mp.items():
                if len(vecs) < self.min_samples:
                    continue
                dim = len(vecs[0])
                c = [0.0] * dim
                for v in vecs:
                    for i in range(dim):
                        c[i] += v[i]
                n = float(len(vecs))
                for i in range(dim):
                    c[i] /= n

                # sigma = RMS distance
                s2 = 0.0
                for v in vecs:
                    d = _l2(v, c)
                    s2 += d * d
                s2 /= max(1.0, n)
                sigma = math.sqrt(s2) + 1e-6

                self.model[hand][label] = {
                    "centroid": c,
                    "sigma": float(sigma),
                    "n": int(n),
                }

        self.last_train_ts = time.time()
        self.save()

    def predict(self, hand: str, lm) -> Tuple[Optional[str], float]:
        if not self.enabled:
            return None, 0.0

        vec = self.extract(lm)
        if vec is None:
            return None, 0.0

        hand = "cursor" if hand != "other" else "other"
        models = self.model.get(hand) or {}
        if not models:
            return None, 0.0

        best_label = None
        best_score = 0.0

        for label, m in models.items():
            c = m.get("centroid")
            sigma = float(m.get("sigma", 1.0))
            if not c:
                continue
            dist = _l2(vec, c)
            score = math.exp(-dist / (sigma + 1e-6))
            if score > best_score:
                best_score = score
                best_label = label

        if best_label is None or best_score < self.min_conf:
            return None, float(best_score)

        return best_label, float(best_score)

    # ---------- capture ----------
    def start_capture(self, hand: str, label: str, seconds: float = 2.0, hz: int = 15):
        hand = "cursor" if hand != "other" else "other"
        hz = max(1, int(hz))
        seconds = max(0.3, float(seconds))

        now = time.time()
        self.capture = {
            "hand": hand,
            "label": str(label),
            "until": now + seconds,
            "interval": 1.0 / hz,
            "next": 0.0,
            "collected": 0,
        }

    def tick_capture(self, cursor_lm, other_lm):
        if not self.capture:
            return

        now = time.time()
        if now >= float(self.capture.get("until", 0.0)):
            self.capture = None
            return

        if float(self.capture.get("next", 0.0)) == 0.0:
            self.capture["next"] = now

        if now < float(self.capture["next"]):
            return

        self.capture["next"] = now + float(self.capture["interval"])

        hand = self.capture["hand"]
        label = self.capture["label"]
        lm = cursor_lm if hand == "cursor" else other_lm
        if lm is None:
            return

        ok = self.add_sample(hand, label, lm)
        if ok:
            self.capture["collected"] = int(self.capture.get("collected", 0)) + 1

    # ---------- profile ----------
    def set_profile(self, profile: str):
        p = _sanitize_profile(profile)
        if p == self.profile:
            return
        # 현재 프로필 모델 저장(안전)
        self.save()
        # 샘플은 프로필별로 분리하고 싶으면 여기서 초기화(추천)
        self.samples = {"cursor": {}, "other": {}}
        self.capture = None
        self.last_pred = None

        self.profile = p
        self.load()

    # ---------- profile management (create/list/delete/rename) ----------
    def list_profiles(self) -> List[str]:
        """Return known profiles by scanning the profile directory."""
        try:
            names: set[str] = set()
            for fn in os.listdir(_BASE_DIR):
                # model files are "<profile>.json" (backup is ".json.bak")
                if not fn.endswith(".json"):
                    continue
                if fn.endswith(".json.bak"):
                    continue
                base = fn[:-5]
                if base:
                    names.add(_sanitize_profile(base))
            # always include default + current
            names.add("default")
            names.add(_sanitize_profile(self.profile))
            out = sorted(names)
            return out if out else ["default"]
        except Exception:
            # last resort
            p = _sanitize_profile(getattr(self, "profile", "default"))
            return sorted({"default", p})

    def create_profile(self, profile: str, copy_from_current: bool = True, switch: bool = True) -> str:
        """Create a new profile.

        - copy_from_current=True: copy current model file if it exists (save() first).
        - switch=True: immediately switch learner to the new profile.
        """
        p = _sanitize_profile(profile)
        if not p:
            p = "default"

        # Ensure current profile file exists if we want to copy.
        try:
            if copy_from_current:
                self.save()
        except Exception:
            pass

        dst = self._model_path(p)
        try:
            if copy_from_current:
                src = self._model_path(self.profile)
                if os.path.exists(src):
                    shutil.copyfile(src, dst)
                else:
                    # create empty model if nothing to copy
                    self._write_empty_model(dst, p)
            else:
                self._write_empty_model(dst, p)
        except Exception:
            # fallback: attempt to write empty
            try:
                self._write_empty_model(dst, p)
            except Exception:
                pass

        if switch:
            try:
                self.set_profile(p)
            except Exception:
                self.profile = p
        return p

    def delete_profile(self, profile: str) -> bool:
        p = _sanitize_profile(profile)
        if p == "default":
            return False

        # If deleting current profile, switch away first (otherwise set_profile() would re-save it).
        if p == _sanitize_profile(self.profile):
            try:
                self.set_profile("default")
            except Exception:
                self.profile = "default"

        ok = False
        for path in (self._model_path(p), self._bak_path(p)):
            try:
                if os.path.exists(path):
                    os.remove(path)
                    ok = True
            except Exception:
                pass
        return ok

    def rename_profile(self, src: str, dst: str) -> bool:
        s = _sanitize_profile(src)
        d = _sanitize_profile(dst)
        if s == "default" or d == "default":
            return False
        if s == d:
            return True

        # If renaming current and model file doesn't exist yet, save() first.
        try:
            if s == _sanitize_profile(self.profile):
                self.save()
        except Exception:
            pass

        src_path = self._model_path(s)
        dst_path = self._model_path(d)
        if not os.path.exists(src_path):
            return False
        if os.path.exists(dst_path):
            # avoid silent overwrite
            return False

        try:
            shutil.move(src_path, dst_path)
            # move backup too if exists
            src_bak = self._bak_path(s)
            dst_bak = self._bak_path(d)
            if os.path.exists(src_bak) and (not os.path.exists(dst_bak)):
                shutil.move(src_bak, dst_bak)
        except Exception:
            return False

        if s == _sanitize_profile(self.profile):
            self.profile = d
            try:
                self.load()
            except Exception:
                pass
        return True

    def _write_empty_model(self, path: str, profile: str):
        """Create a minimal model file for a profile."""
        obj = {
            "profile": _sanitize_profile(profile),
            "enabled": bool(self.enabled),
            "min_samples": int(self.min_samples),
            "min_conf": float(self.min_conf),
            "last_train_ts": None,
            "model": {"cursor": {}, "other": {}},
        }
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False)

    # ---------- rollback ----------
    def rollback(self) -> bool:
        """
        직전 train 직전(.bak)으로 되돌림.
        """
        try:
            bak = self._bak_path()
            if not os.path.exists(bak):
                return False
            shutil.copyfile(bak, self._model_path())
            self.load()
            return True
        except Exception:
            return False

    # ---------- reset/save/load ----------
    def reset(self):
        self.samples = {"cursor": {}, "other": {}}
        self.model = {"cursor": {}, "other": {}}
        self.last_pred = None
        self.last_train_ts = None
        self.capture = None
        self.save()

    def save(self):
        try:
            obj = {
                "profile": self.profile,
                "enabled": bool(self.enabled),
                "min_samples": int(self.min_samples),
                "min_conf": float(self.min_conf),
                "last_train_ts": self.last_train_ts,
                "model": self.model,
            }
            with open(self._model_path(), "w", encoding="utf-8") as f:
                json.dump(obj, f, ensure_ascii=False)
        except Exception:
            pass

    def load(self):
        try:
            path = self._model_path()
            if not os.path.exists(path):
                return
            with open(path, "r", encoding="utf-8") as f:
                obj = json.load(f)
            # enabled는 전역처럼 쓰고싶으면 여기서 로드 안 하도록 바꿔도 됨.
            self.enabled = bool(obj.get("enabled", self.enabled))
            self.min_samples = int(obj.get("min_samples", self.min_samples))
            self.min_conf = float(obj.get("min_conf", self.min_conf))
            self.last_train_ts = obj.get("last_train_ts", None)
            self.model = obj.get("model", self.model) or self.model
        except Exception:
            pass
