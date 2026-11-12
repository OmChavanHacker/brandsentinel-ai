from enum import Enum

class WorkflowState(str, Enum):
    WORKSPACE_LOADED = "WORKSPACE_LOADED"
    REVIEWED = "REVIEWED"
    PENDING_MANAGER = "PENDING_MANAGER"
    PENDING_LEGAL = "PENDING_LEGAL"
    PENDING_DUAL = "PENDING_DUAL"
    APPROVED = "APPROVED"

class WorkflowTransitionError(Exception):
    def __init__(self, message: str, code: str = "INVALID_TRANSITION") -> None:
        super().__init__(message)
        self.message = message
        self.code = code

class Workflow:
    def __init__(self) -> None:
        self.state = WorkflowState.WORKSPACE_LOADED

    def transition(self, action: str, role: str, needs_legal: bool = False) -> WorkflowState:
        if action == "review":
            self.state = WorkflowState.REVIEWED
            return self.state
        if action == "send_for_approval":
            if self.state != WorkflowState.REVIEWED:
                raise WorkflowTransitionError("Run governance check before sending for approval.", "INVALID_TRANSITION")
            self.state = WorkflowState.PENDING_DUAL if needs_legal else WorkflowState.PENDING_MANAGER
            return self.state
        if action == "approve":
            if self.state == WorkflowState.PENDING_LEGAL and role != "LEGAL":
                raise WorkflowTransitionError("Only LEGAL can approve this draft.", "ROLE_NOT_AUTHORIZED")
            if self.state == WorkflowState.PENDING_DUAL:
                raise WorkflowTransitionError("Dual approval requires separate MARKETING_HEAD and LEGAL_COUNSEL sign-offs.", "ROLE_NOT_AUTHORIZED")
            if self.state == WorkflowState.PENDING_MANAGER and role not in ("MANAGER", "LEGAL"):
                raise WorkflowTransitionError("MANAGER or LEGAL role required to approve.", "ROLE_NOT_AUTHORIZED")
            if self.state not in (WorkflowState.PENDING_LEGAL, WorkflowState.PENDING_MANAGER):
                raise WorkflowTransitionError("Draft must be sent for approval first.", "INVALID_TRANSITION")
            self.state = WorkflowState.APPROVED
            return self.state
        raise WorkflowTransitionError(f"Unknown action: {action}", "INVALID_TRANSITION")
