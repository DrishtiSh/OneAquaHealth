"""Orchestrates the offline pipeline end to end: ingestion -> weather -> graph ->
exposure -> model -> detectors -> nlg -> freeze_snapshot (stages 1-8)."""

from pipeline.detectors import detectors
from pipeline.exposure import exposure
from pipeline.graph import river_graph
from pipeline.ingestion import ingest
from pipeline.model import bayesian_model
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
    print("Stage 5: Bayesian model (W/H)")
    bayesian_model.run()
    print("Stage 6: detectors")
    detectors.run()
    raise NotImplementedError("Stages 7-8 not yet implemented")


if __name__ == "__main__":
    run()
