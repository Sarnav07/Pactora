---
name: pactora-wallet-setup
description: Help a human operator provision Pactora's protected testnet wallet service and connect the shopping MCP. Setup only, in a separate operator environment; never authorizes purchases or handles secrets in model context.
---

This is an operator workflow. Do not install or invoke it in the shopping agent's
runtime. If the current environment is the shopping runtime, stop setup and explain
that the user must use a separate trusted operator session.

Use the project's docs/WALLET_PRIVACY.md and docs/AGENT_SETUP.md for the current
commands, configuration and trust boundaries. Inspect public source and templates
only. Do not read secret configurations, environment dumps, wallet databases,
mnemonics, private keys, cookies, receipts or invoice access tokens. Never ask for
secrets in chat or generate them in tool output. Secret provisioning occurs in a
separate trusted terminal outside the model's tool session.

Guide the operator to provision a dedicated small testnet wallet under a separate
OS identity/protected host, deploy the services, and provision an Ed25519 approval
key in the private backend plus its public key in the wallet service. Configure
matching wallet identity and network. Keep the wallet API token outside the MCP
process. Only the restricted gateway token belongs in MCP configuration, supplied
through protected local configuration rather than chat.

Keep mainnet and live Bitrefill settlement gates closed. Never fund a wallet or
send a transaction as part of setup. Use simulator checks first, then the documented
native regtest and Tor-routing checks; report unexecuted checks honestly. Do not
claim containers isolate a shopping agent with Docker administrator access.
