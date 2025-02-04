"""MEF Eline Exceptions."""


class MEFELineException(Exception):
    """MEF Eline Base Exception."""


class EVCException(MEFELineException):
    """EVC Exception."""


class ValidationException(EVCException):
    """Exception for validation errors."""


class FlowModException(MEFELineException):
    """Exception for FlowMod errors."""


class PathFinderException(MEFELineException):
    """Exception related to pathfinder request."""


class InvalidPath(MEFELineException):
    """Exception for invalid path."""


class DisabledSwitch(MEFELineException):
    """Exception for disabled switch in path"""


class EVCPathNotInstalled(MEFELineException):
    """Exception raised when a path was not installed properly."""


class ActivationError(EVCException):
    """Exception when an EVC couldn't get activated."""


class DuplicatedNoTagUNI(MEFELineException):
    """Exception for duplicated no TAG UNI"""
    def __init__(self, msg: str) -> None:
        self.msg = msg

    def __repr__(self) -> str:
        return f"DuplicatedNoTagUNI, {self.msg}"
