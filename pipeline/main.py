"""Orchestrates the offline pipeline end to end: ingestion -> weather -> graph ->
exposure -> model -> detectors -> nlg -> freeze_snapshot (stages 1-8)."""

from pipeline.exposure import exposure
from pipeline.graph import river_graph
from pipeline.ingestion import ingest
from pipeline.weather import weather


def run():
    print("Stage 1: ingestion")
    ingest.run()
    print("Stage 2: weather")
    weather.run()
    print("Stage 3: river graph")
    river_graph.run()
    print("Stage 4: exposure")
    exposure.run()
    raise NotImplementedError("Stages 5-8 not yet implemented")


if __name__ == "__main__":
    run()
