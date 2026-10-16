# Validation Details for Reviewers

[中文](VALIDATION_CN.md) · Customer steps are in [README.md](README.md)

This page is for readers who want to check the numbers: how each path was measured, the input and result of every run, what was not tested, and how to recompute everything offline. A customer following the steps does not need it.

## Architecture and Metrics

The narrative is organized around two questions: who runs the session lifecycle, and whose node the session's micro-VM runs on. The workload contract is comparable, but the container is not identical across all four paths: A and C use the workshop's [module-03 reflection agent](https://github.com/oxcp/ainotes/blob/905f2c2/agenthost/module-03/agent-src/app/main.py); B uses its distinct [module-02 Agent Framework agent with ResponsesHostServer](https://github.com/oxcp/ainotes/blob/905f2c2/agenthost/module-02/agent-src/main.py); D uses the private-preview sample `agent-framework-agent-basic-responses-byoaks`. All call `gpt-5.4-mini` and exercise a new stateful session plus a follow-up.

- **A · ACA Sandboxes.** The agent's container image becomes a sandbox disk image; one sandbox per measured session, `cpu 1000m`, `memory 2048Mi` (the M tier), auto-suspend after 900 s in Memory mode, a VNet connection, a private Blob volume at `/app/app/data` and port 8080 in on-demand mode. The control plane is ARM (`Microsoft.App/sandboxGroups`), the data plane `management.azuredevcompute.io`; the caller needs *Container Apps SandboxGroup Data Owner*.
- **B · Foundry hosted agent.** `azd ai agent init` binds the workshop's `azure.yaml` to the existing project and `azd deploy` builds and publishes a version. Learn describes per-session VM-isolated sandboxes, `$HOME` and `/files` persisted across idle, an idle timeout of 2–60 minutes (default 15) and deletion after 30 days of inactivity.
- **C · AKS + agent-sandbox.** AKS with Workload Identity and the Blob CSI driver, an Azure Linux node pool with `KataVmIsolation` (`Standard_D4s_v3` in our run), agent-sandbox `v0.5.2` (`agents.x-k8s.io/v1beta1`, kind `Sandbox`), a Blob PVC for state and a LoadBalancer restricted to one source address. Suspend and resume are `spec.operatingMode: Suspended | Running`; the pod is deleted and file state is restored from Blob, not from a memory snapshot. Learn names the stack: Azure Linux host, Microsoft Hyper-V, Cloud Hypervisor VMM, Kata Containers.
- **D · BYO-AKS.** The initial one-Kata-node read-back had 13 runtime pods in `foundry-system`: 9 fixed Deployment replicas (router ×3 behind a LoadBalancer on `:443`, controller ×2, identity proxy ×2, telemetry controller ×2) plus 4 DaemonSets. Each DaemonSet adds one pod per matching Kata node, so the total grows with the node pool. Each session is its own Deployment, ReplicaSet and pod with `runtimeClassName: kata-vm-isolation` in a per-project namespace.
- **E · E2B on Azure VM.** An Ubuntu 24.04 LTS Gen2 VM (`Standard_D4ds_v7` with nested virtualization `/dev/kvm`) runs the open-source E2B Embed Docker Compose stack (`e2b-dev/runtime` at `588e5b9`). Each `Sandbox.create("base")` boots a Firecracker `v1.14-0.2.0` micro-VM (2 vCPU, 512 MB, guest kernel `6.1.177+`); `beta_pause` snapshots memory and disk (`vm_state` + `mem_file`) to the VM's OS disk, where E2B also keeps its templates, and `Sandbox.connect` restores it. A Foundry Prompt Agent (`gpt-5.4-mini`) calls the sandbox via a function tool over ports `3000` and `3002`. Embed is [one machine by design](https://github.com/e2b-dev/runtime/blob/588e5b9500b0987bc5a700d91483b03f0ae7d2a2/embed/README.md#when-one-node-is-not-enough), answers over plain HTTP, and has no persistent data volume; `e-2026-10-15-multi` runs two independent installs side by side.

Why these clocks:

| Metric | Start | End | Measured where |
|---|---|---|---|
| Cold, A (component sum) | SDK create call → Running | add first `/reflect` answer duration | create on the client; answer inside the sandbox |
| Cold, B and D | client POST of a new session | full response body read | client, through the Foundry endpoint |
| Cold, C (component sum) | `kubectl apply` → Sandbox Ready | add first answer duration at the LoadBalancer | client via its own LoadBalancer; model inference still uses APIM |
| Warm | request of the next turn | its answer | as for cold |
| Resume, A (component sum) | SDK resume call → Running | add first answer duration after resume | resume on the client; answer inside |
| Resume, C | `operatingMode: Running` patch | first answer at the LoadBalancer | client |
| Pod lost | pod deleted | replacement pod Ready (Kubernetes timestamps) | cluster |
| B session API: create, stop | `POST .../endpoint/sessions`, `POST .../sessions/{id}:stop` | the session reads `active`, `idle` | client; failed attempts and their 2 s pauses included |
| Cold, E A protocol (component sum) | `Sandbox.create("base")` → it returns | add the first Prompt Agent turn: first `POST /openai/v1/responses` until the final answer, every tool round trip included | the tool's process; on the E2B host VM in E's runs |
| Cold, E D protocol | conversation create | the turn's final answer, with `Sandbox.create` in between (one stopwatch) | as above |
| Resume, E (component sum) | `Sandbox.connect` → it returns | add the first turn after it | as above |
| Pause, E | `beta_pause` | it returns | as above |

E's clocks and those of `b-2026-10-15-sessions` are `time.perf_counter()` in the measuring process; a range is the minimum to the maximum. A and E wait 5 s between the end of stop or pause and the start of resume, outside every clock. The E concurrency tables give sandbox create plus turn 1, the clock of the 2026-10-14 driver.

A's answers are timed inside the sandbox because the 2026-09-27 run could not reach the port from the operator address (the port's IP rule saw rotating Azure egress addresses). The paths therefore do not share a network path, and a row compares implementations, not networks.

A's cold is `create_total_s + first.guest_s` and resume-to-answer is `resume_total_s + first_after_resume.guest_s`: component sums, not a single end-to-end client stopwatch. C's cold is also a component sum. For both A and C, stop and idle waiting are excluded from resume-to-answer.

## What the Scripts Run

[`tools/aca_sandbox.py`](tools/aca_sandbox.py) (A), with `azure-containerapps-sandbox` 0.1.0b4:

| Step | SDK or CLI call |
|---|---|
| `vnet` | `SandboxGroupManagementClient.create_or_update_vnet_connection(group, ACA_VNET_CONNECTION, ACA_SUBNET_ID)` |
| `image` | `az acr login --expose-token`, then `SandboxGroupClient.begin_create_disk_image(ACA_IMAGE, registry_credentials=…)` |
| `volume` | `create_volume(ACA_VOLUME, type="AzureBlobByo", storage_container_resource_id=…, auth=UserAssigned identity)` |
| `create` | `_do_create_sandbox(...)` with the configuration above, then poll `get_sandbox` every 0.25 s until Running |
| `ask` | `sandbox.exec("python3 -c …")`, which POSTs `{"query": …}` to `http://127.0.0.1:8080/reflect` and times it inside |
| `stop`, `resume`, `delete` | `sandbox.stop()` / `resume()` and poll; `delete_sandbox(id)` |

[`tools/measure_aca.py`](tools/measure_aca.py) repeats the 2026-10-09 protocol: `agent` mode runs create → answer → answer → stop → resume → answer → answer → delete per run and fails if conversation-history lengths do not keep growing; `create` mode times each configuration (`builtin`, `image`, `vnet`, `port`, `vnetvolume`, `full`) and records whether guest uptime after resume exceeds its pre-stop value. Uptime alone does not prove process-memory continuity; the retained `process_survived` field is a legacy name for that observation.

[`tools/measure_responses.py`](tools/measure_responses.py) (B and D) POSTs `{"input": …}` to `AGENT_RESPONSES_URL` with an Azure CLI token for `https://ai.azure.com` and adds `previous_response_id` for follow-ups. Token acquisition is outside the request timer; it refreshes before each concurrency level and recovery. With `--observe`, it accepts only one new Ready Kata pod as a candidate; ambiguity or a failed pod read is a failure, not a placement result. Run this observation in a quiet project namespace. `--recovery` deletes the one newly observed Kata pod, waits for deletion to finish, then follows up using that session's response ID. Exit 0 requires every requested cold, warm, concurrency and recovery check to pass; skipped recovery, deletion failure and forgotten state return exit 1.

[`tools/check_isolation.py`](tools/check_isolation.py) (C and D) reads `kubectl get pods` and `kubectl get nodes`, requires `runtimeClassName: kata-vm-isolation` and phase Running, and with `--exec-uname` compares `uname -r` inside the pod with the node's `kernelVersion`.

