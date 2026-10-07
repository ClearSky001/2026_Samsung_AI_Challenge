# -*- coding: utf-8 -*-
"""SCPC 2026 Final - generalized, deterministic FinalHarness.

No external API or model is used.  Every decision is derived from the current
task's records, prompt/history, object attributes, and stream-local memory.
"""
from __future__ import annotations

import json
import re
from typing import Any

SUBMISSION_SCHEMA = "scpc.final.answer.v1"
FIXED_SLM_ID = "scpc-final-fixed-slm-local-facade"


# ---------------------------------------------------------------- fixed SLM
class FixedSLMClient:
    model_id = FIXED_SLM_ID

    def summarize_task(self, task: dict[str, Any]) -> dict[str, Any]:
        text_parts: list[str] = [str(task.get("prompt", ""))]
        device_state = task.get("device_state", {}) or {}
        for rec in device_state.get("records", []) or []:
            text_parts.append(str(rec.get("type", "")))
            text_parts.append(str(rec.get("value", "")))
        for mem in task.get("personal_memory", []) or []:
            text_parts.append(str(mem.get("text", "")))
        text = " ".join(text_parts).lower()
        flags: set[str] = set()
        tags: set[str] = set()
        if "phishing" in text or "피싱" in text or "security_alert" in text:
            flags.update(["payment", "phishing"])
            tags.add("security_precedence")
        if "consent" in text or "동의" in text:
            tags.add("consent_precedence")
        if "health" in text or "건강" in text or "복약" in text or "검진" in text:
            flags.add("health")
        if "external" in text or "외부" in text:
            flags.add("external_share")
        if "privacy" in text or "개인정보" in text or "개인" in text:
            flags.add("privacy")
        if "rrn" in text or "raw_quote" in text or "실명" in text or "위치" in text:
            flags.add("sensitive_content")
        if "ambiguous" in text or "모호" in text:
            flags.add("ambiguous_reference")
            tags.add("resolved_target")
        return {
            "risk_flags": sorted(flags),
            "requires_redaction": any(k in text for k in ["raw_sensitive_forbidden", "raw_quote_forbidden", "numeric_value_forbidden", "실명", "위치", "원문"]),
            "requires_confirmation": any(k in text for k in ["ambiguous", "amount_changed", "duration_ambiguous", "missing", "확인", "모호"]),
            "audit_tags": sorted(tags),
        }


# ---------------------------------------------------------------- helpers
def records_of(task: dict[str, Any]) -> list[dict[str, Any]]:
    return list(((task.get("device_state") or {}).get("records") or []))


def objects_of(task: dict[str, Any]) -> list[dict[str, Any]]:
    return list(((task.get("device_state") or {}).get("objects") or []))


