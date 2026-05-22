# AI Agent Implementation Checklist

> **Important Notice**
>
> This Markdown file is the official shared checklist basis for all customer AI agent implementations.
>
> Claude, Codex, AI assistants, developers, and automation tools must not modify, rewrite, remove, or restructure this checklist unless explicitly approved by management.
>
> All teams must use the same checklist as the implementation baseline to ensure consistency across OpenClaw, Nanobot, Nemoclaw, Zeroclaw, Slack agents, app-based agents, MCP agents, and future AI agent systems.
>
> Project-specific notes, implementation details, or customer-specific changes should be added in a separate file instead of editing this checklist directly.

This checklist is intended for building customer-facing AI agents across different frameworks and runtimes such as OpenClaw, Nanobot, Nemoclaw, Zeroclaw, and other future agentic AI systems.
    
The goal is to make sure every customer AI agent is secure, isolated, reliable, auditable, and ready for production use.

---

## Required Project Security Documentation

This checklist is a shared implementation guide and baseline. Not every item will apply to every project, customer, agent, or deployment setup.

For every AI agent project, the team must create a separate security documentation file named `SECURITY.md`.

The `SECURITY.md` file must explain how security is actually implemented for that specific project.

It should document the actual implementation for:

- server hardening
- port restrictions
- firewall rules
- SSH access
- customer isolation
- runtime isolation
- secrets management
- tool permissions
- MCP or connector permissions
- logging and monitoring
- audit trail
- backups and recovery
- human approval rules

If a checklist item is not applicable to a specific project, the team must mention that in `SECURITY.md` and explain why it is not required.

This checklist file must remain unchanged as the shared baseline. Project-specific security details must be written in `SECURITY.md`, not in this checklist.

---

## 1. Agent Identity and Behavior

Defines who the agent is, what its role is, how it should communicate, what language or tone it should use, and what boundaries it must follow.

This includes customer-specific behavior, such as how the agent should respond in Slack, inside an app, through chat, or when acting as a support, operations, sales, or automation assistant.

The agent should have a clear purpose and should not act outside its assigned role.

---

## 2. Customer and Runtime Isolation

Ensures every customer has their own separated environment, configuration, memory, tools, credentials, logs, and workspace.

This prevents one customer’s data, agent behavior, connected accounts, or private configuration from being accessed by another customer.

Isolation can be implemented using separate containers, Linux users, folders, databases, runtime instances, or deployment environments depending on the system design.

---

## 3. Server Security and Network Hardening

Covers the security of the server where the agents are running.

This includes operating system updates, firewall rules, SSH security, fail2ban, restricted ports, limited users, permission control, and protection against unauthorized access.

Internal services such as Ollama, LiteLLM, MCP servers, databases, Redis, dashboards, internal APIs, and agent runtimes should not be exposed publicly unless protected by authentication, IP restriction, VPN, or secure reverse proxy rules.

Only required ports should be open, and access should be limited as much as possible.

---

## 4. Tool, MCP, and Connector Permissions

Defines what tools each agent is allowed to use and what actions are restricted.

This includes Gmail, Facebook, Slack, Salesforce, HubSpot, databases, internal APIs, file access, browser tools, command execution tools, and other MCP or third-party connectors.

Each customer agent should only receive the tools required for its purpose.

Permissions should follow the least-privilege rule, meaning the agent should only have the minimum access needed to complete its assigned tasks.

---

## 5. Secrets and Credential Management

Controls how API keys, OAuth tokens, database passwords, environment variables, private keys, and customer credentials are stored and accessed.

Secrets should never be exposed in agent conversations, logs, memory, user-visible files, or tool responses.

Each customer’s credentials should be isolated from other customers.

Secrets should be stored securely, rotated when needed, and removed immediately when access is no longer required.

---

## 6. Memory, Context, and Data Privacy

Defines what the agent can remember, what context it can use, and how customer data is protected.

This includes short-term memory, long-term memory, conversation history, uploaded files, retrieved data, tool results, and customer-specific knowledge.

The agent should only use relevant customer-specific context and should not mix data between customers.

Sensitive data should not be stored unnecessarily, and memory should have clear rules for updates, deletion, and retention.

---

## 7. Workflow, Approval, and Safety Controls

Defines how the agent understands tasks, plans actions, executes workflows, verifies results, and handles risky operations.

The agent should ask for approval before sensitive, public, destructive, or irreversible actions.

This includes sending emails, deleting records, changing CRM data, posting public messages, modifying production systems, updating billing or account settings, and running dangerous commands.

The agent should also verify important actions before reporting that a task is complete.

---

## 8. Logging, Monitoring, and Audit Trail

Tracks what the agent is doing across conversations, tool usage, errors, connector calls, cost, execution time, and important actions.

For customer-facing systems, audit trails are important because the team needs to know who requested an action, what the agent did, what tool was used, what data changed, and when it happened.

Logs should be useful for debugging, security review, customer support, and incident investigation.

Logs should not expose secrets or unnecessary private data.

---

## 9. Deployment, Backup, and Recovery

Defines how agents are deployed, updated, restarted, backed up, and restored.

For pyinfra-based deployments, this should include repeatable deployment scripts, version-controlled configuration, service management, health checks, monitoring, rollback plans, and environment-specific settings.

Important customer data such as agent configuration, memory, workflow rules, credentials metadata, and logs should have a backup and recovery plan.

The system should be able to recover from server failure, bad deployment, corrupted configuration, or failed updates.

---

## 10. Testing, Cost, and Production Readiness

Ensures the agent is ready before it is used by a real customer.

Testing should cover normal workflows, tool failures, API errors, prompt injection, memory behavior, permission boundaries, approval handling, customer isolation, and security rules.

Cost controls should include model routing, token usage limits, rate limits, fallback models, and customer-level budget rules.

Before production launch, the agent should be secure, isolated, monitored, backed up, tested, cost-controlled, and ready for real customer use.

---

## Summary

Every customer AI agent should have:

1. Clear identity and behavior
2. Customer and runtime isolation
3. Hardened server and restricted network access
4. Controlled tool, MCP, and connector permissions
5. Secure secrets and credential management
6. Safe memory, context, and data privacy rules
7. Workflow approval and safety controls
8. Logging, monitoring, and audit trail
9. Reliable deployment, backup, and recovery
10. Testing, cost control, and production readiness

This checklist should be reviewed before deploying any AI agent for internal use, customer use, or production automation.