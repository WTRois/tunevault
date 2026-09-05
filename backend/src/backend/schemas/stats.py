from pydantic import BaseModel


class StatsOverviewResponse(BaseModel):
    total_songs: int
    total_artists: int
    total_albums: int
    total_genres: int
    total_duration: float  # In seconds
    total_file_size: int  # In bytes
    codecs: dict[str, int]
