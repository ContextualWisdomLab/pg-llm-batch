# PostgreSQL Image Schema Mirror Red Evidence

Pre-fix head: `492dc5a3d3240fcd362f541e0f623d1eceb3d22c`.

A permanent test compared the Docker PostgreSQL initialization schema with the packaged canonical schema and failed before the mirror was changed. The stale image schema omitted the durable lifecycle table and observation sequence as well as earlier canonical integrity migrations. A container could therefore build successfully while initializing a materially different database contract.
