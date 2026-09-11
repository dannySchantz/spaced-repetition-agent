"""Live configuration is opt-in and never inferred from credentials alone."""

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from recall.ai.grader import PROMPT_VERSION, OpenAIProvider
from recall.core import run, uid


@dataclass
class LiveConfig:
    account_sid: str
    auth_token: str
    owner_phone: str
    sender_phone: str
    public_url: str
    toll_free: bool = False

    @classmethod
    def from_env(cls):
        import re

        values = {
            name: os.getenv(env, "")
            for name, env in [
                ("account_sid", "TWILIO_ACCOUNT_SID"),
                ("auth_token", "TWILIO_AUTH_TOKEN"),
                ("owner_phone", "RECALL_OWNER_PHONE"),
                ("sender_phone", "RECALL_SENDER_PHONE"),
                ("public_url", "RECALL_PUBLIC_URL"),
            ]
        }
        if not all(values.values()):
            raise ValueError(
                "Live SMS requires Twilio account, token, owner, sender and public URL"
            )
        if any(
            not re.fullmatch(r"\+[1-9]\d{7,14}", values[k]) for k in ["owner_phone", "sender_phone"]
        ):
            raise ValueError("Use E.164 owner and sender phone numbers")
        parsed = urlparse(values["public_url"])
        if (
            parsed.scheme != "https"
            or not parsed.netloc
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("RECALL_PUBLIC_URL must be an HTTPS origin, with no path or query")
        values["public_url"] = values["public_url"].rstrip("/")
        return cls(**values, toll_free=os.getenv("RECALL_TOLL_FREE", "false") == "true")


class BudgetedProvider:
    """Reserve a conservative token ceiling before a paid call, including failed requests."""

    def __init__(self, core, provider, monthly_tokens):
        self.core, self.provider, self.monthly_tokens = core, provider, monthly_tokens

    def grade(self, items):
        return self.invoke(items, lambda: self.provider.grade(items))

    def invoke(self, items, call):
        # UTF-8 bytes conservatively bound token input; reserve prompt/schema overhead plus output.
        reserved = len(json.dumps(items, ensure_ascii=False).encode()) + 20000
        with self.core.db.transaction() as c:
            month = self.core.now()[:7]
            used = run(
                c,
                "SELECT COALESCE(SUM(COALESCE(actual_tokens,reserved_tokens)),0) FROM ai_usage WHERE month=:month",
                month=month,
            ).scalar_one()
            if used + reserved > self.monthly_tokens:
                raise ValueError("Monthly AI token allowance exhausted")
            request_id = uid()
            run(
                c,
                "INSERT INTO ai_usage VALUES (:id,:month,'openai',:model,:reserved,NULL,:now)",
                id=request_id,
                month=month,
                model=self.provider.model,
                reserved=reserved,
                now=self.core.now(),
            )
        response = call()
        total = response.usage.get("total_tokens")
        if total is not None:
            with self.core.db.transaction() as c:
                run(
                    c,
                    "UPDATE ai_usage SET actual_tokens=:total WHERE id=:id",
                    id=request_id,
                    total=total,
                )
        return response


def configured_grader(core):
    if os.getenv("RECALL_LIVE_AI", "false") != "true":
        return None
    model = os.getenv("RECALL_MODEL", "")
    from importlib.resources import files

    cases = [
        json.loads(line)
        for line in files("recall.ai").joinpath("fixtures.jsonl").read_text().splitlines()
        if line
    ]
    dataset = "".join(json.dumps(case, ensure_ascii=False) + "\n" for case in cases if "id" in case)
    dataset_hash = hashlib.sha256(dataset.encode()).hexdigest()
    # Personal deployments may opt into live calls before a formal evaluation report.
    # Hosted/shared deployments should leave this off and retain the reviewed gate.
    if os.getenv("RECALL_ALLOW_UNEVALUATED_AI", "false") != "true":
        report_path = os.getenv("RECALL_EVAL_REPORT", "")
        if not report_path:
            raise KeyError("RECALL_EVAL_REPORT")
        report = json.loads(Path(report_path).read_text())
        if not (
            report.get("mode") == "live"
            and report.get("model") == model
            and report.get("dataset_sha256") == dataset_hash
            and report.get("prompt_version") == PROMPT_VERSION
            and report.get("count", 0) >= 60
            and report.get("split") == "all"
            and report.get("numeric_gate") is True
            and report.get("human_reviewed") is True
            and report.get("clear_agreement", 0) >= 0.95
            and report.get("false_right_must_fail") == []
        ):
            raise ValueError(
                "Live grading requires a passing evaluation report for this model/prompt"
            )
    limit = int(os.getenv("RECALL_MONTHLY_AI_TOKENS", "0"))
    if limit <= 0:
        raise ValueError("Set an explicit positive monthly AI token allowance")
    return BudgetedProvider(core, OpenAIProvider(model, authorized=True), limit)


class BudgetedAssistant:
    def __init__(self, budgeted):
        from .ai.assistant import LiveAssistantProvider

        self.budgeted = budgeted
        self.provider = LiveAssistantProvider(budgeted.provider)

    def plan(self, message, selected):
        from .ai.assistant import AssistantPlan
        from .ai.grader import ProviderResult

        def invoke():
            plan = self.provider.plan(message, selected)
            return ProviderResult(
                plan.model_dump(), "openai", self.budgeted.provider.model, self.provider.last_usage
            )

        result = self.budgeted.invoke({"message": message, "selected": selected}, invoke)
        return AssistantPlan.model_validate(result.data)