[`tools/measure_e2b.py`](tools/measure_e2b.py) (E) creates its own Prompt Agent version (the instructions and tool schema printed in every output), runs the A-matched 3-run `agent` protocol (`Sandbox.create("base")` → first answer → follow-up → `beta_pause` → wait 5 s → `Sandbox.connect` → follow-ups → `kill`), the D-matched `perf` protocol (cold n=5, warm follow-ups with `LANTERN-7`, concurrency 4 and 8, and sandbox replacement), `scale` (sessions spread over several Embed installs named in `--hosts`) and `hostloss` (stop one install's stack and record what the others and the paused sandboxes can do), then deletes the agent version, every conversation and every sandbox. Exit 1 if any phase failed, lost state or left a resource. The 2026-10-15 runs used its revision `036dc81…`, except host b's agent runs, which used the earlier `89255d0b…`. The repository revision changes only failure handling and keeps the prompts, protocol and clocks: exit 1 when the recovery follow-up loses the code word, or when `hostloss` loses what should survive (the other host's live session and new sessions, the stopped host's paused sandbox and new sessions after restart) or leaves a sandbox or conversation; cleanup when a create fails midway; exit 2 for an unreadable `--hosts` file. The 2026-10-14 numbers came from the author's private driver, whose agent, prompts and clocks it reproduces.

[`tools/measure_code_interpreter.py`](tools/measure_code_interpreter.py) (E) runs the 11 steps of `e-2026-10-15-latest` against E2B's official `code-interpreter-v1` template with `e2b-code-interpreter` 2.11.0 and fails if any step fails or a sandbox is left.

[`tools/measure_sessions.py`](tools/measure_sessions.py) (B) runs the explicit session lifecycle from [Manage hosted agent sessions](https://learn.microsoft.com/azure/foundry/agents/how-to/manage-hosted-sessions): create a session pinned to one agent version, write a file into it, answer twice, `:stop` until `idle`, answer on the same `agent_session_id`, read the file back, answer once more, delete. It authenticates with an Azure CLI token for `https://ai.azure.com` or with the header in `SESSIONS_AUTH_HEADER`, records every HTTP attempt including retries, and writes a private record plus a public one without session IDs or the endpoint. Exit 0 needs every run complete, the file back unchanged, the question count growing and every session it created deleted; the 2026-10-15 run meets all four.

The workshop scripts (`module-01/setup.sh`, `module-03/prepare-agent-sandbox.sh`, `module-04/sandbox-deploy.sh`) are used unchanged at `905f2c2`; this repository does not copy them.

## Measured Runs

All runs used Azure resources in East US 2. The client was a Windows workstation, except `b-2026-10-15-sessions` (a Windows VM in Japan East, from WSL Ubuntu) and E, whose tools ran on the E2B host VM (host a on 2026-10-15). The A/B/C record names Azure CLI 2.88.0 and azd 1.34.1; A's SDK record also names Python 3.13. Raw consoles and IDs stay in the author's private folders; [`tools/export_evidence.py`](tools/export_evidence.py) projected them into [`evidence/runs/`](evidence/runs/), recording the SHA-256 of every private source, and replaced node, pod and namespace names with neutral labels.

Runs are grouped A–E, then by date from oldest to newest within each path, matching the README tables.

### a-2026-09-27-setup: first deployment, and wake on an HTTP request

**Question.** How long does the A path take to set up on the shared foundation, does a stopped sandbox keep its process, and does an HTTP request wake it?

**Input.** The steps of `tools/aca_sandbox.py` in order, then questions sent from inside the sandbox, a stop, a resume, a second stop and an HTTP request to the on-demand port ([`evidence/runs/a-aca-2026-09-27/setup-and-wake.json`](evidence/runs/a-aca-2026-09-27/setup-and-wake.json)). The questions are in the table.

**Varied and fixed.** A single sequence on one sandbox; the full A specification in [Architecture and Metrics](#architecture-and-metrics).

**Result.**

<!-- BEGIN GENERATED: a-setup -->
| Step | Input | s | Reply or state |
|---|---|---:|---|
| sandbox group (Bicep) |  | 90 |  |
| VNet connection |  | 9.6 |  |
| disk image from ACR |  | 21.9 |  |
| Blob volume |  | 3.6 |  |
| sandbox create |  | 21.5 | Running |
| answer, timed inside | "where is Bangkok? one sentence" | 3.6 | Bangkok is the capital city of Thailand, in Southeast Asia. |
| answer, timed inside | "What did I just ask you about? Reply in five words." | 1.1 | Bangkok’s location in the world. |
| stop (memory snapshot) |  | 9.9 | Stopped |
| resume |  | 1.5 | Running |
| answer after resume |  | 12.5 | 2 |
| next answer | "Name the city we discussed. One word." | 0.9 | Bangkok |
| next answer | "Reply with OK." | 1.1 | OK |
| stop again |  | 6.3 | Stopped |
| HTTP request to the stopped sandbox | "How many questions have I asked before this one? Number only." | 23.7 | 5 |
| next HTTP request | "Reply with OK." | 2.5 | OK |

Read inside the sandbox: vmm_type `cloudhypervisor`, kernel `6.12.8+`, 1 vCPU.
<!-- END GENERATED: a-setup -->

**Boundary.**
- One run. The 24 s wake time was a single observation and is not used for the resume row; the 2026-10-09 explicit resume (three runs) is.
- The first outbound call after a memory resume took 12.5 s, then about 1 s; we read this as stale keep-alive connections, which we did not prove.
- The wake test used a temporary anonymous port window because the IP rule could not admit the operator; the port was removed afterwards.

### a-2026-10-09-agent: the full agent path in ACA Sandboxes, 3 runs

**Question.** How long does a new sandbox take to answer, how fast is the next answer, and how long does a resume request → first answer take after suspension has finished, on the GA service with the full specification the workshop uses?

**Input.** Each run created a new sandbox from the agent's disk image and asked, in order, these exact questions ([`evidence/runs/a-aca-2026-10-09/agent-runs.json`](evidence/runs/a-aca-2026-10-09/agent-runs.json)):

<!-- BEGIN GENERATED: a-agent-input -->
> Configuration: custom agent disk image + VNet + Blob volume + OnDemand port; cpu 1000m, memory 2048Mi, auto-suspend 900 s in Memory mode.
> Request: POST http://127.0.0.1:8080/reflect {"query": <input>}, sent with sandbox exec from inside the sandbox.
> First answer: "Where is Bangkok? Answer in one short sentence."
> Every later turn: "How many questions have I asked before this one? Number only."
<!-- END GENERATED: a-agent-input -->

**Varied and fixed.** Only the run number varied. The service ([GA since 2026-09-23](https://techcommunity.microsoft.com/blog/appsonazureblog/azure-container-apps-sandboxes-now-generally-available/4559125)), SDK 0.1.0b4 (still beta), the sandbox group, the image and the specification were the same in all three.

**Result.**

<!-- BEGIN GENERATED: a-agent -->
Seconds; answers are the agent's replies in order. Totals are added per run before taking the median; the independently reported column medians must not be added.

| Run | Create → Running | First answer | Cold | Follow-up | Stop | Resume | Answer after resume | Resume → answer | Answers |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| 1 | 44.86 | 5.55 | 50.41 | 1.54 | 7.56 | 2.83 | 14.39 | 17.22 | Bangkok is the capital city of Thailand in Southeast Asia. / 2 / 3 / 4 |
| 2 | 24.12 | 3.88 | 28.0 | 1.04 | 5.97 | 1.61 | 12.84 | 14.45 | Bangkok is the capital city of Thailand in Southeast Asia. / 2 / 3 / 4 |
| 3 | 24.25 | 2.82 | 27.07 | 1.05 | 9.31 | 3.02 | 9.42 | 12.44 | Bangkok is the capital city of Thailand in Southeast Asia. / 1 / 2 / 3 |
| **median** | **24.25** | **3.88** | **28.0** | **1.05** | **7.56** | **2.83** | **12.84** | **14.45** |  |
<!-- END GENERATED: a-agent -->

All three runs reported `vmm_type` <!--v:a.vmm.value-->cloudhypervisor<!--/v-->, and the conversation history kept growing across stop and resume in <!--v:a.state_kept.count-->3<!--/v--> of 3. No sandbox was left behind.

**Boundary.**
- Three runs. The first run's create took <!--v:a.create.max-->44.86<!--/v--> s against about 24 s for the other two, so its cold time is the maximum of the range.
- Create time is SDK wall time from the laptop and includes its round trip; answer time is measured inside the sandbox and excludes it.
- Cold and resume-to-answer add those separate clocks; stop and idle waiting are excluded, as is the client-side exec overhead.
- The documented sub-second start applies to prewarmed pools; this configuration includes a custom image, a VNet connection and a private Blob volume.

### a-2026-10-09-attribution: which part of the specification costs create time

**Question.** The full specification took over 20 s to create. Is it the custom image, the VNet, the port or the Blob volume?

**Input.** One sandbox at a time, each configuration created, stopped, resumed and deleted. The six configurations, verbatim from [`evidence/runs/a-aca-2026-10-09/create-attribution.json`](evidence/runs/a-aca-2026-10-09/create-attribution.json), are in the first two columns below; the same `cpu`, `memory` and suspend mode as above.

**Varied and fixed.** One configuration item at a time was added to the agent's image. The sandbox group, region, SDK and client stayed the same; runs per configuration were 3 for `builtin`, `image` and `full` and 2 for the others.

**Result.**

<!-- BEGIN GENERATED: a-attr -->
| Configuration | What is added | n | Create → Running, s | Median |
|---|---|---:|---|---:|
| `builtin` | built-in ubuntu disk, SDK defaults, no VNet, volume or port | 3 | 5.74, 2.2, 4.68 | 4.68 |
| `image` | the agent's disk image from ACR, nothing else | 3 | 2.31, 1.6, 2.7 | 2.31 |
| `vnet` | image + VNet connection | 2 | 1.97, 2.52 | — (n=2) |
| `port` | image + OnDemand port with IP access control | 2 | 2.33, 2.3 | — (n=2) |
| `vnetvolume` | image + VNet connection + private Blob volume | 2 | 25.12, 15.79 | — (n=2) |
| `full` | image + VNet connection + private Blob volume + OnDemand port | 3 | 25.9, 22.2, 26.32 | 25.9 |

Guest uptime after resume exceeded its pre-stop value in 15 of 15 sandboxes. This observation alone does not prove process-memory continuity.
<!-- END GENERATED: a-attr -->

**Boundary.**
- Two or three runs per configuration.
- The uptime comparison is only an observation, not proof that a particular process or its memory survived.
- The volume was not tried without the VNet connection to a working end: against Storage with public access disabled the request did not return and no sandbox appeared; it was abandoned after about 8 minutes and is not in the table.
- This shows where the time appears, not why: the Blob mount is on the create path, the reason inside the service is not visible.

### a-2026-10-09-late-mount: start without the volume, mount it afterwards

**Question.** If the volume is the slow part, can the sandbox start without it and attach it once running?

**Input.** Create with the image and the VNet connection but no volume, then `add_volume_mount` of the same Blob volume to the running sandbox, then list the mount ([`evidence/runs/a-aca-2026-10-09/late-mount.json`](evidence/runs/a-aca-2026-10-09/late-mount.json)).

**Varied and fixed.** Only the order changed (volume after start instead of at create); everything else as in `vnetvolume`.

**Result.**

<!-- BEGIN GENERATED: a-late -->
| Run | Create without volume, s | Attach Blob volume, s | State after mount |
|---|---:|---:|---|
| 1 | 7.2 | 20.29 | Running |
| 2 | 3.99 | 12.4 | Running |
<!-- END GENERATED: a-late -->

Both mounts listed the existing state files, and the sandbox stayed Running.

**Boundary.** Two runs. Useful only when the first answer does not need the saved state: the agent starts with an empty state directory until the mount completes.

### b-2026-09-27: Foundry hosted agent, deploy and two routes to the model

**Question.** How long does B take from `azd` to an answering agent, and how fast are a new session and its follow-ups?

**Input.** The workshop's module-02 commands (README step 5): `azd ai agent init`, `azd deploy` with `MODEL_ROUTING=gateway` (version 1), then a second `azd deploy` with `direct` (version 2), each followed by `azd ai agent invoke` on a new session and two follow-up turns. The request text was not kept in the run record ([`evidence/runs/b-hosted-agent-2026-09-27/run.json`](evidence/runs/b-hosted-agent-2026-09-27/run.json)).

**Varied and fixed.** Only the model route differed between the two versions; the project, model and client were the same.

**Result.**

<!-- BEGIN GENERATED: b-run -->
| Step | Route to the model | s |
|---|---|---:|
| `azd ai agent init` |  | 38.4 |
| `azd deploy`, version 1 | gateway | 161 |
| new session → answer | gateway | 9.43 |
| follow-up turns | gateway | 4.03, 5.54 |
| `azd deploy`, version 2 | direct | 100 |
| new session → answer | direct | 5.29 |
| follow-up turns | direct | 4.94, 4.38 |
<!-- END GENERATED: b-run -->

**Boundary.**
- One run, two follow-up samples per route: not enough to call gateway and direct different.
- The direct route ran without the Foundry native AI gateway, because that portal step could not be automated.
- Resume after idle and session loss were not exercised here; resume after an explicit stop is in `b-2026-10-15-sessions`.

### b-2026-10-15-sessions: Foundry hosted agent, explicit session lifecycle, 3 runs

**Question.** How long does B take to create a session, answer, stop, and answer again after the stop? Does the session keep its file and conversation across the stop?

**Input.** [`tools/measure_sessions.py`](tools/measure_sessions.py) against the module-02 agent, version `2` (0.5 vCPU / 1 GiB, `gpt-5.4-mini`, `MODEL_ROUTING=direct`), 3 runs ([`evidence/runs/b-sessions-2026-10-15/sessions.json`](evidence/runs/b-sessions-2026-10-15/sessions.json)). Each run: `POST .../endpoint/sessions` pinned to version `2`; `PUT .../files/content` writes a marker file; first turn "Where is Bangkok? Answer in one short sentence."; every later turn "How many questions have I asked before this one? Number only." with `previous_response_id`; `POST .../sessions/{id}:stop`, then poll until `idle`; the next turn on the same `agent_session_id`; read the marker back; one more turn; `DELETE` the session.

**Varied and fixed.** Nothing varied between the three runs. The agent version, prompts and client were fixed: a Windows VM in Japan East (WSL Ubuntu) calling the project in East US 2 through an Azure API Management gateway. Client times include that path; the service's own `created_at` → `completed_at` is reported separately.

**Result.**

<!-- BEGIN GENERATED: b-sessions -->
Seconds, client wall time; the last column is the agent's replies in order.

| Run | Create → active | First answer | Follow-up | Stop → idle | Answer after stop | Next answer | File kept | Answers |
|---|---:|---:|---:|---:|---:|---:|---|---|
| 1 | 6.69 | 5.62 | 4.59 | 2.9 | 12.35 | 4.6 | yes | Bangkok is the capital city of Thailand in Southeast Asia. / 2 / 3 / 4 |
| 2 | 6.87 | 4.79 | 4.81 | 3.05 | 12.02 | 4.11 | yes | Bangkok is the capital city of Thailand in Southeast Asia. / 2 / 3 / 4 |
| 3 | 6.51 | 5.85 | 4.42 | 7.71 | 11.66 | 3.88 | yes | Bangkok is the capital city of Thailand in Southeast Asia. / 2 / 3 / 4 |
| **median** | **6.69** | **5.62** | **4.59** | **3.05** | **12.02** | **4.11** |  |  |

35 HTTP attempts: 200 ×23, 201 ×6, 204 ×6; none retried.
<!-- END GENERATED: b-sessions -->

The service recorded <!--v:b.sess.server.range-->1–4<!--/v--> s of generation per turn (whole seconds); the rest of each client time is the network path, the gateway and the platform.

**Boundary.**
- Three runs from one client: the client times include a Japan East → East US 2 round trip and the gateway, so they are not comparable with the 2026-09-27 run from China.
- Resume was measured after an explicit `:stop`, not after the idle timeout. There is no memory snapshot: the agent process starts again, and only `$HOME`, `/files` and the conversation stored by the platform carry over.
- One session at a time; no concurrency and no session loss.

### c-2026-09-27: AKS + agent-sandbox, isolation, pod loss, suspend and resume

**Question.** Does the agent pod run in its own micro-VM, and what do pod loss and a suspend/resume cycle cost?

**Input.** The workshop's module-03 script and manifest (README step 3), questions over the LoadBalancer, then `kubectl delete pod`, then `operatingMode: Suspended` and `Running` patches ([`evidence/runs/c-aks-agent-sandbox-2026-09-27/run.json`](evidence/runs/c-aks-agent-sandbox-2026-09-27/run.json)). The kernel check followed the workshop's own verification: `uname -r` in the Sandbox pod and in a pod without `runtimeClassName`. The request text was not kept.

**Varied and fixed.** One Sandbox, one sequence; Kubernetes 1.35.8, one `Standard_D4s_v3` Kata node, agent-sandbox `v0.5.2`.

**Result.**

<!-- BEGIN GENERATED: c-run -->
| Step | Observed |
|---|---|
| `prepare-agent-sandbox.sh` | 600 s |
| Blob private link | 168 s |
| `kubectl apply` → Sandbox Ready | 44.9 s |
| first answer, second answer | 12.75 s, 1.96 s; context remembered: true |
| `uname -r` in the Sandbox pod / in a runc pod | `6.6.137.mshv1-1.azl3` / `6.8.0-1067-azure` |
| delete the pod → Ready again | 23.4 s, state restored: true |
| `operatingMode: Suspended` → pod gone | 9.7 s; health while suspended HTTP 503 |
| `operatingMode: Running` → Ready / LB 200 / answer | 17.1 / 26.1 / 34.2 s |
<!-- END GENERATED: c-run -->

**Boundary.**
- One run.
- The runc comparison pod ran on the Ubuntu system pool, so the two kernels differ by node as well as by runtime. The Kata kernel's `mshv` suffix, the runtime class and Learn's documented stack carry the conclusion.
- Wake on request is not part of agent-sandbox; the resume was a manual patch.

### d-2026-09-29-placement: where a BYO-AKS session runs

**Question.** After binding the cluster, does a session actually run on your Kata pool?

**Input.** The private-preview sample agent (version 3) deployed with `azd deploy`; one new session, then two turns at a later recheck ([`evidence/runs/d-byoaks-2026-09-29/placement.json`](evidence/runs/d-byoaks-2026-09-29/placement.json)). The request text of the first session was not kept; the recheck answers were "OK" and then a code word.

**Varied and fixed.** The one change before this run was the subnet NSG rule; the product group had fixed the subscription's enablement earlier the same day.

**Result.**

<!-- BEGIN GENERATED: d-placement -->
| Check | Observed |
|---|---|
| IP flow verify before the fix | AzureCloud → :443 Deny; AzureCloud → :443 Deny; VNet → :443 Allow |
| rule added to the subnet NSG | `Allow-AzureCloud-FoundryRouter-443`, priority 500, Inbound Allow Tcp AzureCloud → <router-ip>:443 |
| first session after the fix | HTTP 200, "BYO-AKS-OK", 51 s on the client |
| its session pod | runtimeClassName `kata-vm-isolation`, owner ReplicaSet, requests 500m / 1Gi, overhead 600Mi, init containers foundry-sandbox-agent, foundry-sandbox-init |
| scheduled → Ready | 35 s |
| session pods at the 18:15 recheck | 3 of 3 Running with `kata-vm-isolation` |
| two turns at the recheck | "OK" → "HERON-1815" |
| kernel of the Kata pool nodes | `6.6.137.mshv2-2.azl3` |
<!-- END GENERATED: d-placement -->

**Boundary.**
- Before 2026-09-29 our earlier field record (the private repository `foundry-byo-aks-private-preview`) found sessions answered with the cluster stopped and no session pod with the cluster running. Two causes, in order: the product-side enablement of the subscription, then our subnet NSG. That record's placement result is superseded by this run.
- The guest kernel was not read inside a session pod; the node kernel and `runtimeClassName` are the evidence.
- Placement can change in a private preview.

### d-2026-09-29-perf: cold start, follow-ups and concurrency on three nodes

**Question.** On a three-node Kata pool, how fast is a new session and a follow-up, and how many sessions fit at once?

**Input.** [`tools/measure_responses.py`](tools/measure_responses.py) (then named `byoaks_bench.py`) with these exact inputs ([`evidence/runs/d-byoaks-2026-09-29/bench.json`](evidence/runs/d-byoaks-2026-09-29/bench.json), [`cold-early.json`](evidence/runs/d-byoaks-2026-09-29/cold-early.json)):

<!-- BEGIN GENERATED: d-input -->
> Request: POST <agent responses endpoint> {"input": <input>} with previous_response_id for follow-ups.
> New sessions: "Reply with exactly COLD-{i}" (n = 1, 2, 3)
> One session: "Remember the code word LANTERN-7. Reply only OK.", then "What is the code word? Reply with the word only.", then "Reply with exactly WARM-{i}" (n = 1, 2)
> At once, per session: "Remember SCALE-{i}. Reply only OK.", then "What did I ask you to remember? Word only."
> Client: Windows laptop in China; direct REST POST to the agent's Responses endpoint with an Azure CLI token; recorded round trip 320–800 ms.
<!-- END GENERATED: d-input -->

**Varied and fixed.** Cold runs varied whether the node already held the image; concurrency varied 4 and 8. The pool (3 × `Standard_D4s_v5`), the agent version, the session pod shape and the client stayed the same.

**Result.** New sessions:

<!-- BEGIN GENERATED: d-cold -->
| Start (UTC) | Node | Answer | New session → answer, s | Pod created → Ready, s |
|---|---|---|---:|---:|
| 15:43:00 | no image yet | COLD-1 | 41.9 | not paired |
| 15:43:47 | no image yet | COLD-2 | 40.6 | not paired |
| 15:44:32 | image cached | COLD-3 | 26.7 | not paired |
| 15:47:43 | image cached | COLD-1 | 24.01 | 10.0 |
| 15:48:15 | image cached | COLD-2 | 25.49 | 10.0 |
| 15:48:50 | image cached | COLD-3 | 26.16 | 10.0 |
| 15:49:37 | image cached | OK | 23.53 | not paired |

With the image cached: 25.49 s median (23.53–26.7; n=5). First pod on a node without the image: 41.9, 40.6 s (n=2). Session pods created → Ready across the run: 8, 9, 10, 10, 10, 10 s with the image cached, 25, 25 s on a fresh node.
<!-- END GENERATED: d-cold -->

Follow-ups in one session:

<!-- BEGIN GENERATED: d-warm -->
| Turn | Answer | Client wall, s |
|---|---|---:|
| 1 (new session) | OK | 23.53 |
| 2 | LANTERN-7 | 16.42 |
| 3 | WARM-1 | 11.17 |
| 4 | WARM-2 | 12.9 |

The same model called directly from the same client, without an agent: 2.69 s median (1.82–5.07; n=5). This baseline used low reasoning effort; it is not a matched agent-configuration benchmark.
<!-- END GENERATED: d-warm -->

At once:

<!-- BEGIN GENERATED: d-scale -->
| At once | Answered | Refused | Refusal | Refused after, s |
|---:|---|---|---|---:|
| 4 | 0/4 | 4/4 | `500 session_creation_failed` | 18.4–18.9 |
| 8 | 2/8 (24.14, 24.96 s) | 6/8 | `429 aks_quota_exceeded` | 68.03–80.51 |

When the refusals began, 12 session pods were alive on 3 `Standard_D4s_v5` nodes, at most 5 per node, and no node had 500m CPU left.
<!-- END GENERATED: d-scale -->

**Boundary.**
- The concurrency levels ran after earlier sessions had filled the pool, so they measure capacity exhaustion, not latency under load. Latency under true concurrency with free capacity was not measured.
- The harness acquired one token before cold + warm and refreshed it before each concurrency level; token acquisition happened outside every timed request. The responses' own `created_at` to `completed_at` was <!--v:d.agent_turn.range-->2–5<!--/v--> s per turn (run manifest). The remaining client wall time is uninstrumented; the endpoint, session routing, agent execution and client network cannot be separately attributed from these records.
- The cold set mixes the three early runs and the benchmark; the two early runs on nodes without the image are reported separately.

### d-2026-09-29-recovery: delete a session pod

**Question.** After a session pod is deleted, how quickly is a replacement Ready, and can another live session still answer? This run did not test the deleted session's continuity.

**Input.** `kubectl delete pod` of one live session pod, then the next turn on a live session, "What did I ask you to remember? Word only." ([`evidence/runs/d-byoaks-2026-09-29/recovery.json`](evidence/runs/d-byoaks-2026-09-29/recovery.json)).

**Varied and fixed.** One pod deletion on the same pool as the benchmark.

**Result.**

<!-- BEGIN GENERATED: d-recovery -->
| Step | Observed |
|---|---|
| session pod deleted (UTC) | 16:04:16 |
| replacement pod Ready after | 23.9 s |
| follow-up on a different live session | HTTP 200, 14.8 s, "LANTERN-7", that session kept its state: true |
<!-- END GENERATED: d-recovery -->

**Boundary.** One deletion. The follow-up went to a different live session than the deleted one. It shows that the pool kept serving and that other session retained `LANTERN-7`; it does **not** establish continuity of the deleted session.

### e-2026-10-14-agent: Foundry Prompt Agent + E2B Firecracker sandbox on Azure VM, 3 runs

**Question.** When E2B Embed runs on an Azure Gen2 VM with `/dev/kvm`, how fast are Firecracker sandbox creation, pause and resume, and how fast does a Foundry Prompt Agent answer across pause and resume under the same 3-run protocol as A?

**Input.** Each run created a new E2B `base` sandbox and a new Foundry conversation (`gpt-5.4-mini` in East US 2) and asked, in order, these exact questions ([`evidence/runs/e-e2b-2026-10-14/agent-runs.json`](evidence/runs/e-e2b-2026-10-14/agent-runs.json)):

<!-- BEGIN GENERATED: e-agent-input -->
> Host VM: Standard_D4ds_v7; E2B `base` template (2 vCPU, 512 MB, Firecracker memory + disk snapshot via `beta_pause`).
> Versions: E2B Python SDK `e2b 2.46.0`; E2B Embed runtime `588e5b9`.
> Request: POST <Foundry project>/openai/v1/responses with Prompt Agent calling function tool run_in_e2b_sandbox on E2B API :3000/:3002.
> Agent instructions: "You are a concise assistant with access to `run_in_e2b_sandbox`. For EVERY user message, first call `run_in_e2b_sandbox` once to inspect or update files in /home/user, then answer concisely as instructed. When asked for a number only or word only, reply with that exact token only."
> Its one function tool `run_in_e2b_sandbox(python_code)`: "Execute Python 3 code inside the session's isolated E2B Firecracker microVM sandbox on Azure."
> First answer: "Where is Bangkok? Answer in one short sentence."
> Every later turn: "How many questions have I asked before this one? Number only."
<!-- END GENERATED: e-agent-input -->

**Varied and fixed.** Only the run number varied across the 3 agent runs; the 20-run microbenchmark ran on the host VM against `localhost:3000` and `localhost:3002`.

**Result.**

<!-- BEGIN GENERATED: e-agent -->
| Run | Create → Running | First answer | Cold | Follow-up | Pause | Resume | Answer after resume | Resume → answer | Answers |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| 1 | 0.14 | 4.12 | 4.26 | 2.95 | 0.13 | 0.08 | 6.4 | 6.48 | Bangkok is the capital of Thailand in Southeast Asia. / 2 / 3 / 4 |
| 2 | 0.07 | 2.82 | 2.89 | 2.83 | 0.11 | 0.11 | 12.71 | 12.82 | Bangkok is the capital of Thailand in Southeast Asia. / 1 / 2 / 3 |
| 3 | 0.06 | 8.38 | 8.44 | 3.92 | 0.15 | 0.09 | 4.64 | 4.73 | Bangkok is the capital city of Thailand. / 1 / 2 / 3 |
| **median** | **0.07** | **4.12** | **4.26** | **2.95** | **0.13** | **0.09** | **6.4** | **6.48** |  |

On-host 20-sandbox microbenchmark (zero WAN RTT): create 0.051–0.089 s (n=20), warm command 0.007–0.01 s (n=20), pause 0.051–1.81 s (n=20), resume 0.086–0.62 s (n=20). VMM `firecracker` `v1.14-0.2.0` from the host's process list; guest kernel `6.1.177+` from `uname -r` inside the sandbox; host kernel `6.17.0-1022-azure`.
<!-- END GENERATED: e-agent -->

The VMM process behind the sandboxes in the host's process list was <!--v:e.vmm.value-->firecracker<!--/v-->, and the conversation history inside the sandbox grew across pause and resume in <!--v:e.state_kept.count-->3<!--/v--> of 3. Initial VM setup took <!--v:e.setup.value-->177<!--/v--> s.

**Boundary.**
- Three agent runs plus 20 on-host microbenchmark iterations on one `Standard_D4ds_v7` VM in East US 2.
- The Prompt Agent runs in Foundry and calls the E2B sandbox as a function tool over the network, whereas A's reflection agent ran inside the ACA sandbox itself.

### e-2026-10-14-perf: cold start, follow-ups, concurrency and sandbox replacement on E2B

**Question.** Under D's benchmark protocol (`COLD-{i}`, `LANTERN-7` warm follow-ups, 4 and 8 concurrent sessions, and sandbox replacement), how does a single `Standard_D4ds_v7` VM running E2B perform?

**Input.** The D-matched benchmark driver with these exact inputs ([`evidence/runs/e-e2b-2026-10-14/perf.json`](evidence/runs/e-e2b-2026-10-14/perf.json)):

<!-- BEGIN GENERATED: e-perf-input -->
> Request: POST <Foundry project>/openai/v1/responses {"input": <input>} with Prompt Agent calling E2B sandbox tool; agent instructions and tool as in `e-2026-10-14-agent`.
> New sessions: "Use run_in_e2b_sandbox to print COLD-{i}, then reply with exactly COLD-{i}" (n = 1, 2, 3, 4, 5)
> One session: "Use run_in_e2b_sandbox to save the code word LANTERN-7 to /home/user/codeword.txt. Reply only OK.", then "Use run_in_e2b_sandbox to read /home/user/codeword.txt. What is the code word? Reply with the word only.", then "Use run_in_e2b_sandbox to verify the sandbox is alive, then reply with exactly WARM-1", then "Use run_in_e2b_sandbox to verify the sandbox is alive, then reply with exactly WARM-2"
> At once, per session: "Use run_in_e2b_sandbox to write SCALE-{k} to /home/user/scale.txt. Reply only OK.", then "Use run_in_e2b_sandbox to read /home/user/scale.txt. What did I ask you to remember? Word only."
> Replacement: a live session ran "Use run_in_e2b_sandbox to write LANTERN-7 to /home/user/live.txt. Reply only OK."; after another sandbox was killed and replaced, it ran "Use run_in_e2b_sandbox to read /home/user/live.txt. What is the code word? Reply with the word only."
> Driver: the author's private script `run_abcd_matched_benchmarks.py` (SHA-256 `8e8f6fc5b7b6…` in the record); `tools/measure_e2b.py perf` sends the same prompts with the same agent and clocks.
<!-- END GENERATED: e-perf-input -->

**Varied and fixed.** Cold runs repeated 5 new sessions; concurrency varied 4 and 8 sessions at once on 1 `Standard_D4ds_v7` VM.

**Result.** New sessions:

<!-- BEGIN GENERATED: e-cold -->
| Start (UTC) | Answer | Sandbox created → Ready, s | Agent turn, s | New session → answer, s |
|---|---|---:|---:|---:|
| 06:14:58 | COLD-1 | 0.056 | 7.75 | 7.94 |
| 06:15:06 | COLD-2 | 0.068 | 2.28 | 2.54 |
| 06:15:08 | COLD-3 | 0.068 | 3.44 | 3.6 |
| 06:15:12 | COLD-4 | 0.057 | 3.52 | 3.65 |
| 06:15:16 | COLD-5 | 0.066 | 3.19 | 3.34 |

Across the 5 cold runs: sandbox create → Ready 0.066 s median (0.056–0.068; n=5), Prompt Agent turn 3.44 s median (2.28–7.75; n=5), end-to-end new session → answer 3.6 s median (2.54–7.94; n=5).
<!-- END GENERATED: e-cold -->

Follow-ups in one session:

<!-- BEGIN GENERATED: e-warm -->
| Turn | Answer | Sandbox tool, s | Turn, s |
|---|---|---:|---:|
| 1 (new session; includes the sandbox create) | OK | 0.14 | 2.76 |
| 2 | LANTERN-7 | 0.033 | 5.03 |
| 3 | WARM-1 | 0.029 | 3.19 |
| 4 | WARM-2 | 0.028 | 3.39 |
<!-- END GENERATED: e-warm -->

At once and sandbox replacement:

<!-- BEGIN GENERATED: e-scale -->
| At once | Answered | Refused | Sandbox create + turn 1, s |
|---:|---|---|---|
| 4 | 4/4 | 0/4 | 3.9, 3.12, 3.9, 3.17 |
| 8 | 8/8 | 0/8 | 4.59, 2.48, 4.63, 6.94, 5.4, 3.7, 7.34, 3.82 |

Sandbox replacement after `kill`: new Firecracker sandbox Ready in 0.1 s; follow-up on a live session HTTP 200, 2.61 s, "LANTERN-7", state preserved: true. No count of live micro-VMs is published for this run: the driver counted them with `pgrep -fc`, which also counted its own shell.
<!-- END GENERATED: e-scale -->

**Boundary.**
- Single-VM deployment (`Standard_D4ds_v7`, 4 vCPU / 16 GiB RAM). At concurrency 8, one follow-up turn (`SCALE-8`) took 78.99 s while all 8/8 sessions answered and remembered their code words; the record does not say where that time went.
- Like D's recovery run, the follow-up after `kill` went to a different live session (`LANTERN-7`): the host kept serving and the replacement sandbox was ready in <!--v:e.pod_lost.value-->0.1<!--/v--> s. It does not show continuity of the killed sandbox.
- The numbers came from the author's private driver; `tools/measure_e2b.py perf` reproduces its agent, prompts and clocks but was not the program that produced this record.

### e-2026-10-15-latest: the newest E2B SDK, and E2B's official code-interpreter template

**Question.** Does the newest E2B Python SDK (`2.56.0`, released 2026-10-13) still run the measured protocol against this Embed install, and does E2B's own code-interpreter template (`e2b-code-interpreter 2.11.0`) build and work on it?

**Input.** On host a of `e-2026-10-15-multi` ([`evidence/runs/e-e2b-2026-10-15/latest.json`](evidence/runs/e-e2b-2026-10-15/latest.json)):

<!-- BEGIN GENERATED: e-latest-input -->
> SDK check: `tools/measure_e2b.py agent --runs 3` with `e2b 2.56.0` (Python 3.12.3), tool SHA-256 `036dc81db607…`; "Where is Bangkok? Answer in one short sentence.", then "How many questions have I asked before this one? Number only." 3 times, pausing for 5 s after the second turn.
> code-interpreter: template `code-interpreter-v1` (2 vCPU, 2048 MB) from [`e2b-dev/code-interpreter@162a2a2`](https://github.com/e2b-dev/code-interpreter/tree/162a2a25b6a5ea5806749a437b96cbdc5bfc087e/template), built with its unchanged `template/build_prod.py` (build environment `e2b 2.32.0`); checked with `e2b-code-interpreter 2.11.0` and `tools/measure_code_interpreter.py`.
> Cells, in order, with no model: "x = 1", "x+=1; x", a pandas sum, a matplotlib plot, JavaScript "[1, 2, 3].reduce((a, b) => a + b)", "1/0", then after pause and resume "x".
<!-- END GENERATED: e-latest-input -->

**Varied and fixed.** The SDK check kept the agent, prompts, protocol and clocks of `e-2026-10-14-agent` and ran on host a with the tool revision of `e-2026-10-15-multi`. Against `e-2026-10-14-agent` it changed the SDK (2.46.0 → 2.56.0) and the program (the private driver → `tools/measure_e2b.py`); host a had since booted kernel `7.0.0-1017-azure`, and its OS disk was Standard HDD. The code-interpreter template was built with E2B's unchanged script; between build attempts we raised three host settings, listed under the build table. The 4 check runs used the same template and steps.

**Result.** The SDK check:

<!-- BEGIN GENERATED: e-latest-sdk -->
| Run | Create → Running | First answer | Cold | Follow-up | Pause | Resume | Answer after resume | Resume → answer | Answers |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| 1 | 0.1 | 5.24 | 5.34 | 3.7 | 0.15 | 0.08 | 6.72 | 6.8 | Bangkok is the capital city of Thailand in Southeast Asia. / 1 / 2 / 3 |
| 2 | 0.06 | 4.93 | 4.99 | 4.24 | 0.14 | 0.08 | 6.2 | 6.28 | Bangkok is the capital city of Thailand. / 1 / 2 / 3 |
| 3 | 0.06 | 4.0 | 4.06 | 35.02 | 0.17 | 0.11 | 8.14 | 8.25 | Bangkok is the capital city of Thailand. / 2 / 3 / 4 |
| **median** | **0.06** | **4.93** | **4.99** | **4.24** | **0.15** | **0.08** | **6.72** | **6.8** |  |

Model HTTP attempts: 200 ×24. History grew 1, 2, 3, 4 in 3 of 3 runs; no sandbox was left.
<!-- END GENERATED: e-latest-sdk -->

Building `code-interpreter-v1` (30 steps):

<!-- BEGIN GENERATED: e-latest-build -->
| Attempt | HUGEPAGES | Build workspace, MiB | OS disk, GB | Result | Seconds |
|---:|---:|---:|---:|---|---:|
| 1 | 2048 | 512 | 50 | failed at step 6/30: `mmap memfd: cannot allocate memory` while resuming the build VM | 104.5 |
| 2 | 4096 | 512 | 50 | failed at step 8/30: `pip install` in the build VM: `[Errno 28] No space left on device` | 56.5 |
| 3 | 4096 | 8192 | 50 | stopped by us at step 12/30: below 8 GiB free on the OS disk, which also holds the E2B database | 501 |
| 4 | 4096 | 8192 | 128 | built, 30/30 steps; steps 1–11 from attempt 3's cache | 426 |

By step 12 attempt 3 had written 12839 MiB of templates and 10140 MiB under the orchestrator's directory, with 5084 MiB left on the OS disk; attempt 4 then used 29 GiB (free 93 → 64 GiB). What we changed: `HUGEPAGES` in the Compose `.env` 2048 → 4096, then `docker compose up -d --wait`; the test team's build workspace (`disk_mb`) 512 → 8192 MiB, by adding one row to Embed's internal `project_limits` table; the OS disk 50 → 128 GB (deallocate, snapshot, `az disk update --size-gb`, start).
<!-- END GENERATED: e-latest-build -->

The checks, 4 runs:

<!-- BEGIN GENERATED: e-latest-ci -->
| Step | Passed | Seconds, min–max | Observed in run 4 |
|---|---:|---:|---|
| `create (default template)` | 4/4 | 0.116–0.194 |  |
| `README: x = 1` | 4/4 | 0.082–0.11 |  |
| `README: x+=1; x` | 4/4 | 0.011–0.012 | `2` |
| `pandas sum` | 4/4 | 0.565–1.303 | `10` |
| `matplotlib png` | 4/4 | 0.977–3.317 | `png` |
| `javascript kernel` | 0/4 | 0.03–0.064 | `"<template id>"[(1 , 2 , 3)].reduce is not a function` |
| `exception` | 4/4 | 0.038–0.042 | `ZeroDivisionError` |
| `pause` | 4/4 | 0.157–0.4 |  |
| `connect (resume)` | 4/4 | 0.233–0.902 |  |
| `x after resume` | 4/4 | 0.088–0.652 | `2` |
| `kill` | 4/4 | 0.057–0.746 |  |

Why JavaScript failed, reproduced in new sandboxes: JavaScript as the first cell of a new sandbox, then the same cell again: `TypeError` → `6`; a Python cell first, then the JavaScript cell (the order of the check): ok → `TypeError`; the JavaScript cell with a leading semicolon: `6`. In `template/server/messaging.py` at `162a2a2`, line 160 writes `process.env['KEY'] = 'VALUE'` with no semicolon, and lines 351–361 put those lines before the user code on a context's first execution, so code that starts with `[` continues the last of them. Cells that start with `console.log` or a number ran.
<!-- END GENERATED: e-latest-ci -->

**Boundary.**
- With Embed's defaults the official template does not build: the hugepage pool, the build workspace and the 50 GB OS disk each stopped an attempt. The build workspace was raised by adding one row to Embed's internal `project_limits` table, which E2B does not document; a run with that change shows the template working, not a supported configuration.
- The build disk need is from this one build: attempt 4 reused attempt 3's cache for steps 1–11, so a clean build would need about the sum of both, which was not measured.
- Each `code-interpreter-v1` sandbox is 2048 MB, four times `base`; how many fit on one host was not measured.
- The JavaScript failure is in E2B's template server, not in Azure or the host; whether E2B Cloud, which runs the same server code, fails the same way was not checked.
- Host a was deallocated by a subscription automation at 2026-10-15T16:48Z before cleanup, so the raised settings and the built template remain on its disk.

### e-2026-10-15-multi: E2B on two independent Azure VMs

**Question.** E2B Embed is one machine by design. What does a second, independent install add: does the protocol give the same result on another VM, does capacity add up when a client spreads sessions over two hosts, and what survives when one host's E2B stack stops?

**Input.** Two VMs, one tool run on host a for every phase ([`evidence/runs/e-e2b-2026-10-15/multi.json`](evidence/runs/e-e2b-2026-10-15/multi.json)):

<!-- BEGIN GENERATED: e-multi-input -->
> Tool: `tools/measure_e2b.py` (SHA-256 `036dc81db607…`); the agent runs on host b used the revision `89255d0b00a3…`, which did not yet record HTTP statuses. Agent instructions, tool schema and prompts as in `e-2026-10-14-agent` and `e-2026-10-14-perf`.
> Host a: `Standard_D4ds_v7`, zone `1`, host kernel `7.0.0-1017-azure`, Docker `29.9.0`, OS disk `Standard HDD (Standard_LRS) · 50 GB`, `HUGEPAGES=2048`; installed on 2026-10-14 for `e-2026-10-14-agent`, deallocated overnight, then started and brought up once with `docker compose up -d --wait`, as E2B's guide asks after a reboot.
> Host b: `Standard_D4ds_v7`, zone `1`, host kernel `6.17.0-1022-azure`, Docker `29.9.1`, OS disk `Premium SSD P6 (Premium_LRS) · 50 GB`, `HUGEPAGES=2048`; installed on 2026-10-15 with README step 7 (`compose.yaml` and `.env` at `588e5b9`, both SHA-256 OK) in 175 s.
> Network: both hosts in one subnet and zone; the tool ran on host a and reached host b's ports `3000` and `3002` over the private network; host b's NSG admitted only host a's private address on those two ports and no other inbound traffic.
> Agent runs on host b: "Where is Bangkok? Answer in one short sentence.", then "How many questions have I asked before this one? Number only." 3 times, pausing for 5 s after the second turn.
> One host at once, on host a: 8 sessions; new session "Use run_in_e2b_sandbox to print COLD-1, then reply with exactly COLD-1" and one session with "Use run_in_e2b_sandbox to save the code word LANTERN-7 to /home/user/codeword.txt. Reply only OK." before it.
> At once, per session: "Use run_in_e2b_sandbox to write SCALE-{k} to /home/user/scale.txt. Reply only OK.", then "Use run_in_e2b_sandbox to read /home/user/scale.txt. What did I ask you to remember? Word only.".
> Host stop: on each host one live session ("Use run_in_e2b_sandbox to write LANTERN-7 to /home/user/live.txt. Reply only OK.") and one paused sandbox ("Use run_in_e2b_sandbox to write PAUSED-{h} to /home/user/paused.txt. Reply only OK.", `{h}` = the host's name); then `docker compose stop` on host a with the VM running, later `docker compose up -d --wait`; reads back "Use run_in_e2b_sandbox to read /home/user/live.txt. What is the code word? Reply with the word only." and "Use run_in_e2b_sandbox to read /home/user/paused.txt. What does it say? Word only.".
> Idle capacity: `Sandbox.create("base")` on host a, one after another with no model and no command, until a create was refused, 3 times.
<!-- END GENERATED: e-multi-input -->

**Varied and fixed.** Fixed: VM size, image, zone, E2B commit, compose files, hugepage pool, SDK `e2b 2.46.0`, model, agent and prompts. Varied: the host, and how many hosts the sessions were spread over. Not fixed: host a's kernel and OS disk differ from host b's (below).

**Result.** The 3-run agent protocol on host b:

<!-- BEGIN GENERATED: e-multi-agent -->
| Run | Create → Running | First answer | Cold | Follow-up | Pause | Resume | Answer after resume | Resume → answer | Answers |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| 1 | 0.09 | 5.58 | 5.67 | 6.9 | 0.15 | 0.08 | 6.87 | 6.95 | Bangkok is the capital city of Thailand, in Southeast Asia. / 1 / 2 / 3 |
| 2 | 0.06 | 3.85 | 3.91 | 5.92 | 0.11 | 0.1 | 7.05 | 7.15 | Bangkok is the capital city of Thailand. / 1 / 2 / 3 |
| 3 | 0.06 | 45.56 | 45.62 | 3.6 | 0.12 | 0.08 | 45.53 | 45.61 | Bangkok is the capital city of Thailand. / 1 / 2 / 3 |
| **median** | **0.06** | **5.58** | **5.67** | **5.92** | **0.12** | **0.08** | **7.05** | **7.15** |  |

History inside the sandbox grew 1, 2, 3, 4 in 3 of 3 runs. Run 3's slow turns were model turns: its first answer took 45.56 s, of which the sandbox command took 0.11 s.
<!-- END GENERATED: e-multi-agent -->

Sessions at once:

<!-- BEGIN GENERATED: e-multi-scale -->
| Phase | Sessions at once | Answered | Refused | Refusal cause | Sandbox create, s | Whole session, s | Model HTTP attempts |
|---|---:|---|---|---|---:|---:|---|
| host a alone | 8 | 7/8 (a 7/8) | 1/8 | `cannot allocate memory` | 0.164–0.53 | 8.03–25.65 | 200 ×28 |
| hosts a and b | 16 | 14/16 (a 7/8, b 7/8) | 2/16 | `cannot allocate memory` | 0.147–0.432 | 8.57–42.09 | 200 ×56, 500 ×2 |

The client spread the 16 sessions over the two hosts in turn. Each refusal was E2B's `500: Failed to place sandbox`, with `cannot allocate memory` from the orchestrator behind it; the model's 2 HTTP 500 answers were retried within their turns and those sessions answered.
<!-- END GENERATED: e-multi-scale -->

Idle `base` sandboxes on host a:

<!-- BEGIN GENERATED: e-multi-idle -->
| Run | Created before the refusal | Refusal | Hugepages taken: before → at the refusal | After killing them |
|---:|---:|---|---|---|
| 1 | 5 | `error setting fc metrics (connection refused)` | 75 → 1355 | 75 pages, 0 sandboxes |
| 2 | 7 | `cannot allocate memory` | 75 → 1867 | 75 pages, 0 sandboxes |
| 3 | 7 | `cannot allocate memory` | 75 → 1867 | 75 pages, 0 sandboxes |

Pages are 2 MiB. Each `base` sandbox (512 MiB) reserved 256 pages when it was created, idle or not. The pool is 2048 pages and postgres in the Compose stack holds 75, which leaves 1973 pages: room for 7 sandboxes. Run 1 stopped earlier on a different error.
<!-- END GENERATED: e-multi-idle -->

Stopping host a's E2B stack with `docker compose stop` (the VM kept running):

<!-- BEGIN GENERATED: e-multi-hostloss -->
| Check | Observed |
|---|---|
| host b, live session: read its file | ok, 4.72 s, "LANTERN-7" |
| host b: new session | ok, 4.38 s, "COLD-1" |
| host b: resume host a's paused sandbox | failed: `SandboxNotFoundException: Paused sandbox … not found` |
| host a, stopped: create | failed: `connection refused` |
| host a, stopped: resume its own paused sandbox | failed: `connection refused` |
| host a, after restart: resume its own paused sandbox | ok, 4.72 s, "PAUSED-a" |
| host a, after restart: the sandbox that was running when it stopped | failed: `SandboxNotFoundException: Paused sandbox … not found` |
| host a, after restart: new session | ok, 4.09 s, "COLD-2" |
| `docker compose stop` / `docker compose up -d --wait` | 73.69 s / 59.55 s |
<!-- END GENERATED: e-multi-hostloss -->

**Boundary.**
- Two independent installs and a client that spreads sessions over them, not an E2B cluster: there is no shared scheduler, no failover and no shared storage. The sessions per host add up; a paused sandbox can only resume on the host that paused it.
- The host stop was `docker compose stop` on a running VM. A lost VM or disk, and the official Terraform module's scale-set replacement from a fresh disk, were not measured.
- The two hosts were not identical: host a booted kernel `7.0.0-1017-azure` after its overnight deallocation and its OS disk had been changed from Premium SSD to Standard HDD by a subscription policy after the 2026-10-14 runs; host b ran `6.17.0-1022-azure` on Premium SSD.
- One run of each phase; capacity is for the 512 MB `base` template and the Compose default pool on a `Standard_D4ds_v7`.

### Numbers you can recompute

Every published metric above comes from [`evidence/measurements.json`](evidence/measurements.json), which [`tools/build_measurements.py`](tools/build_measurements.py) recomputes from `evidence/runs/` after checking each file's SHA-256 against [`evidence/runs/INDEX.json`](evidence/runs/INDEX.json). It also checks: A's cold equals create plus first answer and recover equals resume plus answer in every run; each D cold pod's create-to-Ready equals its Kubernetes timestamps and runs `kata-vm-isolation`; D's warm session and the different live session used after pod deletion both remembered `LANTERN-7`. Medians are reported only for odd samples; even samples show their values.

Duration fields and published samples must be finite, non-negative numbers, not booleans or numeric strings. An optional timing recorded as null remains unmeasured and cannot enter a published sample. C's resume milestones must satisfy Ready → LoadBalancer healthy → first answer; a paired D pod-ready duration cannot exceed its request wall time beyond timestamp rounding, and concurrency totals require every session record. JSON output rejects NaN and infinity.

These are unit, type, sample-count and timeline checks, not a universal maximum-latency threshold. Small samples, different clock locations and unmatched workloads still prevent a product ranking; values that look plausible are not a substitute for the retained run evidence.

## Tests and Offline Checks

**Deployment evidence boundary.** These are optional checks after deployment, not commands that replace creation of the application. The full parameterized README sequence has not been re-run in a fresh subscription. Original historical runs do not prove every modified deployment command. Module 1 foundation took <!--v:f.deploy.value-->3<!--/v--> minutes in the retained run.

**Live measurement.** Return to `HOSTING_REPO`, load `.env`, and select the deployed B or D endpoint in `AGENT_RESPONSES_URL`. Run only the measurement for that path. The D recovery command deletes a session pod; the A measurement stops and deletes the sandboxes it creates. Obtain explicit approval for those lifecycle operations before running them.

```bash
cd "$HOSTING_REPO"
set -a && . ./.env && set +a
python tools/measure_aca.py agent --runs 3
python tools/measure_responses.py --cold 3 --warm-turns 3
python tools/measure_responses.py --cold 3 --warm-turns 3 --scale 4,8 --recovery --observe
```

Exit 0 requires every requested phase to pass; full-pool refusals are saved but still exit 1. The different historical workloads and clocks do not make this a product ranking.

**Optional isolation observation.** Use the correct namespace for C or D. The base check reads configured runtime and pod state; for D add `--container agent --exec-uname` only when exec is authorized. Requested read failure exits 1.

```bash
python tools/check_isolation.py -n "$NAMESPACE" -l app=agent-host --exec-uname
python tools/check_isolation.py -n "$SESSION_NAMESPACE"
```

**Optional C lifecycle exercise.** These commands intentionally suspend the application. Run only after the owner approves that operation; they are not required to deploy or answer.

```bash
kubectl patch sandbox agent-host -n "$NAMESPACE" --type merge -p '{"spec":{"operatingMode":"Suspended"}}'
kubectl patch sandbox agent-host -n "$NAMESPACE" --type merge -p '{"spec":{"operatingMode":"Running"}}'
kubectl wait sandbox agent-host -n "$NAMESPACE" --for=condition=Ready --timeout=180s
```


The offline checks need Python 3.10 or newer and no Azure access:

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements-dev.txt
python tools/build_measurements.py --check
python tools/render_docs.py --check
python tools/build_diagrams.py --check
python tools/validate_docs.py
python -m pytest -q
```

On Windows, activate with `.venv\Scripts\activate` instead of `. .venv/bin/activate`. Done when every command exits 0 and each check prints `PASS`.

- **`build_measurements.py --check`** rebuilds every metric and fails if a run file's hash, a field or a cross-check is wrong, or if the committed `measurements.json` differs.
- **`render_docs.py --check`** fails if a table or inline number in any of the four pages differs from a fresh render.
- **`build_diagrams.py --check`** compares both architecture figures and every icon with [`images/SOURCES.json`](images/SOURCES.json).
- **`validate_docs.py`** checks the three README headings in order, the VALIDATION headings, the core claim contract and canonical run order in [`evidence/claims.json`](evidence/claims.json), that every measured-run section has Question, Input, Varied and fixed, Result and Boundary in that order with no table before the input, that every run is in the README's results table and all four pages use the same run order, links and images, figure widths, English/Chinese number parity by generated block and table cell (not just document-wide totals), Steps commands that use only variables, keep the reader's shell open (no `set -e` or `exit`), install into a virtual environment and keep `az group delete` alone with its confirmation prompt, and private-content guards (subscription and tenant IDs, IPv4 addresses, emails, internal resource names, and retired claims).
- **`pytest`** runs these checks as tests, recomputes the medians from raw values, evaluates `check_isolation.py` on saved pod and node JSON, runs every tool's `--help` without the Azure SDK, and breaks each guard (a tampered run file, invalid duration, reversed timeline, incomplete concurrency sample, edited number, inserted subscription ID, removed heading, table before an input, reordered runs) to confirm it fails.
- Mocked live-tool tests also check that failed concurrency follow-ups, skipped recovery, failed pod reads or deletions, lost history, invalid arguments and missing settings cannot report success. They make no Azure calls.

CI runs the same on Ubuntu and Windows with Python 3.12 ([workflow](https://github.com/xinyuwei-david/Azure-Agent-Sandbox-Hosting/blob/main/.github/workflows/docs-ci.yml)).

The live checks need Azure and the resources from the README: `tools/aca_sandbox.py`, `tools/measure_aca.py`, `tools/measure_responses.py` and `tools/check_isolation.py` without `--pods-json`.

Not tested here: the tools against a fresh subscription end to end after this repository was assembled (they are the run scripts parameterised with settings; `--help` and the offline logic are tested), regions other than East US 2, and Azure Cloud Shell as the operator shell.

## Limits, Assets and Sources

**Limits.**

- `LOCAL_MEASUREMENT`: A full-agent latency has n=3. B is one end-to-end run plus three session-API runs, and C is one end-to-end run. D is one benchmark campaign: cached-image cold n=5, warm n=3, and one placement and one recovery observation. Repeat with the live measurement commands in this page before relying on a number.
- `LOCAL_MEASUREMENT`: A and C use the workshop reflection agent; B uses its Agent Framework agent with ResponsesHostServer; D uses the private-preview sample. B's 2026-09-27 run and D include the Foundry endpoint and a client in China (round trip <!--v:d.client_rtt.range-->320–800<!--/v--> ms); B's 2026-10-15 runs add a client in Japan East and an API Management gateway; A's answers were timed inside the sandbox; C's at its LoadBalancer. The rows compare field implementations, not identical containers or network paths.
- `LOCAL_MEASUREMENT`: in A, the private Blob volume put create at <!--v:a.attr.vnetvolume.range-->15.79–25.12<!--/v--> s; image, VNet and port alone stayed at <!--v:a.attr.small.range-->1.6–2.7<!--/v--> s.
- `LOCAL_MEASUREMENT`: the oldest D session pod was still Running at least <!--v:d.idle.value-->87<!--/v--> minutes after it was created. This is pod age, not idle duration: no last-request timestamp was retained. It establishes neither a configured idle timeout nor a continuously idle interval.
- `LOCAL_MEASUREMENT`: D's capacity was at most <!--v:d.capacity.per_node-->5<!--/v--> sessions per `Standard_D4s_v5` node with the sample's 500m CPU / 1 Gi request plus 600 Mi Kata overhead; a node that also hosts system pods fits fewer.
- `NOT_MEASURED`: B's resume after the idle timeout (resume after an explicit stop is in `b-2026-10-15-sessions`) and session loss; A's host loss; D's behaviour once the service ends a session; the Foundry-governed agent calling an ACA sandbox per task; latency under concurrency with free capacity; third-party sandboxes other than E2B; E2B Bring Your Own Cloud and private cloud; the official E2B Azure Terraform module, including its scale-set replacement of an unhealthy instance from a fresh disk; the loss of a whole E2B VM or its disk.
- `SOURCE_FACT`: E2B Embed "is one machine, by design"; E2B's ways past one machine are private cloud (in development), Bring Your Own Cloud operated by E2B in your account, and E2B Cloud ([Embed](https://github.com/e2b-dev/runtime/blob/588e5b9500b0987bc5a700d91483b03f0ae7d2a2/embed/README.md#when-one-node-is-not-enough)). It answers over plain HTTP with no TLS of its own. The Azure Terraform install is a scale set of one with no persistent data volume: a replacement starts from a fresh disk and loses the templates you built, and stopping the stack gets the instance replaced about two minutes after `/health` stops answering ([Azure guide](https://github.com/e2b-dev/runtime/blob/588e5b9500b0987bc5a700d91483b03f0ae7d2a2/embed/terraform/azure/README.md#limitations)).
- `SOURCE_FACT`: E2B's Compose guide sizes `HUGEPAGES` by "the sandboxes you will run at once" and states 256 pages for a 512 MiB `base` sandbox at full memory and about 90 idle ([requirements](https://github.com/e2b-dev/runtime/blob/588e5b9500b0987bc5a700d91483b03f0ae7d2a2/embed/compose/README.md#requirements)). In `e-2026-10-15-multi` each idle `base` sandbox reserved 256 pages at create, so the default pool held 7, not about 20.
- `SOURCE_FACT`: ACA Sandboxes start "from prewarmed pools for near-instant availability" and resume "with sub-second restore times" ([overview](https://learn.microsoft.com/azure/container-apps/sandboxes-overview)). Selectable tiers (vCPU / GB): XS 0.25 / 0.5, S 0.5 / 1, M 1 / 2, L 2 / 4, XL 4 / 8. Idle auto-suspend is configurable; Memory preserves memory and disk, while Disk preserves disk only. The local 900 s setting is not a service-wide default.
- `SOURCE_FACT`: hosted agents run in "per-session VM-isolated sandboxes" with `$HOME` and `/files` persisted; idle timeout 2–60 minutes, default 15; sessions deleted after 30 days of inactivity ([hosted agents](https://learn.microsoft.com/azure/foundry/agents/concepts/hosted-agents)). Stopping a session with `POST .../sessions/{id}:stop` ends its compute and keeps the persistent filesystem ([manage sessions](https://learn.microsoft.com/azure/foundry/agents/how-to/manage-hosted-sessions#stop-a-session)).
- `SOURCE_FACT`: hosted agent [sandbox sizes](https://learn.microsoft.com/azure/foundry/agents/concepts/hosted-agents#sandbox-sizes) are 0.5 vCPU / 1 GiB, 1 vCPU / 2 GiB and 2 vCPU / 4 GiB; the values set on an agent version apply to each session, and no VM SKU is chosen. The workshop's module-02 uses 0.5 vCPU / 1 GiB.
- `SOURCE_FACT`: AKS Pod Sandboxing is Azure Linux host + Microsoft Hyper-V + Cloud Hypervisor + Kata Containers; the node VM must be a generation 2 size that supports nested virtualization; each pod VM's memory follows the pod memory limit (512 Mi if unset) and fractional CPU limits round up to a whole vCPU ([pod sandboxing](https://learn.microsoft.com/azure/aks/use-pod-sandboxing)).
- `SOURCE_FACT`: agent-sandbox v0.5.2 supports an absolute `shutdownTime`; underlying pods and services are deleted on expiry, and `shutdownPolicy` controls retention of the Sandbox object ([official API](https://github.com/kubernetes-sigs/agent-sandbox/blob/v0.5.2/docs/api.md)). This is scheduled expiry, not a request-idle timer. `operatingMode` still exposes explicit suspend/resume.
- `NOT_VERIFIED`: no public official BYO-AKS idle policy, suspend support or exhaustive node-SKU list was verified in this review. Confirm preview requirements with the product group; the pod-age observation cannot establish those policies.
- `SOURCE_FACT`: [ACA's official quota documentation](https://sandboxes.azure.com/docs/sandboxes/limits) measures concurrent active cores; stopped sandboxes do not consume this quota. This is not a fixed session-count limit.
- `SOURCE_FACT`: [AKS Pod Sandboxing](https://learn.microsoft.com/azure/aks/concepts-pod-sandboxing) isolates compute, not the control plane, storage/data paths or cluster-admin actions. The isolation tool checks runtime configuration; requested kernel reads must succeed, and a version string is not hardware attestation.
- `SOURCE_FACT`: the [fixed module-02 implementation](https://github.com/oxcp/ainotes/blob/905f2c2/agenthost/module-02/agent-src/main.py) makes `MODEL_ROUTING=direct` call the Foundry project endpoint. A project with a registered native AI Gateway may still forward those calls through APIM; the mode name alone does not prove a gateway bypass.
- `SOURCE_FACT`: status sources: A [GA on 2026-09-23](https://techcommunity.microsoft.com/blog/appsonazureblog/azure-container-apps-sandboxes-now-generally-available/4559125); B [GA in 2026-06](https://azure.microsoft.com/updates?id=563596) (Azure Update "Generally Available: Hosted agents in Foundry Agent Service"; the earlier [Build post of 2026-06-02](https://devblogs.microsoft.com/foundry/hosted-agents-build26/) described the public preview before GA); C [Pod Sandboxing GA on 2025-11-18](https://azure.microsoft.com/updates?id=526237), with agent-sandbox v0.5.2 as an open-source project.
- `LOCAL_MEASUREMENT`: A's history length continued increasing in the saved run. This checks history continuity, not exact answer correctness or preservation of arbitrary process memory.
- `SOURCE_FACT`: D's cost floor of <!--v:d.cost_floor.value-->0.484<!--/v--> USD/h is two `Standard_D4s_v5` nodes at 0.192 USD/h each plus the AKS Standard tier at 0.10 USD/h, East US 2 retail prices queried 2026-09-21; E's single-VM cost floor of <!--v:e.cost_floor.value-->0.344<!--/v--> USD/h is one `Standard_D4ds_v7` Linux VM at 0.326 USD/h, one Standard static public IP at 0.005 USD/h and one 50 GB Premium SSD P6 disk at 0.013 USD/h, East US 2 retail prices queried 2026-10-14; no discounts or tax. This is not the cost of the three-Kata-node benchmark pool.
- D's onboarding durations (role assignments about <!--v:d.role_assignments.value-->120<!--/v--> s, `azd provision` <!--v:d.azd_provision.value-->522<!--/v--> s, `azd deploy` <!--v:d.azd_deploy.value-->212<!--/v--> s) come from the author's console recorded in the earlier field record; the console itself was not kept.

**Assets.**

- [`tools/`](tools/): `aca_sandbox.py`, `measure_aca.py`, `measure_responses.py`, `measure_e2b.py`, `measure_code_interpreter.py`, `measure_sessions.py`, `check_isolation.py` (live); `export_evidence.py` (author only), `build_measurements.py`, `render_docs.py`, `build_diagrams.py`, `validate_docs.py` (offline).
- [`evidence/claims.json`](evidence/claims.json): the canonical A–D identities, statuses, ownership, boundaries, selection contract, letter mapping and run order; [`evidence/runs/`](evidence/runs/): the redacted run records with the SHA-256 of their private sources, and `INDEX.json`; [`evidence/measurements.json`](evidence/measurements.json): every published metric.
- [`images/`](images/): the architecture figures, their source of truth `tools/build_diagrams.py`, the 8 Azure icons and [`SOURCES.json`](images/SOURCES.json).
- [`config/.env.example`](config/.env.example): every setting; [`tests/`](tests/): the offline tests and their fixtures.

**Sources.**

- Microsoft Learn: [Container Apps Sandboxes overview](https://learn.microsoft.com/azure/container-apps/sandboxes-overview) · [Hosted agents in Foundry Agent Service](https://learn.microsoft.com/azure/foundry/agents/concepts/hosted-agents) · [Pod sandboxing with AKS](https://learn.microsoft.com/azure/aks/use-pod-sandboxing) · [Azure Architecture Icons](https://learn.microsoft.com/azure/architecture/icons/)
- [agent-sandbox v0.5.2](https://github.com/kubernetes-sigs/agent-sandbox/releases/tag/v0.5.2) · [agenthost workshop at 905f2c2](https://github.com/oxcp/ainotes/tree/905f2c2/agenthost) (no license file; referenced, not copied)
- [`azure-containerapps-sandbox` on PyPI](https://pypi.org/project/azure-containerapps-sandbox/) (0.1.0b4)
- E2B: [Embed at 588e5b9](https://github.com/e2b-dev/runtime/tree/588e5b9500b0987bc5a700d91483b03f0ae7d2a2/embed) · [code-interpreter template at 162a2a2](https://github.com/e2b-dev/code-interpreter/tree/162a2a25b6a5ea5806749a437b96cbdc5bfc087e/template)
- BYO-AKS private-preview sample and onboarding guide: product group, access on request.
