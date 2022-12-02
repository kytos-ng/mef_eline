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

Published
---------

kytos/mef_eline.created
~~~~~~~~~~~~~~~~~~~~~~~

Event reporting that a L2 circuit was created.

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
