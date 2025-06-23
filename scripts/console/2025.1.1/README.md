# `mef_eline` scripts for Kytos version 2025.1

This folder contains `mef_eline` related scripts that should be run on kytos console:

<details>

<summary>

## Redeploy EVCs which have set_queue action (incorrectly) as the last action

</summary>

[001_redeploy_set_queue.py](./2025.1.1/001_redeploy_set_queue.py) script will reaploy EVCs which have `set_queue` action (incorrectly) as the last action. `set_queue` is supposed to be set before the `output` action.

### How to use

- Change `DRY_RUN` to `False` for the script to make changes.
- Copy all the lines and paste them inside kytos console every time you need to run this script.

### Output example

```
Checking EVCs with action_type set_queue...
It WILL redeploy 50 EVCs
...
Finished!
```

```
Checking EVCs with action_type set_queue...
It WILL redeploy 0 EVCs
Finished!
```

</details>
