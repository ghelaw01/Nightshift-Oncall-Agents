"""Night Shift: an AI on-call team that turns a production alert into a reviewed, tested fix."""
from .agents import Resolution, ask_human, auto_approve, respond, solo_responder
from .evaluate import grade
from .incidents import BY_ID, INCIDENTS, Incident
from .llm import make_model
from .workspace import Workspace

__version__ = "0.1.0"
__all__ = ["BY_ID", "INCIDENTS", "Incident", "Resolution", "Workspace", "ask_human", "auto_approve",
           "grade", "make_model", "respond", "solo_responder"]
