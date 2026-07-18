from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class DomainError(Exception):
    code: str
    message: str
    status_code: int
    details: dict[str, Any] = field(default_factory=dict)

    def __str__(self) -> str:
        return self.message


def not_found(message: str = "The requested resource was not found.") -> DomainError:
    return DomainError("NOT_FOUND", message, 404)


def conflict(code: str, message: str) -> DomainError:
    return DomainError(code, message, 409)


def invalid(code: str, message: str, details: dict[str, Any] | None = None) -> DomainError:
    return DomainError(code, message, 422, details or {})

