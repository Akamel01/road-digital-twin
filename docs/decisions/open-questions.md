# Open questions

The operator answers these; nothing here is assumed.

## Digital twin
- Can 3D vector geometry (nodes and polylines with z) and plan/profile drawings fit in v1, or should v1 stop at 2D plus a vertical profile? (Claude recommends: in v1.)
- Which drawing output format: DXF (CAD), PDF sheets, or both?
- Which coordinate reference system for each source (nuScenes local frames versus a projected CRS for Vancouver)?
- Should the old `AV_Safety` repo be archived with a pointer? (Claude recommends archiving; it can be undone.)

## Risk engine (later)
- Prediction horizon: is 3 s right?
- How the twin feeds the risk engine (geometry as covariates? conflict zones?).

## Safety case (later)
- Which claims the first GSN skeleton should carry.
- Check UL 4600, ISO 21448, ISO 34502, ISO 34503 / SAE J3259 and the NHTSA AV framework against primary sources.
