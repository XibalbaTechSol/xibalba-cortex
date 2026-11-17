from __future__ import annotations

import re
from typing import Any

from .models import EpistemicClass

# =============================================================================
# 1. PARA CLASSIFICATION (Project / Area / Resource / Archive)
# =============================================================================

PARA_LEXICON = {
    "project": {
        "keywords": {
            "task", "feature", "build", "sprint", "deadline", "milestone", "mvp",
            "implement", "deliverable", "deploy", "release", "fix", "issue", "bug",
            "roadmap", "version", "phase", "ship", "launch", "todo", "wip"
        },
        "weight": 1.2,
    },
    "area": {
        "keywords": {
            "security", "compliance", "governance", "trading", "quant", "risk",
            "monitoring", "telemetry", "infrastructure", "operations", "continuous",
            "policy", "protocol", "architecture", "audit", "controller", "pid",
            "enclave", "ebpf", "health", "maintenance", "identity", "did"
        },
        "weight": 1.0,
    },
    "resource": {
        "keywords": {
            "documentation", "reference", "schema", "api", "guide", "library",
            "model", "onnx", "dataset", "handbook", "cheatsheet", "config",
            "specification", "standard", "endpoint", "sdk", "template", "formula"
        },
        "weight": 1.0,
    },
    "archive": {
        "keywords": {
            "deprecated", "superseded", "legacy", "historical", "retired", "old",
            "completed", "closed", "archive", "former", "previous", "prior", "expired"
        },
        "weight": 1.4,
    },
}


def classify_para(text: str) -> dict[str, Any]:
    """Classify text into Project, Area, Resource, or Archive using weighted lexical signals."""
    tokens = set(re.findall(r"\b[a-zA-Z_-]{3,}\b", text.lower()))
    scores: dict[str, float] = {"project": 0.0, "area": 0.0, "resource": 0.0, "archive": 0.0}

    for cat, data in PARA_LEXICON.items():
        matches = tokens.intersection(data["keywords"])
        scores[cat] = len(matches) * data["weight"]

    # Determine winning category
    best_cat = max(scores, key=lambda k: scores[k])
    max_score = scores[best_cat]

    # Default to 'area' if no specific keywords matched
    if max_score == 0.0:
        best_cat = "area"
        confidence = 0.55
    else:
        total = sum(scores.values()) or 1.0
        confidence = min(0.98, 0.65 + (max_score / total) * 0.33)

    return {
        "category": best_cat,
        "confidence": round(confidence, 3),
        "scores": {k: round(v, 2) for k, v in scores.items()},
    }


# =============================================================================
# 2. EPISTEMIC CLASSIFICATION (Fact, Rule, Inference, Goal, Decision, Belief)
# =============================================================================

EPISTEMIC_PATTERNS = [
    (
        EpistemicClass.RULE.value,
        re.compile(
            r"\b(must|always|never|invariant|shall|forbidden|strictly|required|enforce[d]?|guarantee[d]?|mandatory|assert)\b",
            re.IGNORECASE,
        ),
        0.95,
    ),
    (
        EpistemicClass.GOAL.value,
        re.compile(
            r"\b(goal|aim|objective|target|plan to|strive|seek to|intended to|will achieve|vision)\b",
            re.IGNORECASE,
        ),
        0.90,
    ),
    (
        EpistemicClass.DECISION.value,
        re.compile(
            r"\b(decided|chose|selected|resolved|opted|adopted|switched to|determined that)\b",
            re.IGNORECASE,
        ),
        0.92,
    ),
    (
        EpistemicClass.INFERENCE.value,
        re.compile(
            r"\b(suggests|inferred|likely|hypothesize|predicts|implies|probably|deduced|estimated|indicates)\b",
            re.IGNORECASE,
        ),
        0.88,
    ),
    (
        EpistemicClass.BELIEF.value,
        re.compile(
            r"\b(believes|thinks|assumes|speculates|opines|presumes)\b",
            re.IGNORECASE,
        ),
        0.85,
    ),
]


def classify_epistemic(text: str, user_declared: str | None = None) -> dict[str, Any]:
    """Classify epistemic status (rule, goal, decision, inference, belief, or default fact)."""
    # If user/agent explicitly declared a valid epistemic class, honor it with high confidence
    if user_declared:
        try:
            val = EpistemicClass(user_declared.lower()).value
            return {"epistemic_class": val, "confidence": 1.0, "method": "explicit"}
        except ValueError:
            pass

    for ep_class, pattern, conf in EPISTEMIC_PATTERNS:
        if pattern.search(text):
            return {"epistemic_class": ep_class, "confidence": conf, "method": "heuristic"}

    # Default to empirical fact
    return {"epistemic_class": EpistemicClass.FACT.value, "confidence": 0.85, "method": "default_empirical"}


# =============================================================================
# 3. ENTITY & RELATION EXTRACTION (Subject - Predicate - Object Triples)
# =============================================================================

