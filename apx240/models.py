from dataclasses import dataclass, asdict, field

@dataclass
class Evidence:
    source_id: str
    source_type: str
    filename: str
    page: int
    section: str
    chunk_id: str
    version_id: str
    snippet: str
    historical_only: bool = False
    authority: str = ''
    usage: str = ''

@dataclass
class FaultReport:
    report_id: str
    equipment_model: str
    knowledge_version: str
    status: str
    phenomenon: str
    known_facts: list
    possible_causes: list
    evidence: list
    safety_prerequisites: list
    troubleshooting_order: list
    missing_information: list
    expert_required: bool
    escalation_reason: str
    historical_comparison: list
    retrieval: dict
    trace: list
    work_order: dict
    current_observations: dict = field(default_factory=dict)
    model_review: dict = field(default_factory=dict)
    session: dict = field(default_factory=dict)
    stop_policy: dict = field(default_factory=dict)
    execution_metadata: dict = field(default_factory=dict)
    next_best_question: dict = field(default_factory=dict)
    change_summary: list = field(default_factory=list)

    def to_dict(self):
        from .validation import validate_report
        return validate_report(asdict(self))
