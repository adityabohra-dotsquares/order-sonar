from pydantic import BaseModel
from typing import List, Optional

class TrackEvent(BaseModel):
    franchiseCode: Optional[str] = None
    franchiseName: Optional[str] = None
    scanType: Optional[str] = None
    labelNo: Optional[str] = None
    status: Optional[str] = None
    scannedDateTime: Optional[str] = None  # String because it might not be ISO8601 directly or easy to parse
    description: Optional[str] = None
    scanTypeDescription: Optional[str] = None

class TrackResponse(BaseModel):
    data: List[TrackEvent] = []
