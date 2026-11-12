"""Jev-Interaction: full-duplex voice where every interaction decision is a question Jev answers.

    from jev_interaction import Session, Profile, JevClient, preset
"""
from .config import Config, Pace
from .decisions import DECISIONS, Decision, register
from .judge import JevClient
from .policy import ArgmaxPolicy, Policy, SamplePolicy, ThresholdPolicy
from .presets import PRESETS, preset
from .profile import Profile
from .recorder import Recorder
from .session import Session

__all__ = ["Session", "Profile", "Config", "Pace", "preset", "PRESETS", "JevClient", "Recorder",
           "Decision", "DECISIONS", "register", "Policy", "SamplePolicy", "ThresholdPolicy", "ArgmaxPolicy"]
__version__ = "0.1.0"
