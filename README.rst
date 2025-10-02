|Stable| |Tag| |License| |Build| |Coverage| |Quality|

.. raw:: html

  <div align="center">
    <h1><code>kytos/mef_eline</code></h1>

    <strong>NApp that manages point to point L2 Ethernet Virtual Circuits</strong>

    <h3><a href="https://kytos-ng.github.io/api/mef_eline.html">OpenAPI Docs</a></h3>
  </div>


Overview
========

This Napp allows a user to create a point to point L2 Ethernet Virtual Circuit.

Features
========
- REST API to create/modify/delete circuits;
- REST API to create/modify/delete circuit scheduling;
- list of circuits in memory and also synchronized to a permanent storage;
- circuits can be installed at time of request or have an installation schedule;
- circuits can use a predefined path or find a dynamic path;
- the NApp will move circuits to another path in case of a link down;
- web UI for circuits management.

Installing
==========

To install this NApp, first, make sure to have the same venv activated as you have ``kytos`` installed on:

.. code:: shell

   $ git clone https://github.com/kytos-ng/mef_eline.git
   $ cd mef_eline
   $ python3 -m pip install --editable .

To install the kytos environment, please follow our
`development environment setup <https://github.com/kytos-ng/documentation/blob/master/tutorials/napps/development_environment_setup.rst>`_.

Requirements
============
- `kytos/flow_manager <https://github.com/kytos-ng/flow_manager.git>`_
- `kytos/pathfinder <https://github.com/kytos-ng/pathfinder.git>`_
- `kytos/topology <https://github.com/kytos-ng/topology.git>`_
- `amlight/sdntrace_cp <https://github.com/amlight/sdntrace_cp.git>`_
- `MongoDB <https://github.com/kytos-ng/kytos#how-to-use-with-mongodb>`_

Events
======

Subscribed
----------

- ``kytos/topology.topology_loaded``
- ``kytos/topology.link_up``
- ``kytos/topology.link_down``
- ``kytos/flow_manager.flow.error``
- ``kytos/flow_manager.flow.removed``
- ``kytos/of_multi_table.enable_table``
- ``kytos/mef_eline.evc_affected_by_link_down``
- ``kytos/mef_eline.redeployed_link_up``
- ``kytos/mef_eline.redeployed_link_down``
- ``kytos/mef_eline.deployed``
- ``kytos/topology.interface.enabled``
- ``kytos/topology.interface.disabled``

Published
---------

kytos/mef_eline.redeployed_link_down
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Event reporting a redeployed circuit after a link down event.

.. code-block:: python3

  {
    "evc_id": evc.id,
    "id": evc.id,
    "name": evc.name,
    "metadata": evc.metadata,
    "active": evc._active,
    "enabled": evc._enabled,
    "uni_a": evc.uni_a.as_dict(),
    "uni_z": evc.uni_z.as_dict()
  }

kytos/mef_eline.error_redeploy_link_down
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Event reporting an error with redeploying a circuit with a link down event.

.. code-block:: python3

  {
    "evc_id": evc.id,
    "id": evc.id,
    "name": evc.name,
    "metadata": evc.metadata,
    "active": evc._active,
    "enabled": evc._enabled,
    "uni_a": evc.uni_a.as_dict(),
    "uni_z": evc.uni_z.as_dict()
  }

kytos/mef_eline.evcs_affected_by_link_down
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Event reporting that a link down event has occurred.

.. code-block:: python3

  {
    "evc_id": evc.id,
    "id": evc.id,
    "name": evc.name,
    "metadata": evc.metadata,
    "active": evc._active,
    "enabled": evc._enabled,
    "uni_a": evc.uni_a.as_dict(),
    "uni_z": evc.uni_z.as_dict(),
    "link": link
  }

kytos/mef_eline.redeployed_link_up
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Event reporting that a link up event has occurred.

.. code-block:: python3

  {
    "evc_id": evc.id,
    "id": evc.id,
    "name": evc.name,
    "metadata": evc.metadata,
    "active": evc._active,
    "enabled": evc._enabled,
    "uni_a": evc.uni_a.as_dict(),
    "uni_z": evc.uni_z.as_dict()
  }

kytos/mef_eline.updated
~~~~~~~~~~~~~~~~~~~~~~~

Event reporting that a circuit has been updated.

.. code-block:: python3

  {
    "evc_id": evc.id,
    "id": evc.id,
    "name": evc.name,
    "metadata": evc.metadata,
    "active": evc._active,
    "enabled": evc._enabled,
    "uni_a": evc.uni_a.as_dict(),
    "uni_z": evc.uni_z.as_dict()
  }

