# DevPilot fixture repository

Two intentional bugs: percentage discount subtracts an absolute amount, and average uses an off-by-one denominator. Run `python -m pytest -q` here: **2 fail, 2 pass** is the expected baseline. These failures are separate from backend correctness tests.

This folder can be copied into a standalone GitHub repository in a later phase. It is not yet an external repository and DevPilot does not execute it automatically.

Docker recipe (build installs Pytest; obtain permission first):

```powershell
docker build -t devpilot-demo ./demo-repo
docker run --rm --network none --read-only --cap-drop ALL --security-opt no-new-privileges --pids-limit 64 --memory 128m --cpus 1 --tmpfs /tmp:rw,noexec,nosuid,size=16m devpilot-demo
```

This is a manual fixture runner, not the future agent execution sandbox. Do not mount host credentials or the Docker socket into a task container.
