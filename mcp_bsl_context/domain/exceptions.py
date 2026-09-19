"""Domain exception hierarchy."""


class DomainException(Exception):
    pass


class InvalidSearchQueryException(DomainException):
    pass


class PlatformTypeNotFoundException(DomainException):
    pass


class TypeMemberNotFoundException(DomainException):
    pass


class PlatformContextLoadException(DomainException):
    pass
