import enum


class PageFormat(str, enum.Enum):
    DUPLEX = "DUPLEX"
    SIMPLEX = "SIMPLEX"


class FeedDirection(str, enum.Enum):
    ASCENDING = "ASCENDING"
    DESCENDING = "DESCENDING"


class IdSource(str, enum.Enum):
    SEQUENTIAL = "SEQUENTIAL"
    DOCUMENT_EXTRACT = "DOCUMENT_EXTRACT"


class JobStatus(str, enum.Enum):
    DRAFT = "DRAFT"
    PROCESSING = "PROCESSING"
    PARTIAL = "PARTIAL"
    COMPLETE = "COMPLETE"
    ERROR = "ERROR"


class VerificationStatus(str, enum.Enum):
    OK = "OK"
    MISMATCH = "MISMATCH"
    ERROR = "ERROR"


class ImportMethod(str, enum.Enum):
    MANUAL = "MANUAL"
    PASTE = "PASTE"
    CSV = "CSV"


class JobMode(str, enum.Enum):
    PRESET = "PRESET"
    TEMPLATE = "TEMPLATE"


class OutputMode(str, enum.Enum):
    COMBINED = "COMBINED"
    SEPARATE = "SEPARATE"


class SessionStatus(str, enum.Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"


class RegionRole(str, enum.Enum):
    GROUP_BOUNDARY = "GROUP_BOUNDARY"
    PAGE_COUNTER = "PAGE_COUNTER"
    UNIQUE_ID = "UNIQUE_ID"
    CUSTOM = "CUSTOM"


class MatchType(str, enum.Enum):
    EXACT = "EXACT"
    REGEX = "REGEX"
    NUMERIC = "NUMERIC"
