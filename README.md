# MMDBBench

[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.23481288.svg)](https://doi.org/10.5281/zenodo.23481288)

An open benchmark of multi-model databases: databases that serve tables, time series, documents, graphs, key-values, and vectors from one storage engine. Specialist databases built for a single model run the same tasks as per-model baselines. The tasks run on the same x86 Linux machine with published settings and pinned versions, in SQL, Cypher, and native query languages, and the raw result rows are open, so anyone can check a result and any vendor can tell us when a setting is not what they recommend.

## Why

Agent memory is becoming an important workload. An agent keeps what it learns as facts and events (documents and tables), the relations between them (a graph), their meaning (vectors), their words (text), and their time. It asks one database to serve all of these at once, usually in many small collections that change on every turn: a few inserts, then a query right away, with other agents writing next to it. Most benchmarks measure one data model at a time, so the cost of putting them in one engine is not visible. MMDBBench measures multi-model databases across the models, with the specialist engines as per-model baselines, and it states the settings, versions and hardware of every result.

The benchmark was called DBBench until 2026-11-07. The old URLs for the repository and the project page keep working.

- **Results:** <https://humem.ai/research/mmdbbench>
- **Documentation:** <https://docs.humem.ai/mmdbbench/> (methodology, engine settings, how to reproduce, how to contribute a correction)

## Lanes

Tables (documents and SQL analytics), graphs (interactive and analytical queries), vectors (dense and sparse), time series, cross-model queries, and lifecycle (durability and restarts).
Engines are compared inside each lane; an engine appears only in the lanes it is built for.

## Status

The benchmark code is in [`experiments/`](experiments/): the runner, the engine adapters, the landing and page generators, the gates and the pins. It was copied in steps from
[humemai/arcadedb-embedded-python](https://github.com/humemai/arcadedb-embedded-python), and [experiments/PROVENANCE.md](experiments/PROVENANCE.md) names the origin commit of every copy. The benchmark host still runs its current stages from that repository, which is retiring. New work and new issues go to this repository. The results are published on the project page above.
Small self-contained studies that run today live under `experiments/`, starting with the [SQL acceptance corpus](experiments/sql-corpus/README.md).
The documented protocol version is `2026-11`, in development until its first release.

## Citing MMDBBench

Cite a release of this repository rather than the web page, because the page changes with every measurement. Each release is archived on Zenodo with its own DOI, and GitHub's "Cite this repository" button gives an APA and a BibTeX entry from [CITATION.cff](CITATION.cff).

The DOI for all versions is [10.5281/zenodo.23481288](https://doi.org/10.5281/zenodo.23481288); the Zenodo record lists the DOI of each release, for when the exact numbers matter.

```bibtex
@misc{kim2026mmdbbench,
  title     = {{MMDBBench}: an open benchmark of multi-model databases},
  author    = {Kim, Taewoon},
  year      = {2026},
  publisher = {Zenodo},
  doi       = {10.5281/zenodo.23481288},
  url       = {https://github.com/humemai/mmdbbench},
}
```

## Related work

Four academic benchmarks address multi-model databases: UniBench, M2Bench, MMSBench-Net, and GRBench. [Related work](docs/related-work.md) says what each covers and how MMDBBench differs.

## Contributing

If a setting we use for your engine differs from what you recommend, open an issue with the engine, the version, what differs and where your documentation says so; see
[Contribute](https://docs.humem.ai/mmdbbench/latest/contribute/). A corrected configuration is re-run, and the earlier result stays visible in the history.

## License

Apache License 2.0, see [LICENSE](LICENSE).
