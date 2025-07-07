## `mef_eline` scripts for Kytos version 2025.2.0

This folder contains Mef_eline's related scripts:

### Remove Qinq from EVCs flows when VLAN translation is needed


[`000_quinq_evcs.py`](./000_quinq_evcs.py) is a script that redeploys EVCs with VLAN translatio so their flows are updated. This script will only cover cases where both UNIs have different numeric VLAN (from 1 to 4094 inclusive) and a numeric and ``untagged`` VLANs

#### Pre-requisites

- The ``mef_eline`` NApp needs to be installed
- ``kytosd`` needs to be running otherwise the API request are not going to work.
- Make sure MongoDB replica set is up and running.
- Export the following MongnoDB variables accordingly in case your running outside of a container

```
export MONGO_USERNAME=
export MONGO_PASSWORD=
export MONGO_DBNAME=napps
export MONGO_HOST_SEEDS="mongo1:27017,mongo2:27018,mongo3:27099"
```

- The following `CMD` commands are available:

```
number_evcs_affected
redeploy_affected_evcs
```

#### Examples

Use ``number_evcs_affected`` to get the number of EVCs that will be re-deployed.

```
❯ CMD=number_evcs_affected python scripts/db/2025.2.0/000_quinq_evcs.py
There are 3 that need to be redeploy
```

``redeploy_affected_evcs`` command will redeploy every EVC.

```
❯ CMD=redeploy_affected_evcs python scripts/db/2025.2.0/000_quinq_evcs.py
3 EVCs to be redeploy.
Redeploying...
All EVCs were redeployed successfully.
```
