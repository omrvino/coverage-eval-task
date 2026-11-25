class TallyError(Exception):
    """Base class for every error this package raises on purpose."""


class TermsError(TallyError):
    pass


class InvoiceError(TallyError):
    pass


class PaymentError(TallyError):
    pass


class ImportFormatError(TallyError):
    pass


class StoreError(TallyError):
    pass


class ConflictError(StoreError):
    pass
