# CHANGELOG

Servo is an Open Source framework supporting Continuous Optimization of infrastructure
and applications via the Opsani optimization engine. Opsani provides a software as a
service platform that optimizes the resourcing and configuration of cloud native
applications to reduce operational costs and increase performance. Servo instances are
responsible for connecting the optimizer service with the application under optimization
by linking with the metrics system (e.g. Prometheus, Thanos, DataDog, etc) and the
orchestration system (e.g. Kubernetes, CloudFormation, etc) in order to apply changes
and evaluate their impact on cost and performance.

Servo is distributed under the terms of the Apache 2.0 license. 

This changelog catalogs all notable changes made to the project. The format
is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/). Releases are 
versioned in accordance with [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.2.0] - 2020-07-13

Initial public release.

There is quite a bit of functionality available. Please consult the README.md at the
root of the repository for details. The major limitations at the moment are around porting
of connectors to the new architecture. At the moment a connectfor for the Vegeta load 
generator and Kubernetes resource management are bundled in the distribution. The connector
catalog will expand rapidly but porting does involve some effort in order to leverage the
full value of the new system.

### Added
- Configuration management. Generate, validate, and document configuration via JSON Schema.
- Support for dispatching events for communicating between connectors.
- Initial support for check, describe, measure, and adjust operations.
- Vegeta and Kubernetes connectors for testing load generation and adjustments.
- Init command for setting up an assembly.
- Informational commands (`servo show [metrics | events | components]`).
- Foundational documentation within the code and in the README.md at the root of the repository.
- Assets for running a containerized servo under Kubernetes or Docker / Docker Compose.

[Unreleased]: https://github.com/opsani/servox/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/opsani/servox/releases/tag/v0.2.0