kytos/mef_eline.(deployed|undeployed)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Event reporting that a circuit was deployed or removed.

.. code-block:: python3

  {
    "evc_id": evc.id,
    "id": evc.id,
    "name": evc.name,
    "metadata": evc.metadata,
    "active": evc._active,
    "enabled": evc._enabled,
    "uni_a": evc.uni_a.as_dict(),
    "uni_z": evc.uni_z.as_dict()
  }

kytos/mef_eline.created
~~~~~~~~~~~~~~~~~~~~~~~

Event reporting that a L2 circuit was created.

kytos/mef_eline.enable_table
~~~~~~~~~~~~~~~~~~~~~~~~~~~

A response from the ``kytos/of_multi_table.enable_table`` event to confirm table settings.

.. code-block:: python3

  {
    'table_group': <object>
  }

kytos/mef_eline.evcs_loaded
~~~~~~~~~~~~~~~~~~~~~~~~~~~

Event with all evcs that got loaded

.. code-block:: python3

  {
    '<evc_id>': <dict>
  }

kytos/mef_eline.uni_active_updated
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Event published when an EVC active state changes due to a UNI going up or down

.. code-block:: python3
   
  {
   "id", evc.id,
   "evc_id": evc.id,
   "name": evc.name,
   "metadata": evc.metadata,
   "active": evc._active,
   "enabled": evc._enabled,
   "uni_a": evc.uni_a.as_dict(),
   "uni_z": evc.uni_z.as_dict()}
  }

kytos/mef_eline.failover_deployed
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Event published when an EVC failover_path gets deployed. ``flows`` are the new deployed flows, and ``removed_flows`` are the removed ones.

.. code-block:: python3
   
  {
   evc.id: {
     "id", evc.id,
     "evc_id": evc.id,
     "name": evc.name,
     "metadata": evc.metadata,
     "active": evc._active,
     "enabled": evc._enabled,
     "uni_a": evc.uni_a.as_dict(),
     "uni_z": evc.uni_z.as_dict(),
     "flows": [],
     "removed_flows": [],
     "error_reason": string,
     "current_path": evc.current_path.as_dict(),
   }
  }

kytos/mef_eline.failover_link_down
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Event published when an EVC failover_path switches over. ``flows`` are the new deployed flows.

.. code-block:: python3
   
  {
   evc.id: {
     "id", evc.id,
     "evc_id": evc.id,
     "name": evc.name,
     "metadata": evc.metadata,
     "active": evc._active,
     "enabled": evc._enabled,
     "uni_a": evc.uni_a.as_dict(),
     "uni_z": evc.uni_z.as_dict(),
     "flows": [],
   }
  }

kytos/mef_eline.failover_old_path
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Event published when an EVC failover related old path gets removed (cleaned up). ``removed_flows`` are the removed flows.

.. code-block:: python3
   
  {
   evc.id: {
     "id", evc.id,
     "evc_id": evc.id,
     "name": evc.name,
     "metadata": evc.metadata,
     "active": evc._active,
     "enabled": evc._enabled,
     "uni_a": evc.uni_a.as_dict(),
     "uni_z": evc.uni_z.as_dict(),
     "removed_flows": [],
     "current_path": evc.current_path.as_dict(),
   }
  }


.. TAGs

.. |Stable| image:: https://img.shields.io/badge/stability-stable-green.svg
   :target: https://github.com/kytos-ng/mef_eline
.. |License| image:: https://img.shields.io/github/license/kytos-ng/kytos.svg
   :target: https://github.com/kytos-ng/mef_eline/blob/master/LICENSE
.. |Build| image:: https://scrutinizer-ci.com/g/kytos-ng/mef_eline/badges/build.png?b=master
   :alt: Build status
   :target: https://scrutinizer-ci.com/g/kytos-ng/kytos/?branch=master
.. |Coverage| image:: https://scrutinizer-ci.com/g/kytos-ng/mef_eline/badges/coverage.png?b=master
   :alt: Code coverage
   :target: https://scrutinizer-ci.com/g/kytos-ng/mef_eline/
.. |Quality| image:: https://scrutinizer-ci.com/g/kytos-ng/mef_eline/badges/quality-score.png?b=master
   :alt: Code-quality score
   :target: https://scrutinizer-ci.com/g/kytos-ng/mef_eline/
.. |Tag| image:: https://img.shields.io/github/tag/kytos-ng/mef_eline.svg
   :target: https://github.com/kytos-ng/mef_eline/tags
