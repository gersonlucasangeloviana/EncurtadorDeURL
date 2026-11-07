class ApplicationError(Exception):
    def __init__(self, message: str, code: str | None = None):
        super().__init__(message)
        self.code = code


class InvalidInput(ApplicationError):
    pass


class Conflict(ApplicationError):
    pass


class NotFound(ApplicationError):
    pass


class Unavailable(ApplicationError):
    pass


class StorageFailure(Exception):
    pass


class CacheUnavailable(Exception):
    pass