ACTION_VERBS = (
    r"integrat(?:e|es|ed)(?:\s+with)?|us(?:e|es|ed)|utiliz(?:e|es|ed)|enforc(?:e|es|ed)|"
    r"verif(?:y|ies|ied)|anchor(?:s|ed)?|calibrat(?:e|es|ed)|deploy(?:s|ed)?|manag(?:e|es|ed)|"
    r"implement(?:s|ed)?|connect(?:s|ed)?(?:\s+to)?|rout(?:e|es|ed)(?:\s+to)?|refactor(?:s|ed)?|"
    r"configur(?:e|es|ed)|execut(?:e|es|ed)|optimiz(?:e|es|ed)|analyz(?:e|es|ed)|track(?:s|ed)?|"
    r"bind(?:s)?|bound|protect(?:s|ed)?|monitor(?:s|ed)?|stor(?:e|es|ed)|distribut(?:e|es|ed)|"
    r"enabl(?:e|es|ed)|isolat(?:e|es|ed)|generat(?:e|es|ed)|provid(?:e|es|ed)|build(?:s)?|built|"
    r"serv(?:e|es|ed)|index(?:es|ed)?|run(?:s)?|ran|bridg(?:e|es|ed)|link(?:s|ed)?"
)

RELATION_PATTERNS = [
    # Decision / Intent: "We decided to isolate agent memories into separate scopes"
    re.compile(
        r"(?:^|\b)(?:we|team|agent)\s+(?:decided|chose|resolved)\s+to\s+(?P<predicate>[a-z]{3,20})\s+(?P<subject>[A-Za-z0-9_\-\s]{2,30}?)\s+(?:into|as|for)\s+(?P<object>[A-Za-z0-9_\-\s]{2,50})",
        re.IGNORECASE,
    ),
    # Active Transitive Verb with optional modal auxiliary
    re.compile(
        rf"(?:^|\b)(?P<subject>[A-Za-z0-9_\-\s]{{2,40}}?)\s+"
        rf"(?P<predicate>(?:(?:must|should|shall|will|can)\s+(?:always|never|strictly)?\s+)?(?:{ACTION_VERBS}))\s+"
        rf"(?P<object>[A-Za-z0-9_\-\.\:\/]{{2,60}}(?:\s+[A-Za-z0-9_\-\.\:\/]{{1,30}}){{0,6}})",
        re.IGNORECASE,
    ),
    # Copula / Definitional: "X is the / a / an Y" or "X are Y"
    re.compile(
        r"(?:^|\b)(?P<subject>[A-Za-z0-9_\-\s]{2,40}?)\s+"
        r"(?P<predicate>is(?:\s+an?|\s+the)?|are(?:\s+an?|\s+the)?)\s+"
        r"(?P<object>[A-Za-z0-9_\-\.\:\/]{2,60}(?:\s+[A-Za-z0-9_\-\.\:\/]{1,30}){0,6})",
        re.IGNORECASE,
    ),
    # Possession / Invariant Containment: "X has / contains / requires Y"
    re.compile(
        r"(?:^|\b)(?P<subject>[A-Za-z0-9_\-\s]{2,40}?)\s+"
        r"(?P<predicate>has|have|contains|requires|maintains|stores)\s+"
        r"(?P<object>[A-Za-z0-9_\-\.\:\/]{2,60}(?:\s+[A-Za-z0-9_\-\.\:\/]{1,30}){0,6})",
        re.IGNORECASE,
    ),
]


def extract_triples(text: str) -> list[dict[str, Any]]:
    """Extract structured Subject-Predicate-Object triples using syntactic patterns."""
    triples: list[dict[str, Any]] = []
    # Split into individual sentence propositions
    sentences = [s.strip() for s in re.split(r"[.!?;\n]+", text) if s.strip()]

    for sentence in sentences:
        for pat in RELATION_PATTERNS:
            m = pat.search(sentence)
            if m:
                groups = m.groupdict()
                raw_sub = groups.get("subject", "").strip().rstrip(".,")
                raw_obj = groups.get("object", "").strip().rstrip(".,")
                raw_pred = groups.get("predicate", "is_a").strip().replace(" ", "_").lower()

                # Clean subject: strip leading determiners and trailing modal leakages
                sub = re.sub(r"^(?:the|a|an)\s+", "", raw_sub, flags=re.IGNORECASE)
                sub = re.sub(r"\s+(?:must|should|shall|will|can)(?:\s+(?:always|never|strictly))?$", "", sub, flags=re.IGNORECASE).strip()

                # Clean predicate: strip modal prefixes for clean graph labeling
                pred = re.sub(r"^(?:must_always_|must_|should_|will_|can_)", "", raw_pred)

                # Clean object: truncate long subordinate prepositional clauses
                obj = re.split(r"\s+(?:with|across|before|without|to prevent|in order to)\b", raw_obj, flags=re.IGNORECASE)[0].strip("., ")

                # Filter out stopword-only or noise subjects
                if len(sub) >= 2 and len(obj) >= 2 and sub.lower() not in {"this", "that", "there", "it"}:
                    triples.append({
                        "subject": sub,
                        "predicate": pred,
                        "object": obj,
                        "confidence": 0.95,
                    })
                break

    return triples
