# Remote Identifier Length Red Evidence

Pre-implementation head: `3fdfef3dd47c6238e845f3aaddc86615b8ece56b`.

Focused tests were written before production changes and failed for the intended reasons: persistence accepted endpoint aliases longer than 128 characters and provider batch identifiers longer than 256 characters, while the durable client reached reservation/provider seams before rejecting an overlong alias. These limits already existed in the PostgreSQL schema and therefore had to be enforced before avoidable remote/local split-brain behavior.
