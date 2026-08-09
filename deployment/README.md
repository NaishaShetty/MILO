# deployment/

Purpose
-------
Home for everything needed to run this project outside a local dev
checkout -- configuration for deploying the perception/planning stack
to a real robot, a cloud inference endpoint, or a long-running
simulation host.

Why it's separate from `backend/`
-------------------------------------
`backend/` answers "how does perception/planning work." `deployment/`
answers "how does a working system get onto a target environment" --
environment-specific configuration, secrets management, process
supervision, and (per `docs/architecture/perception_pipeline.md`'s
simulator-swap design) eventually the config that points the
`Simulator` abstraction at a real robot instead of AI2-THOR. Neither
concern should leak into the other: `backend/` code should never
hardcode a deployment target, and deployment configuration should
never need to know how a model is implemented internally.

Planned contents
-----------------
- Environment-specific config (dev / simulation / real-robot).
- Process/service definitions for running `VisionAgent` +
  `PerceptionPipeline` continuously rather than as a one-shot script.
- Once a real robot target exists: the concrete `Simulator`-interface
  implementation and its deployment config, kept out of
  `backend/simulator/` itself so swapping targets doesn't touch the
  interface.

See also `docker/README.md` for containerization, which this
directory is expected to reference once a target is defined.

Nothing is implemented here yet -- this file establishes the
directory's purpose ahead of that work.