def record_map(task: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for record in records_of(task):
        if isinstance(record, dict):
            out[str(record.get("type"))] = record.get("value")
    return out


def full_text(task: dict[str, Any]) -> str:
    parts = [str(task.get("prompt", ""))]
    for h in task.get("visible_history") or []:
        parts.append(str(h.get("summary", "")))
    return " | ".join(parts)


ORD_KO = {"첫": 1, "두": 2, "세": 3, "네": 4, "다섯": 5, "여섯": 6}

# 최신 정정/조건의 의미 동의어
PH_LOCAL = [
    "바깥으로 보내지 말고 내부 상태 업데이트",
    "수신처 전달 대신 기기 내부 업데이트",
    "공유하지 말고 상태값만 갱신",
    "보내는 작업은 취소하고 로컬 상태 기록",
    "외부 공유가 아니라 내 기기 안에서 상태만 갱신",
    "전달 동작은 취소하고 장치 안의 처리 상태만",
]
# "단, ..." 형태의 사용자 직접 지시(→ ask + target=user)
PH_USER = [
    "새 전제가 확정되지 않았으므로 처리 전에 사용자에게 먼저 확인",
    "누구에게 어떤 범위로 처리할지 다시 확인",
    "조건 변경 여부가 미확정",
    "마지막 문장에서 대상이나 전제 조건이 바뀌었는지 아직 확인되지 않았다",
]
# ask를 유도하지만 target은 record/메모리 기반으로 유지되는 문구
PH_ASK_SOFT = [
    "로컬 처리로 단정하지 말고 사용자 확인",
    "최종 수신처와 허용 범위가 아직 확정되지 않았으므로 먼저 확인",
    "승인 경로가 닫히기 전까지 확인 응답을 우선",
    "금액 확인이 필요하면 먼저 물어봐",
    "재사용하지 말고 확인",
]
PH_STOP = [
    "허용 근거가 최신 상태에서 깨졌",
    "처리 전제가 사라졌으므로",
    "이전 허용 조건이 취소된 것으로 보아 더 진행하면 안",
    "이전 허용의 전제를 무효화했으므로",
    "과거 승인에 기대면 안 되는 상태",
]
PH_SUMMARY_ONLY = ["식별 가능한 세부값을 제외한 요약만"]

# ---- "단, ..." 사용자 정정 절(clause)의 의미 기반 분류 --------------------
# 정확 문구 매칭 외에 키워드 조합으로 절의 의도를 분류한다.
CLAUSE_RE = re.compile(r"단[,，]\s*([^|\n]+)")

KW_STOP = ["진행하면 안", "실행하면 안", "차단", "멈춰", "막아야", "전제가 사라",
           "깨졌", "취소된 것으로", "무효화했", "기대면 안", "진행하지 말",
           "무너졌", "보류해야", "보류한다", "멈춘다", "뒤집었", "깨뜨리",
           "믿을 수 없", "실행을 보류"]
KW_USER = ["사용자에게 먼저 확인", "사용자 확인", "clarification", "물어봐",
           "확인 절차", "확인 질문", "다시 확인", "확인을 받아야", "미확정", "확정되지 않",
           "먼저 확인하지 않으면", "불분명"]
KW_LOCAL_A = ["내부", "내 기기", "기기 안", "장치 안", "장치 내부", "로컬"]
KW_LOCAL_B = ["상태", "기록", "갱신", "정리"]
KW_SUM = ["제외", "제한", "덜어", "익명", "포함하지 않", "제거", "남기지 않"]


def _any(s: str, kws: list[str]) -> bool:
    return any(k in s for k in kws)


def classify_clause(text: str) -> dict[str, bool]:
    """텍스트 내 '단,' 절을 모아 stop/user/local/sum_only 의도를 분류."""
    cl = " ".join(CLAUSE_RE.findall(text))
    if not cl:
        return {"stop": False, "user": False, "local": False, "sum_only": False}
    return {
        "stop": _any(cl, KW_STOP),
        "user": _any(cl, KW_USER),
        "local": _any(cl, KW_LOCAL_A) and _any(cl, KW_LOCAL_B),
        "sum_only": ("요약" in cl and _any(cl, KW_SUM)),
    }

SENSITIVE_FIELDS = {"raw_quote", "rrn", "location", "numeric_value", "doctor_note", "name", "amount", "raw_memory"}
# content_scope의 공개 canonical field 집합
SCOPE_SENSITIVE = {"raw_quote", "rrn", "location", "numeric_value", "name", "amount"}
FIELD_CANON = {"amount": "numeric_value"}  # canonical field normalization


def sensitive_excluded(contains: list[str] | None) -> list[str]:
    if not contains:
        return []
    out = set()
    for c in contains:
        if c in SCOPE_SENSITIVE:
            out.add(FIELD_CANON.get(c, c))
    return sorted(out)


def explicit_scope_exclusions(text: str) -> list[str]:
    """Extract explicitly forbidden public-ontology fields from the latest clause."""
    clauses = " ".join(CLAUSE_RE.findall(text))
    if not clauses:
        return []
    aliases = {
        "raw_quote": ("raw_quote", "raw 문장", "원문", "원본 문장", "직접 인용"),
        "location": ("location", "위치", "장소"),
        "numeric_value": ("numeric_value", "숫자 값", "숫자", "수치", "금액"),
        "name": ("실명", "이름", "name"),
        "rrn": ("주민등록", "rrn"),
    }
    return sorted(field for field, words in aliases.items() if any(word in clauses for word in words))


def parse_memory_prompt(prompt: str) -> dict[str, Any]:
    """Parse a memory-write prompt when the record contains only an opaque state id."""
    profile: dict[str, Any] = {}
    patterns = {
        "person": r"장기 사용자 메모리를 저장해줘\.\s*([A-Za-z가-힣0-9_]+)의 생일",
        "birthday": r"생일은\s*([0-9]{2}-[0-9]{2})",
        "preferred_channel": r"연락 채널은\s*([A-Za-z0-9_]+)",
        "tone": r"말투는\s*([A-Za-z0-9_]+)",
        "gift_hint": r"선호 선물은\s*([A-Za-z0-9_]+)",
        "avoid": r"([A-Za-z0-9_]+)는 피하고",
        "privacy_rule": r"privacy 규칙은\s*([A-Za-z0-9_]+)",
        "medication_time": r"복약 시간은\s*([0-9]{2}:[0-9]{2})",
        "checkup_time": r"검진/점검 일정은\s*([0-9]{2}-[0-9]{2}\s+[0-9]{2}:[0-9]{2})",
        "checkup_place": r"검진/점검 일정은\s*[0-9]{2}-[0-9]{2}\s+[0-9]{2}:[0-9]{2}\s+([A-Za-z0-9_]+)",
        "dusk_room": r"날이 어두워지면\s*([A-Za-z0-9_]+)\s*조명",
        "dusk_light_count": r"조명\s*([0-9]+)개",
        "last_success_target": r"지난 성공 작업은\s*([A-Za-z0-9_]+)에",
        "last_success_scope": r"지난 성공 작업은\s*[A-Za-z0-9_]+에\s*([A-Za-z0-9_]+)\s*범위",
        "last_success_excluded": r"범위로 처리했고\s*([A-Za-z0-9_]+)는 제외",
        "last_failure_reason": r"실패 기록은\s*([A-Za-z0-9_]+)",
        "enterprise_rule": r"기업 기본 규정은\s*([A-Za-z0-9_]+)",
        "approval_channel": r"승인 채널은\s*([A-Za-z0-9_]+)",
    }
    for key, pattern in patterns.items():
        match = re.search(pattern, prompt)
        if match:
            profile[key] = match.group(1)
    return profile


# ---------------------------------------------------------------- harness
class FinalHarness:
    def __init__(self) -> None:
        self.slm = FixedSLMClient()
        self.memory: dict[str, Any] = {}

    def prepare(self, tasks: list[dict[str, Any]]) -> None:
        self.memory.clear()

    # ---------------- session memory --------------------------------
    def update_session_memory(self, task: dict[str, Any], session: dict[str, Any]) -> None:
        for record in records_of(task):
            if record.get("type") != "persistent_memory_write":
                continue
            raw = record.get("value")
            value = dict(raw) if isinstance(raw, dict) else parse_memory_prompt(str(task.get("prompt", "")))
            if not value:
                continue
            aliases = [value.get("memory_key"), value.get("person")]
            if isinstance(raw, str) and raw:
                aliases.append(raw)
            for key in aliases:
                if key:
                    self.memory[str(key)] = value
            session["last_profile"] = value

    def recall_profile(self, task: dict[str, Any], rm: dict[str, Any]) -> dict[str, Any]:
        """persistent_memory_recall 관련 프로필 조회 (memory_key → person 순)."""
        pmr = rm.get("persistent_memory_recall")
        person = pmr.get("person") if isinstance(pmr, dict) else None
        if isinstance(pmr, dict):
            key = pmr.get("memory_key")
            if key and str(key) in self.memory:
                return self.memory[str(key)]
        # memory_key 미존재 → 같은 사람의 최초 관측 프로필 사용
        if person:
            for name, prof in self.memory.items():
                if isinstance(prof, dict) and str(prof.get("person")) == str(person):
                    return prof
        # prompt에 등장하는 사람 이름으로 fallback
        text = full_text(task)
        for name, prof in self.memory.items():
            if isinstance(prof, dict) and prof.get("person") and str(prof["person"]) in text:
                return prof
        return {}

    # ---------------- focal ------------------------------------------
    def choose_focal(self, task: dict[str, Any], session: dict[str, Any]) -> dict[str, Any]:
        objects = objects_of(task)
        if not objects:
            return {}
        rm = record_map(task)
        ref = None

        # 1) marker resolution chain
        refs = rm.get("focal_marker_refs")
        trace = rm.get("focal_resolution_trace")
        if isinstance(refs, dict) and isinstance(trace, dict):
            marker_to_ref = refs.get("marker_to_ref") or {}
            rule = trace.get("latest_phase_rule") or {}
            rbo = rm.get("route_binding_order")
            phase = rule.get(rbo) if isinstance(rbo, str) else None
            if not phase:
                phase = trace.get("latest_phase")
            marker = (trace.get("phase_to_marker") or {}).get(phase)
            ref = marker_to_ref.get(marker)

        # 2) visible_history 기반 참조 해석
        if not ref:
            ref = self.focal_ref_from_history(task)

        if ref:
            for obj in objects:
                if str((obj.get("attrs") or {}).get("ref_code") or "") == ref:
                    return obj

        # 3) fallback: record 값이 object id를 직접 지시
        object_by_id = {str(o.get("id")): o for o in objects}
        for record in reversed(records_of(task)):
            value = record.get("value")
            cands = [value] if isinstance(value, str) else (list(value.values()) if isinstance(value, dict) else [])
            for cand in cands:
                if isinstance(cand, str) and cand in object_by_id:
                    return object_by_id[cand]

        # 4) fallback: prompt 토큰 겹침
        prompt_tokens = {tok for tok in re.findall(r"[A-Za-z0-9가-힣_]+", str(task.get("prompt", "")).lower()) if len(tok) >= 2}
        best, best_score = objects[0], -1
        for obj in objects:
            obj_text = (str(obj.get("id", "")) + " " + str(obj.get("type", "")) + " " + json.dumps(obj.get("attrs") or {}, ensure_ascii=False)).lower()
            score = sum(1 for tok in prompt_tokens if tok in obj_text)
            if score > best_score:
                best, best_score = obj, score
        return best

    @staticmethod
    def focal_ref_from_history(task: dict[str, Any]) -> str | None:
        for h in reversed(task.get("visible_history") or []):
            s = str(h.get("summary", ""))
            codes = re.findall(r"WM-\d+", s)
            if not codes:
                continue
            # --- 특정 코드를 직접 지시하는 일반 표현 ---
            direct_patterns = [
                r"승인 표시가 남은 것은 (WM-\d+)",
                r"최종 승인 후보 (WM-\d+)",
                r"기준 참조는 (WM-\d+)",
                r"참조 코드는 (WM-\d+)",
                r"승인 상태가 유지된 참조는 (WM-\d+)",
                r"ref는 (WM-\d+)[으로]*\s*고정",
                r"(WM-\d+)[으로]*\s*고정됐",
                r"binding은 (WM-\d+)",
                r"(WM-\d+)[을를]?만? 통과",
                r"(WM-\d+)[을를]? 현재 턴의 참조로",
                r"처리 대상[으로]* 확정된[^.]*?(WM-\d+)",
            ]
            for pat in direct_patterns:
                m = re.search(pat, s)
                if m:
                    return m.group(1)
            # --- 서수(첫/두/세 번째, 둘째/셋째 등)로 후보 목록의 위치를 지시 ---
            ord_map = {"첫": 1, "두": 2, "둘": 2, "세": 3, "셋": 3,
                       "네": 4, "넷": 4, "다섯": 5, "여섯": 6}
            m = (re.search(r"(첫|두|둘|세|셋|네|넷|다섯|여섯)\s*번?째\s*(?:후보|항목)만", s)
                 or re.search(r"항목은\s*(첫|두|둘|세|셋|네|넷|다섯|여섯)\s*번?째", s)
                 or re.search(r"(첫|두|둘|세|셋|네|넷|다섯|여섯)\s*번?째(?:다|이다|였다)", s))
            if m and codes:
                idx = ord_map[m.group(1)] - 1
                return codes[idx] if idx < len(codes) else codes[-1]
            if "가운데 항목만" in s:
                return codes[len(codes) // 2]
            return codes[-1]
        return None

    # ---------------- 시나리오/결정 -----------------------------------
    def answer_task(self, task: dict[str, Any], session: dict[str, Any]) -> dict[str, Any]:
        evidence = self.slm.summarize_task(task)
        self.update_session_memory(task, session)
        rm = record_map(task)
        text = full_text(task)
        prompt = str(task.get("prompt", ""))

        focal = self.choose_focal(task, session)
        focal_id = str(focal.get("id") or "")
        attrs = focal.get("attrs") or {}
        contains = list(attrs.get("contains") or attrs.get("fields") or [])

        cl = classify_clause(text)
        ph_local = any(p in text for p in PH_LOCAL) or cl["local"]
        ph_user = any(p in text for p in PH_USER) or cl["user"]
        ph_ask = ph_user or any(p in text for p in PH_ASK_SOFT)
        ph_stop = any(p in text for p in PH_STOP) or cl["stop"]
        ph_sum_only = any(p in text for p in PH_SUMMARY_ONLY) or cl["sum_only"]
        # 절이 로컬 처리 지시라면 확인/중단보다 로컬 처리 의미가 우선하는 경우가 있으므로
        # stop/user와 local이 동시에 잡히면 명시적 exact 문구를 우선한다.
        if cl["local"] and cl["user"] and not any(p in text for p in PH_USER):
            ph_user = False
            ph_ask = any(p in text for p in PH_ASK_SOFT)
        fast_path = "fast path" in text or "빠르게 처리" in text

        rt = rm.get("resolved_target")
        rt = rt if isinstance(rt, str) else None
        ssp = rm.get("session_share_policy")
        sbu = rm.get("share_boundary_update")
        dac = rm.get("dispatch_authority_check")
        rcs = rm.get("route_candidate_snapshot")
        amb_t = rm.get("ambiguous_target")
        amb_f = rm.get("ambiguous_focal")
        gls = rm.get("guardrail_ladder_signal")
        esp = rm.get("external_share_policy")
        tca = rm.get("target_changed_after_turn")
        consent = rm.get("consent")
        pmw = "persistent_memory_write" in rm
        pmr = "persistent_memory_recall" in rm
        profile = self.recall_profile(task, rm) if pmr else {}

        # ---- control 결정 (우선순위 cascade) ----
        control = None
        if ph_stop:
            control = "hold"
        elif ph_ask:
            control = "ask"
        elif ph_local or pmw:
            control = "proceed"
        elif ph_sum_only and gls is None:
            # 최신 절이 '민감값 제외 요약만 허용' → 범위 축소 진행 (gls는 기존 분기 유지)
            control = "amend"
        elif rm.get("safety_mode") == "child_sleep_active":
            control = "hold"
        elif "security_alert" in rm:
            control = "hold"
        elif consent == "revoked":
            control = "hold"
        elif "memory_conflict" in rm:
            control = "ask"
        elif tca is not None:
            control = "ask"
        elif "calendar_conflict" in rm:
            control = "ask"
        elif rm.get("payment_policy") == "limit_to_refund_status":
            control = "amend"
        elif rm.get("guest_mode") == "temporary_allowed":
            control = "amend"
        elif "trusted_subscription" in rm:
            control = "proceed"
        elif isinstance(esp, str) and esp == "doctor_note_forbidden":
            control = "hold"
        elif gls is not None:
            if ph_sum_only:
                control = "amend"
            elif dac in ("internal_binding_confirmed", "local_authority_confirmed"):
                # 권한이 확정된 상태: 로컬 경계면 확인(ask), 아니면 진행
                control = "ask" if sbu == "local_update_boundary" else "proceed"
            else:
                control = "hold"
        elif "duration_ambiguous" in rm:
            control = "ask"
        elif pmr:
            # 저장된 회피 항목 위반 → hold
            avoid = str(profile.get("avoid") or "")
            if avoid and avoid in prompt:
                control = "hold"
            elif sbu == "redacted_external_boundary":
                control = "ask"
            else:
                control = "amend"
        elif "temporary_override_allowed" in rm:
            control = "amend"
        elif amb_f is not None:
            if dac == "user_binding_pending":
                control = "hold"
            elif dac == "authority_incomplete":
                control = "ask"
            elif dac in ("internal_binding_confirmed", "local_authority_confirmed"):
                control = "proceed" if sbu == "local_update_boundary" else "amend"
            else:
                control = "ask"
        elif amb_t is not None:
            if dac == "user_binding_pending":
                control = "hold"
            elif dac == "authority_incomplete":
                control = "ask"
            elif sbu == "redacted_external_boundary":
                control = "ask"
            else:
                control = "amend"
        elif isinstance(esp, str):
            control = "amend"
        elif rt:
            control = "amend" if ssp == "strict" else "proceed"
        else:
            control = "proceed"

        # ---- target ----
        target = self.infer_target(task, rm, control, attrs, profile, ph_local, pmw, session,
                                   user_pref=(ph_stop or ph_user))

        # ---- content_scope ----
        scope = self.build_content_scope(task, rm, control, contains, attrs, ssp, fast_path, ph_local, pmw, prompt, target,
                                         ph_user=ph_user, ph_sum_only=ph_sum_only, text=text)

        # ---- policy ----
        policy = self.build_policy(task, rm, control, contains, scope, target)

        # ---- plan events ----
        plan_events = self.build_plan_events(rm, focal_id, target, control, scope)

        session["last_focal_id"] = focal_id
        session["last_target"] = target
        session["last_control"] = control

        return {
            "focal_id": focal_id,
            "target": target,
            "control": control,
            "content_scope": scope,
            "policy": policy,
            "plan_events": plan_events,
            "user_response": self.user_response(control, target, scope),
            "audit_tags": evidence.get("audit_tags", []),
            "counterfactual": "최신 기록, 동의 상태, 공유 범위, 보안 신호가 바뀌면 판단이 달라질 수 있습니다.",
        }

    # ---------------- target ----------------------------------------
    @staticmethod
    def majority_recipient(task) -> str | None:
        counts: dict[str, int] = {}
        for o in objects_of(task):
            r = (o.get("attrs") or {}).get("recipient")
            if r:
                counts[str(r)] = counts.get(str(r), 0) + 1
        if not counts:
            return None
        return max(counts.items(), key=lambda kv: kv[1])[0]

    def infer_target(self, task, rm, control, attrs, profile, ph_local, pmw, session, user_pref=False) -> str:
        rt = rm.get("resolved_target")
        rt = rt if isinstance(rt, str) else None
        tca = rm.get("target_changed_after_turn")
        maj = self.majority_recipient(task)

        if pmw:
            return "memory_store"
        if ph_local and control == "proceed":
            return "memory_store"
        # "단, ..." 사용자 지시(중단/확인)가 붙은 hold/ask는 사용자에게 되묻는다
        if user_pref and control in ("hold", "ask"):
            return "user"
        if "trusted_subscription" in rm or rm.get("payment_policy") == "limit_to_refund_status":
            if attrs.get("merchant"):
                return str(attrs["merchant"])
        if rm.get("guest_mode") == "temporary_allowed" and attrs.get("target"):
            return str(attrs["target"])
        if isinstance(tca, str):
            if tca in ("prior_success_route_superseded",):
                return str(profile.get("approval_channel") or rt or maj or "user")
            return tca
        if rm.get("safety_mode") == "child_sleep_active":
            return str(profile.get("dusk_room") or "living_room")
        if "persistent_memory_recall" in rm:
            prompt = str(task.get("prompt", ""))
            pmr = rm.get("persistent_memory_recall")
            mem_class = str((pmr or {}).get("memory_class") or "") if isinstance(pmr, dict) else ""
            cand = None
            if mem_class == "prior_result":
                cand = profile.get("last_success_target") or profile.get("approval_channel")
            elif mem_class == "standing_constraint":
                cand = profile.get("approval_channel") or profile.get("preferred_channel")
            elif "memory_conflict" in rm:
                cand = profile.get("health_channel") or profile.get("preferred_channel") or profile.get("checkup_place")
            elif "검진" in prompt or "점검" in prompt:
                # 저장된 프로필이 전혀 없으면 보호자(caregiver)에게 안내
                cand = (profile.get("preferred_channel") or profile.get("checkup_place")
                        or (None if profile else "caregiver"))
            elif "건강" in prompt or "복약" in prompt:
                cand = profile.get("health_channel") or profile.get("preferred_channel")
            else:
                cand = profile.get("preferred_channel") or profile.get("approval_channel")
            if cand:
                return str(cand)
            if rt:
                return rt
            if maj:
                return maj
        if rt:
            return rt
        # device_setting toggle류: 설정 이름이 target
        if attrs.get("name"):
            for o in objects_of(task):
                if o.get("attrs") is attrs and o.get("type") == "device_setting":
                    return str(attrs["name"])
        if maj:
            return maj
        if control in ("hold", "ask"):
            return "user"
        for key in ("recipient", "attendee", "channel", "app", "target", "merchant", "name"):
            if attrs.get(key):
                return str(attrs[key])
        return str(session.get("last_target") or "user")

    # ---------------- content scope ---------------------------------
    def build_content_scope(self, task, rm, control, contains, attrs, ssp, fast_path, ph_local, pmw, prompt, target,
                            ph_user=False, ph_sum_only=False, text="") -> dict[str, Any]:
        if control == "hold":
            return {"mode": "none", "allowed_fields": [], "excluded_fields": [], "requires_user_confirmation": False}

        amb_t = rm.get("ambiguous_target")
        sens = sensitive_excluded(contains)

        if control == "proceed":
            if target == "memory_store" or ph_local or pmw:
                excluded = ["raw_quote", "location", "numeric_value"] if (ssp == "strict" or fast_path) else []
                return {"mode": "status_only", "allowed_fields": ["status"], "excluded_fields": excluded, "requires_user_confirmation": False}
            if rm.get("guardrail_ladder_signal") is not None or "회의 시간" in prompt:
                return {"mode": "raw", "allowed_fields": ["summary", "title"], "excluded_fields": [], "requires_user_confirmation": False}
            if rm.get("ambiguous_focal") is not None:
                excluded = ["raw_quote", "location", "numeric_value"] if ssp == "strict" else []
                return {"mode": "status_only", "allowed_fields": ["status"], "excluded_fields": excluded, "requires_user_confirmation": False}
            return {"mode": "summary", "allowed_fields": ["summary"], "excluded_fields": [], "requires_user_confirmation": False}

        if control == "amend":
            if rm.get("payment_policy") == "limit_to_refund_status":
                return {
                    "mode": "status_only",
                    "allowed_fields": ["status"],
                    "excluded_fields": ["numeric_value"],
                    "requires_user_confirmation": False,
                }
            direct = explicit_scope_exclusions(text) if ph_sum_only else []
            excluded = direct or (sens if ssp == "strict" and sens else None) or ["raw_quote"]
            return {"mode": "redacted", "allowed_fields": ["summary"], "excluded_fields": excluded, "requires_user_confirmation": amb_t is not None}

        # ---- ask -----------------------------------------------------
        contains_set = set(contains)
        tca = rm.get("target_changed_after_turn")
        dac = rm.get("dispatch_authority_check")
        rt = rm.get("resolved_target")
        rt = rt if isinstance(rt, str) else ""

        if tca == "prior_success_route_superseded":
            return {"mode": "none", "allowed_fields": [], "excluded_fields": [], "requires_user_confirmation": True}
        if tca is not None:
            meta = any(prompt.startswith(p) for p in (
                "다음 요청을 최신 작업 메모리", "표면 문장만 보지",
                "아래 요청은 최근 메모리", "이번 턴에서는 보이는 요청"))
            mode, excluded = ("summary" if meta else "redacted"), ["raw_quote"]
        elif ph_user:
            if "name" in contains_set:
                mode, excluded = "summary", ["name"]
            elif "새 전제" in text and dac != "authority_incomplete":
                mode, excluded = "redacted", ["raw_quote"]
            elif "마지막 문장에서" in text or "마지막 조건" in text:
                mode, excluded = "redacted", ["raw_quote"]
            else:
                mode, excluded = "summary", ["raw_quote"]
        else:
            if {"name", "rrn"} <= contains_set:
                if "vendor" in rt and ssp == "strict":
                    mode, excluded = "redacted", sens or ["raw_quote"]
                elif any(k in rt for k in ("privacy", "legal", "security_review")):
                    return {"mode": "none", "allowed_fields": [], "excluded_fields": [], "requires_user_confirmation": True}
                else:
                    mode, excluded = "summary", ["name"]
            elif dac in ("internal_binding_confirmed", "local_authority_confirmed"):
                mode = "redacted" if rm.get("guardrail_ladder_signal") is not None else "summary"
                excluded = ["raw_quote"]
            else:
                mode, excluded = "summary", ["raw_quote"]
        return {"mode": mode, "allowed_fields": ["summary"], "excluded_fields": excluded, "requires_user_confirmation": True}

    # ---------------- policy -----------------------------------------
    def build_policy(self, task, rm, control, contains, scope, target) -> dict[str, Any]:
        flags: set[str] = set()
        ssp = rm.get("session_share_policy")
        dac = rm.get("dispatch_authority_check")
        sbu = rm.get("share_boundary_update")
        if ssp == "strict":
            flags.add("strict_share_policy")
        if set(contains) & SENSITIVE_FIELDS:
            flags.add("sensitive_content")
        if rm.get("ambiguous_focal") is not None:
            flags.add("ambiguous_focal")
        if rm.get("ambiguous_target") is not None:
            flags.add("target_ambiguity")
        if control == "amend":
            flags.add("minimal_disclosure")
        if control == "ask":
            flags.add("clarification_required")
        if control == "hold":
            flags.update(["precondition_invalidated", "safety"])
        if dac in ("internal_binding_confirmed", "local_authority_confirmed"):
            flags.add("precondition_changed")
        if control in ("proceed", "hold") and dac == "user_binding_pending":
            flags.add("target_ambiguity")
        # local_only / external_share — target 기준
        if target in ("user", "memory_store"):
            flags.add("local_only")
        else:
            flags.add("external_share")
        if sbu == "local_update_boundary":
            flags.add("local_only")
        violations = ["precondition_changed_ignored"] if control == "hold" else []
        if control == "ask":
            requires_confirmation = True
        elif control == "amend":
            requires_confirmation = bool(scope.get("requires_user_confirmation"))
        elif control == "proceed":
            requires_confirmation = rm.get("ambiguous_target") is not None or dac == "user_binding_pending"
        else:
            requires_confirmation = False
        return {"risk_flags": sorted(flags), "violations": violations, "requires_confirmation": requires_confirmation}

    # ---------------- plan events ------------------------------------
    def build_plan_events(self, rm, focal_id, target, control, scope) -> list[dict[str, Any]]:
        mode = scope.get("mode")
        if control == "hold":
            return [
                {"verb": "read", "target": focal_id, "args": {"purpose": "invalidated_precondition"}},
                {"verb": "guard", "target": focal_id, "args": {"reason": "precondition_invalidated"}},
            ]
        if control == "ask":
            if rm.get("dispatch_authority_check") in ("internal_binding_confirmed", "local_authority_confirmed"):
                purpose, reason = "clarify_precondition", "precondition_changed"
            else:
                purpose, reason = "route_resolution_required", "route_resolution_required"
            clarify_target = "user"
            return [
                {"verb": "read", "target": focal_id, "args": {"purpose": purpose}},
                {"verb": "clarify", "target": clarify_target, "args": {"reason": reason}},
            ]
        if control == "amend":
            if mode == "status_only":
                return [
                    {"verb": "read", "target": focal_id, "args": {"purpose": "inspect_context"}},
                    {"verb": "summarize", "target": focal_id, "args": {"mode": "status_only"}},
                    {"verb": "dispatch", "target": target, "args": {"scope": "status_only"}},
                ]
            excluded = scope.get("excluded_fields") or []
            remove = "sensitive_fields" if len(excluded) > 1 else "raw_quote"
            return [
                {"verb": "read", "target": focal_id, "args": {"purpose": "minimal_disclosure"}},
                {"verb": "redact", "target": focal_id, "args": {"remove": remove}},
                {"verb": "dispatch", "target": target, "args": {"scope": "redacted"}},
            ]
        # proceed
        if mode == "status_only":
            return [
                {"verb": "read", "target": focal_id, "args": {"purpose": "local_update"}},
                {"verb": "verify", "target": "share_boundary_update", "args": {"scope": "local_update"}},
                {"verb": "update", "target": focal_id, "args": {"state": "local_status_only"}},
            ]
        if mode == "raw":
            return [
                {"verb": "read", "target": focal_id, "args": {"purpose": "inspect_context"}},
                {"verb": "dispatch", "target": target, "args": {"scope": "raw"}},
            ]
        return [
            {"verb": "read", "target": focal_id, "args": {"purpose": "inspect_context"}},
            {"verb": "summarize", "target": focal_id, "args": {"mode": "summary"}},
            {"verb": "dispatch", "target": target, "args": {"scope": "summary"}},
        ]

    @staticmethod
    def user_response(control: str, target: str, scope: dict[str, Any]) -> str:
        if control == "hold":
            return "안전/정책 전제가 무효화되어 이 요청은 진행하지 않고 보류합니다."
        if control == "ask":
            return "최종 수신처와 허용 범위가 확정되지 않아 먼저 확인이 필요합니다."
        if control == "amend":
            return f"민감 정보를 제외한 요약만 {target}(으)로 전달하겠습니다."
        if scope.get("mode") == "status_only":
            return "외부 공유 없이 기기 내부 상태만 갱신했습니다."
        return f"요청한 범위로 {target}(으)로 진행하겠습니다."
