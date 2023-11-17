"""Settings for the mef_eline NApp."""

# Base URL of the Pathfinder endpoint
PATHFINDER_URL = "http://localhost:8181/api/kytos/pathfinder/v3/"

# Base URL of the Flow Manager endpoint
MANAGER_URL = "http://localhost:8181/api/kytos/flow_manager/v2"

# Base URL of the Pathfinder endpoint
TOPOLOGY_URL = "http://localhost:8181/api/kytos/topology/v3"

# Base URL of SDN trace CP
SDN_TRACE_CP_URL = "http://localhost:8181/api/amlight/sdntrace_cp/v1"

# EVC consistency interval
DEPLOY_EVCS_INTERVAL = 60

# Number of execution rounds to wait for old path to become available.
# i.e., it will wait up to DEPLOY_EVCS_INTERVAL*WAIT_FOR_OLD_PATH to the old
# path become available, otherwise mef_eline consistency will redeploy it
WAIT_FOR_OLD_PATH = 5

# Prefix this NApp has when using cookies
COOKIE_PREFIX = 0xAA

# Maximum number of paths to consider when calculating the disjoint paths
# i.e., the number of paths that will be requested to pathfinder to calculate
# the maximum disjoint paths from unwanted_path
DISJOINT_PATH_CUTOFF = 10

# BATCH_INTERVAL: time interval between batch requests that will be sent to
# flow_manager (in seconds) - zero enable sending all the requests in a row
BATCH_INTERVAL = 0.5

# BATCH_SIZE: size of a batch request that will be sent to flow_manager, in
# number of FlowMod requests. Use 0 (zero) to disable BATCH mode, i.e. sends
# everything at a glance
BATCH_SIZE = 50

# Default values for EVPL and EPL respectively. They are use when sb_priority
# is not set in a request
EVPL_SB_PRIORITY = 20000
EPL_SB_PRIORITY = 10000
ANY_SB_PRIORITY = 15000
UNTAGGED_SB_PRIORITY = 20000

#  Time (seconds) to check if an evc has been updated
#  or flows have been deleted.
TIME_RECENT_DELETED_FLOWS = 60
TIME_RECENT_UPDATED = 60

TABLE_GROUP_ALLOWED = {'evpl', 'epl'}

# Default spf_attribute. Allowed atributes are [0,1,2,3,4,5,6,7]
QUEUE_ID = None
# Default spf_attribute. Allowed values: "hop", "priority", and "delay"
SPF_ATTRIBUTE = "hop"
