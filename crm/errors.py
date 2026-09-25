"""Stable machine-readable errors; never reflect untrusted payloads in messages."""
class CRMError(Exception):
    def __init__(self, code: str, message: str = '', exit_code: int = 3, retryable: bool = False):
        super().__init__(message or code)
        self.code, self.exit_code, self.retryable = code, exit_code, retryable

class Conflict(CRMError):
    def __init__(self, code='CONFLICT', message='Conditional mutation did not pass.'):
        super().__init__(code, message, 5)

class Unsupported(CRMError):
    def __init__(self, code, message='Feature is not admitted in this release.'):
        super().__init__(code, message, 8)
