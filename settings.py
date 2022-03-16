"""Settings for the mef_eline NApp."""

# Base URL of the Pathfinder endpoint
PATHFINDER_URL = "http://localhost:8181/api/kytos/pathfinder/v2/"

# Base URL of the Flow Manager endpoint
MANAGER_URL = "http://localhost:8181/api/kytos/flow_manager/v2"

# Base URL of the Pathfinder endpoint
TOPOLOGY_URL = "http://localhost:8181/api/kytos/topology/v3"

# Base URL of SDN trace CP
SDN_TRACE_CP_URL = "http://localhost:8181/api/amlight/sdntrace_cp"

# EVC consistency interval
DEPLOY_EVCS_INTERVAL = 60

# Number of execution rounds to wait for old path to become available.
# i.e., it will wait up to DEPLOY_EVCS_INTERVAL*WAIT_FOR_OLD_PATH to the old
# path become available, otherwise mef_eline consistency will redeploy it
WAIT_FOR_OLD_PATH = 5

# Prefix this NApp has when using cookies
COOKIE_PREFIX = 0xAA
