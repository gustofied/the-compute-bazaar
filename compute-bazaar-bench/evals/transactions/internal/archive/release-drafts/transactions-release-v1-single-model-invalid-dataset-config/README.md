# Prelaunch configuration correction

This frozen draft passed static parsing but described local task packages under `datasets`. Harbor 0.20 rejected it before job creation, Modal startup, or inference. The active release replaces those keys with `tasks`; every task and verifier byte remains unchanged.
