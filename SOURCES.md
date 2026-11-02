# Sources and provenance

- Baseball Savant Statcast Search CSV documentation: https://baseballsavant.mlb.com/csv-docs
- pybaseball Statcast documentation: https://github.com/jldbc/pybaseball/blob/master/docs/statcast.md
- pybaseball package: https://pypi.org/project/pybaseball/

The downloader uses pybaseball to retrieve pitch-level Statcast data and filters completed plate appearances with `events == home_run`. Source schema and field availability may change; preserve the raw response and retrieval timestamps. Park geometry sources must be documented per stadium and season before use.
