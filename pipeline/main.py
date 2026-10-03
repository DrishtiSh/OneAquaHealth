"""Orchestrates the offline pipeline end to end: ingestion -> weather -> graph ->
exposure -> model -> detectors -> nlg -> benchmark -> freeze_snapshot (stages 1-8 and 11).

The benchmark (Stage 11) runs before the freeze so the snapshot can carry its report; it only
reads the outputs of Stages 1-7 and never feeds back into them."""

from pipeline.benchmark import benchmark
from pipeline.detectors import detectors
from pipeline.exposure import exposure
from pipeline.graph import river_graph
from pipeline.ingestion import ingest
from pipeline.model import bayesian_model
from pipeline.nlg import summarize
from pipeline.snapshot import freeze_snapshot
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
    print("Stage 7: plain-language findings")
    summarize.run()
    print("Stage 11: benchmark vs the simulator's ground truth")
    benchmark.run()
    print("Stage 8: freeze snapshot")
    freeze_snapshot.run()


if __name__ == "__main__":
    run()
